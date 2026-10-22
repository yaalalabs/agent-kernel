"""Tests for PayloadCodec — the JSON-safe rule behind AgentReplyAny.content and DataMessage.content.

Both halves are covered here: `normalise`, which runs as a field validator on every payload
construction, and `encode`, which the serialisation gates call in place of `json.dumps`. The two
documented bypasses are pinned as tested behaviour so nobody builds on a guarantee that is not there.
"""

import datetime
import decimal
import enum
import json
import uuid

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.model import AgentReplyAny
from agentkernel.core.util.payload import JSONPayload, PayloadCodec


class Colour(enum.Enum):
    RED = "red"


class Reading(BaseModel):
    observed_at: datetime.datetime
    amount: decimal.Decimal
    reading_id: uuid.UUID


class Payload(BaseModel):
    """Minimal holder so the annotated type is exercised through pydantic, not called directly."""

    content: JSONPayload


class TestNormaliseCoercion:
    """Values with a canonical JSON form are converted silently."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ({"at": datetime.datetime(2026, 9, 22, 14, 30)}, {"at": "2026-09-22T14:30:00"}),
            ({"on": datetime.date(2026, 9, 22)}, {"on": "2026-09-22"}),
            ({"amount": decimal.Decimal("250.00")}, {"amount": "250.00"}),
            ({"colour": Colour.RED}, {"colour": "red"}),
            ({"blob": b"hi"}, {"blob": "hi"}),
            ({1: "x"}, {"1": "x"}),
            ({"plain": 1, "nested": {"flag": True, "none": None}}, {"plain": 1, "nested": {"flag": True, "none": None}}),
        ],
    )
    def test_coerces(self, value, expected):
        assert Payload(content=value).content == expected

    def test_set_becomes_a_list(self):
        content = Payload(content={"tags": {"a", "b"}}).content

        assert sorted(content["tags"]) == ["a", "b"]

    def test_uuid_becomes_its_string(self):
        identifier = uuid.uuid4()

        assert Payload(content={"id": identifier}).content == {"id": str(identifier)}

    def test_top_level_list_is_accepted(self):
        content = [{"createSurface": {"surfaceId": "s1"}}, {"updateComponents": {}}]

        assert Payload(content=content).content == content


class TestNormaliseRejection:
    """Values with no JSON form raise at construction rather than reaching a surface."""

    def test_unserialisable_object_raises(self):
        with pytest.raises(ValidationError, match="not JSON-serialisable"):
            Payload(content={"row": object()})

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_floats_raise(self, value):
        with pytest.raises(ValidationError, match="have no JSON form"):
            Payload(content={"x": value})

    def test_non_finite_error_names_the_key_path(self):
        with pytest.raises(ValidationError, match=r"content\['stats'\]\['avg'\]"):
            Payload(content={"stats": {"avg": float("nan")}})

    def test_non_finite_inside_a_list_is_found(self):
        with pytest.raises(ValidationError, match=r"content\['xs'\]\[1\]"):
            Payload(content={"xs": [1.0, float("inf")]})

    @pytest.mark.parametrize("value", ["hello", 4, True, None])
    def test_non_object_top_level_raises(self, value):
        with pytest.raises(ValidationError, match="must be a JSON object or array"):
            Payload(content=value)

    def test_non_utf8_bytes_raise(self):
        """bytes coerce only when decodable; this is rule 4 territory, not rule 3."""
        with pytest.raises(ValidationError, match="not JSON-serialisable"):
            Payload(content={"blob": b"\xff\xfe"})


class TestConvergence:
    """The whole point of the rule, in one assertion."""

    def test_pydantic_and_plain_dict_routes_agree(self):
        observed_at = datetime.datetime(2026, 9, 22, 14, 30)
        amount = decimal.Decimal("250.00")
        reading_id = uuid.uuid4()

        from_model = AgentReplyAny.from_output(Reading(observed_at=observed_at, amount=amount, reading_id=reading_id))
        from_dict = AgentReplyAny(content={"observed_at": observed_at, "amount": amount, "reading_id": reading_id})

        assert from_model.content == from_dict.content


class TestEncode:
    """The half the serialisation gates use."""

    def test_encodes_a_plain_body(self):
        body = {"result": "hello", "session_id": "s-1"}

        assert json.loads(PayloadCodec.encode(body)) == body

    def test_encodes_a_value_that_bypassed_normalise(self):
        """A datetime reaching a gate must serialise, not raise — this is why `encode` exists."""
        body = {"result": {"at": datetime.datetime(2026, 9, 22, 14, 30)}, "session_id": "s-1"}

        with pytest.raises(TypeError):
            json.dumps(body)

        assert json.loads(PayloadCodec.encode(body)) == {"result": {"at": "2026-09-22T14:30:00"}, "session_id": "s-1"}

    def test_encodes_a_list_body(self):
        assert json.loads(PayloadCodec.encode([{"a": 1}])) == [{"a": 1}]


class TestBypasses:
    """Pinned so nobody builds on a guarantee that is not there."""

    def test_model_copy_replacing_content_skips_normalisation(self):
        reply = AgentReplyAny(content={"a": 1})

        copied = reply.model_copy(update={"content": {"at": datetime.datetime(2026, 9, 22, 14, 30)}})

        assert isinstance(copied.content["at"], datetime.datetime)

    def test_model_copy_updating_only_media_type_is_safe(self):
        reply = AgentReplyAny(content={"at": datetime.datetime(2026, 9, 22, 14, 30)})

        copied = reply.model_copy(update={"media_type": "application/a2ui+json"})

        assert copied.content == {"at": "2026-09-22T14:30:00"}
        assert copied.media_type == "application/a2ui+json"

    def test_in_place_mutation_skips_normalisation(self):
        reply = AgentReplyAny(content={"a": 1})

        reply.content["at"] = datetime.datetime(2026, 9, 22, 14, 30)

        assert isinstance(reply.content["at"], datetime.datetime)


class TestGatesUseTheCodec:
    """One gate is left, and the rest of the tree is allowed to use plain ``json.dumps``.

    That is the design, not an omission. Two places apply the rule structurally — ``content``
    through `JSONPayload` and ``QueueMessage.body`` through `JSONText` — and the response builder
    re-normalises the one value that can reach a client as an object, so anything it returns
    survives ``json.dumps`` (`TestTheResponseBodyIsJSONSafe`). A deployment adapter that writes the
    obvious call is correct, which is why the adapters no longer carry a gate each.

    ``serialize_message_body`` keeps its gate because it also serves ``SQSHandler``'s direct
    callers, whose bodies never passed through a `QueueMessage` or the response builder.

    The thread recorder is the one place that could use the codec and deliberately does not: it
    mirrors ``AgentReplyAny.__str__``'s own ``json.dumps(default=str)`` so the queue path and the
    direct path hold identical bytes for the same reply, which matters more there than agreeing
    with the live response.
    """

    def test_a_body_that_bare_json_rejects_still_encodes(self):
        body = {"result": {"at": datetime.datetime(2026, 9, 22, 14, 30), "amount": decimal.Decimal("250.00")}, "session_id": "s-1"}

        with pytest.raises(TypeError):
            json.dumps(body)

        assert json.loads(PayloadCodec.encode(body)) == {"result": {"at": "2026-09-22T14:30:00", "amount": "250.00"}, "session_id": "s-1"}

    def test_sqs_transport_gate_serializes_a_dict_body(self):
        from agentkernel.pipeline.transport.sqs import serialize_message_body

        assert json.loads(serialize_message_body({"result": {"at": datetime.datetime(2026, 9, 22, 14, 30)}})) == {
            "result": {"at": "2026-09-22T14:30:00"}
        }

    def test_sqs_transport_gate_passes_strings_through(self):
        from agentkernel.pipeline.transport.sqs import serialize_message_body

        assert serialize_message_body("already encoded") == "already encoded"

    def test_the_deployment_adapters_carry_no_gate_of_their_own(self):
        """Pinned so nobody reinstates one: the guarantee is upstream, and duplicating it here
        taught the next reader that the seam is responsible for it."""
        from agentkernel.deployment.aws.core import websocket_service
        from agentkernel.deployment.aws.serverless.core.router import rest_lambda
        from agentkernel.deployment.azure import akfunction
        from agentkernel.pipeline import request_handler

        for module in (rest_lambda, akfunction, request_handler, websocket_service):
            assert not hasattr(module, "PayloadCodec"), f"{module.__name__} re-imported PayloadCodec"


class TestTheResponseBodyIsJSONSafe:
    """The invariant that lets every deployment adapter write a plain ``json.dumps``.

    A seam that serialises a response body is written by whoever adds the next deployment target,
    and they have no way to know a codec exists. So the body itself carries the guarantee: anything
    `build_response` returns survives ``json.dumps``, and the obvious code is the correct code. The
    object form is the only branch that can carry a payload, so it is the only branch that
    re-normalises — every other value in the body is a `str` already.
    """

    def _bypassed(self, content):
        """The reply shape the field validator cannot reach: `content` replaced after validation."""
        reply = AgentReplyAny(content={"a": 1}, media_type="application/a2ui+json")
        return reply.model_copy(update={"content": content})

    def test_a_bypassed_payload_is_normalised_before_it_leaves(self):
        from agentkernel.core.chat_service import ResponseBuilder

        reply = self._bypassed({"at": datetime.datetime(2026, 9, 22, 14, 30)})
        body = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=reply)

        assert body["result"] == {"at": "2026-09-22T14:30:00"}
        assert json.dumps(body)

    def test_a_deployment_adapter_can_use_bare_json_dumps(self):
        """Stated as the thing a new seam's author is allowed to assume."""
        from agentkernel.core.chat_service import ResponseBuilder

        reply = self._bypassed({"at": datetime.datetime(2026, 9, 22, 14, 30)})
        _status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=reply)

        assert json.dumps(body) == PayloadCodec.encode(body)

    def test_a_bypassed_nan_is_reported_rather_than_shipped_as_null(self):
        """Why the strict `normalise` runs here and not the lenient `encode`.

        Rendering it as `null` would be indistinguishable from a field the agent chose to omit,
        which is the harm Decision 8 refuses at construction. A reply assembled in-process can
        afford to say so: the error names the key path, where `null` ships wrong data in silence.
        """
        from agentkernel.core.chat_service import ResponseBuilder

        reply = self._bypassed({"stats": {"avg": float("nan")}})

        with pytest.raises(ValueError, match=r"avg.*nan"):
            ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=reply)

    def test_an_unlabelled_reply_is_not_touched(self):
        """The re-normalisation sits in the labelled branch only; nothing else pays for it."""
        from agentkernel.core.chat_service import ResponseBuilder

        content = {"city": "Colombo", "temp_c": 31}
        body = ResponseBuilder.build_response(200, "s1", rest_api_mode=True, result=AgentReplyAny(content=content))

        assert body["result"] == json.dumps(content)


