# #803: Agent evaluation on production traffic — Implementation Spec

This spec details how to build the three phases [design.md](design.md) requires: Phase 1 (fetch) in Agent
Kernel core, and Phases 2 (evaluate) and 3 (store) in the `aws-serverless/langfuse-trace-evaluation`
example.

**Phase 1** adds a `fetch_spans(query)` method to `BaseTrace` and `Trace.fetch_spans(...)` / `Trace.fetch_traces(...)` facades.
It also adds a provider-neutral query/result model in `trace/fetch.py`, plus one fetcher class per
built-in tracer in `trace/<provider>/fetch.py`. Each fetcher translates the generic `TraceQuery` into
its provider's read API and returns `FetchedSpan`s. Three small changes complete it: a Logfire scrubbing
callback, so session ids survive export, `httpx` in two extras, and a shared `CloudWatch.region()`
lookup that the CloudWatch exporter and fetcher both use.

Where design.md leaves an open question, this spec follows the design's recommendation or its stated
default, and says so inline.

## Phase 1 design (Agent Kernel core)

### Package layout

```
ak-py/src/agentkernel/trace/
├── __init__.py          # + exports FetchedSpan, FetchedTrace, OTelSpanClassifier, SpanKind, SpanStatus, SpanUsage, TraceQuery
├── base.py              # + BaseTrace.fetch_spans (non-abstract)
├── trace.py             # + Trace.fetch_spans and fetch_traces facades
├── fetch.py             # NEW: SpanKind, SpanStatus, TraceQuery, SpanUsage, FetchedSpan, FetchedTrace, OTelSpanClassifier, TraceFetcher
├── testing.py           # NEW: TraceFetchContract (imports pytest; test code only)
├── langfuse/
│   ├── langfuse.py      # + LangFuse.fetch_spans → LangfuseTraceFetcher; + LangFuse.flush_on_lambda
│   ├── <6 runners>.py   # each run() flushes through LangFuse.flush_on_lambda in a finally
│   └── fetch.py         # NEW: LangfuseTraceFetcher
├── logfire/
│   ├── logfire.py       # + Logfire.fetch_spans → LogfireTraceFetcher; scrubbing callback in init()
│   └── fetch.py         # NEW: LogfireTraceFetcher
├── openllmetry/
│   ├── openllmetry.py   # + OpenLLMetry.fetch_spans → TraceloopTraceFetcher
│   └── fetch.py         # NEW: TraceloopTraceFetcher
└── cloudwatch/
    ├── cloudwatch.py    # + CloudWatch.fetch_spans → CloudWatchTraceFetcher; + CloudWatch.region()
    └── fetch.py         # NEW: CloudWatchTraceFetcher
```

The provider packages' `__init__.py` files are empty today and stay empty. So
`agentkernel.trace.<provider>.fetch` can be imported without the provider SDK.

### Rules

1. **Fetchers never read `AKConfig`.** Each fetcher takes explicit constructor parameters: a client,
   a token, a base URL, an optional transport. The tracer class builds its fetcher and resolves the
   credentials AK reads itself (`LOGFIRE_READ_TOKEN`, `TRACELOOP_API_KEY`) through
   `SecretManager.current().get(key, None)`, which reads `AKConfig.secret`. This is the same rule as
   the shared DB drivers and transports.
2. **Fetcher modules import no provider SDK at module scope.**
   - `langfuse/fetch.py` imports `Langfuse` under `TYPE_CHECKING` only.
   - `logfire/fetch.py` imports `LogfireQueryClient` inside `_collect()`.
   - `openllmetry/fetch.py` imports only `httpx`, which the core test environment already has.
   - `cloudwatch/fetch.py` imports `botocore` and the `CloudWatch` tracer module (which pulls in the
     OpenTelemetry SDK) inside `_create_client()`, used only when no client is injected.
   - This keeps the fetchers testable without the extras.
3. **Classification is per span, never per provider.** Every OTel-shaped result (Logfire, Traceloop and CloudWatch)
   goes through `OTelSpanClassifier`. Langfuse already types its observations server-side, so its
   types are mapped directly. Fetchers map each provider's fields onto the neutral ones but don't patch over a
   provider's own mistakes: Langfuse's `SPAN` type is not re-classified, and callers trust `kind` and `status`.
4. **Same result contract for every tracer.**
   - Spans come back oldest first, with at most `limit` of them; when more match, the most recent are
     kept.
   - Span ids are unique.
   - `raw` holds the provider record.
   - `fetch` itself never parses or rewrites `input`/`output`.
5. **Every fetcher applies `TraceQuery.matches` to every span**, whatever its server-side filters
   already did (window, kinds, session, trace ids, name). The check is strict: a span that doesn't
   report a value for an active filter (start time, session id, name) is rejected, never assumed to
   match. So a provider's undocumented boundary rule (Logfire's `max_timestamp`, Traceloop's whole
   seconds, CloudWatch's `@timestamp`) can't leak into the result.
6. **Paging, dedupe and limit accounting live once, in `TraceFetcher`** (§`trace/fetch.py`). The four
   fetchers subclass it and implement only their requests and their `_to_span` mapping.
7. **Every fetch implementation passes `TraceFetchContract`** where its backend can be faked faithfully
   (§`trace/testing.py`).

### `trace/fetch.py`

```python
class SpanKind(str, Enum):
    AGENT = "agent"; LLM = "llm"; TOOL = "tool"; SPAN = "span"

class SpanStatus(str, Enum):                  # the OpenTelemetry span status
    UNSET = "unset"; OK = "ok"; ERROR = "error"

    @classmethod
    def of(cls, value: Any) -> "SpanStatus": ...   # "ERROR" / "STATUS_CODE_ERROR" / OTLP 2 -> ERROR; "OK" / 1 -> OK;
                                                    # None, bool or anything unknown -> UNSET

class TraceQuery(BaseModel):
    start: Optional[datetime] = None          # inclusive, on span start time
    end: Optional[datetime] = None            # exclusive; defaults to now
    last: timedelta = timedelta(hours=1)      # used only when start is None
    kinds: Optional[list[SpanKind]] = None    # None = all
    session_id: Optional[str] = None
    trace_ids: Optional[list[str]] = None
    name: Optional[str] = None
    limit: int = Field(default=1000, gt=0)

    def window(self) -> tuple[datetime, datetime]: ...   # UTC-aware; ValueError if start >= end
    def accepts(self, kind: SpanKind) -> bool: ...       # kinds is None or kind in kinds
    def matches(self, span: FetchedSpan) -> bool: ...    # start <= start_time < end, session, trace ids, name, kind;
                                                          # an active filter needs a matching reported value:
                                                          # a None start_time, session_id or name is rejected

class SpanUsage(BaseModel):                   # one model call's usage, never a roll-up
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None        # input + output when the span reports no total
    cost: Optional[float] = None              # USD, as the provider/instrumentation reported it

    @classmethod
    def of(cls, input_tokens=None, output_tokens=None, total_tokens=None, cost=None) -> Optional["SpanUsage"]: ...
        # coerces numbers / numeric strings; drops non-numeric values and bools; None when nothing is known

class FetchedSpan(BaseModel):
    provider: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: Optional[str] = None
    kind: SpanKind = SpanKind.SPAN
    status: SpanStatus = SpanStatus.UNSET     # mapped from the provider's own field (see each fetcher)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    session_id: Optional[str] = None
    input: Any = None
    output: Any = None
    usage: Optional[SpanUsage] = None         # None when the span records no model call
    attributes: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    @staticmethod
    def oldest_first(spans: Iterable["FetchedSpan"]) -> list["FetchedSpan"]: ...
        # sort key: start_time, with None sorting first (datetime.min UTC)

class FetchedTrace(BaseModel):                # the spans of one trace id
    trace_id: str
    session_id: Optional[str] = None          # the first session id found on its spans
    spans: list[FetchedSpan] = []             # oldest first

    @property
    def root(self) -> Optional[FetchedSpan]: ...      # the single span with parent_span_id None, else None
    @property
    def user_input(self) -> Any: ...                  # root.input; None without a root
    @property
    def output(self) -> Any: ...                      # root.output; None without a root
    @property
    def started_at(self) -> Optional[datetime]: ...   # root.start_time
    @property
    def ended_at(self) -> Optional[datetime]: ...     # root.end_time
    @property
    def tool_spans(self) -> list[FetchedSpan]: ...    # kind == TOOL
    @property
    def agent_names(self) -> list[str]: ...           # kind == AGENT names, de-duplicated, in order
    @property
    def usage(self) -> SpanUsage: ...                 # summed over the spans; a field stays None when none reports it

    @classmethod
    def group(cls, spans: Iterable[FetchedSpan]) -> list["FetchedTrace"]: ...
        # groups by trace_id in input order; traces ordered by their first span

class OTelSpanClassifier:
    @classmethod
    def classify(cls, attributes: dict, name: str | None = None) -> SpanKind: ...
    @classmethod
    def io(cls, attributes: dict) -> tuple[Any, Any]: ...
    @classmethod
    def session_id(cls, attributes: dict) -> str | None: ...
    @classmethod
    def usage(cls, attributes: dict) -> SpanUsage | None: ...

class TraceFetcher(ABC):                      # base of the four built-in fetchers
    provider: ClassVar[str]                   # written to every FetchedSpan.provider

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]: ...
        # pins the window, runs _collect, keeps the first span per span_id, returns oldest_first(...)[-limit:]
    @abstractmethod
    def _collect(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...   # the provider's requests
    def _follow_cursor(self, query: TraceQuery,
                       page: Callable[[str | None], tuple[list[Any], str | None]],
                       to_span: Callable[[Any], FetchedSpan]) -> list[FetchedSpan]: ...
    def _page_backward(self, query: TraceQuery, before: datetime, max_rows: int,
                       page: Callable[[int, datetime], list[tuple[datetime | None, FetchedSpan]]]) -> list[FetchedSpan]: ...
```

- Every field gets a `Field(description=...)`. `kinds` accepts plain strings (`["tool"]`) through
  Pydantic enum coercion.
- `window()`:
  - A naive `datetime` gets `tzinfo=UTC`; an aware one is converted to UTC.
  - `end` defaults to `datetime.now(timezone.utc)`.
- `OTelSpanClassifier.classify` precedence (first hit wins):

  | # | Attribute | Mapping |
  |---|---|---|
  | 1 | `openinference.span.kind` (upper-cased) | `AGENT`→agent, `LLM`→llm, `TOOL`→tool |
  | 2 | `traceloop.span.kind` (lower-cased) | `agent`→agent, `tool`→tool |
  | 3 | `gen_ai.operation.name` | `invoke_agent`,`create_agent`→agent; `execute_tool`→tool; `chat`,`text_completion`,`generate_content`→llm |
  | 4 | `logfire.msg_template`, else `name` | prefix `Function:`→tool, `Agent run:`→agent |
  | 5 | `"LLM" in logfire.tags` | llm |
  | 6 | — | span |

  - Values outside a row's mapping fall through to the next row. For example, OpenInference `CHAIN`
    and Traceloop `workflow` fall through and end as `span`.
- `OTelSpanClassifier.io`: the first `(input key, output key)` pair where either key is present:
  1. `gen_ai.tool.call.arguments` / `.result`
  2. `input.value` / `output.value`
  3. `gen_ai.input.messages` / `gen_ai.output.messages`
  4. `langfuse.observation.input` / `.output`
  5. `traceloop.entity.input` / `.output`
  6. `input` / `output`
- `OTelSpanClassifier.session_id`: the first truthy value among `session.id`, `session_id`,
  `traceloop.association.properties.session_id`. `gen_ai.conversation.id` is deliberately excluded,
  because it is the framework's conversation id, not AK's session.
- `OTelSpanClassifier.usage`: `SpanUsage.of(...)` over the first non-`None` value of each key list:

  | Field | Keys, in order |
  |---|---|
  | `input_tokens` | `gen_ai.usage.input_tokens`, `llm.token_count.prompt`, `gen_ai.usage.prompt_tokens` |
  | `output_tokens` | `gen_ai.usage.output_tokens`, `llm.token_count.completion`, `gen_ai.usage.completion_tokens` |
  | `total_tokens` | `gen_ai.usage.total_tokens`, `llm.token_count.total`, `llm.usage.total_tokens` |
  | `cost` | `operation.cost` |

  - First column per row: current OTel GenAI names; second: OpenInference; third: the deprecated GenAI
    names and Traceloop's own total, for older instrumentation.
  - Not read, because they are roll-ups that would double-count when summed over a trace: Pydantic AI's
    `gen_ai.aggregated_usage.*` (agent-run span) and the OpenAI Agents `usage` JSON (Logfire turn and
    workflow spans, which also carry it on each chat span).
  - Attributes arrive flattened for CloudWatch (`CloudWatchTraceFetcher._flatten`), so nested
    `llm.token_count` objects resolve to the same keys.
