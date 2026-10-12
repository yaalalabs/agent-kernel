# #803: Agent evaluation on production traffic — Implementation Spec

This spec details how to build the three phases [design.md](design.md) requires: Phase 1 (fetch) in Agent
Kernel core, and Phases 2 (evaluate) and 3 (store) in the `aws-serverless/langfuse-trace-evaluation`
example.

**Phase 1** adds a `fetch(query)` method to `BaseTrace` and a `Trace.fetch(...)` facade.
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
├── __init__.py          # + exports FetchedSpan, OTelSpanClassifier, SpanKind, SpanUsage, TraceQuery
├── base.py              # + BaseTrace.fetch (non-abstract)
├── trace.py             # + Trace.fetch facade
├── fetch.py             # NEW: SpanKind, TraceQuery, SpanUsage, FetchedSpan, OTelSpanClassifier
├── testing.py           # NEW: TraceFetchContract (imports pytest; test code only)
├── langfuse/
│   ├── langfuse.py      # + LangFuse.fetch → LangfuseTraceFetcher; + LangFuse.flush_on_lambda
│   ├── <6 runners>.py   # each run() flushes through LangFuse.flush_on_lambda in a finally
│   └── fetch.py         # NEW: LangfuseTraceFetcher
├── logfire/
│   ├── logfire.py       # + Logfire.fetch → LogfireTraceFetcher; scrubbing callback in init()
│   └── fetch.py         # NEW: LogfireTraceFetcher
├── openllmetry/
│   ├── openllmetry.py   # + OpenLLMetry.fetch → TraceloopTraceFetcher
│   └── fetch.py         # NEW: TraceloopTraceFetcher
└── cloudwatch/
    ├── cloudwatch.py    # + CloudWatch.fetch → CloudWatchTraceFetcher; + CloudWatch.region()
    └── fetch.py         # NEW: CloudWatchTraceFetcher
```

The provider packages' `__init__.py` files are empty today and stay empty. So
`agentkernel.trace.<provider>.fetch` can be imported without the provider SDK.

### Rules

1. **Fetchers never read `AKConfig`.** Each fetcher takes explicit constructor parameters: a client,
   a token, a base URL, an optional transport. The tracer class builds its fetcher. This is the same
   rule as the shared DB drivers and transports.
2. **Fetcher modules import no provider SDK at module scope.**
   - `langfuse/fetch.py` imports `Langfuse` under `TYPE_CHECKING` only.
   - `logfire/fetch.py` imports `LogfireQueryClient` inside `fetch()`.
   - `openllmetry/fetch.py` imports only `httpx`, which the core test environment already has.
   - `cloudwatch/fetch.py` imports `botocore` and the `CloudWatch` tracer module (which pulls in the
     OpenTelemetry SDK) inside `_create_client()`, used only when no client is injected.
   - This keeps the fetchers testable without the extras.
3. **Classification is per span, never per provider.** Every OTel-shaped result (Logfire, Traceloop and CloudWatch)
   goes through `OTelSpanClassifier`. Langfuse already types its observations server-side, so its
   types are mapped directly.
4. **Same result contract for every tracer.**
   - Spans come back oldest first, with at most `limit` of them; when more match, the most recent are
     kept.
   - Span ids are unique.
   - `raw` holds the provider record.
   - `fetch` itself never parses or rewrites `input`/`output`.
5. **Filters are checked again locally** wherever the server-side filter could be approximate. Langfuse
   and Traceloop run every span through `TraceQuery.matches` (window, kinds, session, trace ids, name);
   Logfire re-checks kinds, and CloudWatch window, session and kind (`_matches`). A span whose computed
   `kind` is not in `query.kinds` is never returned. Both checks are strict: a span that doesn't report
   a value for an active filter (start time, session id, name) is rejected, never assumed to match.
6. **Every fetch implementation passes `TraceFetchContract`** where its backend can be faked faithfully
   (§`trace/testing.py`).

### `trace/fetch.py`

```python
class SpanKind(str, Enum):
    AGENT = "agent"; LLM = "llm"; TOOL = "tool"; SPAN = "span"

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

class OTelSpanClassifier:
    @classmethod
    def classify(cls, attributes: dict, name: str | None = None) -> SpanKind: ...
    @classmethod
    def io(cls, attributes: dict) -> tuple[Any, Any]: ...
    @classmethod
    def session_id(cls, attributes: dict) -> str | None: ...
    @classmethod
    def usage(cls, attributes: dict) -> SpanUsage | None: ...
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
- Module-level functions: none. All logic is on these five classes.

### `BaseTrace.fetch` and `Trace.fetch`

```python
# trace/base.py
class BaseTrace(ABC):
    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        raise NotImplementedError(f"{type(self).__name__} does not support fetching spans")

# trace/trace.py
class Trace(BaseTrace):
    def fetch(self, query: TraceQuery | None = None, **filters) -> list[FetchedSpan]:
        if self._instance is None:
            raise AKConfigError("cannot fetch spans: tracing is disabled (set trace.enabled: true)")
        if query is not None and filters:
            raise ValueError("pass either a TraceQuery or keyword filters, not both")
        return self._instance.fetch(query if query is not None else TraceQuery(**filters))
```

