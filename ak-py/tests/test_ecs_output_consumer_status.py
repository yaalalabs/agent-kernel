"""Status persistence in the ECS output consumer (#629 Phase 2).

The stored record gains a status_code so RestHandler._build_sync_response can honor it. Records
written before the runner forwarded a status carry none and must keep behaving as 200.
"""

import json
from unittest.mock import MagicMock, patch

from agentkernel.deployment.aws.containerized.akoutputconsumer import ECSOutputConsumer


def _make_record(body: dict, status_code: str | None = None) -> dict:
    attributes = {"request_id": {"StringValue": "req-1", "DataType": "String"}}
    if status_code is not None:
        attributes["status_code"] = {"StringValue": status_code, "DataType": "String"}
    return {
        "MessageId": "m1",
        "Body": json.dumps(body),
        "Attributes": {"MessageGroupId": "session-1"},
        "MessageAttributes": attributes,
    }


class TestConstructMessageForStore:
    def test_forwarded_status_is_stored(self):
        record = _make_record({"status": "SCHEDULED", "session_id": "s1"}, status_code="202")

        message = ECSOutputConsumer._construct_message_for_store(record)

        assert message["status_code"] == 202
        assert message["session_id"] == "s1"
        assert message["request_id"] == "req-1"
        assert message["body"] == {"status": "SCHEDULED", "session_id": "s1"}

    def test_missing_status_defaults_to_200(self):
        record = _make_record({"result": "ok", "session_id": "s1"})

        assert ECSOutputConsumer._construct_message_for_store(record)["status_code"] == 200

    def test_error_status_is_stored_as_an_int(self):
        record = _make_record({"error": "boom", "session_id": "s1"}, status_code="500")

        assert ECSOutputConsumer._construct_message_for_store(record)["status_code"] == 500


class TestPermanentFailure:
    def test_permanent_failure_stores_500_regardless_of_the_forwarded_status(self, monkeypatch):
        """The delivery itself failed, so the waiting caller must see a server error even though
        the runner had produced a success."""
        monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", None)
        record = _make_record({"result": "ok", "session_id": "s1"}, status_code="200")
        store = MagicMock()

        with patch.object(ECSOutputConsumer, "_get_response_store", return_value=store):
            ECSOutputConsumer.on_permanent_failure(record)

        stored = store.add_message.call_args.args[0]
        assert stored["status_code"] == 500
        assert "error" in stored["body"]