- `TraceQuery.matches` resolves `window()` on every call, so a defaulted `end` (now) would move between
  calls. `TraceFetcher.fetch_spans` therefore pins it first: `query = query.model_copy(update={"start": start,
  "end": end})`, and every later step uses that copy.
- `FetchedSpan.provider` is the tracer's `trace.type` short name, so it round-trips with config:
  `langfuse`, `logfire`, `openllmetry` (not `traceloop`) and `cloudwatch`. Each fetcher sets it from its
  `provider` class variable.
- `TraceFetcher` (house pattern 3: shared logic is lifted, not copied):
  - `_follow_cursor(query, page, to_span)`: the cursor loop Langfuse and Traceloop share. Calls
    `page(cursor)` for `(items, next_cursor)`, maps each item with `to_span`, keeps it when
    `query.matches`. Stops when `next_cursor` is empty, `items` is empty, `next_cursor` equals the
    cursor just sent, or `query.limit` spans are kept. Both APIs page newest first, so the kept spans
    are the most recent.
    - The repeated-cursor stop matters because local filtering can keep `limit` from ever being
      reached; a backend that returned the same cursor would otherwise page forever.
  - `_page_backward(query, before, max_rows, page)`: the backward time paging Logfire and CloudWatch
    share, for APIs with a row cap and no cursor. `page(size, before)` returns `(cursor timestamp,
    span)` rows, newest first, at or before `before`. Per page, with `size = min(max_rows, limit -
    kept)`:
    1. Drop rows whose span id was already seen.
    2. Set `span.session_id = span.session_id or query.session_id` (both callers filter by session
       server-side), then keep the fresh spans that `query.matches`.
    3. Set `before` to the oldest cursor timestamp among the fresh rows. Rows at that boundary are
       re-read by the next page and dropped in step 1.
    4. Stop when `len(rows) < size`, when no fresh row has a cursor timestamp, or when `limit` spans are
       kept. A full page with no fresh rows (more than `size` rows at one timestamp) logs a warning and
       stops, so it can't spin on a block of identical timestamps.
  - Not exported from `agentkernel.trace`: it is the built-ins' shared implementation. Bring-your-own
    tracers override `BaseTrace.fetch_spans` and only have to pass `TraceFetchContract`.
- Module-level functions: none. All logic is on these classes.
- `FetchedTrace.root` is `None` for no parentless span **and** for several; `fetch_traces` still returns the trace
  (design.md §Result model: `FetchedTrace`). `fetch_traces` is one pass over `fetch_spans`, so a trace at the window
  edge can be partial, and AK doesn't wait for late spans.

### `BaseTrace.fetch_spans`, `Trace.fetch_spans` and `Trace.fetch_traces`

```python
# trace/base.py
class BaseTrace(ABC):
    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        raise NotImplementedError(f"{type(self).__name__} does not support fetching spans")

# trace/trace.py
class Trace(BaseTrace):
    def fetch_spans(self, query: TraceQuery | None = None, **filters) -> list[FetchedSpan]:
        if self._instance is None:
            raise AKConfigError("cannot fetch spans: tracing is disabled (set trace.enabled: true)")
        if query is not None and filters:
            raise ValueError("pass either a TraceQuery or keyword filters, not both")
        return self._instance.fetch_spans(query if query is not None else TraceQuery(**filters))

    def fetch_traces(self, query: TraceQuery | None = None, **filters) -> list[FetchedTrace]:
        query = query if query is not None else TraceQuery(**filters)
        if query.kinds is not None or query.name is not None:
            raise ValueError("fetch_traces does not take kinds or name; filter the returned trace's spans instead")
        return FetchedTrace.group(self.fetch_spans(query))
```

- `base.py` imports `FetchedSpan`/`TraceQuery` from `.fetch`. There is no import cycle: `fetch.py`
  imports only stdlib and pydantic.
- Unknown keyword filters raise Pydantic's `ValidationError`, because `TraceQuery` is built from them.
- `query` combined with keyword filters raises `ValueError` (design.md §Public API).
- `fetch_traces` is built once on `fetch_spans`, so a bring-your-own tracer that overrides only `fetch_spans` gets it.
  `kinds` and `name` raise `ValueError` because they select single spans, not traces. Tracing disabled raises the
  same `AKConfigError`, through `fetch_spans`.

### `LangFuse.fetch_spans` → `LangfuseTraceFetcher`

```python
class LangfuseTraceFetcher(TraceFetcher):
    provider = "langfuse"
    _PAGE_SIZE = 100
    _FIELDS = "core,basic,time,io,metadata,model,usage,metrics"
    _EXPAND_METADATA = "attributes"           # metadata values over 200 chars are truncated unless listed
    _TYPES = {SpanKind.AGENT: "AGENT", SpanKind.LLM: "GENERATION", SpanKind.TOOL: "TOOL"}

    def __init__(self, client: "Langfuse"): ...
    def _collect(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _types(self, query) -> list[str | None]: ...      # [None] when kinds is None or contains SPAN
    def _page(self, query, langfuse_type, trace_id, cursor) -> tuple[list[Any], str | None]: ...
    def _to_span(self, observation) -> FetchedSpan: ...
```

- `LangFuse.fetch_spans(query)` returns `LangfuseTraceFetcher(self._client).fetch_spans(query)`. `self._client` is
  the client `init()` builds with `get_client()` (`trace/langfuse/langfuse.py:24`).
- Request matrix: `for type in _types(query)` × `for trace_id in query.trace_ids or [None]`. Each cell
  runs one `_follow_cursor` over `_page`, which calls `client.api.observations.get_many(...)` with these
  parameters:
  - `fields=_FIELDS`, `expand_metadata=_EXPAND_METADATA`, `limit=min(100, query.limit)`, `cursor`
  - `type`, `trace_id`, `session_id=query.session_id`, `name=query.name`
  - `from_start_time=start`, `to_start_time=end`
- Each cell keeps up to `query.limit` spans; `TraceFetcher.fetch_spans` merges the cells, keeping the first
  span per id, and returns the newest `limit`.
- `_to_span` field mapping:

  | `FetchedSpan` | from the observation |
  |---|---|
  | `trace_id`, `span_id` | `trace_id`, `id` |
  | `parent_span_id` | `parent_observation_id` |
  | `kind` | `_TYPES` reversed, default `span`. Not re-classified from attributes: a span Langfuse types `SPAN` stays `span` (design.md §Span kinds) |
  | `status` | `ERROR` when `level` is `ERROR`, else `UNSET`. `level` is in the `basic` field group, which `_FIELDS` already requests |
  | `session_id`, `input`, `output` | same-named fields, read with `getattr`, default `None` |
  | `usage` | `_usage`: `SpanUsage.of(usage_details["input"], ["output"], ["total"], cost=total_cost, else cost_details["total"])` |
  | `attributes` | `metadata["attributes"]` if `metadata` is a dict holding that key, else `metadata`, else `{}` |
  | `raw` | `observation.model_dump(mode="json", exclude_none=True)` |

### `Logfire.fetch_spans` → `LogfireTraceFetcher`

```python
class LogfireTraceFetcher(TraceFetcher):
    provider = "logfire"
    READ_TOKEN_ENV = "LOGFIRE_READ_TOKEN"
    _MAX_ROWS = 10_000
    _COLUMNS = "trace_id, span_id, parent_span_id, span_name, message, start_timestamp, end_timestamp, attributes, tags, otel_scope_name"
    _KIND_SQL: dict[SpanKind, str]            # SQL equivalents of OTelSpanClassifier rows 1–5

    def __init__(self, read_token: str | None, base_url: str | None = None): ...   # None → AKConfigError
    def _collect(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _sql(self, query, limit: int, before: datetime) -> str: ...
    @staticmethod
    def _literal(value: str) -> str: ...      # "'" + value.replace("'", "''") + "'"
    def _to_span(self, row: dict) -> FetchedSpan: ...
```

- Token: `Logfire.fetch_spans` passes `SecretManager.current().get("LOGFIRE_READ_TOKEN", None)` (design.md
  §Configuration). The secret manager reads the environment first, so an `env` deployment behaves as
  a plain `os.getenv`, and an `aws_ssm` deployment reads the token from SSM without exporting it. A
  `None` token raises `AKConfigError` naming `LOGFIRE_READ_TOKEN` in the constructor.
- Client: `from logfire.experimental.query_client import LogfireQueryClient`. That path exists in
  every `logfire>=3.0`; `logfire.query_client` is a later alias. Used as a context manager, with
  `base_url=None` letting the SDK take the region from the token.
- SQL shape:
  `SELECT {_COLUMNS} FROM records WHERE kind = 'span' AND … ORDER BY start_timestamp DESC LIMIT {page}`,
  plus these conditions:

  | Query field | Condition |
  |---|---|
  | `kinds` without `span` | `(_KIND_SQL[k1] OR _KIND_SQL[k2] …)` |
  | `kinds` with `span` | `(NOT COALESCE(<all three _KIND_SQL OR'd>, false) OR <requested non-span kinds>)` |
  | `name` | `COALESCE(message, span_name) = 'x'`, the same value `_to_span` writes to `name`, so `matches` keeps every row it selects |
  | `trace_ids` | `trace_id IN ('a', 'b')` |
  | `session_id` | `trace_id IN (SELECT trace_id FROM records WHERE attributes->>'session_id' = 's')` |
  | page cursor | `start_timestamp <= '<iso>'` |

  - `_KIND_SQL[TOOL]`: `gen_ai.operation.name = 'execute_tool'` OR `openinference.span.kind = 'TOOL'`
    OR `span_name LIKE 'Function:%'`.
  - `_KIND_SQL[LLM]`: `gen_ai.operation.name IN ('chat','text_completion','generate_content')` OR
    `openinference.span.kind = 'LLM'` OR `array_has(tags, 'LLM')`.
  - `_KIND_SQL[AGENT]`: `gen_ai.operation.name IN ('invoke_agent','create_agent')` OR
    `openinference.span.kind = 'AGENT'` OR `span_name LIKE 'Agent run:%'`.
  - The window is passed as `min_timestamp=start, max_timestamp=end`, never in SQL, so Logfire's
    timestamp index is used. Whether `max_timestamp` is inclusive is undocumented; `matches` applies
    the exclusive end either way.
- Paging: `_page_backward(query, before=end, max_rows=_MAX_ROWS, page=...)`, where each page runs
  `_sql(query, size, before)` and returns `(start_time, span)` rows. The first page's `before = end`
  repeats the `max_timestamp` bound, so every page has the same SQL shape.
- `_to_span`:
  - `attributes` = `row["attributes"]`, JSON-decoded if it arrives as a string.
  - Classification uses `{**attributes, "logfire.msg_template": span_name, "logfire.tags": tags or []}`.
    Logfire stores the template as `span_name` and tags in their own column.
  - `name` = `message` (the formatted message), else `span_name`.
  - `status` = `SpanStatus.of(row["otel_status_code"])`; `otel_status_code` is added to `_COLUMNS`. **Unverified against a
    live account**: a wrong column name would fail every query, so confirm it before merge.
  - `usage` = `OTelSpanClassifier.usage(attributes)`.
  - `raw` = the row as returned.

#### Scrubbing fix (`trace/logfire/logfire.py`)

```python
logfire.configure(
    service_name="AgentKernel",
    send_to_logfire="if-token-present",
    scrubbing=logfire.ScrubbingOptions(callback=Logfire._keep_session_id),
)

@staticmethod
def _keep_session_id(match):            # logfire.ScrubMatch
    return match.value if match.path == ("attributes", "session_id") else None
```

- Returning `None` keeps Logfire's redaction for every other match (the `ScrubbingOptions.callback`
  contract). The once-guard (`trace/logfire/logfire.py:29-31`) is unchanged.

