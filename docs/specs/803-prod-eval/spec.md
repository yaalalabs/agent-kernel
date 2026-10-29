# #803: Agent evaluation on production traffic — Implementation Spec

This spec details how to build the three phases [design.md](design.md) requires: Phase 1 (fetch) in Agent
Kernel core, and Phases 2 (evaluate) and 3 (store) in the `aws-serverless/openai-langfuse-trace-evaluation`
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

ak-py/src/agentkernel/test/
└── __init__.py          # + re-exports AKEvaluator, AKEvaluationCase, AKEvaluationResult, AKEvaluationError,
                         #   AKMetricNotSupported, AKMissingInput from .core.evaluator (the example imports them)
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
   - `logfire/fetch.py` imports `LogfireQueryClient` inside `_query_client_class()`.
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
   - `(trace_id, span_id)` pairs are unique (OTel span ids are unique only within a trace).
   - `raw` holds the provider record.
   - `fetch_spans` itself never parses or rewrites `input`/`output`.
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
    AGENT = "agent"; LLM = "llm"; TOOL = "tool"; OTHER = "other"

class SpanStatus(str, Enum):                  # the OpenTelemetry span status
    UNSET = "unset"; OK = "ok"; ERROR = "error"

    @classmethod
    def of(cls, value: Any) -> "SpanStatus": ...   # "ERROR" / "STATUS_CODE_ERROR" / OTLP 2 -> ERROR; "OK" / 1 -> OK;
                                                    # None, bool or anything unknown -> UNSET

class TraceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelled filter fails instead of widening the query

    start: Optional[datetime] = None          # inclusive, on span start time
    end: Optional[datetime] = None            # exclusive; defaults to now
    last: timedelta = timedelta(hours=1)      # used only when start is None
    kinds: Optional[list[SpanKind]] = None    # None = all
    session_id: Optional[str] = None
    trace_ids: Optional[list[str]] = None
    name: Optional[str] = None
    limit: int = Field(default=1000, gt=0)

    @field_validator("kinds", "session_id", "trace_ids", "name")
    def _reject_empty_filter(cls, value): ...  # [] or "" -> ValueError ("must be non-empty, or None ...")
    def window(self) -> tuple[datetime, datetime]: ...   # UTC-aware; ValueError if start >= end
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
        # coerces numbers / numeric strings; drops non-numeric, non-finite (NaN, inf) values and bools;
        # None when nothing is known

class FetchedSpan(BaseModel):
    provider: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: Optional[str] = None
    kind: SpanKind = SpanKind.OTHER
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
    _log = logging.getLogger("ak.trace.fetch")

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]: ...
        # pins the window, runs _query_provider, keeps the first span per (trace_id, span_id),
        # returns oldest_first(...)[-limit:]; logs a warning when the result reaches limit
    @abstractmethod
    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...   # the provider's requests
    @staticmethod
    def _span_key(span: FetchedSpan) -> tuple[str, str]: ...                     # (trace_id, span_id)
    def _fetch_by_cursor(self, query: TraceQuery,
                         fetch_page: Callable[[str | None], tuple[list[Any], str | None]],
                         item_to_span: Callable[[Any], FetchedSpan]) -> list[FetchedSpan]: ...
    def _fetch_by_time_window(self, query: TraceQuery, upper_bound: datetime, max_rows_per_request: int,
                              fetch_page: Callable[[int, datetime], list[tuple[datetime | None, FetchedSpan]]]) -> list[FetchedSpan]: ...
```

- Every `TraceQuery` field gets a `Field(description=...)`. `kinds` accepts plain strings (`["tool"]`) through
  Pydantic enum coercion. `extra="forbid"` makes an unknown filter a `ValidationError`, and an empty filter
  (`kinds=[]`, `trace_ids=[]`, `session_id=""`, `name=""`) is rejected too: providers would read it as an invalid
  or unfiltered query.
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
  | 6 | — | other |

  - Values outside a row's mapping fall through to the next row. For example, OpenInference `CHAIN`
    and Traceloop `workflow` fall through and end as `other`.
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
  - `fetch_spans` dedupes on `_span_key` = `(trace_id, span_id)`, not the span id alone, so two traces
    that reuse a span id both survive. When the result reaches `limit` it logs a warning on `ak.trace.fetch`
    ("The <provider> fetch reached its limit of N spans; older matching spans may be left out, and their
    traces may come back without a root. Narrow the window or raise limit"): paging stops at the limit, so
    it can't tell whether older spans also matched.
  - `_fetch_by_cursor(query, fetch_page, item_to_span)`: the cursor loop Langfuse and Traceloop share.
    Calls `fetch_page(cursor)` for `(items, next_cursor)`, maps each item with `item_to_span`, keeps it
    when `query.matches`. Stops when `next_cursor` is empty, `items` is empty, `next_cursor` equals the
    cursor just sent, or `query.limit` spans are kept. Both APIs page newest first, so the kept spans
    are the most recent.
    - The repeated-cursor stop matters because local filtering can keep `limit` from ever being
      reached; a backend that returned the same cursor would otherwise page forever.
  - `_fetch_by_time_window(query, upper_bound, max_rows_per_request, fetch_page)`: the backward time
    paging Logfire and CloudWatch share, for APIs with a row cap and no cursor. `fetch_page(page_size,
    upper_bound)` returns `(cursor timestamp, span)` rows, newest first, at or before `upper_bound`. Per
    page, with `page_size = min(max_rows_per_request, limit - kept + reread_rows)`:
    1. Drop rows whose `(trace_id, span_id)` was already seen.
    2. Set `span.session_id = span.session_id or query.session_id` (both callers filter by session
       server-side), then keep the fresh spans that `query.matches`.
    3. Set `upper_bound` to the oldest cursor timestamp among the fresh rows, and `reread_rows` to the
       number of this page's rows at that timestamp. The bound is inclusive, so those rows are re-read
       by the next page and dropped in step 1; growing the page by them keeps them from crowding out
       older rows.
    4. Stop when `len(rows) < page_size`, when no fresh row has a cursor timestamp, or when `limit` spans
       are kept.
    5. A full page with no fresh rows (more rows re-read than expected, e.g. CloudWatch re-reading the
       whole boundary second) retries once with `reread_rows = page_size`, while `page_size` is below
       `max_rows_per_request`. At the row cap it logs a warning ("More than N spans share one timestamp;
       stopping the <provider> fetch early") and stops, so it can't spin on a block of identical
       timestamps.
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
        if query is not None and filters:
            raise ValueError("pass either a TraceQuery or keyword filters, not both")
        query = query if query is not None else TraceQuery(**filters)
        if query.kinds is not None or query.name is not None:
            raise ValueError("fetch_traces does not take kinds or name; filter the returned trace's spans instead")
        return FetchedTrace.group(self.fetch_spans(query))
```

- `base.py` imports `FetchedSpan`/`TraceQuery` from `.fetch`. There is no import cycle: `fetch.py`
  imports only stdlib and pydantic.
- Unknown keyword filters raise Pydantic's `ValidationError`, because `TraceQuery` is built from them and
  forbids extra fields.
- `query` combined with keyword filters raises `ValueError` in both facades (design.md §Public API).
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
    _KINDS = {langfuse_type: kind for kind, langfuse_type in _TYPES.items()}

    def __init__(self, client: "Langfuse"): ...
    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _types(self, query) -> list[str | None]: ...      # [None] when kinds is None or contains OTHER
    def _fetch_page(self, query, langfuse_type, trace_id, cursor) -> tuple[list[Any], str | None]: ...
    @staticmethod
    def _usage(observation) -> SpanUsage | None: ...
    def _to_span(self, observation) -> FetchedSpan: ...
