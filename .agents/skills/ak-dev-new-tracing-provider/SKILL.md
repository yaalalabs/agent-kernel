---
name: ak-dev-new-tracing-provider
description: >
  Step-by-step guide for adding a new observability/tracing provider to Agent Kernel.
  Use this skill when you need to integrate a new tracing backend (beyond Langfuse,
  OpenLLMetry/Traceloop, Pydantic Logfire, and AWS CloudWatch). Covers implementing the BaseTrace interface, creating
  framework-specific traced runners, configuration, and testing.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Tracing Provider

This guide walks through adding a new observability/tracing provider to Agent Kernel. Use the Langfuse implementation (`ak-py/src/agentkernel/trace/langfuse/`) as the canonical reference. For a backend reached through plain OpenTelemetry (no vendor SDK), see the CloudWatch provider (`ak-py/src/agentkernel/trace/cloudwatch/`): it installs its own SDK `TracerProvider` and OTLP exporter once (or reuses one already installed, since OpenTelemetry honours only the first), wraps each run through a `span(name, session)` context manager on the provider class that its runners receive, and adds a provider-specific helper module (`sigv4.py`) beside the runners.

## Architecture Overview

Agent Kernel's tracing system:

1. **`BaseTrace`** (`trace/base.py`) defines the interface — one method per supported framework that returns a traced `Runner` (or `None`)
2. **`Trace`** (`trace/trace.py`) is a factory that creates the appropriate trace instance based on `AKConfig.trace.type`
3. Each **framework Module** checks for a trace runner at initialization — if tracing is enabled, it uses the traced runner instead of the default
4. Traced runners **extend the base framework runner** and wrap execution with spans/traces
5. **`BaseTrace.fetch_spans(query)`** (optional, not abstract) reads spans back from the provider's cloud as provider-neutral `FetchedSpan`s; `Trace.fetch_spans` is the facade users call (`Trace.get().fetch_spans(last=..., session_id=...)`), and `Trace.fetch_traces` groups the same spans into `FetchedTrace`s on top of it, so a provider implements only `fetch_spans`. A provider that only sends traces skips it and raises `NotImplementedError` (step 6)

## Step-by-Step

### 1. Create the Trace Provider Directory

```
ak-py/src/agentkernel/trace/<provider>/
├── __init__.py
├── <provider>.py        # Main trace class
├── openai.py            # Traced OpenAI runner
├── langgraph.py         # Traced LangGraph runner
├── crewai.py            # Traced CrewAI runner
├── adk.py               # Traced Google ADK runner
├── smolagents.py        # Traced Smolagents runner
├── pydanticai.py        # Traced Pydantic AI runner
└── fetch.py             # Optional: <Provider>TraceFetcher, reads spans back (step 6)
```

### 2. Implement the Main Trace Class

In the main trace class, there should be a method each agentic framework. Each method should return a traced Runner if the framework is supported, or None if not. The traced Runner should extend the base Runner for that framework and wrap execution with tracing spans.

```python
# ak-py/src/agentkernel/trace/<provider>/<provider>.py
import logging
from agentkernel.core.base import Runner
from agentkernel.trace.base import BaseTrace

logger = logging.getLogger("ak.trace.<provider>")


class <Provider>(BaseTrace):
    """<Provider> tracing implementation for Agent Kernel."""

    def __init__(self):
        logger.info("Initializing <Provider> tracing")
        # Initialize the tracing client/SDK
        # e.g., self._client = ProviderClient()

    def init(self):
        """Initialize the tracing backend. Called once at startup."""
        # Set up any global instrumentation
        # e.g., self._client.configure(api_key=os.getenv("PROVIDER_API_KEY"))
        pass

    def openai(self) -> Runner | None:
        """Return a traced runner for OpenAI framework, or None if not supported."""
        try:
            from .openai import <Provider>OpenAIRunner
            return <Provider>OpenAIRunner(self._client)
        except ImportError:
            logger.warning("OpenAI tracing dependencies not available")
            return None

    def langgraph(self) -> Runner | None:
        try:
            from .langgraph import <Provider>LangGraphRunner
            return <Provider>LangGraphRunner(self._client)
        except ImportError:
            return None

    def crewai(self) -> Runner | None:
        try:
            from .crewai import <Provider>CrewAIRunner
            return <Provider>CrewAIRunner(self._client)
        except ImportError:
            return None

    def adk(self) -> Runner | None:
        try:
            from .adk import <Provider>ADKRunner
            return <Provider>ADKRunner(self._client)
        except ImportError:
            return None

    def smolagents(self) -> Runner:
        from .smolagents import <Provider>SmolagentsRunner

        return <Provider>SmolagentsRunner(self._client)
```

