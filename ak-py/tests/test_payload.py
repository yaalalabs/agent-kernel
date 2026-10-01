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
