"""The unchanged Lambda queue workers already serve A2A and MCP in the REST modes (#932, spec Deviation 3).

A2A and MCP call ``RestHandler.request(body, protocol)``: it enqueues one message tagged with ``protocol`` and
waits for one whole reply in the response store. This file runs that call over the real serverless wire:

    RestHandler.request -> SQSTransport -> [input queue] -> ServerlessAgentRunner.handle
        -> SQSHandler -> [output queue] -> ResponseHandler.handle -> InMemoryResponseStore -> RestHandler.request

Only two things are faked: the boto3 SQS client (its two queues are the two Lambda handlers, standing in for the
Event Source Mapping) and the agent (``ChatService``). The Lambda workers ignore the ``protocol`` tag; in the REST
modes that is enough, because the Lambda response handler stores every reply and every permanent failure, which is
exactly what ``RestHandler.request`` reads. If a worker is ever changed so that this stops being true, these tests fail.
"""

import uuid
from typing import Any

import pytest

from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.config import AKConfig, _ExecutionConfig, _QueuesConfig, _ResponseStoreConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyText, BaseRunRequest, ExecutionMode
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner
from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler
from agentkernel.pipeline.envelope import ATTR_PROTOCOL
from agentkernel.pipeline.request_handler import ReplyTimeoutError, RestHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.sqs import SQSTransport

pytestmark = pytest.mark.asyncio

INPUT_URL = "https://sqs.test/input.fifo"
OUTPUT_URL = "https://sqs.test/output.fifo"
# The wait budget the request side reads from config: two reads, no pause, so a timeout test is instant.
RETRY_COUNT = 2
DELAY = 0.0


class FakeSQS:
    """A boto3 SQS client whose two queues are the two real Lambda handlers.

    ``send_message`` receives exactly the keyword arguments boto3 would, turns them into the record an Event Source
    Mapping hands a Lambda, and runs the handler that consumes that queue.
    """

    def __init__(self) -> None:
        self.input_records: list[dict[str, Any]] = []
        self.output_records: list[dict[str, Any]] = []
        self.batch_failures: list[dict[str, str]] = []
        # What SQS reports as how many times the input message was delivered.
        self.input_receive_count = 1
        # True when no worker is attached to the input queue.
        self.drop_input = False

    def send_message(self, QueueUrl: str, **kwargs: Any) -> dict[str, str]:
        record = self._as_lambda_record(kwargs, receive_count=self.input_receive_count if QueueUrl == INPUT_URL else 1)
        if QueueUrl == INPUT_URL:
            self.input_records.append(record)
            if not self.drop_input:
                self.batch_failures += ServerlessAgentRunner.handle({"Records": [record]}, None)["batchItemFailures"]
        elif QueueUrl == OUTPUT_URL:
            self.output_records.append(record)
            self.batch_failures += ResponseHandler.handle({"Records": [record]}, None)["batchItemFailures"]
        else:
            raise AssertionError(f"Unexpected queue url {QueueUrl}")
        return {"MessageId": record["messageId"]}

    @staticmethod
    def _as_lambda_record(send_kwargs: dict[str, Any], receive_count: int) -> dict[str, Any]:
        """The boto3 ``send_message`` arguments, as the record a Lambda receives (camelCase keys)."""
        system_attributes = {
            "MessageGroupId": send_kwargs.get("MessageGroupId"),
            "MessageDeduplicationId": send_kwargs.get("MessageDeduplicationId"),
            "ApproximateReceiveCount": str(receive_count),
        }
        return {
            "messageId": str(uuid.uuid4()),
            "body": send_kwargs["MessageBody"],
            "attributes": {name: value for name, value in system_attributes.items() if value is not None},
            "messageAttributes": {
                name: {"stringValue": attribute["StringValue"], "dataType": attribute["DataType"]}
                for name, attribute in send_kwargs.get("MessageAttributes", {}).items()
            },
        }