### `OpenLLMetry.fetch_spans` → `TraceloopTraceFetcher`

```python
class TraceloopTraceFetcher(TraceFetcher):
    provider = "openllmetry"
    DEFAULT_BASE_URL = "https://api.traceloop.com"
    _PATH = "/v2/warehouse/spans"
    _PAGE_SIZE = 500
    _TIMEOUT = 60.0
    _SESSION_ATTRIBUTE = "traceloop.association.properties.session_id"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None): ...   # None key → AKConfigError
    def _collect(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _params(self, query) -> dict: ...
    def _page(self, client: httpx.Client, params: dict, cursor: str | None) -> tuple[list[dict], str | None]: ...
    def _to_span(self, item: dict) -> FetchedSpan: ...
    @staticmethod
    def _timestamp(value) -> datetime | None: ...
```

- Credentials, resolved by `OpenLLMetry.fetch_spans` and passed in:
  - API key: `SecretManager.current().get("TRACELOOP_API_KEY", None)`, as for Logfire's read token. A
    `None` key raises `AKConfigError` naming `TRACELOOP_API_KEY` in the constructor.
  - Base URL: `os.environ.get("TRACELOOP_BASE_URL")` (not a secret), else `DEFAULT_BASE_URL`.
  - These are the variables the SDK itself reads (`traceloop/sdk/__init__.py:120-121` in traceloop-sdk
    0.62.3).
  - `transport` exists only so tests can inject an `httpx.MockTransport`.
- Request: `httpx.Client(base_url=..., headers={"Authorization": f"Bearer {key}"}, timeout=60)`, with
  these params:
  - `from_timestamp_sec` / `to_timestamp_sec`: `int(start.timestamp())` / `math.ceil(end.timestamp())`, so
    the last partial second isn't cut off; the exact end is applied locally
  - `limit`: `min(500, query.limit)`
  - `sort_by=timestamp`, `sort_order=desc`
  - `span_name`: when `name` is set
  - `filters`: a JSON list of `{id, operator, value}`:
    - `session_id` → `_SESSION_ATTRIBUTE equals …`
    - `trace_ids` → `trace_id in […]`
    - No kind filter: `kinds` is applied only locally, by `matches`.
      - A span's kind can come from either `gen_ai.operation.name` or `traceloop.span.kind`
        (`OTelSpanClassifier` rows 2 and 3). The SDK's own `@tool` / `@agent` decorators set only
        `traceloop.span.kind`, and the LangGraph / CrewAI / ADK / smolagents instrumentations are
        uncaptured (`research/span-formats.md` §2). A server-side filter on either attribute alone would
        drop spans `matches` can't rescue.
      - The `filters` operators all act on one id, and the API documents no OR across ids
        (`research/provider-read-apis.md` §3), so the two attributes can't be sent as one condition.
      - Cost: a kind-filtered fetch pages through every span of the window. Traceloop's free-plan
        retention is 24 hours, so a window stays small.
- Pagination: one `_follow_cursor` over `_page`. Response body `{"spans": {"data": [...], "next_cursor":
  ...}}`; a body without `spans` is read as the page itself. Each page re-sends the same params with
  `cursor=...`.
- `_to_span`:
  - `attributes` = `span_attributes`, JSON-decoded if it arrives as a string.
  - `parent_span_id` = `parent_span_id or None` (the API may return `""` for a root span).
  - `input`/`output` = the item's top-level `input`/`output` when not `None`, else `OTelSpanClassifier.io`.
  - `end_time` = `start_time + timedelta(milliseconds=duration_ms)` when both are known.
  - `status` = `SpanStatus.of(item["status_code"] or item["status"])`; the warehouse's status field name is
    undocumented and unverified against a live account.
  - `usage` = `OTelSpanClassifier.usage(attributes)`. Top-level warehouse columns (the API sorts by
    `total_tokens`) are not read: their names are undocumented.
- `_timestamp`, because the warehouse format is undocumented:
  - A non-numeric string → `datetime.fromisoformat` (with `Z` → `+00:00`).
  - A number → epoch ns if `> 1e17`, µs if `> 1e14`, ms if `> 1e11`, otherwise seconds; always UTC.

### `CloudWatch.fetch_spans` → `CloudWatchTraceFetcher`

```python
class CloudWatchTraceFetcher(TraceFetcher):
    provider = "cloudwatch"
    LOG_GROUP = "aws/spans"
    _MAX_ROWS = 10_000
    _POLL_INTERVAL = 1.0
    _END_PADDING = timedelta(minutes=15)
    _FAILED = {"Failed", "Cancelled", "Timeout", "Unknown"}
    _KIND_FILTERS: dict[SpanKind, str]        # Logs Insights equivalents of OTelSpanClassifier rows 1 and 3

    def __init__(self, client=None, region: str | None = None, log_group: str = LOG_GROUP, timeout: float = 120.0): ...
    def _collect(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _create_client(self): ...                      # botocore "logs" client, region via CloudWatch.region()
    def _run(self, client, query_string: str, start: datetime, end: datetime) -> list[dict[str, str]]: ...
    def _insights(self, query: TraceQuery, limit: int) -> str: ...
    @staticmethod
    def _literal(value: str) -> str: ...               # json.dumps(value)
    def _to_span(self, row: dict) -> tuple[datetime | None, FetchedSpan]: ...  # (@timestamp, span)
    @classmethod
    def _flatten(cls, attributes: dict, prefix: str = "") -> dict: ...
    @staticmethod
    def _nanos(value) -> datetime | None: ...
    @staticmethod
    def _stamp(value: str | None) -> datetime | None: ...
```

```python
# trace/cloudwatch/cloudwatch.py
class CloudWatch(BaseTrace):
    @staticmethod
    def region(botocore_session: BotocoreSession) -> str | None:
        return os.environ.get("AWS_REGION") or botocore_session.get_config_variable("region")

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        from .fetch import CloudWatchTraceFetcher
        return CloudWatchTraceFetcher().fetch_spans(query)
```

- `CloudWatch.region()` is the expression `_exporter()` used inline (`trace/cloudwatch/cloudwatch.py:137`),
  lifted out unchanged. `_exporter()` keeps its own missing-region and malformed-region errors; botocore
  validates the region name for the fetcher's client.
- Client: the injected `client` if given. Otherwise `BotocoreSession().create_client("logs", region_name=...)`,
  with the region from the argument, else `CloudWatch.region()`. No region → `AKConfigError`.
  - The constructor arguments exist for callers that manage their own AWS sessions, and for tests.
- One Logs Insights query (`_run`):
  1. `client.start_query(logGroupName=log_group, startTime=floor(start), endTime=ceil(end), queryString=...)`,
     with times in epoch seconds. AWS treats both ends as inclusive. A `ResourceNotFoundException`
     becomes `AKConfigError` (§Phase 1 error handling); `botocore.exceptions` is imported inside `_run`,
     keeping rule 2.
  2. Poll `client.get_query_results(queryId=...)` every `_POLL_INTERVAL` seconds.
     - `Complete` → rows, each turned into a `{field: value}` dict.
     - A status in `_FAILED` → `RuntimeError` naming it.
     - Still running when `timeout` elapses → `client.stop_query(queryId=...)`, then `TimeoutError`.
- Query string, joined with ` | `:

  | Part | Logs Insights |
  |---|---|
  | always | `fields @timestamp, @message` … `sort @timestamp desc` … `limit {page}` |
  | `kinds` without `span` | `filter <_KIND_FILTERS[k1]> or <_KIND_FILTERS[k2]> …` |
  | `kinds` with `span` | no kind filter; kinds are checked locally |
  | `name` | `filter name = "x"` |
  | `trace_ids` | `filter traceId in ["a", "b"]` |
  | `session_id` | `filter attributes.session.id = "s"` |

  - `_KIND_FILTERS[TOOL]`: `attributes.gen_ai.operation.name = "execute_tool"` or
    `attributes.openinference.span.kind = "TOOL"`.
  - `_KIND_FILTERS[LLM]`: `attributes.gen_ai.operation.name in ["chat", "text_completion", "generate_content"]`
    or `attributes.openinference.span.kind = "LLM"`.
  - `_KIND_FILTERS[AGENT]`: `attributes.gen_ai.operation.name in ["invoke_agent", "create_agent"]` or
    `attributes.openinference.span.kind = "AGENT"`.
  - Traceloop and Logfire conventions are left out: no CloudWatch runner emits them.
  - Literals are `json.dumps(str(value))`: double-quoted, with `"` and `\` backslash-escaped.
  - The session filter needs no trace subquery (Logs Insights has none anyway), because
    `SessionSpanProcessor` stamps `session.id` onto every span of a run (`trace/cloudwatch/cloudwatch.py:35-44`).
- Window and paging (`_collect`):
  - `_page_backward(query, before=max(end, min(end + _END_PADDING, now)), max_rows=_MAX_ROWS, page=...)`,
    where each page runs one `_run` over `[start, before]` and returns `(@timestamp, span)` rows.
    `@timestamp`'s relation to the span start is not documented, so the range runs past `end`, and
    `matches` applies `start <= start_time < end` locally on `startTimeUnixNano`.
  - Each query's `endTime` is `ceil(before)`, so rows in the boundary second are re-read and dropped
    by span id. More than a page of spans in one second hits the base's warn-and-stop rule.
  - 10,000-row pages: `StartQuery` now accepts `limit` up to 100,000, but `GetQueryResults` returns at
    most 10,000 rows per call and needs `nextToken` beyond that, which botocore releases inside the
    `cloudwatch` extra's `>=1.41.4` range may not model (`research/provider-read-apis.md` §6).
- `_to_span`:
  - `raw` = `json.loads(row["@message"])`, the span's OTel JSON.
  - `attributes` = `_flatten(raw["attributes"])`: nested dicts become dotted keys, flat keys stay as
    they are, so the classifier sees `openinference.span.kind` either way.
  - `trace_id`, `span_id`, `name` = `traceId`, `spanId`, `name`; `parent_span_id` = `parentSpanId or None`.
  - `start_time` / `end_time` = `startTimeUnixNano` / `endTimeUnixNano` (int or numeric string), as UTC.
  - `kind`, `input`, `output`, `session_id`, `usage` from `OTelSpanClassifier`.
  - `status` = `SpanStatus.of(raw["status"]["code"])` (`OK` / `UNSET` / `ERROR`; verified on a live `aws/spans` log group).
  - The `@timestamp` cell (`"YYYY-MM-DD HH:MM:SS.mmm"`, UTC) is parsed with `datetime.fromisoformat` and
    used only for paging.

### `trace/testing.py`: `TraceFetchContract`

```python
class TraceFetchContract:                          # not prefixed Test: pytest collects only subclasses
    @pytest.fixture
    def tracer(self) -> BaseTrace: ...             # subclasses override
    def seed(self, tracer: BaseTrace, spans: list[FetchedSpan]) -> None: ...   # subclasses override
    @staticmethod
    def contract_span(span_id, minute, kind=SpanKind.SPAN, trace_id="t1", session_id="s1", name=None) -> FetchedSpan: ...
    @staticmethod
    def window(**filters) -> TraceQuery: ...       # 2026-01-01 11:00–12:00 UTC plus filters

    def test_contract_returns_spans_oldest_first(self, tracer): ...
    def test_contract_window_is_start_inclusive_end_exclusive(self, tracer): ...
    def test_contract_limit_keeps_the_most_recent(self, tracer): ...
    def test_contract_kind_filter(self, tracer): ...           # tool; llm + agent; span = everything else
    def test_contract_session_filter(self, tracer): ...        # incl. a span with no session id: excluded
    def test_contract_trace_id_filter(self, tracer): ...
    def test_contract_name_filter(self, tracer): ...           # incl. a span with no name: excluded
    def test_contract_empty_backend_returns_nothing(self, tracer): ...
