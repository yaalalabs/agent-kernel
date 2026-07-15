import datetime
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from agentkernel.core.config import AKConfig, _ThreadDynamoDBConfig, _ThreadStoreConfig
from agentkernel.core.thread.model import Thread, ThreadAttachment, ThreadMessage
from agentkernel.core.thread.store.dynamodb import DynamoDBThreadStore
from agentkernel.core.thread.store.in_memory import InMemoryThreadStore


class TestDynamoDBToThread:
    """Unit test for DynamoDBThreadStore._to_thread (no live table required)."""

    def test_top_level_updated_at_overrides_stale_data_blob(self):
        # The data blob carries the creation-time updated_at; the top-level
        # attribute is the authoritative, append-refreshed value. list_threads
        # must reflect the latter so recency ordering and the returned timestamp
        # are correct.
        created = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        latest = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        thread = Thread(session_id="s1", user_id="u1", created_at=created, updated_at=created)

        item = {"data": thread.model_dump_json(), "updated_at": latest.isoformat()}
        rebuilt = DynamoDBThreadStore._to_thread(item)
        assert rebuilt.updated_at == latest

    def test_missing_top_level_updated_at_keeps_blob_value(self):
        created = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        thread = Thread(session_id="s1", user_id="u1", created_at=created, updated_at=created)
        rebuilt = DynamoDBThreadStore._to_thread({"data": thread.model_dump_json()})
        assert rebuilt.updated_at == created


class TestDynamoDBConditionalCreate:
    """create() must use a conditional put so a lost race never overwrites metadata (mocked table)."""

    @pytest.fixture
    def store(self):
        original = AKConfig.get().thread
        AKConfig.get().thread = _ThreadStoreConfig(type="dynamodb", dynamodb=_ThreadDynamoDBConfig())
        store = DynamoDBThreadStore()
        store._driver = MagicMock()
        yield store
        AKConfig.get().thread = original

    def test_create_uses_condition_expression(self, store):
        store.create(Thread(session_id="s1", user_id="u1"))
        assert store._driver.table.put_item.call_args.kwargs["ConditionExpression"] == "attribute_not_exists(session_id)"

    def test_create_conflict_returns_existing(self, store):
        existing = Thread(session_id="s1", user_id="winner")
        store._driver.table.put_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        store._driver.table.get_item.return_value = {"Item": {"data": existing.model_dump_json()}}

        result = store.create(Thread(session_id="s1", user_id="loser"))
        assert result.user_id == "winner"

    def test_create_other_client_error_propagates(self, store):
        store._driver.table.put_item.side_effect = ClientError({"Error": {"Code": "ThrottlingException"}}, "PutItem")
        with pytest.raises(ClientError):
            store.create(Thread(session_id="s1", user_id="u1"))


class TestDynamoDBUpdateName:
    """update_name must rewrite the data blob conditionally and leave updated_at alone (mocked table)."""

    @pytest.fixture
    def store(self):
        original = AKConfig.get().thread
        AKConfig.get().thread = _ThreadStoreConfig(type="dynamodb", dynamodb=_ThreadDynamoDBConfig())
        store = DynamoDBThreadStore()
        store._driver = MagicMock()
        yield store
        AKConfig.get().thread = original

    def test_update_name_rewrites_data_blob(self, store):
        existing = Thread(session_id="s1", user_id="u1", name="old")
        store._driver.table.get_item.return_value = {"Item": {"data": existing.model_dump_json()}}

        result = store.update_name("s1", "new name")

        assert result.name == "new name"
        assert result.name_locked is True
        kwargs = store._driver.table.update_item.call_args.kwargs
        assert kwargs["ConditionExpression"] == "attribute_exists(session_id)"
        written = Thread.model_validate_json(kwargs["ExpressionAttributeValues"][":data"])
        assert written.name == "new name"
        assert written.name_locked is True
        assert "updated_at" not in kwargs["UpdateExpression"]

    def test_update_name_missing_thread_raises(self, store):
        store._driver.table.get_item.return_value = {}
        with pytest.raises(KeyError):
            store.update_name("missing", "new name")
        store._driver.table.update_item.assert_not_called()

    def test_update_name_condition_failure_raises_key_error(self, store):
        existing = Thread(session_id="s1", user_id="u1", name="old")
        store._driver.table.get_item.return_value = {"Item": {"data": existing.model_dump_json()}}
        store._driver.table.update_item.side_effect = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        with pytest.raises(KeyError):
            store.update_name("s1", "new name")


