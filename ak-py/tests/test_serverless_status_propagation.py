"""The status a chat run produced survives the serverless queue round trip.

Direct mode answers with whatever status ``ChatService`` produced (202 for a request deferred to
a schedule, 4xx for one it rejected). In queue mode that status has to cross two SQS hops and the
response store to reach the caller, so it is carried as an output-message attribute, stored on the
response record, and replayed by the REST surface — the same contract the pipeline handlers keep.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig, _ResponseStoreConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner
from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler
from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler
from agentkernel.pipeline.envelope import ATTR_STATUS_CODE

RUNNER_MODULE = "agentkernel.deployment.aws.serverless.akagentrunner"
ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"


def _input_record(prompt: str = "hi") -> dict:
    return {
        "body": json.dumps({"prompt": prompt, "session_id": "s1"}),
        "attributes": {"MessageGroupId": "s1", "MessageDeduplicationId": "req-1"},
        "messageAttributes": {
            "request_id": {"stringValue": "req-1", "DataType": "String"},
            "user_id": {"stringValue": "u1", "DataType": "String"},
        },
    }


def _output_record(body: dict, status_code: str | None = None) -> dict:
    message_attributes = {"request_id": {"stringValue": "req-1", "DataType": "String"}}
    if status_code is not None:
        message_attributes[ATTR_STATUS_CODE] = {"stringValue": status_code, "DataType": "String"}
    return {"body": json.dumps(body), "messageAttributes": message_attributes}


class TestAgentRunnerForwardsTheStatus:
    @staticmethod
    def _sent_attributes(send_mock) -> dict:
        custom_attributes = send_mock.call_args.kwargs["custom_message_attributes"]
        return {attribute.name: attribute.value for attribute in custom_attributes}

    @pytest.mark.parametrize("status_code", [200, 202, 400])
    def test_the_chat_service_status_travels_as_an_attribute(self, status_code):
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (status_code, {"result": "ok", "session_id": "s1"})

        with (
            patch.object(ServerlessAgentRunner, "_get_chat_service", return_value=chat_service),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessAgentRunner.process_message(_input_record())

        assert self._sent_attributes(send)[ATTR_STATUS_CODE] == str(status_code)

    def test_a_permanently_failed_message_is_reported_as_a_server_error(self):
        with (
            patch.object(ServerlessAgentRunner, "_get_max_receive_count", return_value=3),
            patch(f"{RUNNER_MODULE}.SQSHandler.send_message_to_output_queue") as send,
        ):
            ServerlessAgentRunner.on_permanent_failure(_input_record())

        assert self._sent_attributes(send)[ATTR_STATUS_CODE] == "500"


class TestResponseHandlerStoresTheStatus:
    def test_the_forwarded_status_is_stored_on_the_record(self):
        record = ResponseHandler._construct_message_for_store(_output_record({"session_id": "s1"}, status_code="202"))

        assert record["status_code"] == 202

    def test_a_reply_without_a_status_keeps_the_previous_200(self):
        """Replies from a sender that predates the forwarding must not change meaning."""
        record = ResponseHandler._construct_message_for_store(_output_record({"session_id": "s1"}))

        assert record["status_code"] == 200

    def test_an_unparseable_status_falls_back_to_200(self):
        record = ResponseHandler._construct_message_for_store(_output_record({"session_id": "s1"}, status_code="not-a-status"))

        assert record["status_code"] == 200

    def test_a_permanent_failure_is_stored_as_a_server_error(self):
        with patch.object(ResponseHandler, "_get_max_receive_count", return_value=3):
            record = ResponseHandler._construct_message_for_store(
                _output_record({"session_id": "s1"}),
                body={"error": "gave up"},
                status_code=ResponseHandler._PERMANENT_FAILURE_STATUS_CODE,
            )

        assert record["status_code"] == 500


class TestRestSurfaceReplaysTheStatus:
    @pytest.fixture
    def handler_and_store(self):
        config = MagicMock()
        config.execution = _ExecutionConfig(mode=ExecutionMode.REST_SYNC, response_store=_ResponseStoreConfig(type="dynamodb"))
        store = MagicMock()

        with (
            patch(f"{ROUTER_MODULE}.AKConfig.get", return_value=config),
            patch(f"{ROUTER_MODULE}.ResponseStoreFactory.create", return_value=store),
            patch(f"{ROUTER_MODULE}.ChatService"),
        ):
            yield DefaultEndpointsHandler(), store

    @staticmethod
    def _event() -> dict:
        return {"body": json.dumps({"request_id": "req-1", "prompt": "hi", "session_id": "s1"})}

    @pytest.mark.parametrize("stored_status,expected_status", [(200, 200), (202, 202), (400, 400)])
    def test_rest_sync_answers_with_the_stored_status(self, handler_and_store, stored_status, expected_status):
        handler, store = handler_and_store
        body = {"status": "SCHEDULED", "session_id": "s1"}
        store.get_record_with_retry.return_value = {"session_id": "s1", "request_id": "req-1", "status_code": stored_status, "body": body}

        with patch(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}):
            status_code, response_body = handler._handle_rest_sync(self._event(), None)

        assert (status_code, response_body) == (expected_status, body)

    def test_a_record_without_a_status_answers_200(self, handler_and_store):
        handler, store = handler_and_store
        store.get_record_with_retry.return_value = {"session_id": "s1", "request_id": "req-1", "body": {"result": "ok"}}

        with patch(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}):
            status_code, response_body = handler._handle_rest_sync(self._event(), None)

        assert (status_code, response_body) == (200, {"result": "ok"})

    def test_a_response_that_never_arrived_keeps_its_error_body_shape(self, handler_and_store):
        handler, store = handler_and_store
        store.get_record_with_retry.return_value = None

        with patch(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}):
            status_code, response_body = handler._handle_rest_sync(self._event(), None)

        assert status_code == 200
        assert response_body["status"] == "NOT_FOUND"

    def test_the_poll_route_replays_the_stored_status_too(self, handler_and_store):
        handler, store = handler_and_store
        body = {"error": "schedule is in the past", "session_id": "s1"}
        store.get_record_with_retry.return_value = {"session_id": "s1", "request_id": "req-1", "status_code": 400, "body": body}

        status_code, response_body = handler._handle_async_poll(self._event(), None)

        assert (status_code, response_body) == (400, body)

    def test_the_submit_route_still_acknowledges_with_200(self, handler_and_store):
        handler, _ = handler_and_store

        with patch(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", return_value={}):
            status_code, response_body = handler._handle_async_submit(self._event(), None)

        assert status_code == 200
        assert response_body["status"] == "ACCEPTED"


class TestRestSurfaceRefusesAUserId:
    """``from_payload`` raises ValueError for a ``user_id``; the router answers the advertised 400 (#603)."""

    @pytest.fixture
    def handler(self):
        config = MagicMock()
        config.execution = _ExecutionConfig(mode=ExecutionMode.REST_SYNC)
        with patch(f"{ROUTER_MODULE}.AKConfig.get", return_value=config), patch(f"{ROUTER_MODULE}.ChatService"):
            yield DefaultEndpointsHandler()

    def test_a_user_id_in_the_body_is_a_400_with_the_reason(self, handler):
        event = {"body": json.dumps({"prompt": "hi", "session_id": "s1", "user_id": "u1"})}

        status, body = handler._handle_request(event, lambda request: pytest.fail("the operation must not run"))

        assert status == 400
        assert body["error"] == "user_id is not a request field; the acting user comes from the credential"

    def test_an_unreadable_body_is_a_400_too(self, handler):
        """A JSON decoding error is a ValueError: the caller sent something unparsable, which is their 400."""
        status, body = handler._handle_request({"body": "not json"}, lambda request: pytest.fail("the operation must not run"))

        assert status == 400
        assert body["error"].startswith("Expecting value")

    def test_an_unexpected_failure_still_hides_behind_a_500(self, handler):
        def _operation(request):
            raise RuntimeError("the store is down")

        status, body = handler._handle_request({"body": json.dumps({"prompt": "hi", "session_id": "s1"})}, _operation)

        assert status == 500
        assert body["error"] == "An unexpected error occurred"


class TestDirectChatRouteRefusesAUserId:
    """Without an input queue the router serves ``_handle_agent_chat``, which parses on its own path:
    a body the parser refuses is the caller's 400 there too, while a failure inside the chat service
    stays a generic 500 (#603)."""

    @pytest.fixture
    def handler(self):
        config = MagicMock()
        config.execution = _ExecutionConfig(mode=ExecutionMode.REST_SYNC)
        with patch(f"{ROUTER_MODULE}.AKConfig.get", return_value=config), patch(f"{ROUTER_MODULE}.ChatService"):
            yield DefaultEndpointsHandler()

    def test_the_route_without_an_input_queue_is_the_direct_handler(self, handler):
        with patch(f"{ROUTER_MODULE}.SQSHandler.get_input_queue_url", return_value=None):
            routes = handler.get_routes()

        assert list(routes.values())[0]["POST"] == handler._handle_agent_chat

    def test_a_user_id_in_the_body_is_a_400_with_the_reason(self, handler):
        response = handler._handle_agent_chat({"body": json.dumps({"prompt": "hi", "session_id": "s1", "user_id": "u1"})}, None)

        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {
            "error": "user_id is not a request field; the acting user comes from the credential",
            "session_id": None,
        }
        handler._chat_service.process_chat_request.assert_not_called()

    def test_an_unreadable_body_is_a_400_too(self, handler):
        response = handler._handle_agent_chat({"body": "not json"}, None)

        assert response["statusCode"] == 400
        assert json.loads(response["body"])["error"].startswith("Expecting value")

    def test_a_valid_request_answers_with_the_chat_services_status(self, handler):
        handler._chat_service.process_chat_request.return_value = (202, {"result": "queued", "session_id": "s1"})

        response = handler._handle_agent_chat({"body": json.dumps({"prompt": "hi", "session_id": "s1"})}, None)

        assert (response["statusCode"], json.loads(response["body"])) == (202, {"result": "queued", "session_id": "s1"})

    def test_a_value_error_inside_the_chat_service_still_hides_behind_a_500(self, handler):
        """Only the parser's refusals are the caller's; the service's own failures keep their generic body."""
        handler._chat_service.process_chat_request.side_effect = ValueError("an internal invariant broke")

        response = handler._handle_agent_chat({"body": json.dumps({"prompt": "hi", "session_id": "s1"})}, None)

        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "Error processing request", "session_id": None}


class TestResponseStoreRecordPolling:
    def test_get_record_with_retry_polls_until_a_record_lands(self):
        from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore

        store = InMemoryResponseStore()
        store.add_message({"session_id": "s1", "request_id": "req-1", "status_code": 202, "body": {"status": "SCHEDULED"}})

        record = store.get_record_with_retry(request_id="req-1", get_and_delete=True)

        assert record["status_code"] == 202
        assert store.get_record("req-1") is None