- `base.py` imports `FetchedSpan`/`TraceQuery` from `.fetch`. There is no import cycle: `fetch.py`
  imports only stdlib and pydantic.
- Unknown keyword filters raise Pydantic's `ValidationError`, because `TraceQuery` is built from them.
- `query` combined with keyword filters raises `ValueError` (design.md §Public API).

### `LangFuse.fetch` → `LangfuseTraceFetcher`

```python
class LangfuseTraceFetcher:
    _PAGE_SIZE = 100
    _FIELDS = "core,basic,time,io,metadata,model,usage,metrics"
    _EXPAND_METADATA = "attributes"           # metadata values over 200 chars are truncated unless listed"
    _TYPES = {SpanKind.AGENT: "AGENT", SpanKind.LLM: "GENERATION", SpanKind.TOOL: "TOOL"}

    def __init__(self, client: "Langfuse"): ...
    def fetch(self, query: TraceQuery) -> list[FetchedSpan]: ...
    def _types(self, query) -> list[str | None]: ...      # [None] when kinds is None or contains SPAN
    def _pages(self, query, start, end, langfuse_type, trace_id) -> Iterator[Any]: ...
    def _to_span(self, observation) -> FetchedSpan: ...
```

- `LangFuse.fetch(query)` returns `LangfuseTraceFetcher(self._client).fetch(query)`. `self._client` is
  the client `init()` builds with `get_client()` (`trace/langfuse/langfuse.py:24`).
- Request matrix: `for type in _types(query)` × `for trace_id in query.trace_ids or [None]`. Each cell
  runs one cursor loop over `client.api.observations.get_many(...)` with these parameters:
  - `fields=_FIELDS`, `expand_metadata=_EXPAND_METADATA`, `limit=min(100, query.limit)`, `cursor`
  - `type`, `trace_id`, `session_id=query.session_id`, `name=query.name`
  - `from_start_time=start`, `to_start_time=end`
- Each observation is dropped unless `query.matches(span)`. Each loop stops when the cursor is empty, the
  page is empty, the cursor repeats the previous one, or that cell has accepted `query.limit` spans.
  - The repeated-cursor stop matters because local filtering can keep `limit` from ever being reached; a
    backend that returned the same cursor would otherwise page forever. Langfuse pages newest first, so the newest spans are seen first.
- Merge: `dict.setdefault(span_id, span)`, then `FetchedSpan.oldest_first(...)[-limit:]`.
- `_to_span` field mapping:

  | `FetchedSpan` | from the observation |
  |---|---|
  | `trace_id`, `span_id` | `trace_id`, `id` |
  | `parent_span_id` | `parent_observation_id` |
  | `kind` | `_TYPES` reversed, default `span` |
  | `session_id`, `input`, `output` | same-named fields, read with `getattr`, default `None` |
  | `usage` | `_usage`: `SpanUsage.of(usage_details["input"], ["output"], ["total"], cost=total_cost, else cost_details["total"])` |
  | `attributes` | `metadata["attributes"]` if `metadata` is a dict holding that key, else `metadata`, else `{}` |
  | `raw` | `observation.model_dump(mode="json", exclude_none=True)` |

### `Logfire.fetch` → `LogfireTraceFetcher`

```python
class LogfireTraceFetcher:
    READ_TOKEN_ENV = "LOGFIRE_READ_TOKEN"
    _MAX_ROWS = 10_000
    _COLUMNS = "trace_id, span_id, parent_span_id, span_name, message, start_timestamp, end_timestamp, attributes, tags, otel_scope_name"
    _KIND_SQL: dict[SpanKind, str]            # SQL equivalents of OTelSpanClassifier rows 1–5

    def __init__(self, read_token: str | None = None, base_url: str | None = None): ...
    def fetch(self, query: TraceQuery) -> list[FetchedSpan]: ...
    def _sql(self, query, limit: int, before: datetime | None) -> str: ...
    @staticmethod
    def _literal(value: str) -> str: ...      # "'" + value.replace("'", "''") + "'"
    def _to_span(self, row: dict) -> FetchedSpan: ...
```

- Token: the constructor argument, else `os.getenv("LOGFIRE_READ_TOKEN")`, per design.md
  §Configuration (credentials come from the environment, as on the send side).
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
  | `name` | `(span_name = 'x' OR message = 'x')` |
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
    timestamp index is used.
- Paging loop: `page = min(_MAX_ROWS, limit - accepted)`. After each page:
  1. Drop rows whose span id was already seen.
  2. Accept the fresh spans that `query.accepts`, setting `span.session_id = span.session_id or query.session_id`.
  3. Set `before = min(start_time of fresh rows)`.
  4. Stop when `len(rows) < page`, when no fresh row has a start time, or when `limit` is reached.

  Rows at the boundary timestamp are re-read and skipped. A page made only of already-seen rows ends
  the loop, so it can't spin forever on a block of identical timestamps.
