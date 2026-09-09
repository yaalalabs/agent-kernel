import datetime
import json

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.model import AgentReply, AgentReplyAny


class WeatherReport(BaseModel):
    city: str
    temp_c: int
    observed_at: datetime.datetime


class TestAgentReplyAny:
    """Test construction, serialization and __str__ of AgentReplyAny"""

    def test_construction_and_defaults(self):
        reply = AgentReplyAny(content={"a": 1})

        assert reply.content == {"a": 1}
        assert reply.prompt == ""
        assert reply.type == "other"

    def test_str_returns_json(self):
        content = {"city": "Colombo", "temp_c": 31}
        reply = AgentReplyAny(content=content)

        assert str(reply) == json.dumps(content)
        # Must be parseable JSON, not a Python repr
        assert json.loads(str(reply)) == content

    def test_serialization(self):
        reply = AgentReplyAny(content={"k": "v"}, prompt="the prompt")

        dumped = reply.model_dump()
        assert dumped == {"content": {"k": "v"}, "prompt": "the prompt", "type": "other"}
        assert json.loads(reply.model_dump_json()) == dumped

    def test_non_dict_content_raises(self):
        with pytest.raises(ValidationError):
            AgentReplyAny(content="not a dict")


class TestAgentReplyAnyFromOutput:
    """Test the from_output classmethod used by framework runners"""

    def test_pydantic_instance_converted_via_model_dump_json_mode(self):
        model = WeatherReport(city="Colombo", temp_c=31, observed_at=datetime.datetime(2026, 7, 8, 12, 0))

        reply = AgentReplyAny.from_output(model, "weather?")

        assert isinstance(reply, AgentReplyAny)
        assert reply.prompt == "weather?"
        # mode="json" serializes the datetime, so str(reply) cannot fail
        assert reply.content == {"city": "Colombo", "temp_c": 31, "observed_at": "2026-07-08T12:00:00"}
        assert json.loads(str(reply)) == reply.content

    def test_dict_used_as_content_directly(self):
        content = {"k": "v"}

        reply = AgentReplyAny.from_output(content)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == content
        assert reply.prompt == ""

    def test_unstructured_values_return_none(self):
        assert AgentReplyAny.from_output("plain text") is None
        assert AgentReplyAny.from_output(42) is None
        assert AgentReplyAny.from_output(None) is None
        assert AgentReplyAny.from_output(["a", "b"]) is None