class FakeChatService:
    """Stands in for the agent: answers with the body ``ResponseBuilder`` builds, which is what a runner really sends."""

    def __init__(self) -> None:
        self.requests: list[BaseRunRequest] = []
        self.status_code = 200
        self.reply: Any = None
        self.error: Exception | None = None
        self.raises: Exception | None = None

    def process_chat_request(self, req: BaseRunRequest, requests: Any = None) -> tuple[int, dict[str, Any]]:
        self.requests.append(req)
        if self.raises is not None:
            raise self.raises
        result = self.reply if self.reply is not None else AgentReplyText(response=f"echo:{req.prompt}")
        # `rest_api_mode=False` is the queue-mode body shape. #959 (remove direct mode) removes this parameter, so whichever
        # of #959 and #932 merges second drops it here.
        return ResponseBuilder.build_response(self.status_code, req.session_id, rest_api_mode=False, result=result, error=self.error)


class WiredRestHandler(RestHandler):
    """A ``RestHandler`` on the given transport and store, through the same override seams subclasses use."""

    def __init__(self, transport: SQSTransport, store: InMemoryResponseStore):
        super().__init__()
        self._wired = (transport, store)

    def get_transport(self) -> SQSTransport:
        return self._wired[0]

    def get_response_store(self) -> InMemoryResponseStore:
        return self._wired[1]


class LambdaPipeline:
    """The whole serverless queue pipeline, wired for one test."""

    def __init__(self, handler: WiredRestHandler, sqs: FakeSQS, store: InMemoryResponseStore, chat: FakeChatService):
        self.handler = handler
        self.sqs = sqs
        self.store = store
        self.chat = chat

    @staticmethod
    def body(**overrides: Any) -> BaseRunRequest:
        return BaseRunRequest(**{"prompt": "hi", "session_id": "s1", "agent": "triage", **overrides})


@pytest.fixture(params=[ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC], ids=["rest_sync", "rest_async"])
def pipeline(request, monkeypatch) -> LambdaPipeline:
    """The unchanged Lambda workers behind a real SQS transport, once per in-scope execution mode."""

    # The real default config with only `execution` replaced: the handler base classes read other sections too.
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    AKConfig._reset()
    execution = _ExecutionConfig(
        mode=request.param,
        queues=_QueuesConfig(type="sqs"),
        response_store=_ResponseStoreConfig(type="dynamodb", retry_count=RETRY_COUNT, delay=DELAY),
    )
    execution.queues.input.url = INPUT_URL
    execution.queues.output.url = OUTPUT_URL
    config = AKConfig.get().model_copy(update={"execution": execution})
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))

    InMemoryResponseStore.reset()
    sqs = FakeSQS()
    store = InMemoryResponseStore()
    chat = FakeChatService()

    # SQSHandler caches its queue urls and client on the class; the Lambda workers read them from there.
    monkeypatch.setattr(SQSHandler, "_input_queue_url", INPUT_URL)
    monkeypatch.setattr(SQSHandler, "_output_queue_url", OUTPUT_URL)
    monkeypatch.setattr(SQSHandler, "_sqs_client", sqs)
    monkeypatch.setattr(ServerlessAgentRunner, "_chat_service", chat)
    monkeypatch.setattr(ResponseHandler, "_response_store", store)

    transport = SQSTransport(INPUT_URL, OUTPUT_URL)
    monkeypatch.setattr(transport, "_client", sqs)
    yield LambdaPipeline(WiredRestHandler(transport, store), sqs, store, chat)
    InMemoryResponseStore.reset()
    AKConfig._reset()


