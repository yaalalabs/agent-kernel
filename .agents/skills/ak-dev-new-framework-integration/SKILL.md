---
name: ak-dev-new-framework-integration
description: >
  Step-by-step guide for adding a new agent framework adapter to Agent Kernel.
  Use this skill when you need to integrate a new agent framework (beyond OpenAI,
  CrewAI, LangGraph, Google ADK). Covers creating the adapter module, implementing
  Agent/Runner/Module subclasses, adding optional dependencies, exports, and tests.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Framework Integration

This guide walks through adding support for a new agent framework to Agent Kernel. Use the existing OpenAI adapter (`ak-py/src/agentkernel/framework/openai/`) as the canonical reference implementation.

## Prerequisites

- Understand the architecture skill (`.agents/skills/architecture/SKILL.md`)
- Familiarity with the target framework's API
- The target framework must support async execution (or provide an async wrapper)

## Step-by-Step

### 1. Create the Framework Adapter Directory

```
ak-py/src/agentkernel/framework/<name>/
├── __init__.py
└── <name>.py
```

Replace `<name>` with the framework's lowercase identifier (e.g., `openai`, `langgraph`).

### 2. Implement the Session State Class (if needed)

If the framework requires per-session state (e.g., conversation history), create a session data class:

```python
class <Name>Session:
    """Stores framework-specific session data."""
    def __init__(self):
        self._history = []  # or whatever state the framework needs

    def get_history(self):
        return self._history

    def add_to_history(self, item):
        self._history.append(item)

    def clear_session(self):
        self._history.clear()
```

The session data is stored in the Agent Kernel `Session` via `session.set("<name>", <Name>Session())` and retrieved via `session.get("<name>")`.

### 3. Implement the Runner

Subclass `Runner` from `agentkernel.core.base`:

```python
from agentkernel.core.base import Runner, Session
from agentkernel.core.model import AgentReply, AgentReplyText, AgentRequest, AgentRequestText
from agentkernel.core.tool import ToolContext

class <Name>Runner(Runner):
    FRAMEWORK = "<name>"

    def __init__(self):
        super().__init__("<Name>Runner")

    def _session(self, session: Session) -> <Name>Session:
        """Get or create framework-specific session data."""
        data = session.get("<name>")
        if data is None:
            data = <Name>Session()
            session.set("<name>", data)
        return data

    async def run(self, agent, session: Session, requests: list[AgentRequest]) -> AgentReply:
        # 1. Create ToolContext for tool functions to access
        tool_context = ToolContext(
            runtime=Runtime.current(),
            agent=agent,
            session=session,
            requests=requests
        )

        with tool_context:
            tool_context.set()
            try:
                # 2. Get framework-specific session state
                fw_session = self._session(session)

                # 3. Convert AgentRequest models to framework-native format
                # e.g., extract text from AgentRequestText
                prompt = ""
                for req in requests:
                    if isinstance(req, AgentRequestText):
                        prompt = req.text

                # 4. Call the framework's execution API
                result = await self._execute(agent, fw_session, prompt)  # framework-specific

                # 5. Update session state
                fw_session.add_to_history({"input": prompt, "output": result})

                # 6. Return as AgentReply
                return AgentReplyText(text=str(result), prompt=prompt)
            finally:
                tool_context.reset()
```

**Key requirements:**
- Always create a `ToolContext` and set it so tool functions can access `ToolContext.get()`
- Always reset `ToolContext` in a `finally` block
- Handle all `AgentRequest` subtypes (`AgentRequestText`, `AgentRequestImage`, `AgentRequestFile`)
- Return an `AgentReply` (`AgentReplyText` or `AgentReplyImage`)

### 4. Implement the Agent Wrapper

Subclass `Agent` from `agentkernel.core.base`:

```python
from agentkernel.core.base import Agent, Runner, Session

class <Name>Agent(Agent):
    def __init__(self, name: str, runner: Runner, native_agent):
        super().__init__(name, runner)
        self._native_agent = native_agent

    def get_description(self) -> str:
        # Return the agent's description from the native framework object
        return self._native_agent.instructions  # framework-specific

    def get_a2a_card(self):
        from agentkernel.core.builder import A2ACardBuilder
        return A2ACardBuilder.build(
            name=self.name,
            description=self.get_description(),
            skills=[...]  # extract from agent tools
        )
```

**Key requirements:**
- `get_description()` must return a meaningful description from the native framework agent
- `get_a2a_card()` must return a valid A2A agent card built via `A2ACardBuilder`
- Store the native agent in `self._native_agent` for access in the Runner

### 5. Implement the ToolBuilder

Subclass `ToolBuilder` from `agentkernel.core.tool`:

```python
from agentkernel.core.tool import ToolBuilder

class <Name>ToolBuilder(ToolBuilder):
    @classmethod
    def bind(cls, funcs: list) -> list:
        """Wrap plain Python functions into framework-native tool objects."""
        tools = []
        for func in funcs:
            # Convert func to framework-specific tool format
            tool = framework_specific_tool_wrapper(func)
            tools.append(tool)
        return tools
```

### 6. Implement the Module

Subclass `Module` from `agentkernel.core.module`:

```python
from agentkernel.core.module import Module
from agentkernel.core.hooks import PreHook, PostHook
from agentkernel.trace.trace import Trace

class <Name>Module(Module):
    def __init__(self, agents: list):
        super().__init__()
        # Check if tracing is enabled, use traced runner if so
        trace_runner = Trace.get().<name>()  # returns Runner or None
        self.runner = trace_runner if trace_runner else <Name>Runner()
        self.load(agents)

    def _wrap(self, agent, agents) -> <Name>Agent:
        return <Name>Agent(agent.name, self.runner, agent)

    def load(self, agents: list) -> "Module":
        return super().load(agents)

    def pre_hook(self, agent, hooks: list[PreHook]) -> "Module":
        wrapped = self.get_agent(agent.name)
        if wrapped:
            wrapped.pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent, hooks: list[PostHook]) -> "Module":
        wrapped = self.get_agent(agent.name)
        if wrapped:
            wrapped.post_hooks.extend(hooks)
        return self
```

**Key requirements:**
- Constructor takes native framework agents, creates a Runner, calls `self.load(agents)`
- `_wrap()` creates the Agent wrapper — the agent `name` must come from the native agent
- Support trace runners via `Trace.get().<name>()`

### 7. Create the `__init__.py`

```python
# ak-py/src/agentkernel/framework/<name>/__init__.py
from .<name> import <Name>Module, <Name>ToolBuilder
```

### 8. Create the Public API Alias

Create `ak-py/src/agentkernel/<name>.py`:

```python
from .framework.<name> import <Name>Module, <Name>ToolBuilder
```

This allows users to import as `from agentkernel.<name> import <Name>Module`.

### 9. Update Package Exports

Add the framework to `ak-py/src/agentkernel/__init__.py` if appropriate (following the existing pattern).

### 10. Add Optional Dependencies

In `ak-py/pyproject.toml`, add an optional dependency group:

```toml
[project.optional-dependencies]
<name> = [
    "framework-package>=x.y.z",
    # Add any instrumentation packages for tracing support
]
```

### 11. Add Tracing Support

When adding tracing, create `ak-py/src/agentkernel/trace/langfuse/<name>.py`:

```python
from .<name>_runner import <Name>Runner as Base<Name>Runner

class LangFuse<Name>Runner(Base<Name>Runner):
    def __init__(self, langfuse_client):
        super().__init__()
        self._client = langfuse_client

    async def run(self, agent, session, requests):
        with self._client.start_as_current_span(name=agent.name):
            return await super().run(agent, session, requests)
```

Also update `ak-py/src/agentkernel/trace/base.py` and `ak-py/src/agentkernel/trace/trace.py` to add the new framework method.

### 12. Add Tests

Create tests in `ak-py/tests/`:

```python
# ak-py/tests/test_module_<name>.py
# ak-py/tests/test_tool_<name>.py
```

Follow the existing test patterns — use `DummyRunner`, `DummyAgent` for unit tests, `monkeypatch` for config overrides, `@pytest.mark.asyncio` for async tests.

### 13. Add Examples

Create at minimum:
- `examples/cli/<name>/` — CLI demo with `demo.py`, `pyproject.toml`, `demo_test.py`
- `examples/api/<name>/` — API demo (optional but recommended)

### 14. Add Documentation

- Add a page under `docs/docs/frameworks/<name>.md`
- Update `docs/sidebars.js` to include the new framework

## Checklist

- [ ] `ak-py/src/agentkernel/framework/<name>/` directory with `__init__.py` and `<name>.py`
- [ ] `<Name>Session` (if needed), `<Name>Runner`, `<Name>Agent`, `<Name>Module`, `<Name>ToolBuilder`
- [ ] Public alias at `ak-py/src/agentkernel/<name>.py`
- [ ] Optional dependency group in `ak-py/pyproject.toml`
- [ ] Trace runner in `ak-py/src/agentkernel/trace/langfuse/<name>.py` (optional)
- [ ] Updates to `trace/base.py` and `trace/trace.py` (if adding tracing)
- [ ] Unit tests in `ak-py/tests/`
- [ ] CLI example in `examples/cli/<name>/`
- [ ] Documentation in `docs/docs/frameworks/<name>.md`