- `_to_span`:
  - `attributes` = `row["attributes"]`, JSON-decoded if it arrives as a string.
  - Classification uses `{**attributes, "logfire.msg_template": span_name, "logfire.tags": tags or []}`.
    Logfire stores the template as `span_name` and tags in their own column.
  - `name` = `message` (the formatted message), else `span_name`.
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

### `OpenLLMetry.fetch` → `TraceloopTraceFetcher`

```python
class TraceloopTraceFetcher:
    DEFAULT_BASE_URL = "https://api.traceloop.com"
    _PATH = "/v2/warehouse/spans"
    _PAGE_SIZE = 500
    _TIMEOUT = 60.0
    _SESSION_ATTRIBUTE = "traceloop.association.properties.session_id"
    _OPERATIONS = {SpanKind.AGENT: ["invoke_agent", "create_agent"],
                   SpanKind.LLM: ["chat", "text_completion", "generate_content"],
                   SpanKind.TOOL: ["execute_tool"]}

    def __init__(self, api_key=None, base_url=None, transport: httpx.BaseTransport | None = None): ...
    def fetch(self, query: TraceQuery) -> list[FetchedSpan]: ...
    def _params(self, query, start, end) -> dict: ...
    def _pages(self, client: httpx.Client, params: dict) -> Iterator[dict]: ...
    def _to_span(self, item: dict) -> FetchedSpan: ...
    @staticmethod
    def _timestamp(value) -> datetime | None: ...
```

- Credentials:
  - API key: the argument, else `TRACELOOP_API_KEY`.
  - Base URL: the argument, else `TRACELOOP_BASE_URL`, else `DEFAULT_BASE_URL`.
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
    - `kinds` without `span` → `gen_ai.operation.name in [ops…]`
    - `session_id` → `_SESSION_ATTRIBUTE equals …`
    - `trace_ids` → `trace_id in […]`
- Pagination: response body `{"spans": {"data": [...], "next_cursor": ...}}`. A body without `spans`
  is read as the page itself. The loop stops on a missing cursor, empty data, or a cursor equal to the
  one just sent, and otherwise re-sends the same params with `cursor=...`.
- Local re-check: drop a span unless `query.matches(span)`. Stop once `limit` spans are accepted; with
  descending order these are the most recent.
- `_to_span`:
  - `attributes` = `span_attributes`, JSON-decoded if it arrives as a string.
  - `parent_span_id` = `parent_span_id or None` (the API may return `""` for a root span).
  - `input`/`output` = the item's top-level `input`/`output` when not `None`, else `OTelSpanClassifier.io`.
  - `end_time` = `start_time + timedelta(milliseconds=duration_ms)` when both are known.
  - `usage` = `OTelSpanClassifier.usage(attributes)`. Top-level warehouse columns (the API sorts by
    `total_tokens`) are not read: their names are undocumented.
- `_timestamp`, because the warehouse format is undocumented:
  - A non-numeric string → `datetime.fromisoformat` (with `Z` → `+00:00`).
  - A number → epoch ns if `> 1e17`, µs if `> 1e14`, ms if `> 1e11`, otherwise seconds; always UTC.

### `CloudWatch.fetch` → `CloudWatchTraceFetcher`

