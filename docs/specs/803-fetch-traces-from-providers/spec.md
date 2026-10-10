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
├── __init__.py          # + exports FetchedSpan, SpanKind, SpanUsage, TraceQuery
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
   `kind` is not in `query.kinds` is never returned.
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
                                                          # a field the span doesn't report (None) never rejects it

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
        raise NotImplementedError(f"{type(self).__name__} does not support fetching traces")

# trace/trace.py
class Trace(BaseTrace):
    def fetch(self, query: TraceQuery | None = None, **filters) -> list[FetchedSpan]:
        if self._instance is None:
            raise AKConfigError("cannot fetch traces: tracing is disabled (set trace.enabled: true)")
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
    def test_contract_session_filter(self, tracer): ...
    def test_contract_trace_id_filter(self, tracer): ...
    def test_contract_name_filter(self, tracer): ...
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
     UI. Session ids are opaque identifiers, not credentials.
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
| `Trace.fetch` with `trace.enabled: false` | `AKConfigError("cannot fetch traces: tracing is disabled …")` |
| Bring-your-own tracer without `fetch` | `NotImplementedError("<Class> does not support fetching traces")` |
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
- `TraceQuery.matches`: each filter rejects, start inclusive, end exclusive; unreported fields don't
  reject.
- Langfuse: `expand_metadata="attributes"` is sent; a repeated cursor ends paging (a fake that always
  returns the same cursor with out-of-window observations makes exactly two calls).

**New `ak-py/tests/test_trace_fetch_contract.py`:** the three `TraceFetchContract` subclasses
(§`trace/testing.py`).

**Changed `ak-py/tests/test_trace_langfuse_langgraph.py`:** `TestLangFuseLambdaFlush`: flush on Lambda
after a run and after a failing run, no flush off Lambda, a failing flush is logged and not raised.

**Changed `ak-py/tests/test_trace_logfire.py`:**

- The `fake_logfire` fixture (`tests/test_trace_logfire.py:23-38`) adds
  `fake.ScrubbingOptions = MagicMock(side_effect=lambda **kw: kw)`. Without it, `init()` raises
  `AttributeError` against the fake module.
- New `test_init_keeps_session_id_from_scrubbing`: the callback returns the value for
  `("attributes", "session_id")` and `None` for `("attributes", "session_token")`.
- The existing `configure.assert_called_once()` assertions (`:56`, `:66`) stay valid.

**Run:**

```bash
cd ak-py && uv run pytest tests/test_trace_fetch.py tests/test_trace_fetch_contract.py tests/test_trace_logfire.py tests/test_trace.py tests/test_trace_langfuse_langgraph.py tests/test_trace_cloudwatch.py
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
`AKEvaluationResult`, `AKMetricNotSupported` and `AKTestConfig`.

### Example layout

```
examples/aws-serverless/langfuse-trace-evaluation/
├── README.md
├── pyproject.toml           # extras: agent, evaluator; dev group
├── uv.lock
├── build.sh                 # test venv: uv sync --all-extras (or the local ak-py wheel with `local`)
├── config.yaml              # the agent's AKConfig: trace.enabled true, trace.type langfuse
├── test-config.yaml         # Test.compare judge for lambda_test.py (gpt-4.1-mini, like the siblings)
├── lambda.py                # the agent under evaluation
├── simulate_traffic.py      # TrafficSimulator: 5 questions → evaluate → report
├── evaluator/
│   ├── __init__.py
│   ├── handler.py           # handler(event, context): the Lambda entry point
│   ├── job.py               # TraceEvaluationJob, EvaluationWindow, RunSummary
│   ├── case.py              # ToolCall, TraceCase, TraceEvaluationCase
│   ├── opik_evaluator.py    # OpikTraceEvaluator (not opik.py, which would shadow the SDK)
│   └── store.py             # EvaluationStore
├── tests/
│   └── test_evaluator.py    # unit tests, no cloud access
├── lambda_test.py           # weekly integration test
└── deploy/
    ├── main.tf  variables.tf  outputs.tf  providers.tf  backend.tf  terraform.tfvars
    ├── deploy.sh
    ├── Dockerfile.agent      # FROM public.ecr.aws/lambda/python:3.12, CMD ["lambda.handler"]
    └── Dockerfile.evaluator  # same base image, CMD ["evaluator.handler.handler"]