```

- Same shape as `SecretProviderContract` (`secret/testing.py:15`): public, imports `pytest`, so imported
  from test code only; the subclass supplies the fixture and the seeding hook.
- `seed` gets `FetchedSpan`s with ids, name, kind, times and session; a backend with its own vocabulary
  maps them on the way in (Langfuse types, Traceloop `gen_ai.operation.name`), as the instrumentation would.
- `tracer` may be any object with `fetch_spans(query)`; the Traceloop subclass passes the fetcher itself,
  because `OpenLLMetry.fetch_spans` builds its fetcher without a transport.
- Subclasses (`tests/test_trace_fetch_contract.py`):
  - `TestInMemoryTraceContract`: `InMemoryTrace(BaseTrace)`, whose `fetch_spans` is
    `FetchedSpan.oldest_first(s for s in spans if query.matches(s))[-query.limit:]`. This is also the
    bring-your-own example in the docs.
  - `TestLangfuseFetchContract`: a `LangFuse` with `_client` replaced by a fake `api.observations.get_many`
    (single-value filters, both window bounds inclusive, newest first, offset cursor).
  - `TestTraceloopFetchContract`: `TraceloopTraceFetcher` over an `httpx.MockTransport` fake warehouse
    (whole-second inclusive bounds, `filters` JSON `in`/`equals`, newest first, offset cursor).
  - Logfire and CloudWatch don't subclass it: a faithful fake would re-implement SQL and Logs Insights.

### Langfuse flush on AWS Lambda (`trace/langfuse/`)

```python
class LangFuse(BaseTrace):
    @staticmethod
    def flush_on_lambda(client: Langfuse) -> None:
        if "AWS_LAMBDA_FUNCTION_NAME" not in os.environ:
            return
        try:
            client.flush()
        except Exception:      # an exporter error must not replace the agent's reply
            logging.getLogger("ak.trace.langfuse").warning("Flushing Langfuse spans after the run failed", exc_info=True)

# each of the six runners
async def run(self, agent, session, requests):
    try:
        with propagate_attributes(session_id=session.id, tags=["agentkernel"]):
            with self._client.start_as_current_observation(name="Agent Kernel <Framework>", as_type="span") as span:
                result = await super().run(agent, session, requests)
                span.update(input=result.prompt, output=str(result))
    finally:
        LangFuse.flush_on_lambda(self._client)
    return result
```

- The environment check runs per call (one dict lookup), so a process started outside Lambda never
  flushes.
- The runners import `LangFuse` from `.langfuse`; `langfuse.py` imports the runners only lazily inside its
  framework methods, so there is no import cycle. Existing patch targets
  (`agentkernel.trace.langfuse.<framework>.propagate_attributes`) are unchanged.
- The broad `except` is deliberate: the flush runs in a `finally`, so a raise there would replace the
  agent's reply (or its original exception).

### Consumer changes

- **No framework Module, runner or API surface changes.** Traced runners keep using
  `Trace.get().<framework>()` exactly as today. `fetch` is a new entry point with no existing callers.
- Bring-your-own `BaseTrace` subclasses keep working unchanged (`fetch` has a default).
  `tests/test_trace.py`'s `_FakeTrace` (`tests/test_trace.py:15-40`) does not need to change.

### Config changes

- No `AKConfig` changes. `_TraceConfig` (`core/config.py:468-473`) keeps its `enabled` and `type`
  fields, defaults and descriptions.
- New secret `LOGFIRE_READ_TOKEN`, resolved by `Logfire.fetch_spans` through `SecretManager`.
  - It is not an `AK_*` variable, because it is the provider's own credential, like `LOGFIRE_TOKEN` and
    `TRACELOOP_API_KEY`.
  - It can't be derived from `LOGFIRE_TOKEN` (a write token cannot read).
- `TRACELOOP_API_KEY` (through `SecretManager`) and `TRACELOOP_BASE_URL` are reused.
- Credentials AK reads itself go through `SecretManager`; the ones the provider SDKs read themselves
  (`LANGFUSE_*`, `LOGFIRE_TOKEN`, the SDK's own `TRACELOOP_API_KEY` read on the send side) stay
  environment variables, as today. With the default `env` provider the two are the same. Langfuse's `LANGFUSE_*` are reused through
  its client. CloudWatch reuses the standard AWS chain and `AWS_REGION`, as its exporter does.
- `ak-py/pyproject.toml`: `openllmetry` and `logfire` extras gain `"httpx>=0.27.0"`, the same bound the
  `api` and messaging extras (`slack`, `whatsapp`, `messenger`, …) already use. `uv.lock` is regenerated.
  The `cloudwatch` extra (`ak-py/pyproject.toml:37-42`) is unchanged: its `botocore` provides the
  CloudWatch Logs client.
- Existing YAML and env vars are unaffected.

### Behavioural changes

1. **Logfire now exports AK's session id unscrubbed.**
   - Before: the wrapper span's `session_id` attribute reached Logfire as
     `"[Scrubbed due to 'session']"`.
   - After: it carries the real session id.
   - Intentional: without it, Logfire traces can't be filtered by session in Fetch or in the Logfire
     UI.
   - Privacy: session ids are **not** guaranteed to be opaque. `BaseChatRequest.session_id` is any client
     string (`core/model.py:403`), and the session guide suggests deriving it from a user id
     (`docs/docs/core-concepts/session.md:109`). Langfuse, Traceloop and CloudWatch already export it
     unscrubbed. So this change makes Logfire match them and adds no new kind of exposure. It is not
     opt-in, because a config flag for one tracer would leave the other three as they are.
     §Fetching Spans Back says the session id reaches every tracing provider as given, and tells users
     to keep personal data out of it (e.g. use a hash or a random id).
   - Every other scrub match is still redacted.
2. **`pip install agentkernel[openllmetry]` / `[logfire]` now install `httpx`.** Intentional, because
   the fetchers need it. In practice it is usually already present transitively, through
   `langfuse`/`openai`.
3. **Langfuse runners on AWS Lambda flush after every `run()`.** Before: spans waited for the background
   exporter, which a frozen Lambda sandbox never runs, so they arrived on the next invocation or were lost.
   After: each run ends with one export round trip on Lambda. Intentional (design.md §Langfuse flush).
   Off Lambda nothing changes.
4. **CloudWatch fetching needs IAM read permissions the send side does not.** `logs:StartQuery`,
   `logs:GetQueryResults` and `logs:StopQuery` on `aws/spans`; `AWSXrayWriteOnlyAccess` grants none of
   them. Documented, not enforced.

**Non-changes:**
- Span export, runner wrapping and instrumentation for all four providers are unchanged, apart from
  changes 1 and 3. `CloudWatch._exporter()` resolves the region exactly as before, through `CloudWatch.region()`.
- The `BaseTrace` abstract surface is unchanged: the seven abstract methods stay; `fetch` is concrete.
- The `Trace.get()`/`Trace._build()` selection logic and `_BUILTIN_TRACERS` are unchanged.
- No data written before this change is altered. Spans already in Logfire keep their scrubbed session
  value, so a session filter does not match runs recorded before the upgrade.
- Streamed runs (`stream()`) get no Langfuse flush. No tracer wraps `stream()` today: the Langfuse,
  Logfire, Traceloop and CloudWatch runners override only `run()` (checked on `develop`), so a streamed
  run already gets no AK wrapper span, and CloudWatch's Lambda flush is `run()`-only too. Wrapping
  `stream()` is a separate change for all four tracers.

## Phase 1 error handling

| Situation | Surfaces as |
|---|---|
| `Trace.fetch_spans` with `trace.enabled: false` | `AKConfigError("cannot fetch spans: tracing is disabled …")` |
| Bring-your-own tracer without `fetch` | `NotImplementedError("<Class> does not support fetching spans")` |
| Bad filter value (`limit=0`, unknown kind, unknown kwarg) | Pydantic `ValidationError` from `TraceQuery` |
| `start >= end` | `ValueError` from `TraceQuery.window()`, raised before any network call |
| Logfire with no read token | `AKConfigError` naming `LOGFIRE_READ_TOKEN`, raised before the SDK import |
| Traceloop with no API key | `AKConfigError` naming `TRACELOOP_API_KEY`, raised before any request |
| The secret provider fails while resolving either key (e.g. SSM access denied) | `SecretError` from `SecretManager.get`, propagated unchanged |
| CloudWatch with no AWS region | `AKConfigError` naming `AWS_REGION`, raised before any request |
| CloudWatch log group missing (`StartQuery` raises `ClientError` code `ResourceNotFoundException`) | `AKConfigError` naming the log group and saying to enable Transaction Search and make the spans reach X-Ray; chained from the `ClientError`. Any other `ClientError` propagates unchanged |
| CloudWatch query ends `Failed`/`Cancelled`/`Timeout`/`Unknown` | `RuntimeError` naming the status and log group |
| CloudWatch query still running at `timeout` | `StopQuery`, then `TimeoutError` |
| `logfire` extra missing on the fetch path | `ImportError` from the lazy import. Unreachable through `Trace`, since `Trace._build` already wraps the tracer import in `require_extra("logfire", …)` (`trace/trace.py:51-53`) |
| Provider errors (HTTP 4xx/5xx, rate limits, auth) | Propagated unchanged: Langfuse SDK `ApiError`, Logfire `QueryRequestError`/`QueryExecutionError`, `httpx.HTTPStatusError` from `raise_for_status()`, botocore `ClientError` (e.g. `AccessDeniedException`, `ResourceNotFoundException` when Transaction Search was never enabled, `ThrottlingException`) and `NoCredentialsError`. No retries |
| Langfuse not yet authenticated | Can't happen through `Trace.get()`: `init()` already raises if `auth_check()` fails (`trace/langfuse/langfuse.py:25-28`) |

- Concurrency: the Logfire and Traceloop fetchers build their own HTTP/query client per `fetch` call
  and hold no shared mutable state, so concurrent calls are independent. So does the CloudWatch fetcher
  when it builds its own client; an injected botocore client is shared, and botocore clients are
  thread-safe. The Langfuse fetcher reuses
  the tracer's shared SDK client and adds no state of its own. Whether that client is safe to share
  across threads is the SDK's own guarantee, not checked here.
- Cost: `fetch` adds no work to the agent hot path. It runs only when called. Each call makes
  `ceil(matches / page size)` requests per request-matrix cell (Langfuse) or per page (Logfire,
  Traceloop). A CloudWatch page is one `StartQuery` plus one `GetQueryResults` per second until it
  completes, and Logs Insights bills by data scanned, so the cost grows with the window.

## Phase 1 testing

**New `ak-py/tests/test_trace_fetch.py`** (no provider SDK needed):

- `TestTraceQuery`:
  - default window = last hour before `end`
  - naive → UTC
  - `start >= end` raises
  - string kinds coerce
- `TestOTelSpanClassifier`:
  - parametrized over the attribute shapes in `research/span-formats.md` §3–§4: OpenInference
    TOOL/LLM/CHAIN, Traceloop tool/workflow, gen_ai chat/invoke_agent, Logfire `Function:`/`Agent run:`
    templates, Logfire `LLM` tag, empty attributes
  - IO precedence
  - session-id keys
  - `usage` over the captured shapes: OpenInference tokens (total derived), GenAI tokens with
    `operation.cost`, numeric strings, and `None` for the two roll-ups and for non-numeric values
  - `SpanUsage.of` keeps a partial value without inventing a total
- `TestTraceFetch`:
  - disabled tracing raises `AKConfigError`
  - kwargs build a `TraceQuery`
  - an explicit query is passed through
  - `query` plus keyword filters raises `ValueError`
  - the default `BaseTrace.fetch_spans` raises `NotImplementedError`
- `TestSpanStatus`: `SpanStatus.of` over `ERROR`, `STATUS_CODE_ERROR`, OTLP `2`, `OK`, `1`, `UNSET`, `0`, `None`, a bool and
  an unknown string.
- `TestFetchedTrace`: `group` keeps span order and orders traces by their first span; `root`, `user_input`, `output`,
  `started_at`, `ended_at`; no root when every span has a parent; no root when two spans have none; `tool_spans` and
  `agent_names` (de-duplicated, in order); `usage` sums and leaves unreported fields `None`.
- `TestTraceFetchTraces`: groups the spans `fetch_spans` returned; `kinds` and `name` raise `ValueError`; disabled
  tracing raises `AKConfigError`.
- `TestLangfuseFetcher` (a `MagicMock` client):
  - cursor followed
  - parameter translation
  - one request per type × trace id
  - `span` kind → `type=None` plus local filtering
  - `limit=1` keeps the newest span and stops after one page
  - `usage_details` + `total_cost` mapped to `SpanUsage`; an observation without them → `None`
  - `level` `ERROR` → `status` `ERROR`, any other level → `UNSET`
- `TestLogfireFetcher` (fake `logfire`, `logfire.experimental` and `logfire.experimental.query_client`
  modules in `sys.modules`):
  - missing token raises
  - window passed as `min_timestamp`/`max_timestamp`
  - kind and session SQL present
  - backward paging past a patched `_MAX_ROWS = 2`, with boundary dedupe and the `start_timestamp <=`
    cursor
  - literal escaping
  - `NOT COALESCE` for `span`
  - the `name` condition is `COALESCE(message, span_name)`
  - a row at exactly `end` (as an inclusive `max_timestamp` would return it) is dropped by `matches`
  - `gen_ai.usage.*` attributes mapped to `usage`
  - `otel_status_code` mapped to `status`
- `TestTraceloopFetcher` (`httpx.MockTransport`):
  - missing key raises
  - Bearer header, timestamp params and `filters` JSON, with no kind filter even when `kinds` is set
  - cursor followed
  - LLM and other-session spans dropped locally
  - with `kinds=["tool"]`, a span carrying only `traceloop.span.kind=tool` (no `gen_ai.operation.name`)
    is returned; the contract fake seeds `gen_ai.operation.name`, so it wouldn't catch this
  - `end_time` from `duration_ms`
  - empty parent → `None`
  - `_timestamp` over ISO / s / ms / µs / ns
- `TestCloudWatchFetcher` (a `MagicMock` botocore `logs` client):
  - missing region raises `AKConfigError`
  - `start_query` gets `aws/spans`, the window start, an end at or past the window end, and the kind
    and session filters
  - nested `openinference` attributes flattened and classified; LLM span dropped locally
  - nested `llm.token_count` attributes flattened into `usage`
  - `startTimeUnixNano` as a string, `endTimeUnixNano` as an int; empty parent → `None`
  - a span started after `end` (but stamped inside the range) is dropped
  - backward paging past a patched `_MAX_ROWS = 2`: boundary dedupe, next `endTime` = the page's oldest
    `@timestamp`
  - `Failed` status → `RuntimeError`; `timeout=0` → `stop_query` then `TimeoutError`
  - `ResourceNotFoundException` from `start_query` → `AKConfigError` mentioning Transaction Search; an
    `AccessDeniedException` propagates as `ClientError`
  - literal escaping, `traceId in [...]`, and no kind filter when `span` is requested
- `FetchedSpan.oldest_first` with a missing `start_time`.
- `TestTraceFetcher` (a minimal in-test subclass with scripted pages):
  - `fetch` pins a defaulted `end` once (a clock that advances between calls doesn't move the window),
    keeps the first span per id, returns the newest `limit` oldest first, and sets `provider`;
  - `_follow_cursor`: each of the four stop rules;
  - `_page_backward`: boundary dedupe, the session backfill, each stop rule, and the warning on a full
    page with no fresh rows.
- Credentials: `Logfire.fetch_spans` and `OpenLLMetry.fetch_spans` read their key through `SecretManager` (a stub
  manager returning the value with the variable unset in the environment), and a missing one raises
  `AKConfigError` naming the variable.
- Each fetcher's `provider` value: `langfuse`, `logfire`, `openllmetry`, `cloudwatch`.
- `TraceQuery.matches`: each filter rejects, start inclusive, end exclusive; a span with no
  `start_time` is rejected; with `session_id`/`name` set, a span reporting `None` for that field is
  rejected; with the filter unset, `None` is accepted.
- Langfuse: `expand_metadata="attributes"` is sent; a repeated cursor ends paging (a fake that always
  returns the same cursor with out-of-window observations makes exactly two calls).

**New `ak-py/tests/test_trace_fetch_contract.py`:** the three `TraceFetchContract` subclasses
(§`trace/testing.py`).

**New `ak-py/tests/test_trace_langfuse_flush.py`:** `TestLangFuseLambdaFlush`, parametrized over all six
Langfuse runners (OpenAI, LangGraph, CrewAI, ADK, Smolagents, Pydantic AI), because each one carries its
own `finally`:

- For each runner: `propagate_attributes` patched in that runner's module (the existing patch target),
  the parent runner's `run` patched to return a result or to raise, and `LangFuse.flush_on_lambda`
  spied on.
  - Success and failure paths both call `flush_on_lambda(client)` exactly once. On failure, the original
    exception still propagates.
- A runner whose framework extra is missing is skipped with `pytest.importorskip`, so the suite runs in
  any environment.
- `flush_on_lambda` itself, tested once: it flushes when `AWS_LAMBDA_FUNCTION_NAME` is set, doesn't
  flush when it isn't, and logs a failing flush instead of raising it.

**Changed `ak-py/tests/test_trace_logfire.py`:**

- The `fake_logfire` fixture (`tests/test_trace_logfire.py:23-38`) adds
  `fake.ScrubbingOptions = MagicMock(side_effect=lambda **kw: kw)`. Without it, `init()` raises
  `AttributeError` against the fake module.
- New `test_init_keeps_session_id_from_scrubbing`: the callback returns the value for
  `("attributes", "session_id")` and `None` for `("attributes", "session_token")`.
- The existing `configure.assert_called_once()` assertions (`:56`, `:66`) stay valid.

**Run:**

```bash
cd ak-py && uv run pytest tests/test_trace_fetch.py tests/test_trace_fetch_contract.py tests/test_trace_logfire.py tests/test_trace.py tests/test_trace_langfuse_langgraph.py tests/test_trace_langfuse_flush.py tests/test_trace_cloudwatch.py
make lint-check-all   # from the repo root
```

**Before merge, manual live checks** (not CI; they need accounts): run `Trace.get().fetch_spans(kinds=["tool"])`
against each provider after a real agent run, and tick off `research/provider-read-apis.md` §5 and §6:
- Langfuse maps our spans to type `TOOL`: the example trusts `span.kind` and no longer re-classifies.
- Logfire has the `otel_status_code` column, and Traceloop returns a `status_code` or `status` field.
- Logfire `attributes->>` access works and the session subquery matches.
- Traceloop accepts the association-property and `trace_id` filter ids.
- CloudWatch: the `@message` shape, that the dotted `attributes.*` filters match, and what `@timestamp`
  is for a span.

## Phases 2–3 design (example)

Phases 2 and 3 add no Agent Kernel core code. Everything below lives in
`examples/aws-serverless/langfuse-trace-evaluation/` and uses only public AK API: `Trace.get().fetch_spans(...)`,
`Trace.get().fetch_traces(...)`, `FetchedTrace`, `FetchedSpan`, `SpanStatus`, `SpanUsage`, `AKEvaluator`, `AKEvaluationCase`,
`AKEvaluationResult`, `AKMetricNotSupported`, `AKTestConfig` and `Lambda`.

One AK serverless Lambda serves the agent (`POST /api/v1/chat`) and two custom routes: `POST /api/v1/eval`
starts grading one session's traces in an asynchronous self-invocation, and `GET /api/v1/check` reports
whether every request of that session has been graded. Nothing runs on a schedule.

### Example layout

```
examples/aws-serverless/langfuse-trace-evaluation/
├── README.md
├── pyproject.toml           # runtime dependencies; dev group
├── uv.lock
├── build.sh                 # test venv: uv sync (or the local ak-py wheel with `local`)
├── config.yaml              # AKConfig: trace.enabled true, trace.type langfuse
├── lambda.py                # the agent, the two routes and the Lambda entry point (wiring only)
├── simulate_traffic.py      # TrafficSimulator: 3 questions under one session id
├── evaluator/
│   ├── __init__.py
│   ├── api.py               # EvaluationAPI: /eval, /check and the entry point
│   ├── job.py               # TraceEvaluationJob, PrepareSummary, GradeSummary
│   ├── case.py              # ToolCall, TraceCase, TraceEvaluationCase
│   ├── opik_evaluator.py    # OpikTraceEvaluator (not opik.py, which would shadow the SDK)
│   └── store.py             # EvaluationStore, Progress, TraceProgress
├── tests/
│   └── test_evaluator.py    # unit tests, no cloud access
├── lambda_test.py           # weekly integration test, with its EvaluationClient helper
└── deploy/
    ├── main.tf  variables.tf  outputs.tf  providers.tf  backend.tf  terraform.tfvars
    ├── deploy.sh
    └── Dockerfile            # FROM public.ecr.aws/lambda/python:3.12, CMD ["lambda.handler"]