```

- Reads only the v2 observations API (`GET /api/public/v2/observations`); the v1 read endpoints are being
  removed from Langfuse Cloud.

- `LangFuse.fetch_spans(query)` returns `LangfuseTraceFetcher(self._client).fetch_spans(query)`. `self._client` is
  the client `init()` builds with `get_client()` (`trace/langfuse/langfuse.py:42`).
- Request matrix: `for type in _types(query)` × `for trace_id in query.trace_ids or [None]`. Each cell
  runs one `_fetch_by_cursor` over `_fetch_page`, which calls `client.api.observations.get_many(...)` with these
  parameters, and returns `(list(response.data), response.meta.cursor)`:
  - `fields=_FIELDS`, `expand_metadata=_EXPAND_METADATA`, `limit=min(_PAGE_SIZE, query.limit)`, `cursor`
  - `type`, `trace_id`, `session_id=query.session_id`, `name=query.name`
  - `from_start_time=start`, `to_start_time=end`
- Each cell keeps up to `query.limit` spans; `TraceFetcher.fetch_spans` merges the cells, keeping the first
  span per id, and returns the newest `limit`.
- `_to_span` field mapping:

  | `FetchedSpan` | from the observation |
  |---|---|
  | `trace_id`, `span_id` | `trace_id`, `id` |
  | `parent_span_id` | `parent_observation_id` |
  | `name`, `start_time`, `end_time` | `name`, `start_time`, `end_time` |
  | `kind` | `_KINDS` (`_TYPES` reversed), default `other`. Not re-classified from attributes: a span Langfuse types `SPAN` stays `other` (design.md §Span kinds) |
  | `status` | `ERROR` when `str(level).upper()` ends with `ERROR`, else `UNSET`. `level` is in the `basic` field group, which `_FIELDS` already requests |
  | `session_id`, `input`, `output` | same-named fields, read with `getattr`, default `None` |
  | `usage` | `_usage`: `SpanUsage.of(usage_details["input"], ["output"], ["total"], cost=total_cost, else cost_details["total"])` (missing dicts read as `{}`) |
  | `attributes` | `metadata["attributes"]` if `metadata` is a dict holding that key, else `metadata`, else `{}`; `{}` when the result isn't a dict |
  | `raw` | `observation.model_dump(mode="json", exclude_none=True)`, or `{}` when the object has no `model_dump` |

### `Logfire.fetch_spans` → `LogfireTraceFetcher`

```python
class LogfireTraceFetcher(TraceFetcher):
    provider = "logfire"
    READ_TOKEN_ENV = "LOGFIRE_READ_TOKEN"
    _MAX_ROWS = 10_000
    _COLUMNS = ("trace_id, span_id, parent_span_id, span_name, message, start_timestamp, end_timestamp, attributes, "
                "tags, otel_status_code, otel_scope_name")
    _KIND_SQL: dict[SpanKind, str]            # SQL equivalents of OTelSpanClassifier rows 1, 3, 4 and 5

    def __init__(self, read_token: str | None, base_url: str | None = None): ...   # falsy → AKConfigError
    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    @staticmethod
    def _query_client_class() -> type: ...    # LogfireQueryClient, imported lazily
    def _fetch_page(self, client, query, page_size: int, upper_bound: datetime) -> list[tuple[datetime | None, FetchedSpan]]: ...
    def _sql(self, query, limit: int, upper_bound: datetime) -> str: ...
    @staticmethod
    def _literal(value: str) -> str: ...      # "'" + value.replace("'", "''") + "'"
    def _to_span(self, row: dict) -> FetchedSpan: ...
```

- Token: `Logfire.fetch_spans` passes `SecretManager.current().get("LOGFIRE_READ_TOKEN", None)` (design.md
  §Configuration). The secret manager reads the environment first, so an `env` deployment behaves as
  a plain `os.getenv`, and an `aws_ssm` deployment reads the token from SSM without exporting it. A
  missing token raises `AKConfigError("fetching Logfire traces needs a read token; set LOGFIRE_READ_TOKEN
  (logfire read-tokens create)")` in the constructor.
- Client (`_query_client_class()`): `from logfire.query_client import LogfireQueryClient`, falling back to
  `logfire.experimental.query_client` when that import fails: logfire 5 removed the experimental path,
  and versions before the alias have only it. Built as `LogfireQueryClient(read_token=..., base_url=...)`
  and used as a context manager around the whole paging loop, with `base_url=None` letting the SDK take
  the region from the token.
- Each page calls `client.query_json_rows(sql=_sql(query, page_size, upper_bound), min_timestamp=start,
  max_timestamp=end, limit=page_size)["rows"]`.
- SQL shape:
  `SELECT {_COLUMNS} FROM records WHERE kind = 'span' AND … ORDER BY start_timestamp DESC LIMIT {page}`,
  plus these conditions:

  | Query field | Condition |
  |---|---|
  | `kinds` without `other` | `(_KIND_SQL[k1] OR _KIND_SQL[k2] …)` |
  | `kinds` with `other` | `(NOT COALESCE(<all three _KIND_SQL OR'd>, false) OR <the other requested kinds>)` |
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
  - Traceloop conventions are left out: no Logfire runner emits them.
  - The window is passed as `min_timestamp=start, max_timestamp=end`, never in SQL, so Logfire's
    timestamp index is used. Whether `max_timestamp` is inclusive is undocumented; `matches` applies
    the exclusive end either way.
- Paging: `_fetch_by_time_window(query, upper_bound=end, max_rows_per_request=_MAX_ROWS, fetch_page=...)`,
  where each page runs `_sql(query, page_size, upper_bound)` and returns `(start_time, span)` rows. The
  first page's `upper_bound = end` repeats the `max_timestamp` bound, so every page has the same SQL shape.
- `_to_span`:
  - `attributes` = `row["attributes"]`, JSON-decoded if it arrives as a string.
  - Classification uses `{**attributes, "logfire.msg_template": span_name, "logfire.tags": tags or []}`.
    Logfire stores the template as `span_name` and tags in their own column.
  - `name` = `message` (the formatted message), else `span_name`.
  - `status` = `SpanStatus.of(row["otel_status_code"])`; `otel_status_code` is in `_COLUMNS`. A wrong column
    name would fail every query, so it is on the live-check list (§Phase 1 testing).
  - `trace_id`, `span_id`, `parent_span_id`, `start_time` / `end_time` = the same-named columns
    (`start_timestamp` / `end_timestamp`).
  - `kind` = `OTelSpanClassifier.classify(<the classification attributes>, span_name)`; `session_id`,
    `input` / `output` and `usage` from `OTelSpanClassifier` over the row's own attributes.
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
  contract). The once-guard (`trace/logfire/logfire.py:29-36`) is unchanged.

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
                 transport: httpx.BaseTransport | None = None): ...   # falsy key → AKConfigError
    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _params(self, query) -> dict: ...
    def _fetch_page(self, client: httpx.Client, params: dict, cursor: str | None) -> tuple[list[dict], str | None]: ...
    def _to_span(self, item: dict) -> FetchedSpan: ...
    @staticmethod
    def _timestamp(value) -> datetime | None: ...
```

- Credentials, resolved by `OpenLLMetry.fetch_spans` and passed in:
  - API key: `SecretManager.current().get("TRACELOOP_API_KEY", None)`, as for Logfire's read token. A
    missing key raises `AKConfigError("fetching Traceloop traces needs an API key; set TRACELOOP_API_KEY")`
    in the constructor.
  - Base URL: `os.environ.get("TRACELOOP_BASE_URL")` (not a secret), else `DEFAULT_BASE_URL`.
  - These are the variables the SDK itself reads (`traceloop/sdk/__init__.py:120-121` in traceloop-sdk
    0.62.3).
  - `transport` exists only so tests can inject an `httpx.MockTransport`.
- Request: `httpx.Client(base_url=..., headers={"Authorization": f"Bearer {key}"}, timeout=_TIMEOUT,
  transport=...)`, `GET _PATH` with these params, then `raise_for_status()`:
  - `from_timestamp_sec` / `to_timestamp_sec`: `int(start.timestamp())` / `math.ceil(end.timestamp())`, so
    the last partial second isn't cut off; the exact end is applied locally
  - `limit`: `min(500, query.limit)`
  - `sort_order=DESC`, with no `sort_by`: although documented, every `sort_by` value (`timestamp`
    included) makes the API return no spans, while `sort_order` alone orders by timestamp (checked live)
  - `span_name`: when `name` is set
  - `filters`: a JSON list of `{id, operator, value}`, or `{id, operator, values}` for `in`:
    - `session_id` → `_SESSION_ATTRIBUTE equals …`
    - `trace_ids` → `trace_id in […]`, in `values`: the API reference shows `value`, but the API rejects
      that with a 400
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
- Pagination: one `_fetch_by_cursor` over `_fetch_page`. Response body `{"spans": {"data": [...], "next_cursor":
  ...}}`; a body without `spans` is read as the page itself, and a missing `data` as `[]`. Each page after
  the first re-sends the same params plus `cursor=...`.
- `_to_span`:
  - `attributes` = `span_attributes`, JSON-decoded if it arrives as a string.
  - `trace_id`, `span_id`, `name` = `trace_id`, `span_id`, `span_name`; `start_time` = `_timestamp(item["timestamp"])`.
  - `parent_span_id` = `parent_span_id or None` (the API may return `""` for a root span).
  - `kind` = `OTelSpanClassifier.classify(attributes, span_name)`; `session_id` from `OTelSpanClassifier`.
  - `input`/`output` = the item's top-level `input`/`output` when not `None`, else `OTelSpanClassifier.io`.
  - `end_time` = `start_time + timedelta(milliseconds=duration_ms)` when both are known (`duration` when the
    item has no `duration_ms`; a zero duration still gives an end time).
  - `status` = `SpanStatus.of(item["status_code"] or item["status"])`; the warehouse's status field name is
    undocumented and unverified against a live account.
  - `usage` = `OTelSpanClassifier.usage(attributes)`. Top-level warehouse columns (the API sorts by
    `total_tokens`) are not read: their names are undocumented.
- `_timestamp`, because the warehouse format is undocumented:
  - `None` or `""` → `None`.
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
    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]: ...
    def _fetch_page(self, client, query, page_size: int, upper_bound: datetime) -> list[tuple[datetime | None, FetchedSpan]]: ...
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
    def region() -> str | None:
        return os.environ.get("AWS_REGION")

    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        from .fetch import CloudWatchTraceFetcher
        return CloudWatchTraceFetcher().fetch_spans(query)
```