```

### Rules

1. **No AK core changes.** If the example needs something AK lacks, it is raised as a design.md open
   question, not patched in core inside this change.
2. **Classes, not scripts.** Each component below is a class; the only module-level functions are the
   two Lambda entry points (`lambda.handler`, `evaluator.handler.handler`), which Lambda requires.
3. **Configuration from the environment only.** `TraceEvaluationJob.from_env()` is the one place that
   reads environment variables; the other classes take constructor parameters, so the unit tests build
   them directly.
4. **Every write is idempotent**, and the `TRACE` item is written last (§`EvaluationStore`).
5. **One bad trace or metric never fails the run; an infrastructure error always does** (§Error
   handling).

### The agent (`lambda.py`, `config.yaml`)

```python
@function_tool
def get_order_status(order_id: str) -> str: ...      # fixed table lookup: deterministic tool output

support_agent = Agent(name="support", handoff_description="Order and delivery questions",
                      tools=[get_order_status], model="gpt-4.1-mini", instructions=...)
triage_agent = Agent(name="triage", handoffs=[support_agent], model="gpt-4.1-mini", instructions=...)
OpenAIModule([triage_agent, support_agent])

handler = Lambda.handler    # the Langfuse runners flush on Lambda themselves (Phase 1)
```

- `config.yaml`: `trace: {enabled: true, type: langfuse}`. No `session` block (in-memory): each test
  prompt is a single turn, so no Redis is needed.
- `get_order_status` knows two orders (`A-1001`: shipped, arriving Friday; `A-1002`: processing, paid,
  ships Monday) and returns `"Order <id> not found"` for any other id, so the traffic includes one
  tool result the agent must report honestly.

### `simulate_traffic.py`: `TrafficSimulator`

```python
class TrafficSimulator:
    QUESTIONS = (
        "Where is my order A-1001?",                                     # hand-off + tool call
        "Can you check order A-9999 for me?",                            # tool returns "not found"
        "What are your support hours?",                                  # triage answers, no tool
        "Has order A-1002 been paid, and when will it ship?",            # two facts from one tool result
        "Write me a poem about the ocean.",                              # off-topic: should decline
    )
    POLL_EVERY = 20       # seconds
    POLL_FOR = 300        # seconds

    def __init__(self, endpoint: str, function_name: str, table_name: str, lambda_client=None, table=None): ...
    @classmethod
    def from_terraform(cls, deploy_dir: Path) -> "TrafficSimulator": ...   # terraform output -raw ...
    def send(self) -> "TrafficRun": ...                    # 5 POSTs under one new session id
    def evaluate(self, run: "TrafficRun") -> dict: ...     # manual-window invokes until 5 TRACE items exist
    def report(self, run: "TrafficRun") -> list[dict]: ... # TRACE + EVAL# items of the session, per trace
    def main(self, argv: list[str] | None = None) -> int: ...

class TrafficRun(BaseModel):
    session_id: str
    started_at: datetime
    finished_at: datetime
    replies: list[str]

if __name__ == "__main__":
    sys.exit(TrafficSimulator.cli())       # parses flags, builds from terraform or flags, runs main