```python
class CloudWatchTraceFetcher:
    LOG_GROUP = "aws/spans"
    _MAX_ROWS = 10_000
    _POLL_INTERVAL = 1.0
    _END_PADDING = timedelta(minutes=15)
    _FAILED = {"Failed", "Cancelled", "Timeout", "Unknown"}
    _KIND_FILTERS: dict[SpanKind, str]        # Logs Insights equivalents of OTelSpanClassifier rows 1 and 3

    def __init__(self, client=None, region: str | None = None, log_group: str = LOG_GROUP, timeout: float = 120.0): ...
    def fetch(self, query: TraceQuery) -> list[FetchedSpan]: ...
    def _create_client(self): ...                      # botocore "logs" client, region via CloudWatch.region()
    def _run(self, client, query_string: str, start: datetime, end: datetime) -> list[dict[str, str]]: ...
    def _insights(self, query: TraceQuery, limit: int) -> str: ...
    @staticmethod
    def _literal(value: str) -> str: ...               # json.dumps(value)
    @staticmethod
    def _matches(query, span, start, end) -> bool: ...  # window on start_time, session, kind
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

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        from .fetch import CloudWatchTraceFetcher
        return CloudWatchTraceFetcher().fetch(query)
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
- Window and paging (`fetch`):
  - The first query's range is `[start, before]` with `before = max(end, min(end + _END_PADDING, now))`.
    `@timestamp`'s relation to the span start is not documented, so the range runs past `end`, and
    `_matches` applies `start <= start_time < end` locally on `startTimeUnixNano`.
  - `page = min(_MAX_ROWS, limit - accepted)`. After each page:
    1. Drop rows whose span id was already seen.
    2. Accept the fresh spans that `_matches`, setting `span.session_id = span.session_id or query.session_id`.
    3. Set `before = min(@timestamp of fresh rows)`. The next query's `endTime` is `ceil(before)`, so rows
       in the boundary second are re-read and skipped by span id.
    4. Stop when `len(rows) < page`, when no fresh row has a `@timestamp`, or when `limit` is reached.
       A full page with no fresh rows (more than `page` spans in one second) logs a warning and stops.
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
- `tracer` may be any object with `fetch(query)`; the Traceloop subclass passes the fetcher itself,
  because `OpenLLMetry.fetch` builds its fetcher without a transport.
- Subclasses (`tests/test_trace_fetch_contract.py`):
  - `TestInMemoryTraceContract`: `InMemoryTrace(BaseTrace)`, whose `fetch` is
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
- New environment variable `LOGFIRE_READ_TOKEN`, read only by `LogfireTraceFetcher`.
  - It is not an `AK_*` variable, because it is the provider's own credential, like `LOGFIRE_TOKEN` and
    `TRACELOOP_API_KEY`.
  - It can't be derived from `LOGFIRE_TOKEN` (a write token cannot read).
- `TRACELOOP_API_KEY` and `TRACELOOP_BASE_URL` are reused. Langfuse's `LANGFUSE_*` are reused through
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
3. **Langfuse runners on AWS Lambda flush after every run.** Before: spans waited for the background
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

## Phase 1 error handling

| Situation | Surfaces as |
|---|---|
| `Trace.fetch` with `trace.enabled: false` | `AKConfigError("cannot fetch spans: tracing is disabled …")` |
| Bring-your-own tracer without `fetch` | `NotImplementedError("<Class> does not support fetching spans")` |
| Bad filter value (`limit=0`, unknown kind, unknown kwarg) | Pydantic `ValidationError` from `TraceQuery` |
| `start >= end` | `ValueError` from `TraceQuery.window()`, raised before any network call |
| Logfire with no read token | `AKConfigError` naming `LOGFIRE_READ_TOKEN`, raised before the SDK import |
| Traceloop with no API key | `AKConfigError` naming `TRACELOOP_API_KEY`, raised before any request |
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
  - the default `BaseTrace.fetch` raises `NotImplementedError`
- `TestLangfuseFetcher` (a `MagicMock` client):
  - cursor followed
  - parameter translation
  - one request per type × trace id
  - `span` kind → `type=None` plus local filtering
  - `limit=1` keeps the newest span and stops after one page
  - `usage_details` + `total_cost` mapped to `SpanUsage`; an observation without them → `None`
- `TestLogfireFetcher` (fake `logfire`, `logfire.experimental` and `logfire.experimental.query_client`
  modules in `sys.modules`):
  - missing token raises
  - window passed as `min_timestamp`/`max_timestamp`
  - kind and session SQL present
  - backward paging past a patched `_MAX_ROWS = 2`, with boundary dedupe and the `start_timestamp <=`
    cursor
  - literal escaping
  - `NOT COALESCE` for `span`
  - `gen_ai.usage.*` attributes mapped to `usage`
- `TestTraceloopFetcher` (`httpx.MockTransport`):
  - missing key raises
  - Bearer header, timestamp params and `filters` JSON
  - cursor followed
  - LLM and other-session spans dropped locally
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

**Before merge, manual live checks** (not CI; they need accounts): run `Trace.get().fetch(kinds=["tool"])`
against each provider after a real agent run, and tick off `research/provider-read-apis.md` §5 and §6:
- Langfuse maps our spans to type `TOOL`.
- Logfire `attributes->>` access works and the session subquery matches.
- Traceloop accepts the `gen_ai.operation.name` / association-property / `trace_id` filter ids.
- CloudWatch: the `@message` shape, that the dotted `attributes.*` filters match, and what `@timestamp`
  is for a span.

## Phases 2–3 design (example)

Phases 2 and 3 add no Agent Kernel core code. Everything below lives in
`examples/aws-serverless/langfuse-trace-evaluation/` and uses only public AK API: `Trace.get().fetch(...)`,
`FetchedSpan`, `SpanKind`, `SpanUsage`, `OTelSpanClassifier`, `AKEvaluator`, `AKEvaluationCase`,
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
│   ├── job.py               # TraceEvaluationJob, RunSummary
│   ├── case.py              # ToolCall, TraceCase, TraceEvaluationCase
│   ├── opik_evaluator.py    # OpikTraceEvaluator (not opik.py, which would shadow the SDK)
│   └── store.py             # EvaluationStore, RunStatus
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
4. **Every write is idempotent**, and the `TRACE` item is written last (§`evaluator/store.py`).
5. **One bad trace or metric never fails the run; any other error fails it** and is reported through the
   session's `STATUS` item (§Phases 2–3 error handling).

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
    @property
    def latency_ms(self) -> int | None: ...
    @classmethod
    def from_spans(cls, trace_id: str, spans: list[FetchedSpan]) -> "TraceCase | None": ...
    def transcript(self) -> str: ...
    def to_evaluation_case(self, threshold: float) -> "TraceEvaluationCase": ...

class TraceEvaluationCase(AKEvaluationCase):
    transcript: str
    tool_call_count: int = 0
```

