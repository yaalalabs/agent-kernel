"""Provider-neutral model for fetching traces back from a tracing provider's cloud.

``TraceQuery`` is the generic filter every tracer translates into its own query language,
``FetchedSpan`` is the shape every tracer returns (with ``SpanUsage`` for its model call's tokens and
cost), and ``OTelSpanClassifier`` maps the raw
OpenTelemetry attribute conventions AK's runners emit (OpenInference, OTel GenAI, Traceloop,
Logfire native) onto one ``SpanKind``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field


class SpanKind(str, Enum):
    """What a span represents, independent of the provider's own vocabulary."""

    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    SPAN = "span"  # anything else: AK wrapper spans, turns, chains, workflows


class TraceQuery(BaseModel):
    """Generic filter for ``Trace.fetch()``; each tracer translates it to its provider's API."""

    start: Optional[datetime] = Field(default=None, description="Inclusive lower bound on span start time; defaults to end - last")
    end: Optional[datetime] = Field(default=None, description="Exclusive upper bound on span start time; defaults to now")
    last: timedelta = Field(default=timedelta(hours=1), description="Look-back window used when start is not given")
    kinds: Optional[list[SpanKind]] = Field(default=None, description="Only return spans of these kinds; None returns all")
    session_id: Optional[str] = Field(default=None, description="Only return spans belonging to this AK session")
    trace_ids: Optional[list[str]] = Field(default=None, description="Only return spans of these traces")
    name: Optional[str] = Field(default=None, description="Only return spans with exactly this name")
    limit: int = Field(default=1000, gt=0, description="Maximum number of spans to return; when more match, the most recent ones are kept")

    def window(self) -> tuple[datetime, datetime]:
        """Resolve the time window to timezone-aware UTC datetimes."""
        end = self._utc(self.end) if self.end else datetime.now(timezone.utc)
        start = self._utc(self.start) if self.start else end - self.last
        if start >= end:
            raise ValueError(f"fetch window start ({start.isoformat()}) must be before end ({end.isoformat()})")
        return start, end

    def accepts(self, kind: SpanKind) -> bool:
        return self.kinds is None or kind in self.kinds

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class SpanUsage(BaseModel):
    """Tokens and cost of the one model call a span records, never a roll-up of its children.

    Summing ``usage`` over a trace's spans gives the trace's total, so values the instrumentation already
    aggregates (Pydantic AI ``gen_ai.aggregated_usage.*``, the OpenAI Agents ``usage`` JSON on turn and
    workflow spans) are deliberately not read.
    """

    input_tokens: Optional[int] = Field(default=None, description="Prompt (input) tokens")
    output_tokens: Optional[int] = Field(default=None, description="Completion (output) tokens")
    total_tokens: Optional[int] = Field(default=None, description="Total tokens; input + output when the span reports no total")
    cost: Optional[float] = Field(default=None, description="Cost in USD, as the provider or instrumentation computed it")

    @classmethod
    def of(cls, input_tokens: Any = None, output_tokens: Any = None, total_tokens: Any = None, cost: Any = None) -> Optional[SpanUsage]:
        """Builds a usage from raw values (numbers or numeric strings), or None when none is known."""
        input_tokens, output_tokens, total_tokens = cls._int(input_tokens), cls._int(output_tokens), cls._int(total_tokens)
        cost = cls._float(cost)
        if input_tokens is None and output_tokens is None and total_tokens is None and cost is None:
            return None
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return cls(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens, cost=cost)

    @classmethod
    def _int(cls, value: Any) -> Optional[int]:
        number = cls._float(value)
        return None if number is None else int(number)

    @staticmethod
    def _float(value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class FetchedSpan(BaseModel):
    """One span (Langfuse: observation) fetched from a provider, in a provider-neutral envelope.

    ``input``/``output`` are returned as the provider stores them (often JSON strings); ``raw`` keeps the
    provider's full record so later normalisation never loses data.
    """

    provider: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: Optional[str] = None
    kind: SpanKind = SpanKind.SPAN
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    session_id: Optional[str] = None
    input: Any = None
    output: Any = None
    usage: Optional[SpanUsage] = None  # None when the span records no model call
    attributes: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def oldest_first(spans: Iterable[FetchedSpan]) -> list[FetchedSpan]:
        floor = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(spans, key=lambda span: span.start_time or floor)


class OTelSpanClassifier:
    """Classifies raw OTel spans and pulls their input/output, across the conventions AK emits.

    The convention is detected per span, not per provider, because one trace can mix them
    (e.g. Pydantic AI GenAI spans next to Traceloop ``openai.chat`` spans).
    """

    _OPENINFERENCE = {"AGENT": SpanKind.AGENT, "LLM": SpanKind.LLM, "TOOL": SpanKind.TOOL}
    _TRACELOOP = {"agent": SpanKind.AGENT, "tool": SpanKind.TOOL}
    _GEN_AI = {
        "invoke_agent": SpanKind.AGENT,
        "create_agent": SpanKind.AGENT,
        "execute_tool": SpanKind.TOOL,
        "chat": SpanKind.LLM,
        "text_completion": SpanKind.LLM,
        "generate_content": SpanKind.LLM,
    }
    # Logfire's OpenAI Agents instrumentation carries no kind attribute, only message templates
    _LOGFIRE_TEMPLATES = {"Function:": SpanKind.TOOL, "Agent run:": SpanKind.AGENT}

    # (input key, output key) pairs, most specific first
    _IO_KEYS = [
        ("gen_ai.tool.call.arguments", "gen_ai.tool.call.result"),
        ("input.value", "output.value"),
        ("gen_ai.input.messages", "gen_ai.output.messages"),
        ("langfuse.observation.input", "langfuse.observation.output"),
        ("traceloop.entity.input", "traceloop.entity.output"),
        ("input", "output"),
    ]

    _SESSION_KEYS = ["session.id", "session_id", "traceloop.association.properties.session_id"]

    # per-call usage keys, first present wins: OTel GenAI, OpenInference, then older GenAI / Traceloop names
    _INPUT_TOKEN_KEYS = ["gen_ai.usage.input_tokens", "llm.token_count.prompt", "gen_ai.usage.prompt_tokens"]
    _OUTPUT_TOKEN_KEYS = ["gen_ai.usage.output_tokens", "llm.token_count.completion", "gen_ai.usage.completion_tokens"]
    _TOTAL_TOKEN_KEYS = ["gen_ai.usage.total_tokens", "llm.token_count.total", "llm.usage.total_tokens"]
    _COST_KEYS = ["operation.cost"]  # Pydantic AI's per-call cost

    @classmethod
    def classify(cls, attributes: dict[str, Any], name: Optional[str] = None) -> SpanKind:
        if (kind := cls._OPENINFERENCE.get(str(attributes.get("openinference.span.kind", "")).upper())) is not None:
            return kind
        if (kind := cls._TRACELOOP.get(str(attributes.get("traceloop.span.kind", "")).lower())) is not None:
            return kind
        if (kind := cls._GEN_AI.get(str(attributes.get("gen_ai.operation.name", "")))) is not None:
            return kind
        template = str(attributes.get("logfire.msg_template") or name or "")
        for prefix, kind in cls._LOGFIRE_TEMPLATES.items():
            if template.startswith(prefix):
                return kind
        if "LLM" in (attributes.get("logfire.tags") or []):
            return SpanKind.LLM
        return SpanKind.SPAN

    @classmethod
    def io(cls, attributes: dict[str, Any]) -> tuple[Any, Any]:
        for in_key, out_key in cls._IO_KEYS:
            if in_key in attributes or out_key in attributes:
                return attributes.get(in_key), attributes.get(out_key)
        return None, None

    @classmethod
    def usage(cls, attributes: dict[str, Any]) -> Optional[SpanUsage]:
        return SpanUsage.of(
            input_tokens=cls._first(attributes, cls._INPUT_TOKEN_KEYS),
            output_tokens=cls._first(attributes, cls._OUTPUT_TOKEN_KEYS),
            total_tokens=cls._first(attributes, cls._TOTAL_TOKEN_KEYS),
            cost=cls._first(attributes, cls._COST_KEYS),
        )

    @staticmethod
    def _first(attributes: dict[str, Any], keys: list[str]) -> Any:
        return next((attributes[key] for key in keys if attributes.get(key) is not None), None)

    @classmethod
    def session_id(cls, attributes: dict[str, Any]) -> Optional[str]:
        for key in cls._SESSION_KEYS:
            if attributes.get(key):
                return str(attributes[key])
        return None