```

### Rules

1. **No AK core changes.** If the example needs something AK lacks, it is raised as a design.md open
   question, not patched in core inside this change.
2. **Classes, not scripts.** Each component below is a class. `lambda.py` holds no functions: it builds
   the agent and an `EvaluationAPI`, registers the API's bound methods with `Lambda.register` (the router
   stores any callable, `deployment/aws/serverless/core/router/rest_lambda.py:368-377`), and exposes
   `handler = api.handler`.
3. **Configuration from the environment only.** `EvaluationAPI.from_env()` and
   `TraceEvaluationJob.from_env()` are the only places that read environment variables; the other
   classes take constructor parameters, so the unit tests build them directly.
4. **Every write is idempotent**, and a trace's `graded` row is written in one `PutItem`, after all its
   metrics are judged (§`evaluator/store.py`).
5. **One bad trace or metric never fails the run; any other error fails it** and is reported through the
   `/eval` response or the Lambda logs (§Phases 2–3 error handling).

### The agent and the wiring (`lambda.py`, `config.yaml`)

```python
@function_tool
def get_order_status(order_id: str) -> str: ...      # fixed table lookup: deterministic tool output

support_agent = Agent(name="support", handoff_description="Order and delivery questions",
                      tools=[get_order_status], model="gpt-4.1-mini", instructions=...)
triage_agent = Agent(name="triage", handoffs=[support_agent], model="gpt-4.1-mini", instructions=...)
OpenAIModule([triage_agent, support_agent])

api = EvaluationAPI.from_env()
Lambda.register("/eval", method="POST")(api.start)
Lambda.register("/check", method="GET")(api.check)
handler = api.handler       # the evaluate action → the job; everything else → Lambda.handler
```

- `get_order_status` is the one module-level function: the OpenAI Agents SDK's `@function_tool` turns a
  function into the tool.
- `config.yaml`: `trace: {enabled: true, type: langfuse}`. No `session` block (in-memory): each prompt is a
  single turn, so no Redis is needed.
- `get_order_status` knows `A-1001` (shipped, arriving Friday) and returns `"Order <id> not found"` for any
  other id, so the traffic includes one tool result the agent must report honestly.
- The Langfuse runners flush on Lambda themselves (Phase 1), so the agent needs no tracing code.

### `simulate_traffic.py`: `TrafficSimulator`

```python
class TrafficSimulator:
    QUESTIONS = (
        "Where is my order A-1001?",               # hand-off + tool call
        "Can you check order A-9999 for me?",      # tool returns "not found"
        "Write me a poem about the ocean.",        # off-topic: should decline, no tool
    )

    def __init__(self, chat_url: str, session_id: str | None = None, transport: httpx.BaseTransport | None = None): ...
    @property
    def session_id(self) -> str: ...                 # the given id, or one uuid4 generated in __init__
    def send(self) -> list[str]: ...                 # one POST per question, all under session_id; the replies
    @classmethod
    def chat_url_from_env(cls, deploy_dir: Path) -> str: ...   # AK_TEST_ENDPOINT, else terraform output
    @classmethod
    def cli(cls, argv: list[str] | None = None) -> int: ...

if __name__ == "__main__":
    sys.exit(TrafficSimulator.cli())
```

- `send()`: POST `{"prompt": q, "session_id": self.session_id, "agent": "triage"}` to `chat_url` for each
  question in order, with the sibling `APITestClient`'s retry (3 tries on 5xx and timeouts, 30 s timeout;
  `examples/aws-serverless/openai-auth/lambda_test.py:31-62`). Each question is its own request, so each
  becomes its own trace.
- It knows nothing about `/eval` or `/check`.
- `chat_url_from_env(deploy_dir)`: `os.getenv("AK_TEST_ENDPOINT")`, or `terraform -chdir=<deploy_dir> output
  -raw agent_invoke_url` when the variable is unset. A failing or empty output raises `RuntimeError`.
- `cli`: flags `--endpoint` (overrides `chat_url_from_env`) and `--session-id` (default: generated). Sends,
  prints each reply and the session id, and returns `0`. The README shows the `curl` calls to `/eval` and
  `/check` for that id.
- `transport` exists for the unit tests (`httpx.MockTransport`).

### `evaluator/case.py`

```python
class ToolCall(BaseModel):
    name: str
    input: str | None = None
    output: str | None = None
    failed: bool = False