class TestQueueBodyIsText:
    """``QueueMessage.body`` carries JSON text, and the envelope is what makes that true.

    The alternative was a rule every sender had to remember. It would have held in development and
    broken in production: the SQS, Kafka and NATS transports call ``.encode()`` on the body and
    raise ``AttributeError`` on a dict, while the in-memory transport stores the envelope as an
    object and never notices.
    """

    def test_a_dict_body_is_encoded_on_validation(self):
        from agentkernel.pipeline.envelope import QueueMessage

        body = {"result": {"at": datetime.datetime(2026, 9, 22, 14, 30)}, "session_id": "s1"}

        assert QueueMessage(body=body).body == '{"result": {"at": "2026-09-22T14:30:00"}, "session_id": "s1"}'

    def test_an_array_body_is_encoded_too(self):
        from agentkernel.pipeline.envelope import QueueMessage

        assert QueueMessage(body=[{"createSurface": {"surfaceId": "s1"}}]).body == '[{"createSurface": {"surfaceId": "s1"}}]'

    def test_a_string_body_is_untouched(self):
        """Every sender in the tree encodes for itself today; none of their bytes may change."""
        from agentkernel.pipeline.envelope import QueueMessage

        encoded = json.dumps({"prompt": "hi", "session_id": "s1"})

        assert QueueMessage(body=encoded).body == encoded
        assert QueueMessage().body == ""

    def test_a_scalar_body_is_still_rejected(self):
        """The annotation widens the field to objects, not to anything at all."""
        from agentkernel.pipeline.envelope import QueueMessage

        with pytest.raises(ValidationError):
            QueueMessage(body=42)

    def test_the_queue_runner_sends_the_body_without_encoding_it(self):
        """`_send_to_output` hands the envelope a dict; this is what makes that safe."""
        from unittest.mock import MagicMock

        from agentkernel.pipeline.agent_runner import AgentRunner
        from agentkernel.pipeline.envelope import QueueMessage

        transport = MagicMock()
        source = QueueMessage(body="{}", attributes={"request_id": "r1"}, group_id="s1", dedup_id="d1")

        AgentRunner(transport=transport, chat_service=MagicMock())._send_to_output(
            source, {"result": {"amount": decimal.Decimal("250.00")}, "session_id": "s1"}, 200
        )

        sent = transport.send.call_args.args[1]
        assert json.loads(sent.body) == {"result": {"amount": "250.00"}, "session_id": "s1"}
