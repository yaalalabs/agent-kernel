"""Tests for the CloudWatch trace provider (trace/cloudwatch/).

OpenTelemetry's global tracer provider can be set only once per process, so these tests never
install one: `otel_globals` patches the `get_tracer_provider` / `set_tracer_provider` accessors
instead. Spans are recorded by a real SDK `TracerProvider` with an in-memory exporter.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from botocore.exceptions import NoCredentialsError
from botocore.session import Session as BotocoreSession
from google.rpc.status_pb2 import Status
from opentelemetry import baggage
from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import ProxyTracerProvider, StatusCode

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.framework.smolagents.smolagents import SmolagentsRunner
from agentkernel.trace.cloudwatch import cloudwatch as cloudwatch_mod
from agentkernel.trace.cloudwatch.cloudwatch import CloudWatch
from agentkernel.trace.cloudwatch.sigv4 import SigV4Session
from agentkernel.trace.cloudwatch.smolagents import CloudWatchSmolagentsRunner

_ENV = [
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
    "AWS_LAMBDA_FUNCTION_NAME",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))  # keep the developer's default region out
    monkeypatch.setattr(CloudWatch, "_configured", False)  # the once-guard is class-level


@pytest.fixture
def otel_globals(monkeypatch):
    """No SDK provider installed yet; `set_provider` captures the one CloudWatch installs."""
    set_provider = MagicMock()
    monkeypatch.setattr(trace_api, "get_tracer_provider", lambda: ProxyTracerProvider())
    monkeypatch.setattr(trace_api, "set_tracer_provider", set_provider)
    monkeypatch.setattr(cloudwatch_mod, "BatchSpanProcessor", MagicMock())  # no export thread
    return set_provider


@pytest.fixture
def exporter_cls(monkeypatch):
    exporter_cls = MagicMock(name="OTLPSpanExporter")
    monkeypatch.setattr(cloudwatch_mod, "OTLPSpanExporter", exporter_cls)
    return exporter_cls


@pytest.fixture
def recorder(monkeypatch):
    """An installed SDK provider recording finished spans in memory."""
    spans = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))
    set_provider = MagicMock()
    monkeypatch.setattr(trace_api, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(trace_api, "set_tracer_provider", set_provider)
    return provider, spans, set_provider


def _config(type_):
    cfg = MagicMock()
    cfg.trace.enabled = True
    cfg.trace.type = type_
    return cfg


def _installed_provider(set_provider) -> TracerProvider:
    set_provider.assert_called_once()
    return set_provider.call_args[0][0]


# --- factory and provider setup ---------------------------------------------------------------


def test_factory_builds_cloudwatch(monkeypatch, otel_globals, exporter_cls):
    from agentkernel.trace.trace import Trace

    monkeypatch.setenv("AWS_REGION", "us-west-2")
    with patch.object(AKConfig, "get", return_value=_config("cloudwatch")):
        trace = Trace.get()

    assert isinstance(trace._instance, CloudWatch)
    otel_globals.assert_called_once()


def test_init_installs_provider_once(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    CloudWatch().init()
    CloudWatch().init()  # every framework Module calls init() through Trace.get()

    otel_globals.assert_called_once()
    exporter_cls.assert_called_once()


def test_init_reuses_an_installed_sdk_provider(recorder, exporter_cls):
    provider, spans, set_provider = recorder

    CloudWatch().init()

    set_provider.assert_not_called()  # OpenTelemetry honours only the first provider registered
    exporter_cls.assert_not_called()


def test_default_export_is_signed_to_the_regional_xray_endpoint(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    CloudWatch().init()

    kwargs = exporter_cls.call_args.kwargs
    assert kwargs["endpoint"] == "https://xray.eu-west-1.amazonaws.com/v1/traces"
    assert isinstance(kwargs["session"], SigV4Session)
    assert (kwargs["session"].region, kwargs["session"].service) == ("eu-west-1", "xray")


def test_default_region_falls_back_to_aws_default_region(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")

    CloudWatch().init()

    assert exporter_cls.call_args.kwargs["endpoint"] == "https://xray.ap-southeast-2.amazonaws.com/v1/traces"


def test_china_regions_use_the_cn_partition(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "cn-north-1")

    CloudWatch().init()

    assert exporter_cls.call_args.kwargs["endpoint"] == "https://xray.cn-north-1.amazonaws.com.cn/v1/traces"


def test_configured_xray_endpoint_is_signed_for_its_own_region(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://xray.ap-south-1.amazonaws.com/v1/traces")

    CloudWatch().init()

    session = exporter_cls.call_args.kwargs["session"]
    assert isinstance(session, SigV4Session)
    assert session.region == "ap-south-1"
    assert "endpoint" not in exporter_cls.call_args.kwargs  # the exporter resolves the configured endpoint itself


@pytest.mark.parametrize(
    "variable, endpoint",
    [
        ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://cloudwatch-agent:4318"),
    ],
)
def test_collector_endpoint_is_exported_to_unsigned(monkeypatch, otel_globals, exporter_cls, variable, endpoint):
    monkeypatch.setenv(variable, endpoint)  # no region needed: the collector or CloudWatch agent signs

    CloudWatch().init()

    exporter_cls.assert_called_once_with()  # every OTEL_EXPORTER_OTLP_* variable applies as configured


def test_missing_region_raises_config_error(otel_globals, exporter_cls):
    with pytest.raises(AKConfigError) as exc_info:
        CloudWatch().init()

    assert "AWS_REGION" in str(exc_info.value)
    otel_globals.assert_not_called()


def test_resource_defaults_to_agent_kernel_agent_service(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    CloudWatch().init()

    attributes = _installed_provider(otel_globals).resource.attributes
    assert attributes["service.name"] == "AgentKernel"
    assert attributes["aws.service.type"] == "gen_ai_agent"


def test_resource_environment_overrides_the_defaults(monkeypatch, otel_globals, exporter_cls):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "billing-agent")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "aws.service.type=custom,deployment.environment.name=prod")

    CloudWatch().init()

    attributes = _installed_provider(otel_globals).resource.attributes
    assert attributes["service.name"] == "billing-agent"
    assert attributes["aws.service.type"] == "custom"
    assert attributes["deployment.environment.name"] == "prod"


# --- SigV4 signing ------------------------------------------------------------------------------


def _botocore_session(access_key="AKIDEXAMPLE", secret_key="secret", token="session-token") -> BotocoreSession:
    session = BotocoreSession()
    session.set_credentials(access_key, secret_key, token)
    return session


def test_sigv4_session_signs_each_request_for_xray():
    session = SigV4Session("us-west-2", botocore_session=_botocore_session())

    with patch("requests.Session.request", return_value=MagicMock(status_code=200)) as send:
        session.post("https://xray.us-west-2.amazonaws.com/v1/traces", data=b"\x0a\x00")

    headers = send.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-west-2/xray/aws4_request" in headers["Authorization"]
    assert headers["X-Amz-Security-Token"] == "session-token"
    assert "X-Amz-Date" in headers
    assert send.call_args.kwargs["data"] == b"\x0a\x00"  # the signed body is the body sent


def test_sigv4_session_logs_why_xray_rejected_the_export(caplog):
    # X-Ray answers a rejected export with an OTLP google.rpc.Status body; the exporter itself only logs "Bad Request"
    reason = "The OTLP API is supported with CloudWatch Logs as a Trace Segment Destination."
    rejected = requests.Response()
    rejected.status_code, rejected.reason, rejected._content = 400, "Bad Request", Status(code=3, message=reason).SerializeToString()
    session = SigV4Session("us-west-2", botocore_session=_botocore_session())

    with patch("requests.Session.request", return_value=rejected):
        with caplog.at_level(logging.ERROR, logger="ak.trace.cloudwatch"):
            response = session.post("https://xray.us-west-2.amazonaws.com/v1/traces", data=b"")

    assert response is rejected  # the exporter still sees the failure
    assert f"X-Ray in us-west-2 rejected the span export (HTTP 400): {reason}" in caplog.text  # the region shows a mismatch


def test_sigv4_session_without_credentials_fails_the_export():
    botocore_session = MagicMock()
    botocore_session.get_credentials.return_value = None
    session = SigV4Session("us-west-2", botocore_session=botocore_session)

    with patch("requests.Session.request") as send:
        with pytest.raises(NoCredentialsError):  # logged by the batch processor, never sent unsigned
            session.post("https://xray.us-west-2.amazonaws.com/v1/traces", data=b"")

    send.assert_not_called()


# --- agent run spans ----------------------------------------------------------------------------


async def _run(runner, prompt="q", session_id="s1"):
    return await runner.run(MagicMock(), Session(session_id), [AgentRequestText(prompt=prompt)])


@pytest.mark.asyncio
async def test_runner_wraps_the_run_in_a_session_span(recorder):
    provider, spans, _ = recorder
    tracer = CloudWatch()
    tracer.init()

    reply = AgentReplyText(response="hi", prompt="q")
    with patch.object(SmolagentsRunner, "run", AsyncMock(return_value=reply)):
        result = await _run(CloudWatchSmolagentsRunner(tracer))

    assert result is reply
    (span,) = spans.get_finished_spans()
    assert span.name == "Agent Kernel Smolagents"
    assert span.attributes["session.id"] == "s1"
    assert span.attributes["input.value"] == "q"
    assert span.attributes["output.value"] == "hi"


@pytest.mark.asyncio
async def test_runner_records_the_error_on_the_span(recorder):
    provider, spans, _ = recorder
    tracer = CloudWatch()
    tracer.init()

    with patch.object(SmolagentsRunner, "run", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await _run(CloudWatchSmolagentsRunner(tracer))

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]


@pytest.mark.asyncio
async def test_instrumentor_spans_inside_the_run_carry_the_session_id(recorder):
    provider, spans, _ = recorder
    tracer = CloudWatch()
    tracer.init()

    async def framework_run(*args):
        # stands in for an OpenInference instrumentor emitting LLM/tool spans during the run
        with provider.get_tracer("openinference").start_as_current_span("llm"):
            pass
        return AgentReplyText(response="hi", prompt="q")

    with patch.object(SmolagentsRunner, "run", AsyncMock(side_effect=framework_run)):
        await _run(CloudWatchSmolagentsRunner(tracer), session_id="s42")

    llm = next(span for span in spans.get_finished_spans() if span.name == "llm")
    assert llm.attributes["session.id"] == "s42"
    assert baggage.get_baggage("session.id") is None  # the run's session does not leak past it


@pytest.mark.asyncio
async def test_lambda_flushes_after_each_run(monkeypatch, recorder):
    provider, spans, _ = recorder
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "agent")
    monkeypatch.setattr(provider, "force_flush", MagicMock(return_value=True))
    tracer = CloudWatch()
    tracer.init()

    with patch.object(SmolagentsRunner, "run", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await _run(CloudWatchSmolagentsRunner(tracer))

    provider.force_flush.assert_called_once()  # failed runs are flushed too, before the sandbox freezes


@pytest.mark.asyncio
async def test_no_flush_outside_lambda(monkeypatch, recorder):
    provider, spans, _ = recorder
    monkeypatch.setattr(provider, "force_flush", MagicMock(return_value=True))
    tracer = CloudWatch()
    tracer.init()

    with patch.object(SmolagentsRunner, "run", AsyncMock(return_value=AgentReplyText(response="hi", prompt="q"))):
        await _run(CloudWatchSmolagentsRunner(tracer))

    provider.force_flush.assert_not_called()  # the batch processor exports in the background


# --- framework runners --------------------------------------------------------------------------


def test_runners_subclass_their_framework_base_and_activate_instrumentation(recorder):
    import agentkernel.trace.cloudwatch.adk as adk_mod
    import agentkernel.trace.cloudwatch.openai as openai_mod
    import agentkernel.trace.cloudwatch.pydanticai as pydanticai_mod
    from agentkernel.framework.adk.adk import GoogleADKRunner
    from agentkernel.framework.langgraph.langgraph import LangGraphRunner
    from agentkernel.framework.openai.openai import OpenAIRunner
    from agentkernel.framework.pydanticai.pydanticai import PydanticAIRunner

    tracer = CloudWatch()
    with patch.object(openai_mod, "OpenAIAgentsInstrumentor") as openai_instrumentor:
        assert isinstance(tracer.openai(), OpenAIRunner)
    openai_instrumentor.return_value.instrument.assert_called_once()

    with patch.object(adk_mod, "GoogleADKInstrumentor") as adk_instrumentor:
        assert isinstance(tracer.adk(), GoogleADKRunner)
    adk_instrumentor.return_value.instrument.assert_called_once()

    with patch.object(pydanticai_mod, "Agent") as agent_cls, patch.object(pydanticai_mod, "OpenInferenceSpanProcessor"):
        assert isinstance(tracer.pydanticai(), PydanticAIRunner)
    agent_cls.instrument_all.assert_called_once()

    assert isinstance(tracer.langgraph(), LangGraphRunner)
    assert isinstance(tracer.smolagents(), SmolagentsRunner)


def test_crewai_runner_activates_crewai_and_litellm_instrumentation(recorder):
    pytest.importorskip("crewai")  # the crewai extra conflicts with the test extra in CI
    import agentkernel.trace.cloudwatch.crewai as crewai_mod
    from agentkernel.framework.crewai.crewai import CrewAIRunner

    with patch.object(crewai_mod, "CrewAIInstrumentor") as crewai_instrumentor, patch.object(crewai_mod, "LiteLLMInstrumentor") as litellm:
        assert isinstance(CloudWatch().crewai(), CrewAIRunner)
    crewai_instrumentor.return_value.instrument.assert_called_once_with(skip_dep_check=True)
    litellm.return_value.instrument.assert_called_once()
