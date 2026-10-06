from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from typing import Iterator

from botocore.session import Session as BotocoreSession
from opentelemetry import baggage, context
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.environment_variables import OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ...core import Runner, Session
from ...core.util.factory import AKConfigError
from ..base import BaseTrace
from .sigv4 import SigV4Session

"""
Span attribute keys shared by OpenInference and CloudWatch GenAI Observability, which groups sessions by session.id.
"""
SESSION_ID = "session.id"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"

_XRAY_HOST = re.compile(r"^https://xray\.(?P<region>[a-z0-9-]+)\.amazonaws\.com(\.cn)?(/|$)")


class SessionSpanProcessor(SpanProcessor):
    """
    Stamps the session.id baggage entry onto every span started while it is set, so the spans framework
    instrumentors emit during an agent run carry the same session as the run's own span.
    """

    def on_start(self, span, parent_context=None):
        session_id = baggage.get_baggage(SESSION_ID, parent_context)
        if session_id is not None:
            span.set_attribute(SESSION_ID, session_id)


class CloudWatch(BaseTrace):

    _init_lock = threading.Lock()
    _configured = False

    def __init__(self):
        """
        Initializes a CloudWatch instance.
        """
        self._log = logging.getLogger("ak.trace.cloudwatch")
        self._tracer = trace_api.get_tracer("agentkernel.trace.cloudwatch")
        # a frozen Lambda sandbox never runs the batch processor's background export
        self._flush_after_run = "AWS_LAMBDA_FUNCTION_NAME" in os.environ

    def init(self):
        """
        Installs an OpenTelemetry tracer provider exporting to CloudWatch, once. Every framework Module triggers
        init() via Trace.get(), so it is guarded by a class-level lock and flag. A provider the AWS Distro for
        OpenTelemetry already installed (auto-instrumentation, the Lambda layer, AgentCore) is reused instead,
        since OpenTelemetry honours only the first provider registered.
        """
        with CloudWatch._init_lock:
            if CloudWatch._configured:
                return
            provider = trace_api.get_tracer_provider()
            if isinstance(provider, TracerProvider):
                self._log.info("Reusing the installed OpenTelemetry tracer provider for CloudWatch tracing")
            else:
                provider = TracerProvider(resource=self._resource())
                provider.add_span_processor(BatchSpanProcessor(self._exporter()))
                trace_api.set_tracer_provider(provider)
            provider.add_span_processor(SessionSpanProcessor())
            CloudWatch._configured = True
            self._log.debug("CloudWatch tracing configured")

    @contextmanager
    def span(self, name: str, session: Session) -> Iterator[trace_api.Span]:
        """
        Wraps one agent run in a span carrying the session id. The id is also set as session.id baggage for
        the run, so SessionSpanProcessor stamps it onto the instrumentors' child spans. On Lambda the provider
        is flushed after the run, before the sandbox can freeze.
        :param name: The span name.
        :param session: The session the agent runs in.
        """
        token = context.attach(baggage.set_baggage(SESSION_ID, session.id))
        try:
            with self._tracer.start_as_current_span(name, attributes={SESSION_ID: session.id}) as span:
                yield span
        finally:
            context.detach(token)
            if self._flush_after_run:
                self._flush()

    def _flush(self):
        """
        Exports the spans the batch processor still holds.
        """
        provider = trace_api.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.force_flush()

    @staticmethod
    def _resource() -> Resource:
        """
        The resource OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES describe, with Agent Kernel's defaults filled
        in only where they set nothing: service.name, and the aws.service.type marker ADOT sets for agents.
        """
        detected = Resource.create()
        defaults = {}
        if str(detected.attributes.get(SERVICE_NAME, "")).startswith("unknown_service"):
            defaults[SERVICE_NAME] = "AgentKernel"
        if "aws.service.type" not in detected.attributes:
            defaults["aws.service.type"] = "gen_ai_agent"
        return detected.merge(Resource(defaults))

    @staticmethod
    def _exporter() -> OTLPSpanExporter:
        """
        Exports to the endpoint OTEL_EXPORTER_OTLP_TRACES_ENDPOINT or OTEL_EXPORTER_OTLP_ENDPOINT names, defaulting
        to the regional X-Ray OTLP endpoint. X-Ray accepts SigV4 auth only, so an X-Ray endpoint gets a signing
        session; any other (the CloudWatch agent, an OpenTelemetry collector) is exported to as configured.
        """
        configured = os.environ.get(OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) or os.environ.get(OTEL_EXPORTER_OTLP_ENDPOINT)
        if configured:
            match = _XRAY_HOST.match(configured)
            if match is None:
                return OTLPSpanExporter()
            return OTLPSpanExporter(session=SigV4Session(match["region"]))

        botocore_session = BotocoreSession()
        region = os.environ.get("AWS_REGION") or botocore_session.get_config_variable("region")
        if not region:
            raise AKConfigError(
                "trace.type: cloudwatch needs an AWS region to reach the X-Ray OTLP endpoint; set AWS_REGION, "
                "or point OTEL_EXPORTER_OTLP_TRACES_ENDPOINT at a collector or the CloudWatch agent"
            )
        domain = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
        return OTLPSpanExporter(
            endpoint=f"https://xray.{region}.{domain}/v1/traces",
            session=SigV4Session(region, botocore_session=botocore_session),
        )

    def openai(self) -> Runner:
        """
        Returns the CloudWatch OpenAI runner instance.
        """
        from .openai import CloudWatchOpenAIRunner

        return CloudWatchOpenAIRunner(self)

    def langgraph(self) -> Runner:
        """
        Returns the CloudWatch LangGraph runner instance.
        """
        from .langgraph import CloudWatchLangGraphRunner

        return CloudWatchLangGraphRunner(self)

    def crewai(self) -> Runner:
        """
        Returns the CloudWatch CrewAI runner instance.
        """
        from .crewai import CloudWatchCrewAIRunner

        return CloudWatchCrewAIRunner(self)

    def adk(self) -> Runner:
        """
        Returns the CloudWatch ADK runner instance.
        """
        from .adk import CloudWatchADKRunner

        return CloudWatchADKRunner(self)

    def smolagents(self) -> Runner:
        """
        Returns the CloudWatch Smolagents runner instance.
        """
        from .smolagents import CloudWatchSmolagentsRunner

        return CloudWatchSmolagentsRunner(self)

    def pydanticai(self) -> Runner:
        """
        Returns the CloudWatch Pydantic AI runner instance.
        """
        from .pydanticai import CloudWatchPydanticAIRunner

        return CloudWatchPydanticAIRunner(self)