class TestInMemoryThreadStore:
    """Tests for InMemoryThreadStore (metadata/message split + pagination)."""

    def setup_method(self):
        InMemoryThreadStore._threads.clear()
        InMemoryThreadStore._messages.clear()
        self.store = InMemoryThreadStore()

    def test_create_and_load_metadata(self):
        thread = Thread(session_id="s1", user_id="u1", name="First thread")
        self.store.create(thread)

        loaded = self.store.load_metadata("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.user_id == "u1"
        assert loaded.name == "First thread"
        assert loaded.messages == []

    def test_load_metadata_missing_returns_none(self):
        assert self.store.load_metadata("missing") is None

    def test_create_is_conditional_second_create_keeps_first_metadata(self):
        first = self.store.create(Thread(session_id="s1", user_id="u1", name="winner"))
        second = self.store.create(Thread(session_id="s1", user_id="u2", name="loser"))

        assert second.user_id == first.user_id == "u1"
        assert second.name == "winner"
        assert self.store.load_metadata("s1").user_id == "u1"

    def test_append_and_get_messages(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        self.store.append_message("s1", ThreadMessage(role="user", content="hello"))
        self.store.append_message("s1", ThreadMessage(role="assistant", content="hi!"))

        messages, next_offset = self.store.get_messages("s1", limit=50, offset=0)
        assert [(m.role, m.content) for m in messages] == [("user", "hello"), ("assistant", "hi!")]
        assert next_offset is None

    def test_append_message_missing_thread_raises(self):
        with pytest.raises(KeyError):
            self.store.append_message("missing", ThreadMessage(role="user", content="hi"))

    def test_update_name_sets_name_and_lock_without_touching_updated_at(self):
        self.store.create(Thread(session_id="s1", user_id="u1", name="old"))
        before = self.store.load_metadata("s1").updated_at

        updated = self.store.update_name("s1", "new name")
        assert updated.name == "new name"
        assert updated.name_locked is True
        assert updated.updated_at == before

        loaded = self.store.load_metadata("s1")
        assert loaded.name == "new name"
        assert loaded.name_locked is True

    def test_update_name_missing_thread_raises(self):
        with pytest.raises(KeyError):
            self.store.update_name("missing", "new name")

    def test_append_message_updates_updated_at(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        before = self.store.load_metadata("s1").updated_at
        self.store.append_message("s1", ThreadMessage(role="user", content="hi"))
        assert self.store.load_metadata("s1").updated_at >= before

    def test_append_message_with_attachments(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        self.store.append_message(
            "s1",
            ThreadMessage(
                role="user",
                content="see attached",
                attachments=[ThreadAttachment(attachment_id="att-1", name="pic.png", mime_type="image/png")],
            ),
        )
        messages, _ = self.store.get_messages("s1", limit=50)
        assert messages[0].attachments[0].attachment_id == "att-1"

    def test_message_pagination(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        for i in range(5):
            self.store.append_message("s1", ThreadMessage(role="user", content=f"m{i}"))

        page1, next1 = self.store.get_messages("s1", limit=2, offset=0)
        assert [m.content for m in page1] == ["m0", "m1"]
        assert next1 == 2

        page2, next2 = self.store.get_messages("s1", limit=2, offset=2)
        assert [m.content for m in page2] == ["m2", "m3"]
        assert next2 == 4

        page3, next3 = self.store.get_messages("s1", limit=2, offset=4)
        assert [m.content for m in page3] == ["m4"]
        assert next3 is None

    def test_get_messages_empty_thread(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        messages, next_offset = self.store.get_messages("s1", limit=50)
        assert messages == []
        assert next_offset is None

    def test_many_appends_are_all_retained(self):
        # Simulates many sequential appends (the concurrency-safety property is that
        # appends never rewrite prior messages, so none are lost).
        self.store.create(Thread(session_id="s1", user_id="u1"))
        for i in range(100):
            self.store.append_message("s1", ThreadMessage(role="user", content=str(i)))
        all_messages, _ = self.store.get_messages("s1", limit=200)
        assert [m.content for m in all_messages] == [str(i) for i in range(100)]

    def test_list_threads_filters_by_user(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        self.store.create(Thread(session_id="s2", user_id="u2"))
        threads, _ = self.store.list_threads(user_id="u1")
        assert [t.session_id for t in threads] == ["s1"]

    def test_list_threads_filters_by_group(self):
        self.store.create(Thread(session_id="s1", user_id="u1", group_id="g1"))
        self.store.create(Thread(session_id="s2", user_id="u1", group_id="g2"))
        threads, _ = self.store.list_threads(group_id="g1")
        assert [t.session_id for t in threads] == ["s1"]

    def test_list_threads_metadata_only(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        self.store.append_message("s1", ThreadMessage(role="user", content="hello"))
        threads, _ = self.store.list_threads(user_id="u1")
        assert threads[0].messages == []

    def test_list_threads_pagination_and_recency_order(self):
        # Create three threads; append to them in an order that makes s2 most recent.
        for sid in ("s1", "s2", "s3"):
            self.store.create(Thread(session_id=sid, user_id="u1"))
        self.store.append_message("s1", ThreadMessage(role="user", content="a"))
        self.store.append_message("s3", ThreadMessage(role="user", content="b"))
        self.store.append_message("s2", ThreadMessage(role="user", content="c"))  # s2 newest

        page1, next1 = self.store.list_threads(user_id="u1", limit=2, offset=0)
        assert [t.session_id for t in page1] == ["s2", "s3"]
        assert next1 == 2
        page2, next2 = self.store.list_threads(user_id="u1", limit=2, offset=2)
        assert [t.session_id for t in page2] == ["s1"]
        assert next2 is None

    def test_clear(self):
        self.store.create(Thread(session_id="s1", user_id="u1"))
        self.store.append_message("s1", ThreadMessage(role="user", content="hello"))
        self.store.clear()
        assert self.store.load_metadata("s1") is None
        assert self.store.list_threads() == ([], None)