```

- `send()`: POST `{"prompt": q, "session_id": run.session_id, "agent": "triage"}` to the endpoint for each
  question in order, with the sibling `APITestClient`'s retry (3 tries on 5xx and timeouts, 30 s timeout).
  Each question is its own request, so each becomes its own trace.
- `evaluate(run)`: every `POLL_EVERY` seconds up to `POLL_FOR`, invoke the evaluator synchronously with
  `{"start": run.started_at − 1 min, "end": run.finished_at + 1 min}` (retrying
  `TooManyRequestsException`), then count the session's `TRACE` items through `session_id-index`; stop at
  5. Returns the last `RunSummary`. Raises `TimeoutError` with the count found if fewer than 5 appear.
- `report(run)`: queries `session_id-index` for the session, groups by `trace_id`, and returns one dict
  per trace (question, tool calls, tokens, cost, and per metric score, passed, reason), oldest first.
  `main` prints it as a table.
- Flags: `--endpoint`, `--function`, `--table` (default: `terraform output` in `deploy/`),
  `--no-evaluate` (send only; the scheduled run scores them later).
- AWS access: the caller's default credentials and region (`lambda:InvokeFunction`, `dynamodb:Query`).

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
    def complete(self) -> bool: ...           # ended_at is not None and output != ""
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
  - Root: the single span whose `parent_span_id` is `None`. None, or more than one → `None`, logged.
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
class EvaluationStore:
    TRACE_SK = "TRACE"
    JOB_KEY = {"trace_id": "#job", "sk": "WATERMARK"}
    FIELD_LIMIT = 4_096          # characters per input/output field
    SPANS_LIMIT = 300_000        # bytes of gzip-compressed spans
    TTL = timedelta(days=90)

    def __init__(self, table: Any): ...                             # a boto3 dynamodb Table resource
    @classmethod
    def for_table(cls, table_name: str) -> "EvaluationStore": ...  # boto3.resource("dynamodb").Table(name)
    def evaluated(self, trace_ids: list[str]) -> set[str]: ...
    def save(self, case: TraceCase, results: list[AKEvaluationResult], evaluated_at: datetime) -> None: ...
    def watermark(self) -> datetime | None: ...
    def set_watermark(self, at: datetime) -> None: ...
    @staticmethod
    def _number(value: float | int | None) -> Decimal | None: ...  # Decimal(str(value))
    @classmethod
    def _cut(cls, text: str | None) -> str | None: ...
```

- `evaluated`: `table.meta.client.batch_get_item` in chunks of 100 keys `{"trace_id": id, "sk": "TRACE"}`,
  projecting only `trace_id`. `UnprocessedKeys` are retried up to 3 times with 0.5 s, 1 s, 2 s waits, then
  raise `RuntimeError` (an infrastructure error under rule 5).
- `save`:
  1. `EVAL#<metric>#<evaluator>` items through `table.batch_writer(overwrite_by_pkeys=["trace_id", "sk"])`
     (boto3 retries unprocessed items itself).
  2. Then `table.put_item` of the `TRACE` item.
  - Shared attributes on every item: `trace_id`, `sk`, `session_id` (omitted when `None`, so the sparse
    `session_id-index` skips it), `evaluated_at` (ISO 8601 UTC), `evaluated_date` (`YYYY-MM-DD`),
    `expires_at` (epoch seconds, `evaluated_at + TTL`).
  - `EVAL#…` attributes: `metric`, `evaluator`, `score`, `threshold`, `passed`, `reason`,
    `higher_is_better`, `attempts`. `None` values are omitted rather than written (boto3 would store them
    as DynamoDB `NULL`), so a missing `score` reads the same as an unscored one.
  - `TRACE` attributes: `provider="langfuse"`, `root_name`, `started_at`, `latency_ms`, `input`,
    `output`, `tool_calls` (list of maps, each field cut), `tool_call_count`, `tool_error_count`,
    `agents`, `span_count`, `input_tokens`, `output_tokens`, `total_tokens`, `cost`, `passed`
    (`True` when every scored result passed, `False` when one failed, omitted when none scored),
    `metric_errors` (count of `score=None` results), and `spans_gz` or `spans_truncated`.
  - `spans_gz`: `gzip.compress(json.dumps([span.model_dump(mode="json") for span in case.spans]))`, stored as
    Binary when ≤ `SPANS_LIMIT`; otherwise omitted and `spans_truncated=True`.
  - `_cut`: the first `FIELD_LIMIT` characters plus `"…[truncated]"` when longer.
- `watermark` / `set_watermark`: `get_item` / `put_item` on `JOB_KEY` with attribute `at` (ISO 8601 UTC).

### `evaluator/job.py`

