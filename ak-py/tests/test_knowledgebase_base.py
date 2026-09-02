"""The reshaped KnowledgeBase ABC (#553 iteration 2).

Three things here are the contract every backend depends on and are easy to break silently:
read() routing on the declaration, an undeclared operation raising rather than returning
empty, and schema() precedence — where capabilities must be the one key a deployment cannot
contradict through add_schema().

Backends are declared inline rather than through a shared fixture; the reusable
FakeKnowledgeBase lands with KnowledgeBaseContract.
"""

from typing import Any, List, Mapping

import pytest

from agentkernel.knowledgebase.base import KnowledgeBase, Record
from agentkernel.knowledgebase.errors import KnowledgeCapabilityError
from agentkernel.knowledgebase.model import KnowledgeCapabilities


class MinimalBackend(KnowledgeBase):
    """Implements only the three members that stayed abstract."""

    def __init__(self, capabilities: KnowledgeCapabilities, name: str | None = None) -> None:
        super().__init__(capabilities=capabilities, name=name)
        self.calls: list[tuple[str, tuple, dict]] = []

    @property
    def backend_name(self) -> str:
        return "minimal"

    def connect(self, **kwargs) -> None:
        pass

    def get_description(self) -> str:
        return "minimal: a backend with nothing but the required surface"


class RecordingBackend(MinimalBackend):
    """Records which operation was reached, so routing is observable."""

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        self.calls.append(("search", (query, limit), kwargs))
        return [{"text": f"search:{query}", "metadata": {}}]

    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Record]:
        self.calls.append(("query", (statement, limit), kwargs))
        return [{"text": f"query:{statement}", "metadata": {}}]


def _searcher() -> RecordingBackend:
    return RecordingBackend(KnowledgeCapabilities(kinds=["vector"], search=True))


def _querier() -> RecordingBackend:
    return RecordingBackend(KnowledgeCapabilities(kinds=["structured"], query=True, query_language="sql"))


class TestConstruction:
    def test_the_class_name_is_the_validation_subject_when_name_is_omitted(self):
        with pytest.raises(ValueError, match="'MinimalBackend'"):
            MinimalBackend(KnowledgeCapabilities())

    def test_a_given_name_is_the_validation_subject(self):
        with pytest.raises(ValueError, match="'my-kb'"):
            MinimalBackend(KnowledgeCapabilities(), name="my-kb")

    def test_a_query_incoherent_declaration_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="without a query_language"):
            MinimalBackend(KnowledgeCapabilities(query=True))

    def test_the_declaration_is_kept_on_the_instance(self):
        backend = _searcher()
        assert backend.capabilities.search is True
        assert backend.capabilities.kinds == ["vector"]

    def test_only_three_members_stay_abstract(self):
        assert set(KnowledgeBase.__abstractmethods__) == {"backend_name", "connect", "get_description"}

    def test_a_backend_implementing_neither_read_nor_write_constructs(self):
        # read and write stopped being abstract, so the required surface is three members.
        backend = MinimalBackend(KnowledgeCapabilities(browse=True))
        assert backend.get_description().startswith("minimal:")


class TestReadRouting:
    def test_read_routes_to_query_for_a_query_backend(self):
        backend = _querier()
        assert backend.read("SELECT 1") == [{"text": "query:SELECT 1", "metadata": {}}]
        assert backend.calls[0][0] == "query"

    def test_read_routes_to_search_for_a_non_query_backend(self):
        backend = _searcher()
        assert backend.read("refund policy") == [{"text": "search:refund policy", "metadata": {}}]
        assert backend.calls[0][0] == "search"

    def test_read_forwards_limit_and_kwargs_unchanged(self):
        backend = _querier()
        backend.read("SELECT 1", limit=17, where="x", flag=True)
        operation, positional, kwargs = backend.calls[0]
        assert operation == "query"
        assert positional == ("SELECT 1", 17)
        assert kwargs == {"where": "x", "flag": True}

    def test_read_defaults_to_a_limit_of_three(self):
        backend = _searcher()
        backend.read("anything")
        assert backend.calls[0][1] == ("anything", 3)

    def test_a_subclass_overriding_read_still_wins(self):
        class OverridingBackend(RecordingBackend):
            def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
                return [{"text": "override", "metadata": {}}]

        backend = OverridingBackend(KnowledgeCapabilities(query=True, query_language="sql"))
        assert backend.read("SELECT 1") == [{"text": "override", "metadata": {}}]
        assert backend.calls == []