class TraceCase(BaseModel):
    trace_id: str
    session_id: str | None = None
    root_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    user_input: str = ""
    output: str = ""
    tool_calls: list[ToolCall] = []
    agents: list[str] = []
    usage: SpanUsage = SpanUsage()            # summed over the trace's spans
    span_count: int
    spans: list[FetchedSpan] = []             # kept for EvaluationStore's spans_gz

    @property
    def finished(self) -> bool: ...           # ended_at is not None and output != "" (the run ended)
    def ready(self, now: datetime, settle: timedelta) -> bool: ...
    @property
    def latency_ms(self) -> int | None: ...
    @classmethod
    def from_trace(cls, trace: FetchedTrace) -> "TraceCase": ...   # needs trace.root; ValueError otherwise
    def transcript(self) -> str: ...
    def to_evaluation_case(self, threshold: float) -> "TraceEvaluationCase": ...

class TraceEvaluationCase(AKEvaluationCase):
    transcript: str
    tool_call_count: int = 0
```

- `from_trace` reads a `FetchedTrace` that has a root; the job skips the others (`root is None`), so grouping spans,
  finding the single parentless root and summing usage are AK's (`fetch_traces`), not the example's:
  - `user_input`, `output`, `session_id`, `started_at`, `ended_at`: from the trace (its root span), through `_text`.
  - Tool calls: `trace.tool_spans`, oldest first. `failed` = `span.status == SpanStatus.ERROR`. The example trusts
    `span.kind`: it doesn't re-classify spans, so a tool span a provider labels as a plain span is missing from
    the transcript (design.md §Trace case).
  - `agents`: `trace.agent_names`. `usage`: `trace.usage`. `span_count`: `len(trace.spans)`. `spans`: `trace.spans`.
  - There is no `missing_parents`: the settle time is what waits for late spans.
- `ready(now, settle)`: `finished` and the root ended at least `settle` ago.
- Text fields (`_text`): Langfuse returns `input`/`output` as strings that are often JSON. A string that
  decodes to a JSON string is unwrapped; any other string is kept; anything else is `json.dumps`-ed.
- `transcript()`:
  ```
  User request:
  <user_input>

  Tool calls:
  1. get_order_status({"order_id": "A-1001"}) -> "Shipped, arriving Friday" [failed]   # "[failed]" only when failed
  (none)                                                                                  # when there are no tool calls

  Final answer:
  <output>
  ```
- `to_evaluation_case(threshold)`: `user_input`, `actual=output`, `context=[call.output for call in
  tool_calls if call.output]` or `None`, `transcript`, `tool_call_count`, `threshold`.

### `evaluator/opik_evaluator.py`

```python
os.environ.setdefault("OPIK_TRACK_DISABLE", "True")   # before any Opik metric is built, as AK's own evaluator does

class OpikTraceEvaluator(AKEvaluator):
    THRESHOLD = 0.5
    ATTEMPTS = 2
    METRICS = ("task_completion", "tool_correctness", "answer_relevance", "hallucination")

    def __init__(self, config: AKTestConfig, metric: str): ...   # ValueError for an unknown metric
    @classmethod
    def all(cls, config: AKTestConfig) -> list["OpikTraceEvaluator"]: ...
    @property
    def metric(self) -> str: ...
    def applies_to(self, case: TraceEvaluationCase) -> bool: ...  # tool_correctness needs tool_call_count > 0
    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult: ...  # raises AKMetricNotSupported
    def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult: ...
    def _opik_metric(self) -> BaseMetric: ...                     # built once, lazily
    def _score(self, case: TraceEvaluationCase) -> ScoreResult: ...
```

- Metric table (model `f"{config.llm.provider}/{config.llm.model}"`, `track=False` on every metric):

  | `metric` | Opik class | `_score` call | `higher_is_better` |
  |---|---|---|---|
  | `task_completion` | `AgentTaskCompletionJudge(model, track=False)` | `score(output=case.transcript)` | true |
  | `tool_correctness` | `AgentToolCorrectnessJudge(model, track=False)` | `score(output=case.transcript)` | true |
  | `answer_relevance` | `AnswerRelevance(model, require_context=False, track=False)` | `score(input=case.user_input, output=case.actual)` | true |
  | `hallucination` | `Hallucination(model, track=False)` | `score(input=case.user_input, output=case.actual, context=case.context)` | false |

  - The two agent judges take one `output` string only (Opik 2.2 signature `score(self, output: str, **ignored_kwargs)`),
    so the transcript carries the request, the tool calls and the answer.
- `evaluate_by_llm(case)`:
  1. Up to `ATTEMPTS` calls of `_score`. An exception, or a `ScoreResult` with `scoring_failed` or
     `value is None`, counts as a failed attempt.
  2. On success: `score = float(value)`; `passed = score >= case.threshold` (or `score < case.threshold`
     when `higher_is_better` is false); `reason` = the judge's reason.
  3. After the last failed attempt: `score=None`, `passed=None`, `reason="<metric> failed after 2 attempts:
     <error>"`. No exception escapes.
  4. Always: `metric`, `evaluator="opik"`, `threshold=case.threshold`, `mode="llm"`, `metadata` =
     `{"higher_is_better": ..., "opik_metric": "<class name>", "attempts": n}`.
- The broad `except Exception` in step 1 is deliberate: Opik and litellm raise many unrelated types
  (`MetricComputationError`, `litellm.RateLimitError`, `openai.APIError`, …), and rule 5 needs all of them
  contained. Each one is logged with the trace id and metric.

### `evaluator/store.py`

```python
class Progress(StrEnum):
    PENDING = "pending"          # finished, not ready yet
    GRADING = "grading"          # ready and queued for the judges
    GRADED = "graded"            # every metric judged and stored; final
    FAILED = "failed"            # grading raised; error recorded; retried by the next /eval
    UNFINISHED = "unfinished"    # root span has no output; final, never graded

class TraceProgress(BaseModel):
    progress: Progress
    updated_at: datetime

class SessionProgress(BaseModel):
    counts: dict[Progress, int] = {}
    errors: list[dict[str, str]] = []    # {"trace_id", "error"} per failed row

class EvaluationStore:
    FIELD_LIMIT = 4_096          # characters per input/output/reason field
    TOOL_CALLS_LIMIT = 25        # tool calls stored on the trace row
    ITEM_LIMIT = 380_000         # bytes: DynamoDB's 400 KB item cap minus headroom
    TTL = timedelta(days=90)

    def __init__(self, table: Any): ...                             # a boto3 dynamodb Table resource
    @classmethod
    def for_table(cls, table_name: str) -> "EvaluationStore": ...  # boto3.resource("dynamodb").Table(name)
    def progress(self, trace_ids: list[str]) -> dict[str, TraceProgress]: ...
    def mark(self, case: TraceCase, progress: Progress, now: datetime) -> None: ...
    def save(self, case: TraceCase, results: list[AKEvaluationResult], now: datetime) -> None: ...
    def fail(self, trace_ids: list[str], error: str, now: datetime) -> None: ...
    def session(self, session_id: str) -> SessionProgress: ...
    def _summary(self, case: TraceCase, progress: Progress, now: datetime) -> dict: ...
    @staticmethod
    def _number(value: float | int | None) -> Decimal | None: ...  # Decimal(str(value))
    @classmethod
    def _cut(cls, text: str | None) -> str | None: ...
    @staticmethod
    def _item_size(item: dict) -> int: ...                          # DynamoDB-sized bytes of a whole item
```

- `progress`: `table.meta.client.batch_get_item` with `ConsistentRead=True`, in chunks of 100 keys
  `{"trace_id": id}`, projecting
  `trace_id`, `progress` and `updated_at`; traces with no row are absent from the result.
  `UnprocessedKeys` are retried up to 3 times with 0.5 s, 1 s, 2 s waits, then raise `RuntimeError` (an
  infrastructure error under rule 5).
- `_summary(case, progress, now)`: the attributes every row has: `trace_id`, `session_id`, `progress`,
  `updated_at` (ISO 8601 UTC), `expires_at` (epoch seconds, `updated_at + TTL`), and the trace summary
  listed under `save`, without metrics or spans.
- `mark`: `table.put_item` of `_summary(case, progress, now)` with
  `ConditionExpression="attribute_not_exists(trace_id) OR progress <> :graded"`. A
  `ConditionalCheckFailedException` (the row turned `graded` meanwhile) is swallowed: a graded trace is
  never downgraded.