```python
class EvaluationWindow(BaseModel):
    start: datetime          # roots owned from here (inclusive)
    end: datetime            # to here (exclusive)
    manual: bool             # from the event; never reads or moves the watermark

class RunSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    manual: bool
    spans_fetched: int
    traces_seen: int
    evaluated: int
    already_evaluated: int
    incomplete: int
    abandoned: int
    deferred: int            # left for the next run by the per-run cap
    metric_errors: int
    watermark: datetime | None

class TraceEvaluationJob:
    LAG = timedelta(minutes=5)
    OVERLAP = timedelta(minutes=5)
    FIRST_WINDOW = timedelta(minutes=30)
    MAX_CATCH_UP = timedelta(hours=24)
    ABANDON_AFTER = timedelta(hours=1)
    FETCH_LIMIT = 5_000

    def __init__(self, trace: Trace, evaluators: list[OpikTraceEvaluator], store: EvaluationStore,
                 max_traces: int = 50, clock: Callable[[], datetime] = ...): ...
    @classmethod
    def from_env(cls) -> "TraceEvaluationJob": ...
    def run(self, event: dict) -> RunSummary: ...
    def _window(self, event: dict, now: datetime) -> EvaluationWindow: ...
    def _cases(self, spans: list[FetchedSpan], window: EvaluationWindow) -> list[TraceCase]: ...
    def _evaluate(self, case: TraceCase) -> list[AKEvaluationResult]: ...
    def _next_watermark(self, window, deferred, incomplete, spans, hit_limit) -> datetime: ...
```

- `from_env()`: `Trace.get()` (reads `AK_TRACE__*`; `LangFuse.init()` checks the Langfuse keys),
  `OpikTraceEvaluator.all(AKTestConfig.get())` (reads `AK_TEST__LLM__*`),
  `EvaluationStore.for_table(os.environ["RESULTS_TABLE"])`, `max_traces=int(os.getenv("MAX_TRACES_PER_RUN", "50"))`.
- `evaluator/handler.py`:
  ```python
  class _Holder:  # one job per sandbox: Trace.get() and the Opik metrics are built once, on the first invoke
      job: TraceEvaluationJob | None = None

  def handler(event: dict, context: Any) -> dict:
      _Holder.job = _Holder.job or TraceEvaluationJob.from_env()
      return _Holder.job.run(event).model_dump(mode="json")
  ```