- `from_spans`:
  - Root: the single span whose `parent_span_id` is `None`. None, or more than one → `None`, logged. A
    `None` result means "not a request": the job never counts it (design.md §Trace case).
  - Tool spans: `span.kind == SpanKind.TOOL`, or `OTelSpanClassifier.classify(span.attributes) == TOOL`
    (the fallback design.md §Trace case explains). `failed` = `span.raw.get("level") == "ERROR"`.
  - Agent spans: `span.kind == SpanKind.AGENT` (or the same fallback), their `name`s, de-duplicated in order.
  - `usage`: each field is the sum of the non-`None` values across spans, or `None` when no span has
    one.
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
class RunStatus(StrEnum):
    NOT_STARTED = "not_started"      # returned by /check only; never written
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

class EvaluationStore:
    TRACE_SK = "TRACE"
    STATUS_SK = "STATUS"
    FIELD_LIMIT = 4_096          # characters per input/output field
    TOOL_CALLS_LIMIT = 25        # tool calls stored on the TRACE item
    ITEM_LIMIT = 380_000         # bytes: DynamoDB's 400 KB item cap minus headroom
    TTL = timedelta(days=90)

    def __init__(self, table: Any): ...                             # a boto3 dynamodb Table resource
    @classmethod
    def for_table(cls, table_name: str) -> "EvaluationStore": ...  # boto3.resource("dynamodb").Table(name)
    def evaluated(self, trace_ids: list[str]) -> set[str]: ...
    def save(self, case: TraceCase, results: list[AKEvaluationResult], evaluated_at: datetime) -> None: ...
    def graded(self, session_id: str) -> int: ...
    def set_status(self, session_id: str, status: RunStatus, summary: "RunSummary | None" = None,
                   error: str | None = None) -> None: ...
    def status(self, session_id: str) -> dict | None: ...           # the STATUS item, or None
    @staticmethod
    def _status_key(session_id: str) -> dict: ...                   # {"trace_id": f"#run#{session_id}", "sk": "STATUS"}
    @staticmethod
    def _number(value: float | int | None) -> Decimal | None: ...  # Decimal(str(value))
    @classmethod
    def _cut(cls, text: str | None) -> str | None: ...
    @staticmethod
    def _item_size(item: dict) -> int: ...                          # DynamoDB-sized bytes of a whole item
```

- `evaluated`: `table.meta.client.batch_get_item` in chunks of 100 keys `{"trace_id": id, "sk": "TRACE"}`,
  projecting only `trace_id`. `UnprocessedKeys` are retried up to 3 times with 0.5 s, 1 s, 2 s waits, then
  raise `RuntimeError` (an infrastructure error under rule 5).
- `save`:
  1. `EVAL#<metric>#<evaluator>` items through `table.batch_writer(overwrite_by_pkeys=["trace_id", "sk"])`
     (boto3 retries unprocessed items itself).
  2. Then `table.put_item` of the `TRACE` item.
  - Shared attributes on every item: `trace_id`, `sk`, `session_id` (omitted when `None`, so the sparse
    `session_id-index` skips it), `evaluated_at` (ISO 8601 UTC), `expires_at` (epoch seconds,
    `evaluated_at + TTL`).
  - `EVAL#…` attributes: `metric`, `evaluator`, `score`, `threshold`, `passed`, `reason`,
    `higher_is_better`, `attempts`. `None` values are omitted rather than written (boto3 would store them
    as DynamoDB `NULL`), so a missing `score` reads the same as an unscored one.
  - `TRACE` attributes: `provider="langfuse"`, `root_name`, `started_at`, `latency_ms`, `input`,
    `output`, `tool_calls` (list of maps, each field cut), `tool_call_count`, `tool_error_count`,
    `agents`, `span_count`, `input_tokens`, `output_tokens`, `total_tokens`, `cost`, `passed`
    (`True` when every scored result passed, `False` when one failed, omitted when none scored),
    `metric_errors` (count of `score=None` results), and `spans_gz` or `spans_truncated`.
  - Size budget for the `TRACE` item. A per-field limit alone can't keep an item under 400 KB: strings
    are cut by characters (up to 4 bytes each in UTF-8), and the number of tool calls has no bound.
    1. Text fields are cut with `_cut`. `tool_calls` keeps the first `TOOL_CALLS_LIMIT` calls; when it
       drops any, it sets `tool_calls_truncated=True`. `tool_call_count` and `tool_error_count` still
       count every call.
    2. `_item_size(item)` measures the whole item without spans: the UTF-8 bytes of each attribute name
       and string value, binary lengths, and 21 bytes per number (DynamoDB's documented upper bound),
       recursing into lists and maps.
    3. If it is still over `ITEM_LIMIT` (many long tool calls), tool calls are dropped from the end, then
       `input` and `output` are cut by halves, until it fits.
    4. `spans_gz` = `gzip.compress(json.dumps([span.model_dump(mode="json") for span in case.spans]))`.
       It is attached as Binary only when the item size plus `len("spans_gz") + len(spans_gz)` is ≤
       `ITEM_LIMIT`. Otherwise it is omitted and `spans_truncated=True`.
  - `EVAL#…` items hold only a metric's fields; `reason` is cut with `_cut`, so they stay far below the
    cap.
  - Without the budget, an oversized trace would make `put_item` raise `ValidationException` and fail the
    run.
  - `_cut`: the first `FIELD_LIMIT` characters plus `"…[truncated]"` when longer.
- `graded(session_id)`: `table.query` on `session_id-index` with `session_id = :s AND sk = :trace`,
  `Select="COUNT"`, following `LastEvaluatedKey`. The `STATUS` item carries no `session_id` attribute, so
  the index never holds it.
- `set_status`: `put_item` of `_status_key(session_id)` with `status`, `updated_at` (ISO 8601 UTC),
  `expires_at`, plus, when given, the summary's counts (`requests`, `graded`, `already_graded`,
  `unfinished`, `no_root`, `metric_errors`) and `error` (cut with `_cut`).