@pytest.mark.parametrize("protocol", ["a2a", "mcp"])
class TestAReplyReachesTheCaller:
    async def test_the_whole_reply_comes_back(self, pipeline, protocol):
        reply = await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert reply.status_code == 200
        assert not reply.is_error
        assert reply.result == "echo:hi"
        assert reply.body["session_id"] == "s1"

    async def test_the_agent_runs_once_on_the_callers_request(self, pipeline, protocol):
        await pipeline.handler.request(pipeline.body(prompt="plan my trip", agent="planner"), protocol=protocol)

        [seen] = pipeline.chat.requests
        assert (seen.prompt, seen.session_id, seen.agent) == ("plan my trip", "s1", "planner")

    async def test_the_tag_crosses_the_input_queue_and_the_unchanged_runner_tolerates_it(self, pipeline, protocol):
        await pipeline.handler.request(pipeline.body(), protocol=protocol)

        [record] = pipeline.sqs.input_records
        assert record["messageAttributes"][ATTR_PROTOCOL]["stringValue"] == protocol
        assert pipeline.sqs.batch_failures == []

    async def test_the_session_is_the_ordering_key_on_both_queues(self, pipeline, protocol):
        await pipeline.handler.request(pipeline.body(session_id="s-42"), protocol=protocol)

        [input_record] = pipeline.sqs.input_records
        [output_record] = pipeline.sqs.output_records
        assert input_record["attributes"]["MessageGroupId"] == "s-42"
        assert output_record["attributes"]["MessageGroupId"] == "s-42"

    async def test_the_stored_record_is_deleted_by_the_read(self, pipeline, protocol):
        reply = await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert pipeline.store.get_record(reply.request_id) is None

    async def test_a_labelled_reply_keeps_its_label_and_object(self, pipeline, protocol):
        pipeline.chat.reply = AgentReplyAny(content={"surface": "card"}, media_type="application/a2ui+json")

        reply = await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert reply.result == {"surface": "card"}
        assert reply.media_type == "application/a2ui+json"

    async def test_two_calls_on_one_session_each_get_their_own_reply(self, pipeline, protocol):
        first = await pipeline.handler.request(pipeline.body(prompt="one"), protocol=protocol)
        second = await pipeline.handler.request(pipeline.body(prompt="two"), protocol=protocol)

        assert (first.result, second.result) == ("echo:one", "echo:two")
        assert first.request_id != second.request_id


@pytest.mark.parametrize("protocol", ["a2a", "mcp"])
class TestAFailureReachesTheCaller:
    @pytest.mark.parametrize("status_code", [400, 500])
    async def test_an_error_status_the_agent_produced_is_returned_not_raised(self, pipeline, protocol, status_code):
        pipeline.chat.status_code = status_code
        pipeline.chat.error = ValueError("no such agent")

        reply = await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert reply.is_error
        assert reply.status_code == status_code
        assert reply.error

    async def test_a_permanent_failure_is_stored_as_a_500_and_returned(self, pipeline, protocol):
        # SQS delivered the message more often than input.max_receive_count: the runner reports a failure instead of running.
        pipeline.sqs.input_receive_count = 4

        reply = await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert reply.is_error
        assert reply.status_code == 500
        assert "Failed to process message" in reply.error
        assert reply.body["session_id"] == "s1"
        assert pipeline.chat.requests == []

    async def test_a_run_that_raises_is_retried_and_the_caller_times_out(self, pipeline, protocol):
        # Below max_receive_count the runner re-raises so SQS redelivers; nothing is stored in the meantime.
        pipeline.chat.raises = RuntimeError("model unavailable")

        with pytest.raises(ReplyTimeoutError):
            await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert len(pipeline.sqs.batch_failures) == 1
        assert pipeline.sqs.output_records == []

    async def test_no_worker_means_a_timeout_naming_the_budget(self, pipeline, protocol):
        pipeline.sqs.drop_input = True

        with pytest.raises(ReplyTimeoutError) as excinfo:
            await pipeline.handler.request(pipeline.body(), protocol=protocol)

        assert (excinfo.value.retry_count, excinfo.value.delay) == (RETRY_COUNT, DELAY)
        assert excinfo.value.request_id == pipeline.sqs.input_records[0]["messageAttributes"]["request_id"]["stringValue"]