class TestUndeclaredOperations:
    @pytest.mark.parametrize(
        "operation, call",
        [
            ("search", lambda b: b.search("q")),
            ("query", lambda b: b.query("SELECT 1")),
            ("fetch", lambda b: b.fetch(["a"])),
            ("browse", lambda b: b.browse("")),
            ("write", lambda b: b.write([{"text": "x"}])),
        ],
    )
    def test_an_undeclared_operation_names_the_backend_and_the_operation(self, operation, call):
        backend = MinimalBackend(KnowledgeCapabilities(browse=True))
        with pytest.raises(KnowledgeCapabilityError) as excinfo:
            call(backend)
        assert excinfo.value.subject == "minimal"
        assert excinfo.value.capability == operation
        assert str(excinfo.value) == f"minimal does not support capability: {operation}"

    def test_an_undeclared_operation_raises_rather_than_returning_empty(self):
        # The distinction matters: an empty list means "nothing matched", not "unsupported".
        backend = MinimalBackend(KnowledgeCapabilities(search=True))
        with pytest.raises(KnowledgeCapabilityError):
            backend.fetch(["a"])

    def test_a_declared_operation_a_backend_forgot_to_implement_still_raises(self):
        # Declaration and implementation are only checked together by the contract suite,
        # so the base must not silently pretend the operation exists.
        backend = MinimalBackend(KnowledgeCapabilities(fetch=True))
        with pytest.raises(KnowledgeCapabilityError, match="fetch"):
            backend.fetch(["a"])


class TestSchema:
    def test_no_schema_from_either_source_raises_the_unchanged_message(self):
        backend = _searcher()
        with pytest.raises(ValueError) as excinfo:
            backend.schema()
        assert str(excinfo.value) == "Schema for 'minimal' has not been set! Call .add_schema() before passing to the Agent."

    def test_add_schema_alone_is_enough(self):
        backend = _searcher()
        schema = backend.add_schema({"tables": ["orders"]}).schema()
        assert schema["tables"] == ["orders"]
        assert schema["backend"] == "minimal"

    def test_a_derived_schema_alone_no_longer_raises(self):
        class DerivingBackend(MinimalBackend):
            def _derived_schema(self) -> Mapping[str, Any]:
                return {"concepts": 4}

        schema = DerivingBackend(KnowledgeCapabilities(browse=True, derives_schema=True)).schema()
        assert schema["concepts"] == 4

    def test_add_schema_beats_the_derived_schema(self):
        class DerivingBackend(MinimalBackend):
            def _derived_schema(self) -> Mapping[str, Any]:
                return {"concepts": 4, "kept": "yes"}

        backend = DerivingBackend(KnowledgeCapabilities(browse=True, derives_schema=True))
        schema = backend.add_schema({"concepts": 99}).schema()
        assert schema["concepts"] == 99
        assert schema["kept"] == "yes"

    def test_backend_stays_overridable_through_add_schema(self):
        backend = _searcher()
        assert backend.add_schema({"backend": "renamed"}).schema()["backend"] == "renamed"

    def test_capabilities_is_not_overridable_through_add_schema(self):
        # capabilities is what the tool layer routes on; a deployment must not contradict it.
        backend = _searcher()
        schema = backend.add_schema({"capabilities": {"search": False, "fetch": True}}).schema()
        assert schema["capabilities"] == backend.capabilities.model_dump()
        assert schema["capabilities"]["search"] is True
        assert schema["capabilities"]["fetch"] is False

    def test_schema_always_carries_the_declaration(self):
        schema = _querier().add_schema({"tables": ["orders"]}).schema()
        assert schema["capabilities"]["query"] is True
        assert schema["capabilities"]["query_language"] == "sql"

    def test_neither_backend_nor_capabilities_counts_as_content_for_the_guard(self):
        # An empty add_schema must not satisfy the guard just because two keys get added later.
        backend = _searcher()
        with pytest.raises(ValueError, match="has not been set"):
            backend.add_schema({}).schema()


class TestFormatResults:
    def test_no_rows_returns_the_sentinel(self):
        assert _searcher().format_results([]) == "No relevant knowledge found."

    def test_a_non_fetch_backend_renders_the_unprefixed_line(self):
        rows = [{"text": "hello", "metadata": {"source": "docs", "id": "a/b.md"}}]
        assert _searcher().format_results(rows) == "- hello (source: docs)"

    def test_a_missing_source_falls_back_to_na(self):
        assert _searcher().format_results([{"text": "hello"}]) == "- hello (source: N/A)"

    def test_a_fetch_backend_prefixes_the_record_id(self):
        backend = MinimalBackend(KnowledgeCapabilities(fetch=True))
        rows = [{"text": "hello", "metadata": {"source": "docs", "id": "a/b.md"}}]
        assert backend.format_results(rows) == "- [a/b.md] hello (source: docs)"

    @pytest.mark.parametrize("record_id", [None, "", 42, ["a"]])
    def test_an_unusable_id_degrades_to_the_unprefixed_line(self, record_id):
        backend = MinimalBackend(KnowledgeCapabilities(fetch=True))
        rows = [{"text": "hello", "metadata": {"source": "docs", "id": record_id}}]
        assert backend.format_results(rows) == "- hello (source: docs)"

    def test_a_null_metadata_value_is_tolerated(self):
        backend = MinimalBackend(KnowledgeCapabilities(fetch=True))
        assert backend.format_results([{"text": "hello", "metadata": None}]) == "- hello (source: N/A)"

    def test_every_row_gets_its_own_line(self):
        rows = [{"text": "one", "metadata": {"source": "a"}}, {"text": "two", "metadata": {"source": "b"}}]
        assert _searcher().format_results(rows) == "- one (source: a)\n- two (source: b)"