- `status(session_id)`: `get_item` of `_status_key(session_id)` with `ConsistentRead=True`, so `/check`
  never reads a stale status after the run's final write.

### `evaluator/job.py`

```python
class RunSummary(BaseModel):
    session_id: str
    spans_fetched: int = 0
    requests: int = 0            # traces with one root span
    graded: int = 0              # graded in this run
    already_graded: int = 0      # skipped: TRACE item already present
    unfinished: int = 0          # root span without end time or output: not graded
    no_root: int = 0             # traces with no root span (or several): not requests, not graded
    metric_errors: int = 0

class TraceEvaluationJob:
    FETCH_WINDOW = timedelta(hours=24)
    FETCH_LIMIT = 5_000

    def __init__(self, trace: Trace, evaluators: list[OpikTraceEvaluator], store: EvaluationStore,
                 clock: Callable[[], datetime] = ...): ...
    @classmethod
    def from_env(cls) -> "TraceEvaluationJob": ...
    def run(self, session_id: str) -> RunSummary: ...
    def _fetch(self, session_id: str) -> list[FetchedSpan]: ...
    def _cases(self, spans: list[FetchedSpan], summary: RunSummary) -> list[TraceCase]: ...
    def _evaluate(self, case: TraceCase) -> list[AKEvaluationResult]: ...
```

- `from_env()`: `Trace.get()` (reads `AK_TRACE__*`; `LangFuse.init()` checks the Langfuse keys),
  `OpikTraceEvaluator.all(AKTestConfig.get())` (reads `AK_TEST__LLM__*`),
  `EvaluationStore.for_table(os.environ["RESULTS_TABLE"])`.