- `_window(event, now)`:
  - Manual: `event` has both `start` and `end` (ISO 8601; naive → UTC). `start >= end` → `ValueError`.
  - Scheduled (any other event, e.g. EventBridge's): `end = now − LAG`; `start = watermark − OVERLAP`, or
    `end − FIRST_WINDOW` without one; when `start < end − MAX_CATCH_UP`, `start = end − MAX_CATCH_UP`, with a
    warning.
- `run(event)`:
  1. `now = clock()`; `window = _window(event, now)`.
  2. `spans = trace.fetch(start=window.start, end=now, limit=FETCH_LIMIT)`; `hit_limit = len(spans) == FETCH_LIMIT`.
  3. `_cases`: group by `trace_id`; `TraceCase.from_spans`; keep cases with
     `window.start <= started_at < window.end`, oldest first.
  4. Split: incomplete and `started_at >= window.end − ABANDON_AFTER` → `incomplete`; incomplete and older →
     `abandoned` (logged per trace); complete → candidates.
  5. Drop candidates in `store.evaluated(...)` → `already_evaluated`.
  6. Take the first `max_traces`; the rest → `deferred`.
  7. For each: `results = _evaluate(case)`; `store.save(case, results, clock())`.
  8. Scheduled windows only: `store.set_watermark(_next_watermark(...))`.
  9. Log and return the `RunSummary`.
- `_evaluate(case)`: `evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)`; one
  `evaluate_by_llm` per evaluator that `applies_to` it.
- `_next_watermark`: `min` of `window.end`; the `started_at` of the first deferred case; the oldest
  `incomplete` case's `started_at`; and, when `hit_limit`, the oldest fetched span's `start_time`.

### Deployment (`deploy/`)

```hcl
module "serverless_agents" {                       # the agent: same shape as aws-serverless/openai-auth
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.4"                                # the siblings' pin
  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  region               = var.region
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK Langfuse Trace Evaluation Example"
  request_handler = {
    function_name     = "trace-eval-agent"
    handler_path      = "lambda.handler"
    package_path      = "../dist_agent"
    package_type      = "Image"
    memory_size       = 1024
    security_group_id = var.request_handler_security_group_id
    environment_variables = {
      OPENAI_API_KEY      = var.openai_api_key
      LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
      LANGFUSE_SECRET_KEY = var.langfuse_secret_key
      LANGFUSE_BASE_URL   = var.langfuse_base_url
    }
  }
}

locals {
  # rebuild the evaluator image only when its code or locked dependencies change
  evaluator_tag = sha1(join("", concat(
    [for f in fileset("${path.module}/../evaluator", "**/*.py") : filesha1("${path.module}/../evaluator/${f}")],
    [filesha1("${path.module}/../uv.lock")],
  )))
}

module "evaluator_image" {
  source          = "terraform-aws-modules/lambda/aws//modules/docker-build"
  version         = "8.9.0"
  create_ecr_repo = true
  ecr_repo        = "${var.prefix}-trace-evaluator"
  source_path     = "${path.module}/../dist_evaluator"
  platform        = "linux/amd64"
  image_tag       = local.evaluator_tag
}

module "evaluator" {
  source                         = "terraform-aws-modules/lambda/aws"
  version                        = "8.9.0"
  function_name                  = "${var.prefix}-trace-evaluator"
  description                    = "Scores the agent's Langfuse traces with Opik and stores them in DynamoDB"
  create_package                 = false
  package_type                   = "Image"
  image_uri                      = module.evaluator_image.image_uri
  architectures                  = ["x86_64"]
  timeout                        = 900
  memory_size                    = 1024
  reserved_concurrent_executions = 1
  cloudwatch_logs_retention_in_days = 14
  environment_variables = {
    AK_TRACE__ENABLED      = "true"
    AK_TRACE__TYPE         = "langfuse"
    LANGFUSE_PUBLIC_KEY    = var.langfuse_public_key
    LANGFUSE_SECRET_KEY    = var.langfuse_secret_key
    LANGFUSE_BASE_URL      = var.langfuse_base_url
    OPENAI_API_KEY         = var.openai_api_key
    AK_TEST__LLM__PROVIDER = "openai"
    AK_TEST__LLM__MODEL    = "gpt-4.1-mini"
    OPIK_TRACK_DISABLE     = "true"
    RESULTS_TABLE          = aws_dynamodb_table.results.name
    MAX_TRACES_PER_RUN     = tostring(var.max_traces_per_run)
  }
  attach_policy_statements = true
  policy_statements = {
    results = {
      effect    = "Allow"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:Query"]
      resources = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
    }
  }
  allowed_triggers = {
    EvaluationSchedule = {
      principal  = "events.amazonaws.com"
      source_arn = aws_cloudwatch_event_rule.evaluation.arn
    }
  }
  create_current_version_allowed_triggers = false   # the rule targets the unqualified function
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
  attribute {
    name = "evaluated_date"
    type = "S"
  }
  attribute {
    name = "evaluated_at"
    type = "S"
  }
  global_secondary_index {
    name            = "session_id-index"
    hash_key        = "session_id"
    range_key       = "sk"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "evaluated_date-index"
    hash_key        = "evaluated_date"
    range_key       = "evaluated_at"
    projection_type = "ALL"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_cloudwatch_event_rule" "evaluation" {
  name                = "${var.prefix}-trace-evaluation"
  schedule_expression = var.evaluation_schedule      # default "rate(30 minutes)"
}

resource "aws_cloudwatch_event_target" "evaluation" {
  rule = aws_cloudwatch_event_rule.evaluation.name
  arn  = module.evaluator.lambda_function_arn
}
```

- `variables.tf`: `region`, `prefix`, `is_production` (default `false`), `openai_api_key`,
  `langfuse_public_key`, `langfuse_secret_key` (both `sensitive = true`), `langfuse_base_url` (default
  `"https://cloud.langfuse.com"`), `evaluation_schedule` (default `"rate(30 minutes)"`),
  `max_traces_per_run` (default `50`), `vpc_id`, `private_subnet_ids`, `request_handler_security_group_id`
  (default `null`). The last three take the names the weekly pipeline injects (`run_single_test.py`
  `deploy_aws_resources`).
- `outputs.tf`: `agent_invoke_url` (`module.serverless_agents.agent_invoke_url`, the name
  `run_single_test.py` `test_aws_deployment` reads), `evaluator_function_name`
  (`module.evaluator.lambda_function_name`), `results_table_name`.
- `providers.tf`: the siblings' file (`aws` and the ECR-authenticated `docker` provider), with
  `hashicorp/aws >= 6.28` (the lambda module 8.x minimum) instead of `>= 6.11.0`.
- `backend.tf`: the siblings' S3 backend with key `examples/aws-serverless/langfuse-trace-evaluation/terraform.tfstate`.
- `terraform.tfvars`: `region = "ap-southeast-2"`, `prefix = "ak-lf-trace-eval-dev-examples"`.
- `deploy.sh [local]`: builds `../dist_agent` (`uv export --extra agent`, or the `agentkernel[aws,openai,langfuse]`
  wheel from `../../../ak-py/dist` with `local`) and `../dist_evaluator` (`--extra evaluator`, or
  `agentkernel[langfuse,opik]` from the local wheel plus the exported `opik`/`boto3` pins), copies the
  sources and Dockerfiles in, then `terraform init` and `terraform apply`.

### `pyproject.toml`

```toml
[project.optional-dependencies]
agent = ["agentkernel[aws,openai,langfuse]>=0.9.4"]
evaluator = ["agentkernel[langfuse,opik]>=0.9.4", "boto3>=1.40.0"]

[dependency-groups]
dev = ["agentkernel[test]>=0.9.4", "boto3>=1.40.0", "httpx>=0.27.0", "moto[dynamodb]>=5.0.0", "black==26.5.1", "isort>=5.0.0"]
```

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

- No `AKConfig` changes. The example sets existing fields through the environment: `AK_TRACE__ENABLED`,
  `AK_TRACE__TYPE` (agent via `config.yaml`, evaluator via env), and `AK_TEST__LLM__PROVIDER` /
  `AK_TEST__LLM__MODEL` for the judge model.
- Example-only environment variables: `RESULTS_TABLE`, `MAX_TRACES_PER_RUN`.

### Behavioural changes

- None in AK from Phases 2–3 (the Langfuse flush is Phase 1 behavioural change 3). The weekly integration run gains one deployment (one agent Lambda, one evaluator Lambda,
  one ECR repository, one DynamoDB table, one EventBridge rule) and its judge calls: a few `gpt-4.1-mini`
  calls per test trace, on the existing CI OpenAI key.

## Phases 2–3 error handling

| Situation | What happens |
|---|---|
| Langfuse keys missing or wrong | `LangFuse.init()` raises on the first invoke (`trace/langfuse/langfuse.py:25-28`); the invocation fails; nothing is written |
| Langfuse fetch fails (HTTP error, rate limit) | Propagates (Phase 1 does no retries); the invocation fails before the watermark moves, so the next run covers the window again |
| A trace has no root, or several | Skipped and logged; not counted as incomplete; never written |
| Root still running | `incomplete`: not written; holds the watermark back so the next run sees it again |
| Root still running after `ABANDON_AFTER` | `abandoned`: logged, not written, no longer holds the watermark |
| A judge call fails twice | That metric's item is stored with `score`/`passed` omitted and the error in `reason`; `metric_errors` counts it; the trace is still committed |
| DynamoDB error (throttling after boto3's retries, access denied, unprocessed keys after 3 tries) | Propagates; the invocation fails. Traces committed before it stay committed; the rest are evaluated again next run (their `TRACE` item is missing) |
| Lambda timeout mid-run | Same as a DynamoDB error: the watermark isn't written, the committed traces are skipped next run. `MAX_TRACES_PER_RUN` keeps a normal run well inside 900 s |
| Two invocations at once | Reserved concurrency 1: the second is throttled (`TooManyRequestsException` for a synchronous invoke; EventBridge retries asynchronous ones) |
| Manual event with `start >= end` or bad ISO | `ValueError` before any fetch |

- Concurrency: one run at a time (reserved concurrency 1), and each run is single-threaded, so the job,
  store and evaluators hold no locks.
- Cost per run: one Langfuse fetch of ~`ceil(spans / 100)` requests; one `BatchGetItem` per 100 candidates;
  per evaluated trace three or four judge calls (one more per failed attempt) and one batch write plus one
  put.

## Phases 2–3 testing

**Unit tests, `tests/test_evaluator.py`** (no network; run by the weekly pipeline's `pytest` too):

- Span fixtures: a `FetchedSpan` factory shaped like the Langfuse OpenAI Agents tree in
  `research/span-formats.md` §3 (root `Agent Kernel OpenAI`, `triage` and `support` agents, a
  `get_order_status` tool, two generations with `usage`).
- `TestTraceCase`:
  - root input/output, JSON-string unwrapping, tool calls in order, `failed` from `raw.level`, agents,
    summed usage (and `None` when no span has usage), latency;
  - the tool fallback through `OTelSpanClassifier` for a span typed `span`;
  - no root and two roots → `None`; root without `end_time` → not `complete`;
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
  - `_cut` on long fields; `spans_gz` round-trips; over `SPANS_LIMIT` → `spans_truncated`;
  - `evaluated()` across more than 100 ids; watermark round-trip; no watermark → `None`.
- `TestTraceEvaluationJob` (fake `Trace` returning fixed spans, fake evaluators, the moto store, a fixed
  clock):
  - first-run window, watermark − overlap, the 24-hour clamp, the manual window (watermark neither read
    nor written), a bad manual window;
  - the fetch call (`start`, `end=now`, `limit`);
  - ownership: a root before `start` or at/after `end` isn't evaluated; later spans of an owned trace are
    included;
  - already-evaluated traces skipped; the per-run cap defers the rest and the watermark stops at the
    first deferred root;
  - an incomplete trace holds the watermark; an abandoned one doesn't; `hit_limit` holds it at the oldest
    span;
  - a fetch error propagates and the watermark is unchanged;
  - the `RunSummary` counts.

**Weekly integration test, `lambda_test.py`** (`AK_TEST_ENDPOINT` from the pipeline; AWS credentials from
the job's OIDC role). It drives `TrafficSimulator`, so it tests the same path a user runs:

1. `simulator = TrafficSimulator.from_terraform(Path("deploy"))`, with `endpoint` replaced by
   `AK_TEST_ENDPOINT`.
2. `run = simulator.send()`. `Test.compare` checks the `A-1001` reply mentions the order's fixed status
   ("shipped").
3. `simulator.evaluate(run)`: 5 `TRACE` items within 5 minutes.
4. `simulator.report(run)`, then assert:
   - 5 traces, each with its question as `input` and `total_tokens > 0`;
   - the three order traces have a `get_order_status` tool call;
   - every trace has `task_completion`, `answer_relevance` and `hallucination` scores, and the
     tool-calling traces also `tool_correctness`, each in [0, 1] with a non-empty reason (judge outcomes
     are not asserted, only that they ran).
5. Invoke once more with the same window; assert the summary reports all 5 as `already_evaluated` and
   their `evaluated_at` values are unchanged.
- `TestTrafficSimulator` in `tests/test_evaluator.py` (unit): `send` posts the 5 questions under one
  session id; `evaluate` polls until 5 and raises `TimeoutError` otherwise; `report` groups items per trace.


**Run:**

```bash
cd examples/aws-serverless/langfuse-trace-evaluation
./build.sh local && uv run pytest tests/                    # unit tests
cd deploy && ./deploy.sh local && cd ..
uv run python simulate_traffic.py                          # 5 questions → evaluate → print the scores
AK_TEST_ENDPOINT=$(terraform -chdir=deploy output -raw agent_invoke_url) uv run pytest lambda_test.py
```
