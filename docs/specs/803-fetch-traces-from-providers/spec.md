# #803: Fetch traces back from the tracing providers' clouds — Implementation Spec

This spec details how to build Phase 1 of production agent evaluation, as required by
[design.md](design.md). It adds a `fetch(query)` method to `BaseTrace` and a `Trace.fetch(...)` facade.
It also adds a provider-neutral query/result model in `trace/fetch.py`, plus one fetcher class per
built-in tracer in `trace/<provider>/fetch.py`. Each fetcher translates the generic `TraceQuery` into
its provider's read API and returns `FetchedSpan`s. Three small changes complete it: a Logfire scrubbing
callback, so session ids survive export, `httpx` in two extras, and a shared `CloudWatch.region()`
lookup that the CloudWatch exporter and fetcher both use.

Where design.md leaves an open question, this spec follows the design's recommendation or its stated
default, and says so inline.

## Design

### Package layout

```
ak-py/src/agentkernel/trace/
├── __init__.py          # + exports FetchedSpan, SpanKind, TraceQuery
├── base.py              # + BaseTrace.fetch (non-abstract)
├── trace.py             # + Trace.fetch facade
├── fetch.py             # NEW: SpanKind, TraceQuery, FetchedSpan, OTelSpanClassifier
├── langfuse/
│   ├── langfuse.py      # + LangFuse.fetch → LangfuseTraceFetcher
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
5. **Kind and session filters are checked again locally** wherever the server-side filter could be
   approximate: Langfuse with `span` among the kinds, Logfire, Traceloop and CloudWatch always. A span whose
   computed `kind` is not in `query.kinds` is never returned.

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
- Module-level functions: none. All logic is on these four classes.

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
        return self._instance.fetch(query or TraceQuery(**filters))
```

- `base.py` imports `FetchedSpan`/`TraceQuery` from `.fetch`. There is no import cycle: `fetch.py`
  imports only stdlib and pydantic.
- Unknown keyword filters raise Pydantic's `ValidationError`, because `TraceQuery` is built from them.

### `LangFuse.fetch` → `LangfuseTraceFetcher`