### 3. Implement Framework-Specific Traced Runners

Each traced runner **extends the base framework runner** and wraps execution with tracing spans.

#### OpenAI Traced Runner

```python
# ak-py/src/agentkernel/trace/<provider>/openai.py
from agentkernel.framework.openai.openai import OpenAIRunner
from agentkernel.core.base import Session
from agentkernel.core.model import AgentReply, AgentRequest


class <Provider>OpenAIRunner(OpenAIRunner):
    def __init__(self, client):
        super().__init__()
        self._trace_client = client

    async def run(self, agent, session: Session, requests: list[AgentRequest]) -> AgentReply:
        # Wrap the base runner's execution with a trace span
        with self._trace_client.start_span(
            name=f"agent.{agent.name}",
            attributes={
                "framework": "openai",
                "session_id": session.id,
                "agent_name": agent.name,
            }
        ) as span:
            try:
                result = await super().run(agent, session, requests)
                span.set_attribute("output_length", len(result.response) if hasattr(result, 'response') else 0)
                span.set_status("OK")
                return result
            except Exception as e:
                span.set_status("ERROR")
                span.record_exception(e)
                raise
```

#### LangGraph Traced Runner

```python
# ak-py/src/agentkernel/trace/<provider>/langgraph.py
from agentkernel.framework.langgraph.langgraph import LangGraphRunner


class <Provider>LangGraphRunner(LangGraphRunner):
    def __init__(self, client):
        super().__init__()
        self._trace_client = client

    async def run(self, agent, session, requests):
        with self._trace_client.start_span(
            name=f"agent.{agent.name}",
            attributes={"framework": "langgraph", "session_id": session.id}
        ):
            return await super().run(agent, session, requests)
```

Follow the same pattern for CrewAI, Google ADK, Smolagents, and Pydantic AI runners (see `trace/langfuse/smolagents.py` and `trace/openllmetry/smolagents.py` for reference).

### 4. Update the `__init__.py`

```python
# ak-py/src/agentkernel/trace/<provider>/__init__.py
from .<provider> import <Provider>
```

### 5. Update the BaseTrace Interface

Add the new provider as a recognized option. The `BaseTrace` class (`trace/base.py`) already defines the interface — your implementation just needs to conform to it. No changes to `base.py` are needed unless you're adding a new framework. Note that `init()` and all six framework methods (`openai`, `langgraph`, `crewai`, `adk`, `smolagents`, `pydanticai`) are declared `@abstractmethod` on `BaseTrace`, so every new provider must implement all seven — otherwise the class cannot be instantiated.

### 6. Implement Fetching (Optional)

`BaseTrace.fetch_spans(query: TraceQuery) -> list[FetchedSpan]` is not abstract: it raises `NotImplementedError("<Class> does not support fetching spans")`, so a send-only provider needs nothing here. To let users read spans back, put the reading code in `trace/<provider>/fetch.py` and have the tracer build it lazily:

```python
# ak-py/src/agentkernel/trace/<provider>/<provider>.py
from ..fetch import FetchedSpan, TraceQuery

class <Provider>(BaseTrace):
    def fetch_spans(self, query: TraceQuery) -> list[FetchedSpan]:
        """Fetches spans back from <Provider> through its query API."""
        from .fetch import <Provider>TraceFetcher

        return <Provider>TraceFetcher(self._client).fetch_spans(query)
```