- `save`: one `table.put_item` of the whole row with `progress = graded`, unconditional. A single
  `PutItem` is atomic, so the row turns `graded` with every metric column in it at once.
  - Attributes: everything in `_summary` (`session_id` is omitted when `None`, so the sparse
    `session_id-index` skips it), plus `evaluated_at` (= `updated_at`).
  - The summary (on every row): `provider="langfuse"`, `root_name`, `started_at`, `latency_ms`, `input`,
    `output`, `tool_calls` (list of maps, each field cut), `tool_call_count`, `tool_error_count`,
    `agents`, `span_count`, `input_tokens`, `output_tokens`, `total_tokens`, `cost`.
  - Only on `graded` rows: `passed` (`True` when every scored result passed, `False` when one failed,
    omitted when none scored), `metric_errors` (count of `score=None` results), and `spans_gz` or
    `spans_truncated`.
  - One attribute per result, named by `result.metric` (`task_completion`, `tool_correctness`,
    `answer_relevance`, `hallucination`). Its value is a map: `evaluator`, `score`, `threshold`, `passed`,
    `reason` (cut with `_cut`), `higher_is_better`, `attempts`.
  - `None` values are omitted rather than written (boto3 would store them as DynamoDB `NULL`), so a
    missing `score` reads the same as an unscored one.
  - Size budget for the trace row. A per-field limit alone can't keep an item under 400 KB: strings
    are cut by characters (up to 4 bytes each in UTF-8), and the number of tool calls has no bound.
    1. Text fields, including each metric's `reason`, are cut with `_cut`. `tool_calls` keeps the first
       `TOOL_CALLS_LIMIT` calls; when it drops any, it sets `tool_calls_truncated=True`.
       `tool_call_count` and `tool_error_count` still count every call.
    2. `_item_size(item)` measures the whole item without spans: the UTF-8 bytes of each attribute name
       and string value, binary lengths, and 21 bytes per number (DynamoDB's documented upper bound),
       recursing into lists and maps.
    3. If it is still over `ITEM_LIMIT` (many long tool calls), tool calls are dropped from the end, then
       `input` and `output` are cut by halves, until it fits. Metric attributes are never dropped: four
       cut reasons stay under 70 KB even at 4 bytes per character.
    4. `spans_gz` = `gzip.compress(json.dumps([span.model_dump(mode="json") for span in case.spans]))`.
       It is attached as Binary only when the item size plus `len("spans_gz") + len(spans_gz)` is ≤
       `ITEM_LIMIT`. Otherwise it is omitted and `spans_truncated=True`.
  - Without the budget, an oversized trace would make `put_item` raise `ValidationException` and fail the
    run.
  - `_cut`: the first `FIELD_LIMIT` characters plus `"…[truncated]"` when longer.
- `fail(trace_ids, error, now)`: per id, `table.update_item` setting `progress = failed`, `error` (cut
  with `_cut`) and `updated_at`, with `ConditionExpression="progress = :grading"`; a
  `ConditionalCheckFailedException` is swallowed (the row moved on meanwhile).
- `session(session_id)`: `table.query` on `session_id-index` with `session_id = :s`, projecting `trace_id`,
  `progress` and `error`, following `LastEvaluatedKey`: counts per `Progress` and the errors of `failed`
  rows. Index reads are eventually consistent, so only `/check` uses it. A row with an unknown `progress` is
  logged and skipped. The index projects only `progress`, `error` and `updated_at` (plus the keys), so
  it doesn't hold a second copy of every row's `spans_gz` (§Deployment).

### `evaluator/job.py`

```python
class PrepareSummary(BaseModel):
    session_id: str
    spans_fetched: int = 0
    found: int = 0               # traces with a root span
    no_root: int = 0             # traces with no single root span: no row
    already_graded: int = 0      # row already graded
    grading: int = 0             # marked grading now
    pending: int = 0
    unfinished: int = 0
    grading_ids: list[str] = []  # sent to grade in the invoke payload

class GradeSummary(BaseModel):
    session_id: str
    graded: int = 0
    failed: int = 0
    metric_errors: int = 0

class TraceEvaluationJob:
    FETCH_WINDOW = timedelta(hours=24)
    SETTLE = timedelta(minutes=2)

    def __init__(self, trace: Trace, store: EvaluationStore,
                 evaluators: Callable[[], list[OpikTraceEvaluator]],
                 clock: Callable[[], datetime] = ...): ...         # evaluators: built on first grade
    @classmethod
    def from_env(cls) -> "TraceEvaluationJob": ...
    def prepare(self, session_id: str) -> PrepareSummary: ...
    def grade(self, session_id: str, trace_ids: list[str]) -> GradeSummary: ...
    def _fetch(self, session_id: str) -> list[FetchedTrace]: ...
    def _cases(self, traces: list[FetchedTrace]) -> tuple[list[TraceCase], int]: ...   # cases, no_root count
    def _next(self, case: TraceCase, current: TraceProgress | None, now: datetime) -> Progress | None: ...
    def _evaluate(self, case: TraceCase) -> list[AKEvaluationResult]: ...
```

- `from_env()`: `Trace.get()` (reads `AK_TRACE__*`; `LangFuse.init()` checks the Langfuse keys),
  `EvaluationStore.for_table(os.environ["RESULTS_TABLE"])`, and as `evaluators` a factory calling
  `OpikTraceEvaluator.all(AKTestConfig.get())` (reads `AK_TEST__LLM__*`). The job calls the factory once,
  on the first `grade`, and keeps the list; `prepare` never calls it, so `/eval` doesn't load Opik or
  litellm.
- `_cases(traces)`: `TraceCase.from_trace` for each trace with a root; a trace with `root is None` counts as
  `no_root` (no row; the next `/eval` fetches it again); the cases are oldest first by `started_at`.
- `_next(case, current, now)`: the design's `prepare` table (design.md §Evaluation run). `None` means
  "leave the row as it is":
  - `current` is `graded` or `unfinished` → `None`;
  - otherwise (no row, `pending`, `failed` or `grading`): not `case.finished` →
    `UNFINISHED`; not `case.ready(now, SETTLE)` → `PENDING`; else `GRADING`. A span that lands after `SETTLE` is not detected.
- `prepare(session_id)`: `now = clock()`; `cases, no_root = _cases(_fetch(session_id))`;
  `current = store.progress([c.trace_id for c in cases])`; for each case, `new = _next(...)`, and
  `store.mark(case, new, now)` when `new` is not `None`. Counts each case under its resulting
  `progress` (`already_graded` for `graded`) and lists the `grading` ones in `grading_ids`, logs the
  summary and returns it. Exceptions propagate.
- `grade(session_id, trace_ids)`:
  1. `ids` = the `trace_ids` whose row `store.progress(trace_ids)` reports as `grading` (a consistent
     read: the rows were written moments ago); none → return an empty summary.
  2. `cases, _ = _cases(_fetch(session_id))`. An exception here → `store.fail(ids, error, clock())`,
     where `error = f"{type(e).__name__}: {e}"`; return the summary with `failed = len(ids)`.
  3. An id with no case in the fetch → `store.fail([id], "trace not found in the fetch", clock())`.
  4. For each remaining case, oldest first, inside its own `try`: `results = _evaluate(case)`;
     `store.save(case, results, clock())`; `graded += 1`; `metric_errors +=` the results with
     `score is None`. An exception → logged with the trace id, `store.fail([case.trace_id], error,
     clock())`, `failed += 1`, and the loop goes on.
  5. Logs the summary and returns it.
  - Nothing is re-raised except an exception from `store.fail` itself, which leaves those rows
    `grading` for the next `/eval` (AWS's automatic retry is off, §Deployment).
- `_fetch(session_id)`: `trace.fetch_traces(session_id=session_id, last=FETCH_WINDOW)`. The fetch keeps at most the newest
  1000 spans (the default `limit`), which a demo session never reaches, so there is no truncation check; a
  provider or HTTP error propagates.
- `_evaluate(case)`: `evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)`; one
  `evaluate_by_llm` per evaluator that `applies_to` it.
- Overlap: `/eval` called while a `grade` invocation is still running queues its `grading` rows again,
  so those traces are judged twice. Writes go to the same keys, `save` is a whole-row put and `fail` only
  touches rows still `grading`, so the table stays consistent; only judge cost is duplicated.

### `evaluator/api.py`

```python
class EvaluationAPI:
    GRADE_ACTION = "grade"

    def __init__(self, store: EvaluationStore, lambda_client: Any,
                 job_factory: Callable[[], TraceEvaluationJob],
                 lambda_handler: Callable[[dict, Any], dict] = Lambda.handler): ...
    @classmethod
    def from_env(cls) -> "EvaluationAPI": ...
    def start(self, event: dict, context: Any) -> tuple[int, dict]: ...    # POST /eval
    def check(self, event: dict, context: Any) -> tuple[int, dict]: ...    # GET /check
    def handler(self, event: dict, context: Any) -> dict: ...              # the Lambda entry point
    def _job(self) -> TraceEvaluationJob: ...                              # built once per sandbox, on first use
```

- `from_env()`: `EvaluationStore.for_table(os.environ["RESULTS_TABLE"])`, `boto3.client("lambda")`, and
  `TraceEvaluationJob.from_env` as the factory. Nothing heavy is built at import: `Trace.get()` and the
  Opik metrics are created on first use, so `/chat` cold starts don't pay for them.
- `start(event, context)`:
  1. `body = json.loads(event.get("body") or "{}")`, as `schedule-openai/lambda_request_handler.py:93` reads
     it; invalid JSON or a missing/empty `session_id` string → `(400, {"error": ...})`.
  2. `summary = self._job().prepare(session_id)`.
  3. When `summary.grading_ids`: `lambda_client.invoke(FunctionName=context.function_name,
     InvocationType="Event", Payload=json.dumps({"action": "grade", "session_id": session_id,
     "trace_ids": summary.grading_ids}))`.
  4. `(202, summary.model_dump(mode="json"))`.
  - An exception in 2 or 3 propagates; `Lambda.handler` turns it into
    `500 {"error": "Custom handler error: <message>"}` (`deployment/aws/serverless/aklambda.py:84-90`).
  - Building the job on the first `/eval` (Opik metrics, `Trace.get()`) adds a few seconds to that
    request's cold path, still well inside API Gateway's 29 s.
- `check(event, context)`:
  1. `params = event.get("queryStringParameters") or {}`; missing `session_id`, or `expected` that isn't
     a positive integer → `(400, {"error": ...})`.
  2. `progress = store.session(session_id)`.
  3. `(200, {"session_id", "expected", "graded", "grading", "pending", "failed", "unfinished",
     "errors": progress.errors[:10], "complete": graded >= expected})`, each count `0` when absent.
     `>=`, not `==`: a retried chat request can leave one trace more than the requests counted.
- `handler(event, context)`:
  - `event.get("action") == GRADE_ACTION` →
    `self._job().grade(event["session_id"], event["trace_ids"]).model_dump(mode="json")`.
  - Anything else → `lambda_handler(event, context)`, which serves `/chat`, `/eval` and `/check`.

### Deployment (`deploy/`)

```hcl
module "serverless_agents" {                       # same shape as aws-serverless/openai-auth
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.4"                                # the siblings' pin
  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Langfuse Trace Evaluation Example"
  execution_mode       = "rest_sync"
  gateway_endpoints = [
    { path = "eval", method = "POST" },
    { path = "check", method = "GET" },
  ]
  request_handler = {
    function_name     = "trace-eval"
    handler_path      = "lambda.handler"
    package_path      = "../dist"
    package_type      = "Image"
    timeout           = 600                        # 10 minutes; default 45 s: too short for the judges
    memory_size       = 1024                       # default 128 MB
    security_group_id = var.request_handler_security_group_id
    environment_variables = {
      OPENAI_API_KEY         = var.openai_api_key
      LANGFUSE_PUBLIC_KEY    = var.langfuse_public_key
      LANGFUSE_SECRET_KEY    = var.langfuse_secret_key
      LANGFUSE_BASE_URL      = var.langfuse_base_url
      AK_TEST__LLM__PROVIDER = "openai"
      AK_TEST__LLM__MODEL    = "gpt-4.1-mini"
      OPIK_TRACK_DISABLE     = "true"
      RESULTS_TABLE          = aws_dynamodb_table.results.name
    }
  }
}

resource "aws_dynamodb_table" "results" {
  name         = "${var.prefix}-trace-evaluations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "trace_id"
  attribute {
    name = "trace_id"
    type = "S"
  }
  attribute {
    name = "session_id"
    type = "S"
  }
  global_secondary_index {
    name               = "session_id-index"
    hash_key           = "session_id"
    projection_type    = "INCLUDE"                  # /check reads only these; ALL would copy spans_gz
    non_key_attributes = ["progress", "error", "updated_at"]
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_iam_role_policy" "evaluation" {
  name = "${var.prefix}-trace-evaluation"
  role = module.serverless_agents.request_handler_lambda_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
      },
    ]
  })
}

resource "aws_lambda_function_event_invoke_config" "grading" {
  function_name          = module.serverless_agents.request_handler_lambda_function_name
  maximum_retry_attempts = 0                       # the next /eval re-queues a killed grading
}
```

- The module creates the role and the function; the example only adds a policy to the role
  (`ak-deployment/ak-aws/serverless/outputs.tf:1-20`). There is no dependency cycle: the table doesn't
  depend on the module, the module reads only the table name, and the policy depends on both.
- The self-invoke needs no statement here: the module attaches the AWS-managed `AWSLambdaRole` policy
  (`lambda:InvokeFunction` on `*`) to the request handler's role (`modules/request-handler/main.tf:17-20`).
- `aws_lambda_function_event_invoke_config.grading`: `function_name =
  module.serverless_agents.request_handler_lambda_function_name`, `maximum_retry_attempts = 0`. AWS
  would otherwise retry a killed grading invocation up to twice, overlapping with the next `/eval`, which
  already re-queues leftover `grading` rows (design.md §Evaluation run).
- Network: the Lambda runs in the base VPC like the siblings, and reaches Langfuse, OpenAI, DynamoDB and
  the Lambda API through the same egress path the sibling agents use for OpenAI.
- `variables.tf`: `region`, `prefix`, `is_production` (default `false`), `openai_api_key`,
  `langfuse_public_key`, `langfuse_secret_key` (both `sensitive = true`), `langfuse_base_url` (default
  `"https://cloud.langfuse.com"`), `vpc_id`, `private_subnet_ids`, `request_handler_security_group_id`
  (default `null`). The last three take the names the weekly pipeline injects (`run_single_test.py`
  `deploy_aws_resources`).
- `outputs.tf`: `agent_invoke_url` (`module.serverless_agents.agent_invoke_url`, the name
  `run_single_test.py` `test_aws_deployment` reads), `results_table_name`.
- `providers.tf`, `backend.tf`: the siblings' files, with backend key
  `examples/aws-serverless/langfuse-trace-evaluation/terraform.tfstate`.
- `terraform.tfvars`: `region = "ap-southeast-2"`, `prefix = "ak-lf-trace-eval-dev-examples"`.
- `deploy.sh [local]`: builds `../dist` like `openai-auth/deploy/deploy.sh` (`uv export`, or the local
  `agentkernel` wheel from `../../../ak-py/dist` with `local`), copies `lambda.py`, `config.yaml` and
  `evaluator/` into `dist/data` and the Dockerfile into `dist/`, then `terraform init` and `terraform apply`.

### `pyproject.toml`

```toml
[project]
dependencies = ["agentkernel[aws,openai,langfuse,opik]>=0.9.4", "boto3>=1.40.0", "langfuse>=4.7.0"]

[dependency-groups]
dev = ["agentkernel[test]>=0.9.4", "httpx>=0.27.0", "moto[dynamodb]>=5.0.0", "black==26.5.1", "isort>=5.0.0"]
```

- One dependency set: the agent and the evaluator ship in one image. `boto3` is pinned because container
  images don't include the Lambda runtime's copy.
- `langfuse>=4.7.0` raises the `langfuse` extra's `>=4.2.0` floor: older SDKs use Langfuse's slow
  ingestion path (up to 15 minutes), which the job's 2-minute `SETTLE` assumes away (design.md
  §Evaluation run).
- The minimum `agentkernel` version is the first release that contains Phase 1 (`fetch` and `usage`),
  set when that release is cut; until then CI uses the local wheel (`./deploy.sh local`, `./build.sh local`).

### Consumer changes

- **AK core:** none (rule 1).
- **`.github/integration-test-config.yaml`:** a new weekly entry under `# AWS Serverless`:
  `type: aws-serverless`, `path: examples/aws-serverless/langfuse-trace-evaluation`, `deploy_dir: deploy`.
- **`.github/workflows/integration-test-weekly.yaml`, job `run-tests`:** the Deploy, Test and Destroy steps
  gain `TF_VAR_langfuse_public_key: ${{ secrets.LANGFUSE_PUBLIC_KEY }}`,
  `TF_VAR_langfuse_secret_key: ${{ secrets.LANGFUSE_SECRET_KEY }}` and
  `TF_VAR_langfuse_base_url: ${{ vars.LANGFUSE_BASE_URL }}`. Destroy needs them because the variables
  have no defaults. No other step, job or script changes: the example fits the existing
  deploy → test → destroy contract (`deploy/deploy.sh`, `agent_invoke_url`, `pytest` in the example root).
- **Repository settings:** secrets `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and variable
  `LANGFUSE_BASE_URL` for a CI Langfuse project (design.md open question).

### Config changes

- No `AKConfig` changes. The example sets existing fields: `trace.enabled` / `trace.type` in
  `config.yaml`, and `AK_TEST__LLM__PROVIDER` / `AK_TEST__LLM__MODEL` for the judge model.
- Example-only environment variable: `RESULTS_TABLE`.

### Behavioural changes

- None in AK from Phases 2–3 (the Langfuse flush is Phase 1 behavioural change 3). The weekly
  integration run gains one deployment (one Lambda behind one API Gateway, one ECR repository, one
  DynamoDB table) and its judge calls: three or four `gpt-4.1-mini` calls per test trace, on the existing
  CI OpenAI key.

## Phases 2–3 error handling

| Situation | What happens |
|---|---|
| `/eval` with a missing or empty `session_id`, or invalid JSON | `400`; nothing written or invoked |
| `/check` with a missing `session_id`, or `expected` not a positive integer | `400` |
| `/check` before any `/eval` for the session | `200`, every count `0`, `complete = false` |
| Langfuse keys missing or wrong | `LangFuse.init()` raises in `prepare` (`trace/langfuse/langfuse.py:25-28`) → `/eval` returns `500` with the error |
| Langfuse fetch fails (HTTP error, rate limit) in `prepare` | Propagates from `fetch_traces` (Phase 1 does no retries) → `/eval` returns `500` with the error |
| DynamoDB or IAM error in `prepare` (`progress`, `mark`, or the self-invoke) | `/eval` returns `500` with the error; rows marked before it stay, and the next `/eval` continues from them |
| A trace has no single root span (`root is None`) | `no_root`: not a request, no row; the next `/eval` fetches it again |
| A root span without output | `unfinished` row: never graded; `/check` reports it and `graded < expected` |
| A finished trace whose root span ended less than `SETTLE` ago | `pending` row; a later `/eval` moves it to `grading` |
| A trace not readable at all yet | No row; a later `/eval` finds it |
| A judge call fails twice | That metric's column is stored with `score`/`passed` omitted and the error in `reason`; `metric_errors` counts it; the row still turns `graded` |
| Fetch error in `grade` | Every `grading` row of the session → `failed` with the error; the next `/eval` retries them |
| Any other error while grading one trace (DynamoDB, unexpected exception) | That row → `failed` with the error; the other traces are still graded; the next `/eval` retries it |
| `failed` rows at the end of the weekly test | The test fails with the counts and the rows' `errors` from `/check` |
| The Lambda times out (10 minutes) or runs out of memory, or the `failed` write itself fails | Rows stay `grading` (no automatic retry); the next `/eval` (the test's next round) queues them again |

- Concurrency: each invocation is single-threaded, so the job, store and evaluators hold no locks.
  Sessions are independent. Overlap within a session is covered in §`evaluator/job.py`.
- Cost per `/eval`: one Langfuse fetch of ~`ceil(spans / 100)` requests, one `BatchGetItem` per 100
  traces and one put per trace whose `progress` changes. Per `grade`: the same fetch and `BatchGetItem`,
  then per graded trace three or four judge calls (one more per failed attempt) and one put. `/check`: one
  `Query` per call.

## Phases 2–3 testing

**Unit tests, `tests/test_evaluator.py`** (no network; run by the weekly pipeline's `pytest` too):

- Span fixtures: a `FetchedSpan` factory shaped like the Langfuse OpenAI Agents tree in
  `research/span-formats.md` §3 (root `Agent Kernel OpenAI`, `triage` and `support` agents, a
  `get_order_status` tool, two generations with `usage`).
- `TestTraceCase`:
  - root input/output, JSON-string unwrapping, tool calls in order, `failed` from `span.status == ERROR`, agents,
    summed usage (and `None` when no span has usage), latency;
  - `from_trace` raises for a trace without a root; root span without `end_time` → not `finished`;
  - `ready` false just before `settle` has passed and true just after;
  - the transcript with and without tool calls.
- `TestOpikTraceEvaluator` (each Opik class monkeypatched in `evaluator.opik_evaluator` with a fake whose
  `score` records its kwargs and returns a `ScoreResult`):
  - each metric's call arguments and model string `openai/gpt-4.1-mini`;
  - pass rules, including `hallucination`'s inverted one;
  - `applies_to` for `tool_correctness`;
  - first attempt raises, second succeeds → scored, `attempts == 2`; both fail → `score None`, reason
    names the error; `scoring_failed` counts as a failure;
  - `evaluate_by_score` raises `AKMetricNotSupported`; an unknown metric name raises `ValueError`.
- `TestEvaluationStore` (`moto.mock_aws`, table created with the `main.tf` schema):
  - `save` writes one trace row with the documented attributes and one map column per metric (no
    `tool_correctness` column for a trace without tool calls), `Decimal` numbers, omitted `None`s,
    `expires_at`;
  - `mark` writes the summary with the given `progress` and no metric columns, updates a `pending` row
    to `grading`, and never overwrites a `graded` row;
  - a store whose `put_item` raises in `save` leaves the row as it was (still `grading`);
  - `_cut` on long fields; `spans_gz` round-trips; spans that would push the item past `ITEM_LIMIT` →
    `spans_truncated`;
  - size budget: 100 tool calls with 4,096-char multi-byte (4-byte UTF-8) inputs/outputs → the item is
    written (moto enforces 400 KB), `tool_calls_truncated` is set, and `tool_call_count` is 100;
    `_item_size` against a hand-computed item;
  - `progress()` across more than 100 ids, absent for a trace with no row;
  - `session()` counts per `progress` for one session only, lists `failed` errors and `grading` ids, and
    is empty for a session with no rows;
  - `fail` sets `failed` and `error` on a `grading` row and leaves a `graded` row untouched.
- `TestTraceEvaluationJob` (fake `Trace` returning fixed spans, fake evaluators, the moto store, a fixed
  clock):
  - the `fetch_traces` call (`session_id`, `last=24h`);
  - `prepare`, one case per row of the design's table: no row + ready → `grading`; no row + inside `SETTLE`
    → `pending`; no row + no output → `unfinished`; `pending` + now ready → `grading`; leftover `grading` →
    `grading` again with a new `updated_at`; `failed` + ready → `grading`; `graded` and `unfinished` → left
    as is; with the matching `PrepareSummary` counts;
  - a trace with no root span → `no_root`, no row;
  - `grade` judges only the payload's traces whose row is still `grading`, turns them `graded`, and
    leaves other rows alone; `prepare` never calls the evaluators factory, and `grade` calls it once
    across two calls;
  - `metric_errors` counts `score=None` results;
  - `prepare` raises on a fetch error;
  - `grade`: a fetch error marks every `grading` row `failed` with the error; an exception on one trace
    marks only that row `failed` and the next trace is still graded; a `grading` id missing from the
    fetch → `failed`; nothing is raised; an exception from `fail` itself is re-raised.
- `TestEvaluationAPI` (moto store, a fake Lambda client recording `invoke` calls, a fake job factory, a
  fake `lambda_handler`):
  - `start`: `202` with the `prepare` counts; one `invoke` with `FunctionName=context.function_name`,
    `InvocationType="Event"` and the grade payload (with `trace_ids`) when a trace is `grading`, none
    otherwise; invalid JSON
    and a missing `session_id` → `400`, no `prepare`, no invoke; an exception from `prepare` propagates;
  - `check`: a session with no rows (all `0`, `complete` false), a mixed one with the right counts and
    the `failed` rows' `errors`, and `complete` true exactly when `graded >= expected`; bad `expected` → `400`;
  - `handler`: the grade action → the job's `grade`, built once across two calls; any other event → the
    fake `lambda_handler`, untouched.
- `TestTrafficSimulator` (`httpx.MockTransport`):
  - `send` posts the 3 questions in order, all with the given `session_id`;
  - without a `session_id`, all 3 requests carry the same generated id, which `session_id` returns;
  - 5xx then 200 is retried;
  - `chat_url_from_env`: `AK_TEST_ENDPOINT` wins; otherwise the `terraform output` (subprocess
    monkeypatched); an empty output raises.

**Weekly integration test, `lambda_test.py`** (`AK_TEST_ENDPOINT` from the pipeline,
`.github/scripts/run_single_test.py:350-370`). Only HTTP calls, so it needs no AWS credentials:

```python
INITIAL_WAIT = 150     # s: the job's SETTLE (2 minutes) plus 30 s
ROUNDS = 3             # /eval calls, the first one included
ROUND_INTERVAL = 30    # s between rounds
POLL_INTERVAL = 10     # s between /check calls
POLL_TIMEOUT = 180     # s per round

class EvaluationClient:                      # test helper, like APITestClient in openai-auth/lambda_test.py:15
    def __init__(self, chat_url: str): ...   # eval_url / check_url: the trailing "/chat" replaced
    async def evaluate(self, session_id: str) -> tuple[int, dict]: ...   # POST /eval; status code and body
    async def wait(self, session_id: str, expected: int, timeout: float = POLL_TIMEOUT,
                   every: float = POLL_INTERVAL) -> dict: ...   # polls GET /check (see below)
```

- Session-scoped fixtures: `chat_url = os.getenv("AK_TEST_ENDPOINT")` (as
  `openai-auth/lambda_test.py:82-84`), `simulator = TrafficSimulator(chat_url, session_id=str(uuid4()))`,
  `client = EvaluationClient(chat_url)`.
- `EvaluationClient.__init__` raises `ValueError` when `chat_url` doesn't end in `/chat`.
- `wait` returns as soon as `complete` is true or `grading == 0`; at the timeout it returns the last
  response.
- `test_every_request_is_graded`:
  1. `replies = simulator.send()` (run in a thread, since `send` is synchronous); 3 non-empty replies.
  2. `await asyncio.sleep(INITIAL_WAIT)` (design.md §Evaluation run).
  3. Up to `ROUNDS` grading rounds:
     ```python
     for _ in range(ROUNDS):
         code, body = await client.evaluate(simulator.session_id)
         assert code == 202, f"/eval failed: {body.get('error')}"
         result = await client.wait(simulator.session_id, expected=3)
         if result["complete"]:
             break
         # not all graded: the next /eval queues pending, failed and leftover grading traces
         await asyncio.sleep(ROUND_INTERVAL)
     ```
  4. Assert `result["complete"]`, with the message `"<graded> of 3 requests graded after <ROUNDS> rounds
     (<pending> pending, <failed> failed, <grading> still grading, <unfinished> unfinished): <errors>"`.
  - Judge outcomes are not asserted, only that every request was graded and stored.

**Run:**

```bash
cd examples/aws-serverless/langfuse-trace-evaluation
./build.sh local && uv run pytest tests/                    # unit tests
cd deploy && ./deploy.sh local && cd ..
uv run python simulate_traffic.py                          # 3 questions; prints the session id
AK_TEST_ENDPOINT=$(terraform -chdir=deploy output -raw agent_invoke_url) uv run pytest lambda_test.py
```