- `CloudWatch.region()` reads only `AWS_REGION`, with no fallback to `AWS_DEFAULT_REGION` or the profile,
  so a missing region raises instead of exporting to or reading from an unexpected region. `_exporter()`
  keeps its own missing-region and malformed-region errors; botocore validates the region name for the
  fetcher's client.
- Client: the injected `client` if given. Otherwise `BotocoreSession().create_client("logs", region_name=...)`,
  with the region from the argument, else `CloudWatch.region()`. No region → `AKConfigError("fetching
  CloudWatch traces needs an AWS region; set AWS_REGION")`.
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
  | `kinds` without `other` | `filter <_KIND_FILTERS[k1]> or <_KIND_FILTERS[k2]> …` |
  | `kinds` with `other` | no kind filter; kinds are checked locally |
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
    `SessionSpanProcessor` stamps `session.id` onto every span of a run (`trace/cloudwatch/cloudwatch.py:36-45`).
- Window and paging (`_query_provider`):
  - `_fetch_by_time_window(query, upper_bound=max(end, min(end + _END_PADDING, now)), max_rows_per_request=_MAX_ROWS,
    fetch_page=...)`, where each page (`_fetch_page`) runs one `_run` over `[start, upper_bound]` and returns
    `(@timestamp, span)` rows.
    `@timestamp`'s relation to the span start is not documented, so the range runs past `end`, and
    `matches` applies `start <= start_time < end` locally on `startTimeUnixNano`.
    A fetch that reaches `limit` stops in `@timestamp` order, so the spans kept near the cut may differ
    slightly from the newest by start time; such a fetch is truncated anyway and logs the limit warning.
  - Each query's `endTime` is `ceil(upper_bound)`, so rows in the boundary second are re-read and dropped
    as already seen. When that re-reads more rows than the base expected, the base grows the next page
    (step 5 of `_fetch_by_time_window`); more than `_MAX_ROWS` spans in one second hits its warn-and-stop rule.
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
  - `status` = `SpanStatus.of(raw["status"]["code"])` when `status` is a dict, else `SpanStatus.of(raw["status"])`
    (`OK` / `UNSET` / `ERROR`; verified on a live `aws/spans` log group).
  - The `@timestamp` cell (`"YYYY-MM-DD HH:MM:SS.mmm"`, UTC) is parsed with `datetime.fromisoformat` and
    used only for paging.

### `trace/testing.py`: `TraceFetchContract`

```python
class TraceFetchContract:                          # not prefixed Test: pytest collects only subclasses
    @pytest.fixture
    def tracer(self) -> BaseTrace: ...             # subclasses override
    def seed(self, tracer: BaseTrace, spans: list[FetchedSpan]) -> None: ...   # subclasses override
    @staticmethod
    def contract_span(span_id, minute, kind=SpanKind.OTHER, trace_id="t1", session_id: str | None = "s1",
                      name=None) -> FetchedSpan: ...   # starts `minute` min into the window, lasts 30 s;
                                                      # name defaults to f"{kind.value}-{span_id}"
    @staticmethod
    def window(**filters) -> TraceQuery: ...       # 2026-01-01 11:00–12:00 UTC plus filters

    def test_contract_returns_spans_oldest_first(self, tracer): ...
    def test_contract_window_is_start_inclusive_end_exclusive(self, tracer): ...
    def test_contract_limit_keeps_the_most_recent(self, tracer): ...
    def test_contract_kind_filter(self, tracer): ...           # tool; llm + agent; other = everything else
    def test_contract_session_filter(self, tracer): ...        # incl. a span with no session id: excluded
    def test_contract_trace_id_filter(self, tracer): ...
    def test_contract_name_filter(self, tracer): ...           # incl. a span with no name: excluded
    def test_contract_empty_backend_returns_nothing(self, tracer): ...
    def test_contract_fetch_traces_groups_spans_by_trace(self, tracer): ...   # through Trace(tracer).fetch_traces:
                                                                              # trace order, span order, root
```

- `testing.py` imports `Trace` from `.trace` for the `fetch_traces` case, so it also covers a bring-your-own
  tracer that overrides only `fetch_spans`.

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
  `Trace.get().<framework>()` exactly as today. `fetch_spans` and `fetch_traces` are new entry points with no existing callers.
- Bring-your-own `BaseTrace` subclasses keep working unchanged (`fetch_spans` has a default).
  `tests/test_trace.py`'s `_FakeTrace` (`tests/test_trace.py:26-51`) does not need to change.
