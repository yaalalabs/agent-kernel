---
name: ak-dev-new-tracing-provider
description: >
  Step-by-step guide for adding a new observability/tracing provider to Agent Kernel.
  Use this skill when you need to integrate a new tracing backend (beyond Langfuse
  and OpenLLMetry/Traceloop). Covers implementing the BaseTrace interface, creating
  framework-specific traced runners, configuration, and testing.
license: apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Tracing Provider

This guide walks through adding a new observability/tracing provider to Agent Kernel. Use the Langfuse implementation (`ak-py/src/agentkernel/trace/langfuse/`) as the canonical reference.

## Architecture Overview

Agent Kernel's tracing system:

1. **`BaseTrace`** (`trace/base.py`) defines the interface — one method per supported framework that returns a traced `Runner` (or `None`)
2. **`Trace`** (`trace/trace.py`) is a factory that creates the appropriate trace instance based on `AKConfig.trace.type`
3. Each **framework Module** checks for a trace runner at initialization — if tracing is enabled, it uses the traced runner instead of the default
4. Traced runners **extend the base framework runner** and wrap execution with spans/traces

## Step-by-Step

### 1. Create the Trace Provider Directory

```
ak-py/src/agentkernel/trace/<provider>/
├── __init__.py
├── <provider>.py        # Main trace class
├── openai.py            # Traced OpenAI runner
├── langgraph.py         # Traced LangGraph runner
├── crewai.py            # Traced CrewAI runner
└── adk.py               # Traced Google ADK runner
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
                span.set_attribute("output_length", len(result.text) if hasattr(result, 'text') else 0)
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

Follow the same pattern for CrewAI and Google ADK runners.

### 4. Update the `__init__.py`

```python
# ak-py/src/agentkernel/trace/<provider>/__init__.py
from .<provider> import <Provider>
```

### 5. Update the BaseTrace Interface

Add the new provider as a recognized option. The `BaseTrace` class (`trace/base.py`) already defines the interface — your implementation just needs to conform to it. No changes to `base.py` are needed unless you're adding a new framework.

### 6. Register with the Trace Factory

Update `ak-py/src/agentkernel/trace/trace.py`:

```python
class Trace(BaseTrace):
    @classmethod
    def get(cls) -> "Trace":
        config = AKConfig.get().trace
        if config and config.enabled:
            if config.type == "langfuse":
                from .langfuse import LangFuse
                instance = LangFuse()
            elif config.type == "openllmetry":
                from .openllmetry import OpenLLMetry
                instance = OpenLLMetry()
            elif config.type == "<provider>":          # ADD THIS
                from .<provider> import <Provider>
                instance = <Provider>()
            else:
                return cls._noop()
            instance.init()
            return instance
        return cls._noop()
```

### 7. Add Configuration

The existing `_TraceConfig` in `config.py` supports `type` field. Your provider needs to respond to `type: "<provider>"`:

```yaml
# config.yaml
trace:
  enabled: true
  type: <provider>
```

Add provider-specific environment variables as needed (e.g., `PROVIDER_API_KEY`).

### 8. Add Optional Dependencies

In `ak-py/pyproject.toml`:

```toml
[project.optional-dependencies]
<provider> = [
    "provider-sdk>=x.y.z",
    # Add any framework-specific instrumentation packages
]
```

### 9. Add Tests

Create `ak-py/tests/test_trace_<provider>.py`:

- Test that the factory creates the correct instance for `type: "<provider>"`
- Test that traced runners properly wrap execution with spans
- Test that errors are recorded in spans
- Use mocks for the tracing client

### 10. Add Documentation

Add `docs/docs/advanced/tracing-<provider>.md` covering:
- Provider setup (API keys, dashboard URL)
- Configuration
- What gets traced (spans, attributes)
- Dashboard screenshots (optional)

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
- [ ] Traced runners for each framework (OpenAI, LangGraph, CrewAI, ADK)
- [ ] Registration in `trace/trace.py` factory
- [ ] Configuration via `type: "<provider>"` in `config.yaml`
- [ ] Optional dependencies in `pyproject.toml`
- [ ] Tests for factory creation and span wrapping
- [ ] Documentation