The models live in `trace/fetch.py`: `TraceQuery` (window via `start`/`end` or `last`, `kinds`, `session_id`, `trace_ids`, `name`, `limit`; `window()` returns the UTC bounds and `matches(span)` checks every filter), `FetchedSpan`, `FetchedTrace` (spans grouped by trace, with `root`, `usage`, ...), `SpanKind`, `SpanStatus` (`SpanStatus.of(...)` maps a provider's status code onto `UNSET`/`OK`/`ERROR`), `SpanUsage` (`SpanUsage.of(...)` coerces raw values) and `OTelSpanClassifier` (kind, input/output, usage and session id from OTel attributes). The four built-in fetchers (`langfuse/`, `logfire/`, `openllmetry/`, `cloudwatch/` `fetch.py`) subclass the internal `TraceFetcher` base (also in `trace/fetch.py`, not exported) and follow these rules:

1. **The fetcher never reads `AKConfig`.** It takes explicit constructor parameters (a client, a token, a base URL, an optional `httpx` transport or boto client); the tracer class builds it. A credential AK reads itself (not one the provider SDK reads) is resolved by the tracer with `SecretManager.current().get(KEY, None)` and passed in; the fetcher's constructor raises `AKConfigError` naming the key when it is `None` (see `Logfire.fetch_spans` / `OpenLLMetry.fetch_spans`).
2. **No provider SDK import at module scope** in `fetch.py`: import it under `TYPE_CHECKING` or inside the method that uses it, so the fetcher is testable without the extra. Keep the provider package's `__init__.py` empty for the same reason.
3. **Classify per span, never per provider.** OTel-shaped results go through `OTelSpanClassifier`; a backend that types spans server side (Langfuse observations) maps its types directly.
4. **Same result contract:** oldest first (`FetchedSpan.oldest_first`), at most `limit` spans with the most recent kept when more match, unique span ids, the provider record in `raw`, `status` mapped from the provider's own field (never a workaround for its mistakes: `kind` and `status` are trusted as the provider reports them), `provider` set from the fetcher's `provider` class variable (the `trace.type` short name), and `input`/`output` returned as stored (never parsed or rewritten).
5. **Every span goes through `query.matches(span)`**, whatever the server-side filters already did, so no provider's undocumented boundary rule leaks into the result. A span missing a value for an active filter (start time, session id, name) is rejected, never assumed to match. Don't send a server-side filter that can drop spans `matches` would keep (Traceloop sends no kind filter, because a kind can come from either of two attributes and its API has no OR).
6. **Paging, dedupe and limit live once, in `TraceFetcher`.** Implement only `_query_provider(query)` (the provider's requests) and `_to_span`. `TraceFetcher.fetch_spans` pins the window (so a defaulted `end` doesn't move between `matches` calls), keeps the first span per `(trace_id, span_id)` and returns the newest `limit` oldest first. Inside `_query_provider`, use `_fetch_by_cursor(query, fetch_page, item_to_span)` for a newest-first cursor API (Langfuse, Traceloop) or `_fetch_by_time_window(query, upper_bound, max_rows_per_request, fetch_page)` for a row-capped API with no cursor (Logfire, CloudWatch); both apply `matches` and stop on `limit`.
7. **Pass `TraceFetchContract`** where the backend can be faked faithfully (below).

Test it by subclassing `TraceFetchContract` (`agentkernel.trace.testing`, imports `pytest`) in `tests/test_trace_fetch_contract.py`: override the `tracer` fixture and `seed(tracer, spans)` over a faithful fake of the backend (see `TestLangfuseFetchContract` and `TestTraceloopFetchContract`). Backends whose query language can't be faked faithfully (Logfire SQL, CloudWatch Logs Insights) get targeted tests in `tests/test_trace_fetch.py` instead.

### 7. Register with the Trace Factory

Update `ak-py/src/agentkernel/trace/trace.py`. The factory shares the house pluggable-backend
shape from `core/util/factory.py` (`resolve_dotted`, `require_extra`, `AKConfigError` — the same
pattern used by the guardrail, session/thread/multimodal store, and sandbox provider factories):
`Trace.get()` builds an instance via `Trace._build()` only when tracing is enabled, each built-in's
lazy import is wrapped in `require_extra` (so a missing optional dependency raises an actionable
`ImportError` naming the pip extra), and anything that isn't a recognized short name is treated as
a dotted path to a `BaseTrace` subclass (bring-your-own). When tracing is disabled, `instance` stays
`None` and the factory returns `Trace(None)`, whose `init()` and framework methods no-op / return
`None`:

```python
_BUILTIN_TRACERS = ["langfuse", "openllmetry", "logfire", "cloudwatch"]

class Trace(BaseTrace):
    @classmethod
    def get(cls) -> "Trace":
        config = AKConfig.get()
        instance = cls._build(config.trace.type) if config.trace.enabled else None
        trace = cls(instance)
        trace.init()
        return trace

    @staticmethod
    def _build(trace_type: str) -> BaseTrace:
        if trace_type == "langfuse":
            with require_extra("langfuse", "trace.type: langfuse"):
                from .langfuse.langfuse import LangFuse
            return LangFuse()
        if trace_type == "openllmetry":
            with require_extra("openllmetry", "trace.type: openllmetry"):
                from .openllmetry.openllmetry import OpenLLMetry
            return OpenLLMetry()
        if trace_type == "logfire":
            with require_extra("logfire", "trace.type: logfire"):
                from .logfire.logfire import Logfire
            return Logfire()
        if trace_type == "cloudwatch":
            with require_extra("cloudwatch", "trace.type: cloudwatch"):
                from .cloudwatch.cloudwatch import CloudWatch
            return CloudWatch()
        if trace_type == "<provider>":                                    # ADD THIS
            with require_extra("<provider>", "trace.type: <provider>"):
                from .<provider>.<provider> import <Provider>
            return <Provider>()
        if "." not in trace_type:
            raise AKConfigError(
                f"unknown trace type '{trace_type}'; expected one of {_BUILTIN_TRACERS} or a dotted path to a BaseTrace subclass"
            )
        return resolve_dotted(trace_type, base=BaseTrace)()  # bring-your-own
```

A dotted `type` (e.g. `myorg.tracing.CustomTrace`) resolves via `resolve_dotted` without any
factory edit at all — only add an `if` branch here for a first-party, in-repo provider you want
addressable by a short name.

### 8. Add Configuration

The existing `_TraceConfig.type` in `config.py` is a free-form string (no regex pattern) described
as "a built-in short name (langfuse, openllmetry, logfire, cloudwatch) or a dotted path to a BaseTrace subclass" — do
not add a `pattern=` constraint, since that would break the bring-your-own path. Your provider
needs to respond to `type: "<provider>"`:

```yaml
# config.yaml
trace:
  enabled: true
  type: <provider>
```

Add provider-specific environment variables as needed (e.g., `PROVIDER_API_KEY`).

### 9. Add Optional Dependencies

In `ak-py/pyproject.toml`:

```toml
[project.optional-dependencies]
<provider> = [
    "provider-sdk>=x.y.z",
    # Add any framework-specific instrumentation packages
]
```

### 10. Add Tests

Create `ak-py/tests/test_trace_<provider>.py`, and add a missing-extra test to `tests/test_trace.py` asserting the friendly `agentkernel[<provider>]` `ImportError`. Two existing files show the two styles: `test_trace_logfire.py` injects a fake SDK module into `sys.modules` (the SDK is not a test dependency), and `test_trace_cloudwatch.py` records spans with a real OpenTelemetry SDK `TracerProvider` and `InMemorySpanExporter` while patching `trace.get_tracer_provider` / `set_tracer_provider` (the global provider is settable once per process, so a test must never install one). Cover:

- Test that the factory creates the correct instance for `type: "<provider>"`
- Test that traced runners properly wrap execution with spans
- Test that errors are recorded in spans
- Use mocks for the tracing client

### 11. Add Documentation

Add `docs/docs/advanced/tracing-<provider>.md` covering:
- Provider setup (API keys, dashboard URL)
- Configuration
- What gets traced (spans, attributes)
- Dashboard screenshots (optional)

Then update the landing page inventories in `docs/src/components/*/data.tsx`: add a tile to the **Observability, safety & testing** row in `IntegrationsMarquee/data.tsx` (role `Tracing`, `href` to the provider's docs page, logo under `docs/static/img/integrations/` or a `react-icons/si` glyph); add the provider to the **Tracing** card's `tags` and `description` under the Observe tab in `FeatureExplorer/data.tsx`; optionally add `pick("<tile name>")` to the **Clouds & observability** card in `ArchitectureOverview/data.tsx` if it is a headline backend. Logo sourcing and the build check are in `ak-dev-sync-docs-from-branch`, *Docs-Site Landing and Features Pages*.

Then add the provider to the docs-site features page (`docs/src/pages/features.tsx`): the Observability card's `highlights` list one entry per provider, and the Problem section's `rows` name the built-in tracing providers in a `with:` cell. Grep `docs/src/pages/*.tsx` for "Langfuse" to find every roll call.

## How Framework Modules Consume Tracing

Each framework Module's constructor checks for tracing:

```python
class OpenAIModule(Module):
    def __init__(self, agents):
        super().__init__()
        trace_runner = Trace.get().openai()  # Returns traced Runner or None
        self.runner = trace_runner if trace_runner else OpenAIRunner()
        self.load(agents)
```

This means tracing is **transparent** — users don't change their agent code, they just add `trace` config.

## Checklist

- [ ] `ak-py/src/agentkernel/trace/<provider>/` directory with `__init__.py` and main class
- [ ] Traced runners for each framework (OpenAI, LangGraph, CrewAI, ADK, Smolagents, Pydantic AI)
- [ ] Optional: `fetch_spans` on the main class and `<provider>/fetch.py` (step 6), with a `TraceFetchContract` subclass where the backend can be faked
- [ ] Registration in `trace/trace.py` factory
- [ ] Configuration via `type: "<provider>"` in `config.yaml`
- [ ] Optional dependencies in `pyproject.toml`
- [ ] Tests for factory creation and span wrapping
- [ ] Documentation in `docs/docs/advanced/tracing-<provider>.md`
- [ ] Landing page inventories: marquee tile (`IntegrationsMarquee/data.tsx`), Tracing card tags (`FeatureExplorer/data.tsx`); features page Observability highlights and `with:` cells