- `agentkernel.test` now re-exports the evaluator contract (`AKEvaluator`, `AKEvaluationCase`,
  `AKEvaluationResult`, `AKEvaluationError`, `AKMetricNotSupported`, `AKMissingInput`) next to `AKTestConfig`,
  so an evaluator outside AK (the example's `OpikTraceEvaluator`) imports them from the package rather than
  from `agentkernel.test.core.evaluator`. Additive; the old import path still works.

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
  The `cloudwatch` extra (`ak-py/pyproject.toml:39-44`) is unchanged: its `botocore` provides the
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
- The `BaseTrace` abstract surface is unchanged: the seven abstract methods stay; `fetch_spans` is concrete.
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
| Bring-your-own tracer without `fetch_spans` | `NotImplementedError("<Class> does not support fetching spans")` |
| Bad filter value (`limit=0`, unknown kind, unknown kwarg, an empty `kinds` / `trace_ids` / `session_id` / `name`) | Pydantic `ValidationError` from `TraceQuery` |
| `query` plus keyword filters, or `fetch_traces` with `kinds` / `name` | `ValueError`, before any network call |
| The result reaches `limit` | Returned as is, plus a warning on `ak.trace.fetch` that older matching spans may be left out |
| `start >= end` | `ValueError` from `TraceQuery.window()`, raised before any network call |
| Logfire with no read token | `AKConfigError` naming `LOGFIRE_READ_TOKEN`, raised before the SDK import |
| Traceloop with no API key | `AKConfigError` naming `TRACELOOP_API_KEY`, raised before any request |
| The secret provider fails while resolving either key (e.g. SSM access denied) | `SecretError` from `SecretManager.get`, propagated unchanged |
| CloudWatch with no AWS region | `AKConfigError` naming `AWS_REGION`, raised before any request |
| CloudWatch log group missing (`StartQuery` raises `ClientError` code `ResourceNotFoundException`) | `AKConfigError` naming the log group and saying to enable Transaction Search and make the spans reach X-Ray; chained from the `ClientError`. Any other `ClientError` propagates unchanged |
| CloudWatch query ends `Failed`/`Cancelled`/`Timeout`/`Unknown` | `RuntimeError` naming the status and log group |
| CloudWatch query still running at `timeout` | `StopQuery`, then `TimeoutError` |
| `logfire` extra missing on the fetch path | `ImportError` from the lazy import. Unreachable through `Trace`, since `Trace._build` already wraps the tracer import in `require_extra("logfire", …)` (`trace/trace.py:52-54`) |
| Provider errors (HTTP 4xx/5xx, rate limits, auth) | Propagated unchanged: Langfuse SDK `ApiError`, Logfire `QueryRequestError`/`QueryExecutionError`, `httpx.HTTPStatusError` from `raise_for_status()`, botocore `ClientError` (e.g. `AccessDeniedException`, `ResourceNotFoundException` when Transaction Search was never enabled, `ThrottlingException`) and `NoCredentialsError`. No retries |
| Langfuse not yet authenticated | Can't happen through `Trace.get()`: `init()` already raises if `auth_check()` fails (`trace/langfuse/langfuse.py:43-46`) |

- Concurrency: the Logfire and Traceloop fetchers build their own HTTP/query client per `fetch_spans` call
  and hold no shared mutable state, so concurrent calls are independent. So does the CloudWatch fetcher
  when it builds its own client; an injected botocore client is shared, and botocore clients are
  thread-safe. The Langfuse fetcher reuses
  the tracer's shared SDK client and adds no state of its own. Whether that client is safe to share
  across threads is the SDK's own guarantee, not checked here.
- Cost: fetching adds no work to the agent hot path. It runs only when called. Each call makes
  `ceil(matches / page size)` requests per request-matrix cell (Langfuse) or per page (Logfire,
  Traceloop). A CloudWatch page is one `StartQuery` plus one `GetQueryResults` per second until it
  completes, and Logs Insights bills by data scanned, so the cost grows with the window.

## Phase 1 testing

**New `ak-py/tests/test_trace_fetch.py`** (no provider SDK needed):

- `TestTraceQuery`:
  - default window = last hour before `end`
  - naive → UTC
  - `start >= end` raises
  - `matches`: each filter rejects; with `session_id`/`name` set, a span reporting `None` for that field (or
    with no `start_time`) is rejected; with the filter unset, `None` is accepted
  - string kinds coerce
  - empty filters (`kinds=[]`, `trace_ids=[]`, `session_id=""`, `name=""`) and an unknown field raise
    `ValidationError`
- `TestOTelSpanClassifier`:
  - `classify` parametrized over the attribute shapes in `research/span-formats.md` §3–§4: OpenInference
    TOOL/LLM/CHAIN, Traceloop tool/workflow, gen_ai chat/invoke_agent, Logfire `Function:`/`Agent run:`
    templates, Logfire `LLM` tag, empty attributes
  - IO precedence (tool-call attributes win over `input`)
  - session-id keys
  - `usage` over the captured shapes: OpenInference tokens (total derived), GenAI tokens with
    `operation.cost`, numeric strings, and `None` for the two roll-ups and for non-numeric values
  - `SpanUsage.of` keeps a partial value without inventing a total, and ignores non-finite values
    (`"nan"`, `"inf"`, `"1e400"`, `float("nan")`, …)
- `TestTraceFetch` (`Trace.fetch_spans`):
  - disabled tracing raises `AKConfigError`
  - kwargs build a `TraceQuery`
  - an explicit query is passed through
  - `query` plus keyword filters raises `ValueError`; an unknown keyword raises `ValidationError`
  - the default `BaseTrace.fetch_spans` raises `NotImplementedError`
- `TestSpanStatus`: `SpanStatus.of` over `ERROR`, `STATUS_CODE_ERROR`, OTLP `2`, `OK`, `1`, `UNSET`, `0`, `None`, a bool and
  an unknown string.
- `TestFetchedTrace`: `group` keeps span order and orders traces by their first span; `root`, `user_input`, `output`,
  `started_at`, `ended_at`; no root when every span has a parent; no root when two spans have none; `tool_spans` and
  `agent_names` (de-duplicated, in order); `usage` sums and leaves unreported fields `None`.
- `TestTraceFetchTraces`: groups the spans `fetch_spans` returned; `kinds` and `name` raise `ValueError`; `query`
  plus keyword filters raises `ValueError`; an unknown keyword raises `ValidationError`; disabled tracing raises
  `AKConfigError`.
- `TestTraceFetcher` (`_ScriptedFetcher`, a minimal in-test subclass):
  - `fetch_spans` pins a defaulted window once (a clock that advances on every `now()` call doesn't move it),
    keeps the first span per `(trace_id, span_id)` and the newest `limit` oldest first, keeps spans sharing a
    span id across traces, and warns only when the result reaches `limit`;
  - `_fetch_by_cursor`: each of the four stop rules, and only matching spans kept;
  - `_fetch_by_time_window`: boundary dedupe and the session backfill; stops on a short page or at `limit`;
    page sizes grown past the re-read boundary rows; a page grown when more rows are re-read than expected
    (the CloudWatch case); stops on rows without a cursor timestamp; the warning on a full page with no
    fresh rows.
- `TestLangfuseFetcher` (a `MagicMock` client):
  - cursor followed, parameter translation, observations mapped (oldest first, `provider`, `kind`, attributes
    from `metadata["attributes"]`)
  - `level` `ERROR` → `status` `ERROR`, any other level → `UNSET`
  - `expand_metadata="attributes"` is sent
  - `usage_details` + `total_cost` mapped to `SpanUsage`; an observation without them → `None`
  - one request per type × trace id
  - `other` kind → `type=None` plus local filtering
  - `limit=1` keeps the newest span and stops after one page
  - a repeated cursor ends paging (a fake that always returns the same cursor with out-of-window
    observations makes exactly two calls)
- `TestLogfireFetcher` (fake `logfire.query_client` module, and again at the pre-5 `logfire.experimental.query_client`
  path):
  - missing token raises
  - window passed as `min_timestamp`/`max_timestamp`; kind and session SQL present
  - backward paging past a patched `_MAX_ROWS = 2`, with boundary dedupe and the `start_timestamp <=` cursor
  - `otel_status_code` mapped to `status`
  - `gen_ai.usage.*` attributes mapped to `usage`
  - literal escaping, `NOT COALESCE` for `other`, and the `COALESCE(message, span_name)` name condition
  - a row at exactly `end` (as an inclusive `max_timestamp` would return it) is dropped by `matches`
- `TestTraceloopFetcher` (`httpx.MockTransport`):
  - missing key raises
  - Bearer header, timestamp params, `sort_order=DESC` without `sort_by`, and `filters` JSON with no kind
    filter even when `kinds` is set; cursor followed; LLM and other-session spans dropped locally;
    `end_time` from `duration_ms`; empty parent → `None`
  - `status_code` mapped to `status`; a zero `duration_ms` still gives an `end_time`
  - `trace_ids` sent as `{"operator": "in", "values": [...]}`
  - with `kinds=["tool"]`, a span carrying only `traceloop.span.kind=tool` (no `gen_ai.operation.name`)
    is returned; the contract fake seeds `gen_ai.operation.name`, so it wouldn't catch this
  - `OpenLLMetry.fetch_spans` reads the key through `SecretManager` (a stub manager, the variable unset in
    the environment) and `TRACELOOP_BASE_URL` from the environment; a missing key raises `AKConfigError`
    naming `TRACELOOP_API_KEY`
  - `_timestamp` over ISO / s / ms / µs / ns
- `TestCloudWatchFetcher` (a `MagicMock` botocore `logs` client):
  - missing region raises `AKConfigError`
  - `start_query` gets `aws/spans`, the window start, an end at or past the window end, and the kind
    and session filters; nested `openinference` attributes flattened and classified; LLM span dropped
    locally; `startTimeUnixNano` as a string, `endTimeUnixNano` as an int; empty parent → `None`
  - `status.code` mapped to `status`
  - nested `llm.token_count` attributes flattened into `usage`
  - a span started after `end` (but stamped inside the range) is dropped
  - backward paging past a patched `_MAX_ROWS = 2`: boundary dedupe, next `endTime` = the page's oldest
    `@timestamp`
  - `ResourceNotFoundException` from `start_query` → `AKConfigError` mentioning Transaction Search; an
    `AccessDeniedException` propagates as `ClientError`
  - `Failed` status → `RuntimeError`; `timeout=0` → `stop_query` then `TimeoutError`
  - literal escaping, `traceId in [...]`, and no kind filter when `other` is requested
- Each fetcher's `provider` value: `langfuse`, `logfire`, `openllmetry`, `cloudwatch`.
- `FetchedSpan.oldest_first` with a missing `start_time`.

**New `ak-py/tests/test_trace_fetch_contract.py`:** the three `TraceFetchContract` subclasses
(§`trace/testing.py`):

- `TestInMemoryTraceContract`: `InMemoryTrace`, defined in the test file.
- `TestLangfuseFetchContract`: a `LangFuse` whose `_client` is a fake `api.observations.get_many` (`_FakeObservations`:
  single-value filters, both window bounds inclusive, newest first, offset cursor; `other` seeded as type `SPAN`).
- `TestTraceloopFetchContract`: `TraceloopTraceFetcher` over an `httpx.MockTransport` fake warehouse
  (`_FakeWarehouse`: whole-second inclusive bounds, `span_name`, `filters` JSON `in` (`values`) / `equals`, newest
  first, offset cursor).

**New `ak-py/tests/test_trace_langfuse_flush.py`** (skipped without `langfuse`):

- `TestRunnersFlush`, over a fixture parametrized on all six Langfuse runners (OpenAI, LangGraph, CrewAI, ADK,
  Smolagents, Pydantic AI), because each one carries its own `finally`:
  - Each runner is built with `object.__new__` (so no framework instrumentation is installed), with
    `propagate_attributes` patched in that runner's module (the existing patch target), the parent runner's
    `run` patched to return a result or to raise, and `LangFuse.flush_on_lambda` replaced by a spy. A runner
    whose framework extra is missing is skipped with `pytest.importorskip`.
  - `test_flushes_after_a_successful_run` / `test_flushes_after_a_failed_run_and_keeps_the_error`: both paths
    call `flush_on_lambda(client)` exactly once; on failure the original exception still propagates.
- `TestFlushOnLambda`: flushes when `AWS_LAMBDA_FUNCTION_NAME` is set, doesn't flush when it isn't, and logs a
  failing flush instead of raising it.

**Changed `ak-py/tests/test_trace_logfire.py`:**

- The `fake_logfire` fixture adds `fake.ScrubbingOptions = MagicMock(side_effect=lambda **kwargs: kwargs)`.
  Without it, `init()` raises `AttributeError` against the fake module.
- New `test_init_keeps_session_id_from_scrubbing`: the callback returns the value for
  `("attributes", "session_id")` and `None` for `("attributes", "session_token")`.
- New `test_fetch_resolves_the_read_token_through_the_secret_manager`: `Logfire.fetch_spans` passes the token
  the secret manager returns (the variable unset in the environment), and a missing one raises
  `AKConfigError` naming `LOGFIRE_READ_TOKEN`.
- The existing `configure.assert_called_once()` assertions stay valid.

**Changed `ak-py/tests/test_trace.py`:** the four missing-extra tests evict the whole
`agentkernel.trace.<provider>` package through a new `_evict_tracer_package(monkeypatch, package)` helper, which
also restores the parent package attribute afterwards, so a failed re-import can't leave a half-built package
behind for later dotted-path patches.

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

Phases 2 and 3 add no Agent Kernel core code beyond the `agentkernel.test` re-exports (§Phase 1 consumer
changes). Everything below lives in `examples/aws-serverless/openai-langfuse-trace-evaluation/` and uses only
public AK API: `Trace.get().fetch_traces(...)`, `FetchedTrace`, `SpanStatus`, `SpanUsage`, `AKEvaluator`,
`AKEvaluationCase`, `AKEvaluationResult`, `AKMetricNotSupported`, `AKTestConfig`, `Lambda`,
`ServerlessAgentRunner` and `ResponseHandler`.

The example is an AK serverless deployment in queue mode, with three Lambdas:

- **Request handler** (`lambda_request_handler.py`): its `handler` runs the grading for a `START_GRADE` event
  and passes every other event to `Lambda.handler`, which serves `POST /api/v1/chat` (enqueues the request on
  the input SQS queue and polls the Redis response store for the reply) and two custom routes:
  `POST /api/v1/eval` invokes the function asynchronously with `START_GRADE`, and `GET /api/v1/check` returns
  the session's graded rows.
- **Agent runner** (`lambda_agent_runner.py`): `ServerlessAgentRunner.handle` runs the agent on each queued
  request; its Langfuse runner traces the run and flushes before the sandbox freezes (Phase 1).
- **Response handler** (`lambda_response_handler.py`): `ResponseHandler.handle` stores each reply.

Nothing runs on a schedule. The example grades 3 requests, so it is kept simple: no retries, no progress
states, no leases and no re-run step.

### Example layout

```
examples/aws-serverless/openai-langfuse-trace-evaluation/
├── README.md
├── pyproject.toml              # one optional-dependency set per Lambda; dev group
├── uv.lock
├── build.sh                    # test venv: uv sync --all-extras (or the local ak-py wheel with `local`)
├── config.yaml                 # AKConfig: Redis session, rest_sync over SQS, Redis response store, trace langfuse
├── lambda_request_handler.py   # /eval, /check → EvaluationAPI; handler: START_GRADE or Lambda.handler
├── lambda_agent_runner.py      # the agent; handler = ServerlessAgentRunner.handle
├── lambda_response_handler.py  # handler = ResponseHandler.handle
├── simulate_traffic.py         # TrafficSimulator: 3 questions under one session id
├── evaluator/
│   ├── __init__.py
│   ├── api.py                  # EvaluationAPI: /eval, /check and the START_GRADE entry point
│   ├── grader.py               # SessionGrader: fetch, judge, store
│   ├── case.py                 # ToolCall, TraceCase, TraceEvaluationCase
│   ├── opik_evaluator.py       # OpikTraceEvaluator (not opik.py, which would shadow the SDK)
│   └── store.py                # EvaluationStore
├── lambda_test.py              # weekly integration test
└── deploy/
    ├── main.tf  variables.tf  outputs.tf  providers.tf  terraform.tfvars
    ├── deploy.sh
    ├── Dockerfile.request_handler   # FROM public.ecr.aws/lambda/python:3.12, CMD ["lambda_request_handler.handler"]
    └── Dockerfile.agent_runner      # same base, CMD ["lambda_agent_runner.handler"]
```

There is no unit-test suite in the example; `lambda_test.py` is its only test (§Phases 2–3 testing).

### Rules

1. **No AK core changes.** If the example needs something AK lacks, it is raised as a design.md open
   question, not patched in core inside this change.
2. **Classes, not scripts.** Each component below is a class. `lambda_request_handler.py` builds one
   `EvaluationAPI`, registers two one-line route functions with `@Lambda.register`, and defines `handler`
   (the `START_GRADE` check). The only other module-level function is the agent's tool.
3. **Each class builds what it needs in `__init__`.** No factories and no injected dependencies: the
   example has no unit tests to inject into. `EvaluationStore()` reads `RESULTS_TABLE`; `SessionGrader()`
   reads the judge model through `AKTestConfig.get()`.
4. **No fault tolerance beyond what the 3-request demo needs.** No retries, no progress state, nothing
   caught in the grading: an error ends the grading invocation and shows up as a missing row
   (§Phases 2–3 error handling).
5. **Opik loads only in the grading invocation.** `api.py` imports `grader.py` inside `grade`, and
   `grader.py` imports `opik_evaluator.py` at its top, so `/chat`, `/eval` and `/check` never import Opik or
   litellm.

### The agent and the wiring (`lambda_*.py`, `config.yaml`)

```python
# lambda_agent_runner.py
ORDERS = {"A-1001": "Shipped, arriving Friday"}

@function_tool
def get_order_status(order_id: str) -> str: ...      # ORDERS lookup on order_id.strip().upper()

support_agent = Agent(name="support", handoff_description="Order and delivery questions",
                      tools=[get_order_status], model="gpt-4.1-mini", instructions=...)
triage_agent = Agent(name="triage", handoffs=[support_agent], model="gpt-4.1-mini", instructions=...)
OpenAIModule([triage_agent, support_agent])
handler = ServerlessAgentRunner.handle

# lambda_request_handler.py
api = EvaluationAPI()

@Lambda.register("/eval", method="POST")
def start_evaluation(event, context): return api.start_evaluation(event, context)

@Lambda.register("/check", method="GET")
def check_results(event, context): return api.check_results(event, context)

def handler(event, context):
    if event.get("action") == EvaluationAPI.START_GRADE:   # a plain Lambda event: not reachable through the API
        return api.grade(event)
    return Lambda.handler(event, context)

# lambda_response_handler.py
handler = ResponseHandler.handle
```

- `get_order_status` is a module-level function because the OpenAI Agents SDK's `@function_tool` turns a
  function into the tool. It returns `"Shipped, arriving Friday"` for `A-1001` and `"Order <id> not found"`
  for any other id, so the traffic includes one tool result the agent must report honestly.
- `handler` checks `START_GRADE` before `Lambda.handler` because the REST router can't route an event with no
  path (`deployment/aws/serverless/aklambda.py:70-82`). An API Gateway event carries the request body as a
  string under `body`, never a top-level `action`, so only the function's own invoke reaches `api.grade`.
- `config.yaml`:
  - `session: {type: redis, redis: {prefix, url}}` on the base deployment's Redis cluster.
  - `execution: {mode: rest_sync, queues: {type: sqs, input: {max_receive_count: 3}, output:
    {max_receive_count: 3}}, response_store: {type: redis, redis: {...}, retry_count: 10, delay: 3}}`. The
    queue URLs are injected per component (`AK_EXECUTION__QUEUES__*__URL`); polling every 3 s for up to 27 s
    keeps the wait under API Gateway's 29 s.
  - `trace: {enabled: true, type: langfuse}`; `logging.ak.level: INFO`.
- The Langfuse runners flush on Lambda themselves (Phase 1), so the agent needs no tracing code.

### `simulate_traffic.py`: `TrafficSimulator`

```python
class TrafficSimulator:
    QUESTIONS = (
        "Where is my order A-1001?",               # hand-off + tool call
        "Can you check order A-9999 for me?",      # tool returns "not found"
        "Write me a poem about the ocean.",        # off-topic: should decline, no tool
    )
    TIMEOUT = 30.0
    WARM_UP_QUESTION = "Hello"

    def __init__(self, chat_url: str, session_id: str | None = None): ...
    @property
    def session_id(self) -> str: ...                 # the given id, or one uuid4 generated in __init__
    def send_questions(self) -> list[str]: ...       # one POST per question, all under session_id; the replies
    def warm_up(self) -> None: ...                   # one question under a throwaway session; result ignored
    @classmethod
    def chat_url_from_env(cls, deploy_dir: Path) -> str: ...   # AK_TEST_ENDPOINT, else terraform output
    @classmethod
    def cli(cls, argv: list[str] | None = None) -> int: ...

if __name__ == "__main__":
    sys.exit(TrafficSimulator.cli())
```

- `send_questions()`: POST `{"prompt": q, "session_id": self.session_id, "agent": "triage"}` to `chat_url` for
  each question in order, `raise_for_status()`, and return each response's `result` (`""` when absent). Each
  question is its own request, so each becomes its own trace. No retries.
- `warm_up()`: posts `WARM_UP_QUESTION` under `warm-up-<uuid4>`, ignoring the reply and any `httpx.HTTPError`,
  so Lambda cold starts (which can outlast API Gateway's 29 s) hit it rather than the graded requests.
- It knows nothing about `/eval` or `/check`.
- `chat_url_from_env(deploy_dir)`: `os.getenv("AK_TEST_ENDPOINT")`, or `terraform -chdir=<deploy_dir> output
  -raw agent_invoke_url` (`check=True`) when the variable is unset.
- `cli`: flags `--endpoint` (overrides `chat_url_from_env(<example>/deploy)`) and `--session-id` (default:
  generated). Sends, prints each question with its reply and then the session id, and returns `0`. The README
  shows the `curl` calls to `/eval` and `/check` for that id.

### `evaluator/case.py`

```python
class ToolCall(BaseModel):
    name: str
    input: str | None = None
    output: str | None = None
    failed: bool = False

class TraceEvaluationCase(AKEvaluationCase):         # what the judges read
    transcript: str
    tool_call_count: int = 0

class TraceCase(BaseModel):
    trace_id: str
    session_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    user_input: str = ""
    output: str = ""
    tool_calls: list[ToolCall] = []
    agents: list[str] = []
    usage: SpanUsage = SpanUsage()                   # summed over the trace's spans

    @property
    def latency_ms(self) -> int | None: ...          # root start → end; None while it hasn't ended
    @classmethod
    def from_trace(cls, trace: FetchedTrace) -> "TraceCase": ...
    def build_transcript(self) -> str: ...
    def to_evaluation_case(self, threshold: float) -> TraceEvaluationCase: ...
    @staticmethod
    def _as_text(value: Any) -> str | None: ...
```

- `from_trace(trace)`, for a trace with a root span (the grader skips the others): `trace_id`, `session_id`,
  `started_at`, `ended_at`, `user_input`, `output` (both through `_as_text`, `""` when absent), `agents =
  trace.agent_names`, `usage = trace.usage`, and one `ToolCall` per `trace.tool_spans` (oldest first) with
  `failed = span.status == SpanStatus.ERROR`.
- `build_transcript()`:
  ```
  User request:
  <user_input>

  Tool calls:
  1. <name>(<input>) -> <json.dumps(output)>[ [failed]]
  ...                                   # "(none)" when there are no tool calls

  Final answer:
  <output>
  ```
- `to_evaluation_case(threshold)`: `user_input`, `actual = output`, `context` = the tool calls' non-empty
  outputs (`None` when there are none), `transcript`, `tool_call_count`, `threshold`.
- `_as_text(value)`: `None` stays `None`; a string that decodes as a JSON string is unwrapped (Langfuse often
  returns JSON-encoded strings); any other string is returned as is; anything else is `json.dumps`-ed.

### `evaluator/opik_evaluator.py`

```python
os.environ.setdefault("OPIK_TRACK_DISABLE", "True")   # before any Opik import, as AK's own Opik evaluator does

class OpikTraceEvaluator(AKEvaluator):
    THRESHOLD = 0.5
    METRICS = ("task_completion", "tool_correctness", "answer_relevance", "hallucination")
    _LOWER_IS_BETTER = {"hallucination"}
    _JUDGE_CLASSES: dict[str, tuple[type[BaseMetric], dict]] = {
        "task_completion": (AgentTaskCompletionJudge, {}),
        "tool_correctness": (AgentToolCorrectnessJudge, {}),
        "answer_relevance": (AnswerRelevance, {"require_context": False}),
        "hallucination": (Hallucination, {}),
    }

    def __init__(self, config: AKTestConfig, metric: str): ...   # builds the metric's judge
    @property
    def higher_is_better(self) -> bool: ...
    def applies_to(self, case: TraceEvaluationCase) -> bool: ...  # tool_correctness needs tool_call_count > 0
    def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult: ...   # AKMetricNotSupported
    def evaluate_by_llm(self, case: TraceEvaluationCase) -> AKEvaluationResult: ...
    def _run_judge(self, case: TraceEvaluationCase) -> ScoreResult: ...
```

- The judge is built in `__init__`: `judge_class(model=f"{config.llm.provider}/{config.llm.model}",
  track=False, **judge_kwargs)`.
- `_run_judge`: `task_completion` and `tool_correctness` score `output=case.transcript`; `answer_relevance`
  scores `input`, `output`; `hallucination` scores `input`, `output`, `context`.
- `evaluate_by_llm`: one judge call. A raised exception propagates; a result with `scoring_failed` or a `None`
  value raises `RuntimeError("<metric> judge failed: <reason>")`. Otherwise an `AKEvaluationResult` with
  `evaluator="opik"`, `mode="llm"`, `score`, `threshold`, `passed` (`score >= threshold`, or
  `score < threshold` for `hallucination`), the judge's `reason`, and `metadata={"higher_is_better": ...}`.

### `evaluator/store.py`

```python
class EvaluationStore:
    MAX_FIELD_CHARS = 4_096
    ROW_TTL = timedelta(days=90)
    SESSION_INDEX = "session_id-index"

    def __init__(self): ...                          # boto3.resource("dynamodb").Table(os.environ["RESULTS_TABLE"])
    def save_results(self, case: TraceCase, results: list[AKEvaluationResult]) -> None: ...
    def list_session_results(self, session_id: str) -> list[dict]: ...
    @classmethod
    def _to_dynamodb_attributes(cls, attributes: dict) -> dict: ...  # drops None, numbers → Decimal
    @classmethod
    def _truncate(cls, text: str | None) -> str | None: ...          # cut at MAX_FIELD_CHARS + "…[truncated]"
```

- `save_results`: one `PutItem` of:

  | Attribute | Value |
  |---|---|
  | `trace_id`, `session_id` | from the case |
  | `evaluated_at` | now, ISO 8601 UTC |
  | `expires_at` | now + `ROW_TTL`, epoch seconds (the table's TTL attribute) |
  | `started_at`, `latency_ms` | from the case |
  | `input`, `output` | truncated |
  | `agents` | list of names |
  | `tool_calls` | list of maps `name`, `input`, `output` (truncated), `failed` |
  | `input_tokens`, `output_tokens`, `total_tokens`, `cost` | `case.usage` |
  | `passed` | every result passed |
  | one per metric (`task_completion`, ...) | map `score`, `threshold`, `passed`, `reason` (truncated), `higher_is_better` |

  `None` values are dropped (boto3 would store DynamoDB `NULL`s) and numbers become `Decimal`. A re-run
  overwrites the same `trace_id`, so a second grading is idempotent.
- `list_session_results`: one `Query` on `SESSION_INDEX` (`KeyConditionExpression=Key("session_id").eq(...)`)
  returning `Items`. One page is enough for a demo session's 3 rows. The index is eventually consistent; the
  test reads it 3 minutes after the writes.

### `evaluator/grader.py`

```python
class SessionGrader:
    FETCH_WINDOW = timedelta(hours=1)                # the demo grades within minutes of its requests

    def __init__(self): ...                          # an EvaluationStore and one OpikTraceEvaluator per metric
    def grade_session(self, session_id: str) -> int: ...
```

- `__init__`: `EvaluationStore()` and
  `[OpikTraceEvaluator(AKTestConfig.get(), m) for m in OpikTraceEvaluator.METRICS]`.
- `grade_session(session_id)`:
  1. `traces = Trace.get().fetch_traces(session_id=session_id, last=FETCH_WINDOW)`.
  2. For each trace: `root is None` → log a warning and skip. Else `case = TraceCase.from_trace(trace)`,
     `evaluation_case = case.to_evaluation_case(OpikTraceEvaluator.THRESHOLD)`, run `evaluate_by_llm` on
     every evaluator that `applies_to(evaluation_case)`, then `store.save_results(case, results)`.
  3. Log and return the number of rows written.
- Nothing is caught. The fetch keeps at most the newest 1000 spans, which a demo session never reaches.
- Readiness is the caller's job: it waits about 2 minutes after the last request before `/eval`
  (design.md §Grading).

### `evaluator/api.py`

```python
class EvaluationAPI:
    START_GRADE = "START_GRADE"

    def __init__(self): ...                          # an EvaluationStore and boto3.client("lambda")
    def start_evaluation(self, event: dict, context: Any) -> tuple[int, dict]: ...   # POST /eval
    def check_results(self, event: dict, context: Any) -> tuple[int, dict]: ...      # GET /check
    @staticmethod
    def grade(event: dict) -> dict: ...              # the START_GRADE invocation
```

- `start_evaluation`: `session_id = json.loads(event.get("body") or "{}").get("session_id")`; missing → `(400,
  {"error": "session_id is required"})`. Else `lambda_client.invoke(FunctionName=context.function_name,
  InvocationType="Event", Payload=json.dumps({"action": START_GRADE, "session_id": session_id}))` and
  `(202, {"session_id": ..., "status": "grading started"})`.
- `check_results`: `session_id` from `queryStringParameters`; missing → `400`. Else `(200, {"session_id",
  "graded": len(rows), "results": rows})`, with the rows' `Decimal`s turned into floats for JSON.
- `grade(event)`: `{"graded": SessionGrader().grade_session(event["session_id"])}`. The grader is
  built per invocation; a warm container rebuilds it, which costs nothing next to the judge calls.
- There is no `/grade` route; `START_GRADE` is not an API Gateway event.

### Deployment (`deploy/`)

```hcl
module "serverless_agents" {                       # queue mode, like aws-serverless/scalable-openai
  source  = "yaalalabs/ak-serverless/aws"
  version = "0.9.5"
  providers            = { aws = aws, docker = docker }
  prefix               = var.prefix
  region               = var.region
  is_production        = var.is_production
  vpc_id               = var.vpc_id
  private_subnet_ids   = var.private_subnet_ids
  product_display_name = "AK OpenAI Langfuse Trace Evaluation Serverless Example"
  queue_mode           = true
  execution_mode       = "rest_sync"
  create_redis_cluster        = false              # session and response stores: the base deployment's Redis
  create_redis_response_store = false
  gateway_endpoints = [
    { path = "eval", method = "POST" },
    { path = "check", method = "GET" },
  ]
  request_handler = {
    function_name     = "trace-eval-rqh"
    handler_path      = "lambda_request_handler.handler"
    package_path      = "../dist_request_handler"
    package_type      = "Image"
    timeout           = 600                        # 10 minutes for the grading invocation; default 45 s
    memory_size       = 1024                       # default 128 MB: too small for Opik and litellm
    security_group_id = var.request_handler_security_group_id
    environment_variables = {
      OPENAI_API_KEY         = var.openai_api_key  # the judges
      LANGFUSE_PUBLIC_KEY    = var.langfuse_public_key
      LANGFUSE_SECRET_KEY    = var.langfuse_secret_key
      LANGFUSE_BASE_URL      = var.langfuse_base_url
      AK_TEST__LLM__PROVIDER = "openai"
      AK_TEST__LLM__MODEL    = "gpt-4.1-mini"
      OPIK_TRACK_DISABLE     = "true"
      RESULTS_TABLE          = aws_dynamodb_table.results.name
    }
  }
  agent_runner = {
    function_name     = "trace-eval-ar"
    handler_path      = "lambda_agent_runner.handler"
    package_path      = "../dist_agent_runner"
    package_type      = "Image"
    memory_size       = 1024
    security_group_id = var.agent_runner_security_group_id
    environment_variables = { OPENAI_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL }
  }
  response_handler = {
    function_name     = "trace-eval-rsh"
    handler_path      = "lambda_response_handler.handler"
    package_type      = "LocalZip"
    package_path      = "../dist_response_handler.zip"
    memory_size       = 256
    security_group_id = var.response_handler_security_group_id
  }
  queue_config = {                                 # input and output queues alike
    input_queue_visibility_timeout        = 60     # above the agent runner's 45 s timeout
    input_queue_max_receive_count         = 3
    input_queue_create_dlq                = false
    input_queue_message_retention_seconds = 300
    # output_queue_*: the same four values
    batch_size                         = 10
    maximum_batching_window_in_seconds = 0
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
    name            = "session_id-index"
    hash_key        = "session_id"
    projection_type = "ALL"                        # /check returns whole rows
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
        Action   = ["dynamodb:PutItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.results.arn, "${aws_dynamodb_table.results.arn}/index/*"]
      },
    ]
  })
}

resource "aws_lambda_function_event_invoke_config" "grading" {
  function_name          = module.serverless_agents.request_handler_lambda_function_name
  maximum_retry_attempts = 0                       # a failed grading shows up as missing rows
}
```

- Each module function also sets a `function_description`.
- The module creates the roles and the functions; the example only adds a policy to the request handler's
  role (`ak-deployment/ak-aws/serverless/outputs.tf:1-20`). There is no dependency cycle: the table doesn't
  depend on the module, the module reads only the table name, and the policy depends on both. The agent
  runner and response handler need no table access.
- The self-invoke needs no statement here: the module attaches the AWS-managed `AWSLambdaRole` policy
  (`lambda:InvokeFunction` on `*`) to the request handler's role (`modules/request-handler/main.tf:17-20`).
- `aws_lambda_function_event_invoke_config.grading`: `maximum_retry_attempts = 0`, so AWS doesn't re-run a
  failed grading and pay for its judge calls again (rule 4).
- Network: the Lambdas run in the base VPC like the other `aws-serverless` examples, and reach Langfuse, OpenAI, Redis, SQS,
  DynamoDB and the Lambda API through the same egress path those examples use.
- `variables.tf`: `region`, `prefix`, `is_production` (default `false`), `openai_api_key`,
  `langfuse_public_key`, `langfuse_secret_key` (all three `sensitive = true`), `langfuse_base_url` (default
  `"https://cloud.langfuse.com"`), `vpc_id`, `private_subnet_ids` (`sensitive = true`),
  `request_handler_security_group_id`, `agent_runner_security_group_id`, `response_handler_security_group_id`
  (each default `null`). The last five take the names the weekly pipeline injects (`run_single_test.py`
  `deploy_aws_resources`).
- `outputs.tf`: `agent_invoke_url` (`module.serverless_agents.agent_invoke_url`, the name
  `run_single_test.py` `test_aws_deployment` reads), `results_table_name`.
- `providers.tf`: the same file as the other `aws-serverless` examples (aws `6.70.0`, kreuzwerker/docker `3.6.2`, ECR registry
  auth). There is no `backend.tf`.
- `terraform.tfvars`: `region = "us-east-2"`, `prefix = "ak-oai-lf-eval-dev-examples"`.
- `deploy.sh [local]`: builds one package per Lambda from its `pyproject.toml` extra (`uv export --extra
  <name> --no-dev`, installed with `--compile-bytecode`; with `local`, the `agentkernel` wheel from
  `../../../ak-py/dist` is force-reinstalled on top):
  - `../dist_request_handler/data`: `lambda_request_handler.py`, `config.yaml` and `evaluator/`, plus
    `Dockerfile.request_handler` as `dist_request_handler/Dockerfile`;
  - `../dist_agent_runner/data`: `lambda_agent_runner.py` and `config.yaml`, plus `Dockerfile.agent_runner`;
  - `../dist_response_handler.zip`: `lambda_response_handler.py` and `config.yaml`.

  Then `terraform init` and `terraform apply`. The request handler and agent runner are images because Opik
  and the OpenAI Agents SDK don't fit Lambda's 250 MB unzipped zip limit; Terraform builds and pushes them,
  so Docker must be running.

### `pyproject.toml`

```toml
[project]
dependencies = []

[project.optional-dependencies]   # one set per Lambda; deploy.sh installs each with `uv export --extra <name>`
request_handler  = ["agentkernel[aws,redis,langfuse]>=0.9.5", "boto3>=1.40.0", "langfuse>=4.7.0", "opik>=1.9.0"]
agent_runner     = ["agentkernel[aws,openai,redis,langfuse]>=0.9.5", "langfuse>=4.7.0"]
response_handler = ["agentkernel[aws,redis]>=0.9.5"]

[dependency-groups]
dev = ["agentkernel[test]>=0.9.5", "httpx>=0.27.0", "black==26.5.1", "isort>=5.0.0"]
```

- `opik` is the example's own dependency: the example writes `OpikTraceEvaluator` itself, so it doesn't lean
  on AK's `opik` extra (which stays, for AK's built-in Opik test evaluator). `build.sh local` reinstalls
  `agentkernel[aws,openai,redis,langfuse,test]`, without `opik`, for the same reason. The floor is `1.9.0`,
  the first release with `AgentTaskCompletionJudge` and `AgentToolCorrectnessJudge` (1.8.0 lacks them,
  checked by import).
- Only the agent runner needs the OpenAI Agents SDK. `boto3` is pinned because container images don't
  include the Lambda runtime's copy.
- `langfuse>=4.7.0` raises the `langfuse` extra's `>=4.2.0` floor: older SDKs use Langfuse's slow
  ingestion path (up to 15 minutes), longer than the 2 minutes the caller waits before `/eval`.
- `[tool.pytest.ini_options]`: `pythonpath = ["."]`, `log_cli = true` at `INFO`, so the live test shows its
  progress.
- The minimum `agentkernel` version is the first release that contains Phase 1 (`fetch_traces` and `usage`),
  set when that release is cut; until then CI uses the local wheel (`./deploy.sh local`, `./build.sh local`).

### Consumer changes

- **AK core:** none beyond the Phase 1 `agentkernel.test` re-exports (rule 1).
- **`.github/integration-test-config.yaml`:** a new weekly entry under `# AWS Serverless`:
  `type: aws-serverless`, `path: examples/aws-serverless/openai-langfuse-trace-evaluation`, `deploy_dir: deploy`.
- **`.github/workflows/integration-test-weekly.yaml`, job `run-tests`:**
  - The Deploy, Test and Destroy steps gain `TF_VAR_langfuse_public_key: ${{ secrets.LANGFUSE_PUBLIC_KEY }}`,
    `TF_VAR_langfuse_secret_key: ${{ secrets.LANGFUSE_SECRET_KEY }}` and
    `TF_VAR_langfuse_base_url: ${{ vars.LANGFUSE_BASE_URL }}`. Destroy needs them because the key variables
    have no defaults.
  - Deploy and Destroy pass the base's `--agent-runner-security-group-id` and
    `--response-handler-security-group-id` for this example too, as they already do for the other queue-mode
    examples (`scalable-openai`, `schedule-openai`).
  - No other step, job or script changes: the example fits the existing deploy → test → destroy contract
    (`deploy/deploy.sh`, `agent_invoke_url`, `pytest` in the example root).
- **Repository settings:** secrets `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and variable
  `LANGFUSE_BASE_URL` for a CI Langfuse project (design.md open question).

### Config changes

- No `AKConfig` changes. The example sets existing fields: `session`, `execution` and `trace` in
  `config.yaml`, and `AK_TEST__LLM__PROVIDER` / `AK_TEST__LLM__MODEL` for the judge model.
- Example-only environment variable: `RESULTS_TABLE`.

### Behavioural changes

- None in AK from Phases 2–3 (the Langfuse flush is Phase 1 behavioural change 3). The weekly
  integration run gains one deployment (three Lambdas behind one API Gateway, two SQS queues, two ECR
  repositories, one DynamoDB table; Redis is the base deployment's) and its judge calls: three or four
  `gpt-4.1-mini` calls per test trace, on the existing CI OpenAI key.

## Phases 2–3 error handling

The example handles only bad input; every other failure shows up as fewer than 3 rows in `/check`, with
the cause in the request handler's CloudWatch logs.

| Situation | What happens |
|---|---|
| `/eval` or `/check` with no `session_id` | `400` |
| `/eval` with a body that isn't JSON | `json.loads` raises → `Lambda.handler` returns `500` |
| The async invoke fails (IAM, throttling) | `/eval` returns `500` with the error |
| `/check` before the grading wrote anything | `200`, `graded: 0` |
| Langfuse keys missing or wrong, or the fetch fails | The grading invocation raises; no rows |
| The traces aren't readable yet when the grading fetches | The fetch returns fewer traces; fewer rows |
| A trace has no root span | Logged and skipped; no row |
| A judge call raises or its result is `scoring_failed` | The grading invocation raises; that trace and the ones after it get no row |
| DynamoDB error on `PutItem` | Same as a judge error |
| The grading invocation takes over 3 minutes (the test's wait) or times out (10 minutes) | The traces not yet saved have no row when `/check` runs |
| Any of the above in the weekly test | `graded < 3` → the test fails |

- No automatic retry (`maximum_retry_attempts = 0`) and no manual re-run step. Calling `/eval` again re-grades
  the whole session and overwrites its rows by `trace_id`.
- Concurrency: each invocation is single-threaded; two `/eval` calls for one session just grade it twice, and
  the later `PutItem` per trace wins.
- Cost per grading: one Langfuse fetch of ~`ceil(spans / 100)` requests, then per trace three or four judge
  calls and one put. `/check`: one `Query`.

## Phases 2–3 testing

There are no unit tests in the example: everything is exercised end to end by the weekly integration test.

**Weekly integration test, `lambda_test.py`** (`AK_TEST_ENDPOINT` from the pipeline,
`.github/scripts/run_single_test.py:941-969`). Only HTTP calls, so it needs no AWS credentials:

```python
WARM_UP_WAIT = 120     # s: lets the warm-up run finish even if the gateway timed out
INGEST_WAIT = 120      # s: time for Langfuse to store the traces
GRADING_WAIT = 180     # s: time for the grading invocation to judge and store every trace
EXPECTED = len(TrafficSimulator.QUESTIONS)
```

- Fixture `chat_url = os.getenv("AK_TEST_ENDPOINT")` (trailing `/` stripped), skipping the test when unset.
- `test_every_request_is_graded`:
  1. `simulator.warm_up()`, then `time.sleep(WARM_UP_WAIT)`.
  2. `replies = simulator.send_questions()`; assert every reply is non-empty.
  3. `time.sleep(INGEST_WAIT)`.
  4. `httpx.post(.../eval, {"session_id"})`; assert `202`.
  5. `time.sleep(GRADING_WAIT)`.
  6. `httpx.get(.../check?session_id=...)`; assert `graded == EXPECTED`.
  - Judge outcomes are not asserted, only that every request was graded and stored.

**Run:**

```bash
cd examples/aws-serverless/openai-langfuse-trace-evaluation
./build.sh local                                           # test venv with every extra
cd deploy && ./deploy.sh local && cd ..
uv run python simulate_traffic.py                          # 3 questions; prints the session id
AK_TEST_ENDPOINT=$(terraform -chdir=deploy output -raw agent_invoke_url) uv run --no-sync pytest lambda_test.py
```
