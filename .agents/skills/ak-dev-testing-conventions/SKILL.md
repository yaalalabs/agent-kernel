---
name: ak-dev-testing-conventions
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
| `test_sessions_redis.py` | RedisSessionStore missing-config error, shared RedisDriver retry exhaustion |
| `test_sessions_valkey.py` | ValkeySessionStore round trips (fake client), shared ValkeyDriver retry exhaustion |
| `test_sessions_dynamodb.py` | DynamoDBSessionStore Binary wrap/unwrap, missing-item skip (mocked driver) |
| `test_shared_drivers.py` | Shared DB drivers (`core/util/driver/`): retry scope, ping/reconnect, command surface, DynamoDB item-dict semantics |
| `test_multimodal_redis_store.py` | RedisAttachmentStore index TTL refresh, JSON round trip, pruning (mocked driver) |
| `test_config.py` | AKConfig loading, env vars |
| `test_test_config.py` | AKTestConfig (Test framework config) loading, defaults |
| `test_tool.py` | ToolContext, cache |
| `test_tool_openai.py` | OpenAI ToolBuilder |
| `test_tool_crewai.py` | CrewAI ToolBuilder |
| `test_tool_langgraph.py` | LangGraph ToolBuilder |
| `test_tool_adk.py` | Google ADK ToolBuilder |
| `test_tool_smolagents.py` | Smolagents ToolBuilder |
| `test_tool_pydanticai.py` | Pydantic AI ToolBuilder |
| `test_openai_runner.py` | OpenAIRunner execution, error handling |
| `test_crewai_runner.py` | CrewAIRunner execution (mocked Crew kickoff) |
| `test_smolagents_runner.py` | SmolagentsRunner execution, multimodal requests, error handling |
| `test_pydanticai_runner.py` | PydanticAIRunner execution, structured output, BinarySerde session round-trip, multimodal wiring |
| `test_guardrail.py` | Guardrail factories, hooks |
| `test_api_http.py` | REST API handler |
| `test_chat_service_core.py` | ChatService execution core (`execute`/`execute_stream`): typed replies, prebuilt request lists, validation, error propagation, wrapper wire shapes |
| `test_chat_service_streaming.py` | ChatService SSE/stream chunk formatting |
| `test_slack_integration.py` | Slack handler on the ChatService core: request/identity mapping, attachment-only, error paths, chunking (pattern for integration handler tests) |
| `test_whatsapp_integration.py` | WhatsApp handler on the ChatService core: text/media paths, rejections before execute |
| `test_gmail_integration.py` | Gmail handler on the ChatService core: prompt assembly, session fallback, attachments, error paths |
| `test_thread_integration.py` | Thread integration: `ThreadRecorder` ordering/enforcement, `AgentThreadRequestHandler` recording + no-phantom-thread prechecks, stream accumulation, end-to-end read-back |
| `test_thread_router.py` | Thread read routes (`ThreadRESTRequestHandler`): pagination, `Authoriser` 401/403 semantics |
| `test_akagentrunner_stream.py` | Serverless `ServerlessStreamAgentRunner` (SQS streaming) |
| `test_akresponsehandler.py` | Serverless response handler (`CHAT_RESPONSE` / `STREAM_CHUNK` broadcast) |
| `test_ws_lambda_stream.py` | WebSocket Lambda router in `stream` mode |
| `test_cli_tester.py` | CLI test framework |
| `test_auth_handler.py` | Auth handler |
| `test_akauthorizer.py` | AWS Lambda authorizer |
| `test_lambda_router.py` | Lambda routing |
| `test_sqs_handler.py` | AWS SQSHandler config, client, message sending |
| `test_serverless_request_handle.py` | BaseRequest/BaseRunRequest parsing from serverless payloads |
| `test_firestore_database_id.py` | Shared `FirestoreDriver` (`core/util/driver/firestore.py`, explicit constructor params) named `database_id` configuration |
| `test_ak_logger.py` | AKLogger level resolution, configuration |
| `test_error_util.py` | `user_facing_error_message` error mapping |
| `test_thread_runner.py` | ThreadRunner task validation, failure/shutdown semantics |
| `test_ecs_sqs_consumer_parallel.py` | ECSSQSConsumer message processing + delete/retry semantics |
| `test_sandbox.py` | Sandbox core: model/capabilities, error hierarchy, config, provider contract, manager + factory + embedded broker, agent surface (system tools + task-completion pre-hook), `agents` scoping |
| `test_sandbox_broker.py` | Broker flavors (embedded/thread) end-to-end, thread loop-identity contract, wait-policy promotion + late-completion recovery, suspend/resume completion ingestion |
| `test_sandbox_providers.py` | `local_subprocess` (real subprocess) + `docker` (mocked SDK) providers, run against the reusable `SandboxProviderContract` |
| `test_factory.py` | Shared pluggable-backend helpers (`resolve_dotted`, `require_extra`, `AKConfigError`) in `core/util/factory.py` |
| `test_store_builders.py` | Session/thread/multimodal store builders: fail-loud on unknown type, BYO dotted-path subclass resolution |
| `test_trace.py` | Trace factory built-in resolution, BYO dotted path, unknown-type error |

## Test Patterns

### Dummy Implementations for Unit Testing

Create minimal implementations of abstract classes:

```python
from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReplyText, AgentRequest, AgentRequestText


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].prompt if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(response=f"ok:{prompt}")

    async def stream(self, agent, session, requests):
        # Runner.stream() is abstract — implement even in test doubles.
        # Raise NotImplementedError() (with a trailing `yield`) if the test doesn't exercise streaming,
        # or yield token strings to test Runtime.stream() / AgentService.stream_multi().
        raise NotImplementedError()
        yield


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

    result = await runtime.run(agent, session, [AgentRequestText(prompt="hello")])
    assert result.response == "ok:hello"
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
                    req.prompt = req.prompt.upper()
            return requests
        def name(self): return "test_hook"

    agent = DummyAgent()
    agent.pre_hooks.append(TestPreHook())
    # ... run through Runtime and verify modified input


@pytest.mark.asyncio
async def test_pre_hook_halts_execution():
    class BlockingHook(PreHook):
        async def on_run(self, session, agent, requests):
            return AgentReplyText(response="blocked", prompt="")
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
- **judge**: Ragas-based LLM evaluation — uses the `answer_similarity` metric against expected answers (ground truth), or `answer_relevancy` against the question when no expected answers are given (see `ak-py/src/agentkernel/test/test.py`)
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

- **`test.yaml`**: Triggers on pull requests, pushes to `develop`, and manual dispatch; has an `update-lock-files` job (dispatch-only) and a `run-tests` job that delegates to `test-reusable.yaml`
- **`test-reusable.yaml`**: Reusable workflow (`workflow_call`) containing the actual test jobs, including the `uv run pytest` invocation
- **`test-trusted-pr.yaml`**: Runs `test-reusable.yaml` with secrets for fork PRs that have been reviewed and labeled `safe-to-test` (`pull_request_target`)
- **`test-github-app.yaml`**: Manual dispatch only; verifies the GitHub App secrets (`APP_ID`/`APP_PRIVATE_KEY`) are configured correctly
- **`integration-test.yaml`**: "Nightly" (tier `nightly`) integration tests against deployed environments; scheduled weekly on Sundays at 5:30 PM UTC (`cron: '30 17 * * 0'`), plus manual dispatch
- **`integration-test-weekly.yaml`**: Weekly integration tests against deployed environments (cron currently commented out; manual dispatch, with option to keep cloud resources on failure)
- **`code-quality.yml`**: Runs linting checks (see `code-quality` skill)

Both integration workflows restore the branch-built `agentkernel` wheel from the `ak-py-${{ github.sha }}` cache with `fail-on-cache-miss: true` — the job fails loudly instead of silently falling back to the published PyPI wheel if the build/cache step didn't run first. `.github/scripts/run_single_test.py`'s `test_aws_deployment()` then runs `./build.sh local` in the example directory (force-reinstalling the local wheel with `--no-cache-dir` before packaging/deploying) and invokes the test client with `uv run --no-sync pytest ...` so `uv` doesn't re-sync the venv from `uv.lock` and revert the local wheel back to the PyPI version. When adding a new example to `integration-test-config.yaml`, make sure its `build.sh`/`deploy.sh` `local` branch force-reinstalls `agentkernel` from `../../../ak-py/dist` with `--no-cache-dir`, matching this pattern — otherwise the test can silently exercise a stale published version instead of the branch's code.

`integration-test-weekly.yaml`'s deploy/test/destroy are separate workflow steps (not one bash block) so each shows up as its own status: the `Test` step only runs `if: steps.deploy.outcome == 'success'`, and `Destroy` runs `if: !cancelled() && !(keep_resources_on_failure && (deploy or test failed))`. `.github/scripts/generate_test_matrix.py` assigns each `gcp-*` matrix entry a `deploy_stagger` (90s apart) so parallel GCP jobs don't provision VPC connectors on the same network simultaneously; the workflow sleeps that many seconds before deploying. Known infra-flakiness mitigations to preserve when touching this area, since they were added specifically to fix recurring weekly e2e failures:

- **AWS containerized examples' `deploy.sh`** call `wait_for_ecs_stable` after `terraform apply` (reads `region`/`product_alias`/`env_alias`/`module_name` from `terraform.tfvars`, then `aws ecs wait services-stable`) so the test doesn't hit the app before the ECS service has finished rolling out.
- **`run_single_test.py`'s `destroy_aws_resources`** pre-deletes Lambda functions on the example's security groups and runs a background thread that periodically deletes their now-detached ENIs, so `terraform destroy` isn't blocked waiting ~20 min for AWS to release Hyperplane ENIs.
- **`run_single_test.py`'s `deploy_gcp_resources`/`destroy_gcp_resources`** retry the deploy up to 3 times and sweep `ERROR`-state VPC Access Connectors between attempts (`sweep_gcp_error_connectors`, matched by network name from `terraform.tfvars`).
- **Azure serverless/containerized deploys** accept an `AK_PRE_DEPLOY_AUTH_CMD` env var (set in the workflows to refresh the OIDC-based `az login`) and re-run it before each long-running `az` step in `linux_function.tf`'s `deploy_function_code`, since the OIDC token can expire mid-deploy.

If a weekly/nightly integration run fails with a symptom matching one of these (ECS "still rolling out", GCP `VPC_ACCESS_CONNECTOR_ERROR`, AWS destroy timing out on ENIs, or Azure CLI auth expiring), look here before re-adding ad-hoc sleeps or retries.

## Best Practices

1. **Use ordered tests** (`@pytest.mark.order(n)`) when testing conversational flows where follow-up questions depend on prior context
2. **Use session-scoped fixtures** for test clients that are expensive to create
3. **Mock external services** (LLM APIs, cloud services) in unit tests — only hit real APIs in integration tests
4. **Test both success and failure paths** — especially for hooks and guardrails
5. **Use `DummyAgent`/`DummyRunner`** to isolate the component under test from framework-specific behavior
6. **Test session persistence** — verify that state survives across multiple `Runtime.run()` calls within the same session
