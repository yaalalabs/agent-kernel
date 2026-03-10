---
name: testing-conventions
description: >
  Testing conventions, patterns, and automation for Agent Kernel development.
  Use this skill when writing tests for new features, debugging test failures,
  or understanding the test infrastructure. Covers pytest patterns, async testing,
  mocking, the built-in Test framework, and CI/CD test workflows.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Testing Conventions

## Running Tests

```bash
cd ak-py
uv run pytest                           # Run all tests with coverage
uv run pytest tests/test_runtime.py     # Run specific test file
uv run pytest -k "test_session"         # Run tests matching pattern
uv run pytest -x                        # Stop on first failure
```

Coverage and HTML reports are auto-generated per `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term --cov-report=html --html=report.html"
```

## Test File Organization

Tests live in `ak-py/tests/` and follow the naming convention `test_<module>.py`:

| Test File | Tests |
|-----------|-------|
| `test_base.py` | Session, Agent, Runner abstractions |
| `test_runtime.py` | Runtime registration, execution, hooks |
| `test_module.py` | Module load/unload, wrapping |
| `test_session.py` | Session state, caches, context vars |
| `test_session_cache.py` | LRU SessionCache |
| `test_sessions_in_memory.py` | InMemorySessionStore |
| `test_config.py` | AKConfig loading, env vars |
| `test_tool.py` | ToolContext, cache |
| `test_tool_openai.py` | OpenAI ToolBuilder |
| `test_tool_crewai.py` | CrewAI ToolBuilder |
| `test_tool_langgraph.py` | LangGraph ToolBuilder |
| `test_tool_adk.py` | Google ADK ToolBuilder |
| `test_guardrail.py` | Guardrail factories, hooks |
| `test_api_http.py` | REST API handler |
| `test_cli_tester.py` | CLI test framework |
| `test_auth_handler.py` | Auth handler |
| `test_akauthorizer.py` | AWS Lambda authorizer |
| `test_lambda_router.py` | Lambda routing |

## Test Patterns

### Dummy Implementations for Unit Testing

Create minimal implementations of abstract classes:

```python
from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReplyText, AgentRequest, AgentRequestText


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].text if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(text=f"ok:{prompt}")


class DummyAgent(Agent):
    def __init__(self, name="test-agent"):
        runner = DummyRunner("DummyRunner")
        super().__init__(name, runner)

    def get_description(self) -> str:
        return "Test agent"

    def get_a2a_card(self):
        return None
```

### Async Test Patterns

Use `@pytest.mark.asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_runtime_run():
    runtime = Runtime(InMemorySessionStore())
    agent = DummyAgent()
    runtime.register(agent)
    session = runtime.sessions().new("test-session")

    result = await runtime.run(agent, session, [AgentRequestText(text="hello")])
    assert result.text == "ok:hello"
```

### Monkeypatching Config

Use `monkeypatch` to override `AKConfig` for tests:

```python
def test_redis_session_store(monkeypatch):
    class FakeCfg:
        class session:
            type = "redis"
            cache = None
            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))
    store = SessionStoreBuilder.build()
    assert isinstance(store, RedisSessionStore)
```

### Session Context Tests

Test the async context manager pattern:

```python
@pytest.mark.asyncio
async def test_session_context():
    session = Session("test-id")

    async with session:
        current = Session.current()
        assert current is session
        assert current.id == "test-id"

    # Outside context, no current session
    assert Session.current() is None
```

### Testing Volatile vs Non-Volatile Caches

```python
@pytest.mark.asyncio
async def test_volatile_cache_cleared():
    session = Session("test-id")

    async with session:
        session.get_volatile_cache().set("key", "value")
        assert session.get_volatile_cache().get("key") == "value"

    # Volatile cache is cleared after Runtime.run() completes
    # Non-volatile cache persists
```

### Testing Hooks

```python
@pytest.mark.asyncio
async def test_pre_hook_modifies_request():
    class TestPreHook(PreHook):
        async def on_run(self, session, agent, requests):
            for req in requests:
                if isinstance(req, AgentRequestText):
                    req.text = req.text.upper()
            return requests
        def name(self): return "test_hook"

    agent = DummyAgent()
    agent.pre_hooks.append(TestPreHook())
    # ... run through Runtime and verify modified input


@pytest.mark.asyncio
async def test_pre_hook_halts_execution():
    class BlockingHook(PreHook):
        async def on_run(self, session, agent, requests):
            return AgentReplyText(text="blocked", prompt="")
        def name(self): return "blocking_hook"

    # When a PreHook returns AgentReply, Runtime.run() returns it immediately
    # without calling the agent's runner
```

## Built-in Test Framework

Agent Kernel provides a `Test` class (`ak-py/src/agentkernel/test/`) for integration testing. This framework is used in examples and can be used for testing deployed agents as well.

```python
from agentkernel.test import Test

# In test files
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")       # Path to agent definition file
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

@pytest.mark.order(1)
async def test_agent_response(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])
```

### Test Modes

Configured via `config.yaml`:

```yaml
test:
  mode: fuzzy    # fuzzy | judge | fallback
  judge:
    model: gpt-4o-mini
```

- **fuzzy**: Uses `rapidfuzz` string similarity matching (default threshold)
- **judge**: Uses an LLM to evaluate if the response is semantically correct
- **fallback**: Tries fuzzy first, falls back to judge if fuzzy fails

### Test.compare() for API Tests

For HTTP API tests, use `Test.compare()`:

```python
response = await http_client.send("What is 2+2?")
Test.compare(response, ["4", "The answer is 4"])
```

## HTTP API Integration Tests

Pattern for testing deployed agents:

```python
class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, endpoint=""):
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": "triage"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    endpoint = os.getenv("AK_TEST_ENDPOINT")
    yield APITestClient(endpoint)
```

## CI/CD Workflows

- **`test.yaml`**: Runs `uv run pytest` on every PR
- **`integration-test.yaml`**: Runs integration tests against deployed environments
- **`code-quality.yml`**: Runs linting checks (see `code-quality` skill)

## Best Practices

1. **Use ordered tests** (`@pytest.mark.order(n)`) when testing conversational flows where follow-up questions depend on prior context
2. **Use session-scoped fixtures** for test clients that are expensive to create
3. **Mock external services** (LLM APIs, cloud services) in unit tests — only hit real APIs in integration tests
4. **Test both success and failure paths** — especially for hooks and guardrails
5. **Use `DummyAgent`/`DummyRunner`** to isolate the component under test from framework-specific behavior
6. **Test session persistence** — verify that state survives across multiple `Runtime.run()` calls within the same session