- `run(session_id)`:
  1. `store.set_status(session_id, RUNNING)`.
  2. Inside one `try`:
     1. `spans = _fetch(session_id)`.
     2. `cases = _cases(spans, summary)`: group by `trace_id`; `TraceCase.from_spans`; a `None` →
        `no_root`; otherwise `requests += 1`; oldest first by `started_at`.
     3. Unfinished cases → `unfinished`, not graded.
     4. Drop finished cases in `store.evaluated(...)` → `already_graded`.
     5. For each remaining case: `results = _evaluate(case)`; `store.save(case, results, clock())`;
        `graded += 1`; `metric_errors += ` the results with `score is None`.
     6. `store.set_status(session_id, DONE, summary)`; log the summary; return it.
  3. `except Exception as e`: log it with the session id, `store.set_status(session_id, FAILED, summary,
     error=f"{type(e).__name__}: {e}")`, return the summary. Not re-raised: the status already carries the
     failure, and a re-raise would make AWS retry the asynchronous invocation. If that
     final `set_status` itself raises, the exception propagates and the status stays `running` (the
     caller's timeout reports it).
- `_fetch(session_id)`: `trace.fetch(session_id=session_id, last=FETCH_WINDOW, limit=FETCH_LIMIT)`.
  `len(spans) == FETCH_LIMIT` → `RuntimeError("session <id> has at least 5000 spans; refusing to grade a
  truncated session")`, because `fetch` keeps the newest `limit` spans and older requests would be silently
  missing.
- `_evaluate(case)`: `evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)`; one
  `evaluate_by_llm` per evaluator that `applies_to` it.
- Calling `run` twice for one session re-fetches, skips every trace already committed, and grades only
  the rest. Two overlapping runs for one session may both judge the same trace; their writes go to the
  same keys, so the table stays consistent and only judge cost is duplicated. The example accepts this
  rather than adding a run lock.

### `evaluator/api.py`

```python
class EvaluationAPI:
    EVALUATE_ACTION = "evaluate"

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
  Opik metrics are created by the first evaluation run, so `/chat` cold starts don't pay for them.
- `start(event, context)`:
  1. `body = json.loads(event.get("body") or "{}")`, as `schedule-openai/lambda_request_handler.py:93` reads
     it; invalid JSON or a missing/empty `session_id` string → `(400, {"error": ...})`.
  2. `store.set_status(session_id, RUNNING)`.
  3. `lambda_client.invoke(FunctionName=context.function_name, InvocationType="Event",
     Payload=json.dumps({"action": "evaluate", "session_id": session_id}))`.
  4. `(202, {"session_id": session_id, "status": "running"})`.
  - An exception in 2 or 3 propagates; `Lambda.handler` turns it into a `500` (`deployment/aws/serverless/aklambda.py:84-90`).
- `check(event, context)`:
  1. `params = event.get("queryStringParameters") or {}`; missing `session_id`, or `expected` that isn't
     a positive integer → `(400, {"error": ...})`.
  2. `item = store.status(session_id)`; `graded = store.graded(session_id)`.
  3. `(200, {"session_id", "status": item["status"] if item else "not_started", "expected", "graded",
     "complete": status == "done" and graded == expected, "error": item.get("error") if item else None})`.
  - `graded` is counted from the `TRACE` items, not read from the status item, so traces graded by an
    earlier run of the same session still count.
- `handler(event, context)`:
  - `event.get("action") == EVALUATE_ACTION` → `self._job().run(event["session_id"]).model_dump(mode="json")`.
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
    timeout           = 300                        # default 45 s: too short for the judges
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
  range_key    = "sk"
  attribute {
    name = "trace_id"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "session_id"
    type = "S"
  }
  global_secondary_index {
    name            = "session_id-index"
    hash_key        = "session_id"
    range_key       = "sk"
    projection_type = "ALL"
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
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
      },
    ]
  })
}
```

- The module creates the role and the function; the example only adds a policy to the role
  (`ak-deployment/ak-aws/serverless/outputs.tf:1-20`). There is no dependency cycle: the table doesn't
  depend on the module, the module reads only the table name, and the policy depends on both.
- The self-invoke needs no statement here: the module attaches the AWS-managed `AWSLambdaRole` policy
  (`lambda:InvokeFunction` on `*`) to the request handler's role (`modules/request-handler/main.tf:17-20`).
- Asynchronous invocations keep AWS's default of two retries. Only a timeout or crash triggers one (the
  run never raises), and a retry resumes the run, skipping the traces already graded.
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
dependencies = ["agentkernel[aws,openai,langfuse,opik]>=0.9.4", "boto3>=1.40.0"]