```python
class LangfuseTraceFetcher:
    _PAGE_SIZE = 100
    _FIELDS = "core,basic,time,io,metadata,model,usage,metrics"
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
  - `fields=_FIELDS`, `limit=min(100, query.limit)`, `cursor`
  - `type`, `trace_id`, `session_id=query.session_id`, `name=query.name`
  - `from_start_time=start`, `to_start_time=end`
- Each loop stops when the cursor is empty, the page is empty, or that cell has accepted `query.limit`
  spans. Langfuse pages newest first, so the newest spans are seen first.
- Merge: `dict.setdefault(span_id, span)`, then `FetchedSpan.oldest_first(...)[-limit:]`.
- `_to_span` field mapping:

  | `FetchedSpan` | from the observation |
  |---|---|
  | `trace_id`, `span_id` | `trace_id`, `id` |
  | `parent_span_id` | `parent_observation_id` |
  | `kind` | `_TYPES` reversed, default `span` |
  | `session_id`, `input`, `output` | same-named fields, read with `getattr`, default `None` |
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
  §Configuration. If the open question on credential resolution goes to SecretManager, only this line
  changes, to `SecretManager.current().get(READ_TOKEN_ENV, default=None)`.
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
  - `from_timestamp_sec` / `to_timestamp_sec`: `int(start.timestamp())` / `int(end.timestamp())`
  - `limit`: `min(500, query.limit)`
  - `sort_by=timestamp`, `sort_order=desc`
  - `span_name`: when `name` is set
  - `filters`: a JSON list of `{id, operator, value}`:
    - `kinds` without `span` → `gen_ai.operation.name in [ops…]`
    - `session_id` → `_SESSION_ATTRIBUTE equals …`
    - `trace_ids` → `trace_id in […]`
- Pagination: response body `{"spans": {"data": [...], "next_cursor": ...}}`. A body without `spans`
  is read as the page itself. The loop stops on a missing cursor or empty data, and re-sends the same
  params with `cursor=...`.
- Local re-check: drop a span if `not query.accepts(kind)`, or if `query.session_id` is set and differs
  from the span's session id. Stop once `limit` spans are accepted; with descending order these are
  the most recent.
- `_to_span`:
  - `attributes` = `span_attributes`, JSON-decoded if it arrives as a string.
  - `parent_span_id` = `parent_span_id or None` (the API may return `""` for a root span).
  - `input`/`output` = the item's top-level `input`/`output` when not `None`, else `OTelSpanClassifier.io`.
  - `end_time` = `start_time + timedelta(milliseconds=duration_ms)` when both are known.
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
     with times in epoch seconds. AWS treats both ends as inclusive.
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
  - `kind`, `input`, `output`, `session_id` from `OTelSpanClassifier`.
  - The `@timestamp` cell (`"YYYY-MM-DD HH:MM:SS.mmm"`, UTC) is parsed with `datetime.fromisoformat` and
    used only for paging.

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
3. **CloudWatch fetching needs IAM read permissions the send side does not.** `logs:StartQuery`,
   `logs:GetQueryResults` and `logs:StopQuery` on `aws/spans`; `AWSXrayWriteOnlyAccess` grants none of
   them. Documented, not enforced.

**Non-changes:**
- Span export, runner wrapping and instrumentation for all four providers are unchanged, apart from
  change 1. `CloudWatch._exporter()` resolves the region exactly as before, through `CloudWatch.region()`.
- The `BaseTrace` abstract surface is unchanged: the seven abstract methods stay; `fetch` is concrete.
- The `Trace.get()`/`Trace._build()` selection logic and `_BUILTIN_TRACERS` are unchanged.
- No data written before this change is altered. Spans already in Logfire keep their scrubbed session
  value, so a session filter does not match runs recorded before the upgrade.

## Error handling

| Situation | Surfaces as |
|---|---|
| `Trace.fetch` with `trace.enabled: false` | `AKConfigError("cannot fetch traces: tracing is disabled …")` |
| Bring-your-own tracer without `fetch` | `NotImplementedError("<Class> does not support fetching traces")` |
| Bad filter value (`limit=0`, unknown kind, unknown kwarg) | Pydantic `ValidationError` from `TraceQuery` |
| `start >= end` | `ValueError` from `TraceQuery.window()`, raised before any network call |
| Logfire with no read token | `AKConfigError` naming `LOGFIRE_READ_TOKEN`, raised before the SDK import |
| Traceloop with no API key | `AKConfigError` naming `TRACELOOP_API_KEY`, raised before any request |
| CloudWatch with no AWS region | `AKConfigError` naming `AWS_REGION`, raised before any request |
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

## Testing

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
- `TestTraceFetch`:
  - disabled tracing raises `AKConfigError`
  - kwargs build a `TraceQuery`
  - an explicit query is passed through
  - the default `BaseTrace.fetch` raises `NotImplementedError`
- `TestLangfuseFetcher` (a `MagicMock` client):
  - cursor followed
  - parameter translation
  - one request per type × trace id
  - `span` kind → `type=None` plus local filtering
  - `limit=1` keeps the newest span and stops after one page
- `TestLogfireFetcher` (fake `logfire`, `logfire.experimental` and `logfire.experimental.query_client`
  modules in `sys.modules`):
  - missing token raises
  - window passed as `min_timestamp`/`max_timestamp`
  - kind and session SQL present
  - backward paging past a patched `_MAX_ROWS = 2`, with boundary dedupe and the `start_timestamp <=`
    cursor
  - literal escaping
  - `NOT COALESCE` for `span`
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
  - `startTimeUnixNano` as a string, `endTimeUnixNano` as an int; empty parent → `None`
  - a span started after `end` (but stamped inside the range) is dropped
  - backward paging past a patched `_MAX_ROWS = 2`: boundary dedupe, next `endTime` = the page's oldest
    `@timestamp`
  - `Failed` status → `RuntimeError`; `timeout=0` → `stop_query` then `TimeoutError`
  - literal escaping, `traceId in [...]`, and no kind filter when `span` is requested
- `FetchedSpan.oldest_first` with a missing `start_time`.

**Changed `ak-py/tests/test_trace_logfire.py`:**

- The `fake_logfire` fixture (`tests/test_trace_logfire.py:23-38`) adds
  `fake.ScrubbingOptions = MagicMock(side_effect=lambda **kw: kw)`. Without it, `init()` raises
  `AttributeError` against the fake module.
- New `test_init_keeps_session_id_from_scrubbing`: the callback returns the value for
  `("attributes", "session_id")` and `None` for `("attributes", "session_token")`.
- The existing `configure.assert_called_once()` assertions (`:56`, `:66`) stay valid.

**Run:**

```bash
cd ak-py && uv run pytest tests/test_trace_fetch.py tests/test_trace_logfire.py tests/test_trace.py tests/test_trace_langfuse_langgraph.py tests/test_trace_cloudwatch.py
make lint-check-all   # from the repo root
```

**Before merge, manual live checks** (not CI; they need accounts): run `Trace.get().fetch(kinds=["tool"])`
against each provider after a real agent run, and tick off `research/provider-read-apis.md` §5 and §6:
- Langfuse maps our spans to type `TOOL`.
- Logfire `attributes->>` access works and the session subquery matches.
- Traceloop accepts the `gen_ai.operation.name` / association-property / `trace_id` filter ids.
- CloudWatch: the `@message` shape, that the dotted `attributes.*` filters match, and what `@timestamp`
  is for a span.