[dependency-groups]
dev = ["agentkernel[test]>=0.9.4", "httpx>=0.27.0", "moto[dynamodb]>=5.0.0", "black==26.5.1", "isort>=5.0.0"]
```

- One dependency set: the agent and the evaluator ship in one image. `boto3` is pinned because container
  images don't include the Lambda runtime's copy.
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
| `/check` before any `/eval` for the session | `200`, `status = "not_started"`, `complete = false` |
| `/eval` can't write the status or invoke itself (DynamoDB or IAM error) | `500` from `Lambda.handler`; no run starts |
| Langfuse keys missing or wrong | `LangFuse.init()` raises in the run (`trace/langfuse/langfuse.py:25-28`) → `failed`, error recorded |
| Langfuse fetch fails (HTTP error, rate limit) | Propagates from `fetch` (Phase 1 does no retries) → `failed` |
| The session has `FETCH_LIMIT` spans or more | `RuntimeError` from `_fetch` → `failed` |
| A trace has no root span, or several | `no_root`: logged, not a request, never written |
| A root span without end time or output | `unfinished`: counted, not written; `/check` then reports `graded < expected` |
| A judge call fails twice | That metric's item is stored with `score`/`passed` omitted and the error in `reason`; `metric_errors` counts it; the trace is still committed |
| DynamoDB error during the run (throttling after boto3's retries, access denied, unprocessed keys after 3 tries) | `failed`. Traces committed before it stay committed and are skipped by the next run |
| The `failed` status write itself fails | Propagates; the status stays `running`; the caller's poll deadline reports a timeout |
| Lambda timeout (300 s) mid-run | No status write; the status stays `running`. AWS retries the invocation (up to twice), which resumes the run and skips committed traces. A test still polling at its 360 s deadline reports a timeout |

- Concurrency: each run is single-threaded, so the job, store and evaluators hold no locks. Runs for
  different sessions are independent. Two runs for the same session may overlap (§`evaluator/job.py`).
- Cost per run: one Langfuse fetch of ~`ceil(spans / 100)` requests; one `BatchGetItem` per 100 requests;
  per graded trace three or four judge calls (one more per failed attempt), one batch write and one put;
  two status writes. `/check`: one `GetItem` and one `Query` per call.

## Phases 2–3 testing

**Unit tests, `tests/test_evaluator.py`** (no network; run by the weekly pipeline's `pytest` too):

- Span fixtures: a `FetchedSpan` factory shaped like the Langfuse OpenAI Agents tree in
  `research/span-formats.md` §3 (root `Agent Kernel OpenAI`, `triage` and `support` agents, a
  `get_order_status` tool, two generations with `usage`).
- `TestTraceCase`:
  - root input/output, JSON-string unwrapping, tool calls in order, `failed` from `raw.level`, agents,
    summed usage (and `None` when no span has usage), latency;
  - the tool fallback through `OTelSpanClassifier` for a span typed `span`;
  - no root span and two root spans → `None`; root span without `end_time` → not `finished`;
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
  - `save` writes the `EVAL#…` items and the `TRACE` item with the documented attributes, `Decimal`
    numbers, omitted `None`s, `expires_at`;
  - the `TRACE` item is written after the `EVAL#…` items (a store whose `put_item` raises leaves only
    `EVAL#…` items, and `evaluated()` doesn't report the trace);
  - `_cut` on long fields; `spans_gz` round-trips; spans that would push the item past `ITEM_LIMIT` →
    `spans_truncated`;
  - size budget: 100 tool calls with 4,096-char multi-byte (4-byte UTF-8) inputs/outputs → the item is
    written (moto enforces 400 KB), `tool_calls_truncated` is set, and `tool_call_count` is 100;
    `_item_size` against a hand-computed item;
  - `evaluated()` across more than 100 ids;
  - `graded()` counts only the session's `TRACE` items (not `EVAL#…`, not `STATUS`, not other sessions);
  - `set_status` / `status` round-trip with counts and error; no item → `None`.
- `TestTraceEvaluationJob` (fake `Trace` returning fixed spans, fake evaluators, the moto store, a fixed
  clock):
  - the fetch call (`session_id`, `last=24h`, `limit=5000`);
  - status `running` while the run is in progress (checked from a fake evaluator), then `done` with the
    summary's counts;
  - a trace with no root span → `no_root`, not counted in `requests`, nothing written;
  - an unfinished trace → `unfinished`, not written;
  - an already-graded trace → `already_graded`, its evaluator not called;
  - `metric_errors` counts `score=None` results;
  - a fetch error, a `FETCH_LIMIT`-sized result and a store error each → `failed` with the error, not
    raised; traces committed before a store error stay committed.
- `TestEvaluationAPI` (moto store, a fake Lambda client recording `invoke` calls, a fake job factory, a
  fake `lambda_handler`):
  - `start`: `202`, status `running` written, one `invoke` with `FunctionName=context.function_name`,
    `InvocationType="Event"` and the evaluate payload; invalid JSON and a missing `session_id` → `400`, no
    invoke;
  - `check`: `not_started`, `running`, `failed` (with `error`), `done` with `graded < expected`
    (`complete` false) and `done` with `graded == expected` (`complete` true); bad `expected` → `400`;
  - `handler`: the evaluate action → the job's `run`, built once across two calls; any other event → the
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
class EvaluationClient:                      # test helper, like APITestClient in openai-auth/lambda_test.py:15
    def __init__(self, chat_url: str): ...   # eval_url / check_url: the trailing "/chat" replaced
    async def evaluate(self, session_id: str) -> None: ...          # POST /eval; asserts 202
    async def wait(self, session_id: str, expected: int, timeout: float = 360,
                   every: float = 10) -> dict: ...                  # polls /check until done/failed or timeout
```

- Session-scoped fixtures: `chat_url = os.getenv("AK_TEST_ENDPOINT")` (as
  `openai-auth/lambda_test.py:82-84`), `simulator = TrafficSimulator(chat_url, session_id=str(uuid4()))`,
  `client = EvaluationClient(chat_url)`.
- `EvaluationClient.__init__` raises `ValueError` when `chat_url` doesn't end in `/chat`.
- `test_every_request_is_graded`:
  1. `replies = simulator.send()` (run in a thread, since `send` is synchronous); 3 non-empty replies.
  2. `await asyncio.sleep(60)` for Langfuse ingestion (design.md open question).
  3. Up to `ROUNDS = 3` grading rounds:
     ```python
     for _ in range(ROUNDS):
         await client.evaluate(simulator.session_id)
         result = await client.wait(simulator.session_id, expected=3)
         # stop on success, or on failed/running: another round wouldn't help
         if result["complete"] or result["status"] != "done":
             break
         # some traces weren't readable yet; the next run grades only those
         await asyncio.sleep(30)
     ```
  4. Assert `result["complete"]`. The failure message depends on the result:
     - `status == "failed"` → `"evaluation failed: <error>"`;
     - `status == "done"` → `"<graded> of 3 requests graded after 3 rounds"`;
     - `status == "running"` → `"timed out after 360 s"`.
  - Judge outcomes are not asserted, only that every request was graded and stored.

**Run:**

```bash
cd examples/aws-serverless/langfuse-trace-evaluation
./build.sh local && uv run pytest tests/                    # unit tests
cd deploy && ./deploy.sh local && cd ..
uv run python simulate_traffic.py                          # 3 questions; prints the session id
AK_TEST_ENDPOINT=$(terraform -chdir=deploy output -raw agent_invoke_url) uv run pytest lambda_test.py
```
