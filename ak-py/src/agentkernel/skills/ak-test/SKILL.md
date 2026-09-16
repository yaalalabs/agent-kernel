---
name: ak-test
description: >
  Set up testing and debug common issues in Agent Kernel projects. This skill guides
  you through configuring the built-in test framework, writing agent tests, choosing
  test modes (score, llm, fallback), and troubleshooting common errors.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: user
---

# Testing & Debugging

Use this skill to set up testing for your Agent Kernel project or debug issues.

## Instructions for the Agent

### Setting Up Tests

#### 1. Add Test Dependencies

Update `pyproject.toml`:
```toml
[dependency-groups]
dev = [
    "agentkernel[test]>=0.9.0",
    "black>=23.0.0",
    "isort>=5.0.0",
    "mypy>=1.0.0",
]
```

Run `uv sync` to install test dependencies.

#### 2. Choose a Test Mode

Create `test-config.yaml` in the directory you run tests from — it is a separate, un-nested file
(no top-level `test:` key), loaded only when the test harness runs. A `test:` section left over in
`config.yaml` is ignored:

```yaml
mode: score       # Options: score | llm | fallback (default: fallback)
```

| Mode | How it Works | Best For |
|------|-------------|----------|
| **score** | Deterministic string-match scoring (built-in `deepeval`: `Scorer.quasi_exact_match_score`; built-in `opik`: graded `LevenshteinRatio`) | Deterministic responses, exact answers |
| **llm** | LLM evaluates if response is semantically correct (`GEval`, from either built-in evaluator) | Open-ended responses, creative agents |
| **fallback** | Tries score first, falls back to llm if score fails | General-purpose testing |

For llm mode, configure the llm model:
```yaml
mode: llm
llm:
  model: gpt-4o-mini
  provider: openai
```

**Evaluator backend:** `evaluator` selects the scoring backend used by both `score` and `llm`
modes — `deepeval` (the default, `pip install "agentkernel[test]"`) and `opik` (`pip install
"agentkernel[opik]"`, [Opik](https://www.comet.com/docs/opik/) by Comet, runs entirely locally) are
the two built-ins. Set it to a dotted path (e.g. `my_evaluator.MyEvaluator`) to bring your own
`AKEvaluator` subclass instead:

```yaml
evaluator: opik   # switch to the other built-in
```

```yaml
mode: fallback
evaluator: my_evaluator.MyEvaluator   # resolves against my_evaluator.py next to your test file
```

#### 2a. Bring Your Own Evaluator (optional)

Use this when neither built-in evaluator's scoring fits your agent — e.g. `deepeval`'s binary
exact-match score mode is too strict and `opik`'s graded `LevenshteinRatio` still doesn't capture
what you need, or you want a judge call that doesn't depend on DeepEval/Opik at all, or a
domain-specific rubric. No AK core change is required: any dotted path to an `AKEvaluator` subclass
works as the `evaluator:` value, resolved the same way sandbox providers and session stores resolve
their own bring-your-own backends.

1. Create a module next to your test file (e.g. `my_evaluator.py`) and subclass `AKEvaluator`,
   importing the interface from `agentkernel.test.core.evaluator`:

   ```python
   from agentkernel.test.core.evaluator import (
       AKEvaluationCase,
       AKEvaluationError,
       AKEvaluationResult,
       AKEvaluator,
       AKMissingInput,
   )

   class MyEvaluator(AKEvaluator):
       def evaluate_by_score(self, case: AKEvaluationCase) -> AKEvaluationResult:
           if not case.expected:
               raise AKMissingInput("evaluate_by_score requires AKEvaluationCase.expected")
           score = ...  # your deterministic, offline scoring logic
           return AKEvaluationResult(
               metric="my_metric",
               evaluator="my_evaluator",
               score=score,
               passed=score >= case.threshold,
           )

       def evaluate_by_llm(self, case: AKEvaluationCase) -> AKEvaluationResult:
           if not case.expected:
               raise AKMissingInput("evaluate_by_llm requires AKEvaluationCase.expected")
           try:
               score = ...  # your judge call (any LLM client — litellm, an SDK, a hosted judge)
           except Exception as exc:
               raise AKEvaluationError(f"judge call failed: {exc}") from exc
           return AKEvaluationResult(
               metric="my_llm_metric",
               evaluator="my_evaluator",
               score=score,
               passed=score >= case.threshold,
           )
   ```

2. Both methods are synchronous and must set `result.passed` themselves — `Test.compare` decides
   whether a failing `passed` is fatal (raises `AssertionError`) or, with `return_metrics=True`,
   returned to the caller; it never overrides `passed`.
3. Follow the same error contract every evaluator (built-in or custom) must honor: raise
   `AKMissingInput` if a required `AKEvaluationCase` field (usually `expected`) is missing; raise
   `AKEvaluationError` if your backend fails (bad credentials, transport error, unparseable judge
   output) — never return a `0.0` to stand in for a failure, since `0.0` must only ever mean
   "scored zero". If your evaluator only supports one of the two modes (e.g. judge-only, no offline
   scoring), raise `AKMetricNotSupported` from the other — `fallback` mode uses this to skip
   straight to the supported one.
4. Point `test-config.yaml` at it by dotted path — `module_name.ClassName`, resolved against the
   module's location (next to your test file, since that's what's on `sys.path` under pytest's
   default import mode):

   ```yaml
   evaluator: my_evaluator.MyEvaluator
   ```

5. No AK extra beyond `agentkernel[test]` is needed unless your evaluator's own dependencies
   (an LLM client, a scoring library) require one — each built-in's import (`deepeval`, `opik`)
   lives entirely inside its own resolution branch, so a custom evaluator never pulls either in.

See `examples/cli/custom-evaluator/` for a complete worked example — a stdlib-only Jaccard
token-overlap scorer plus a raw `litellm` judge call, no DeepEval dependency at all — and
[`docs/docs/testing/cli-testing.md`](../../../../../docs/docs/testing/cli-testing.md#bring-your-own-evaluator)
for the reference documentation.

#### 3. Write CLI Agent Tests

For agents running via CLI (`demo.py`):

```python
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")       # Path to your agent definition file
    await test.start()
    try:
        yield test
    finally:
        await test.stop()


@pytest.mark.order(1)
async def test_greeting(test_client):
    await test_client.send("Hello!")
    await test_client.expect(["Hello", "Hi", "Greetings"])


@pytest.mark.order(2)
async def test_specific_question(test_client):
    await test_client.send("What is the capital of France?")
    await test_client.expect(["Paris"])


@pytest.mark.order(3)
async def test_follow_up(test_client):
    # Follow-up questions work because session state is maintained
    await test_client.send("What is its population?")
    await test_client.expect(["2 million", "2.1 million", "approximately 2 million"])
```

**Key patterns:**
- Use `@pytest.mark.order(n)` for sequential tests where context matters
- Use `scope="session"` fixtures so the agent stays running across tests
- `expect()` takes a list of acceptable answer patterns
- The test framework uses the configured mode to compare responses
- Pass `return_metrics=True` to `expect()` (or `Test.compare()`) to get back an
  `AKEvaluationResult` (score, evaluator, metric, reason) instead of raising `AssertionError` on a
  mismatch — useful for asserting on the score itself rather than just pass/fail

#### 4. Write API Agent Tests

For agents running via REST API:

```python
import asyncio
import os
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")


class APITestClient:
    def __init__(self, url: str):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt: str, agent: str = "triage") -> str:
        payload = {
            "prompt": prompt,
            "session_id": self.session_id,
            "agent": agent,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.url}/run", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    # Option A: Test against running server
    endpoint = os.getenv("AK_TEST_ENDPOINT", "http://localhost:8000")

    # Option B: Start server in fixture
    # proc = subprocess.Popen(["python3", "app.py"], stdout=sys.stdout, stderr=sys.stderr)
    # await asyncio.sleep(5)

    yield APITestClient(endpoint)

    # proc.terminate(); proc.wait()  # if using Option B


@pytest.mark.order(1)
async def test_basic_question(http_client):
    response = await http_client.send("What is 2+2?")
    Test.compare(response, ["4", "The answer is 4"])


@pytest.mark.order(2)
async def test_agent_routing(http_client):
    response = await http_client.send("Tell me about World War 2")
    Test.compare(response, ["World War II", "World War 2", "WWII"])
```

#### 5. Run Tests

```bash
uv run pytest                          # All tests
uv run pytest demo_test.py             # Specific file
uv run pytest -k "test_greeting"       # By name pattern
uv run pytest -x                       # Stop on first failure
uv run pytest -v                       # Verbose output
uv run pytest --tb=long                # Full tracebacks
```

---

### Debugging Common Issues

#### Issue: "No agents available"

**Symptom:** CLI shows "No agents available. Please load an agent module using !load."

**Cause:** The Module constructor was not called, so no agents are registered with Runtime.

**Fix:** Ensure your agent file calls the Module constructor:
```python
# This line registers agents with the global Runtime
OpenAIModule([triage_agent, math_agent])
```

#### Issue: Session state not persisting

**Symptom:** Agent doesn't remember context from previous messages.

**Causes & Fixes:**
1. **In-memory sessions (default):** State is lost when the process restarts. Switch to Redis/DynamoDB/CosmosDB for persistence.
2. **Different session IDs:** Ensure you're using the same `session_id` across requests.
3. **Lambda cold starts:** Session state must be stored externally. Use Redis or DynamoDB.

Check session config:
```yaml
session:
  type: redis
  redis:
    url: "redis://localhost:6379"
    prefix: "ak:myproject:"
```

#### Issue: "ToolContext not available"

**Symptom:** `RuntimeError: ToolContext is not set` inside a tool function.

**Cause:** The tool is being called outside of the agent execution context.

**Fix:** Ensure tool functions are bound via the framework's ToolBuilder and called within agent execution. Don't call tool functions directly outside of `Runtime.run()`.

```python
# Correct: bound via ToolBuilder
tools = OpenAIToolBuilder.bind([my_tool])
agent = Agent(name="test", tools=tools, instructions="...")

# Inside tool function:
def my_tool(query: str) -> str:
    context = ToolContext.get()  # Works during agent execution
    session = context.session
    return "result"
```

#### Issue: Guardrail blocks all requests

**Symptom:** Every request returns a guardrail violation message.

**Fixes:**
1. Check guardrail config — ensure `config_path` points to a valid JSON file
2. Review guardrail rules — thresholds may be too strict
3. Check the guardrail model — ensure `model` field is correct
4. Disable temporarily to isolate: set `enabled: false` in config

#### Issue: Import errors for framework packages

**Symptom:** `ModuleNotFoundError: No module named 'agents'` (or `crewai`, `langgraph`, etc.)

**Fix:** Install the correct extras:
```bash
pip install "agentkernel[openai]"     # For OpenAI Agents SDK
pip install "agentkernel[crewai]"     # For CrewAI
pip install "agentkernel[langgraph]"  # For LangGraph
pip install "agentkernel[adk]"        # For Google ADK
pip install "agentkernel[smolagents]" # For Smolagents
pip install "agentkernel[pydanticai]" # For Pydantic AI (add a provider, e.g. pydantic-ai-slim[openai])
```

Or in `pyproject.toml`:
```toml
dependencies = ["agentkernel[openai,api]>=0.9.0"]
```

#### Issue: Redis connection errors

**Symptom:** `ConnectionError: Error connecting to Redis` or similar.

**Fixes:**
1. Verify Redis is running: `redis-cli ping` should return `PONG`
2. Check the URL in config: `redis://host:port` format
3. For AWS ElastiCache: ensure your app is in the same VPC
4. Check security groups / firewall rules

#### Issue: Terraform deployment fails

**Symptom:** `terraform apply` errors out.

**Common fixes:**
1. Run `terraform init` first
2. Check AWS/Azure credentials: `aws sts get-caller-identity` or `az account show`
3. Verify the Terraform module version matches your `agentkernel` version
4. Check that required variables are set in `terraform.tfvars`
5. For state conflicts: `terraform state list` and `terraform state rm` to clean up

#### Issue: Webhook not receiving messages

**Symptom:** Messages sent on Slack/WhatsApp/etc. don't reach the agent.

**Fixes:**
1. Verify webhook URL is publicly accessible (use ngrok for local dev: `ngrok http 8000`)
2. Check platform webhook configuration points to the correct path:
   - Slack: `/slack/events`
   - WhatsApp: `/whatsapp/webhook`
   - Telegram: `/telegram/webhook`
3. Verify environment variables (bot tokens, signing secrets)
4. Check server logs for incoming webhook requests
5. Test health endpoint: `curl http://localhost:8000/health`

---

### Enabling Debug Logging

Add to `config.yaml`:
```yaml
logging:
  ak:
    level: DEBUG  # Agent Kernel logger level (INFO, DEBUG, ERROR, WARNING, CRITICAL)
  system:
    level: DEBUG  # System/root logger level (affects process-wide logging)
```

Or set environment variables:
```bash
export AK_LOGGING__AK__LEVEL=DEBUG
# Optional: Enable system-wide debug logging
export AK_LOGGING__SYSTEM__LEVEL=DEBUG
```

- `logging.ak.level` controls Agent Kernel's own logger verbosity
- `logging.system.level` controls the process-wide/root logger (use with caution as it affects all application logging)
- If you do not want Agent Kernel to modify application-wide logging, omit the `system` section

### Health Check Endpoint

All API-mode agents expose a health endpoint:
```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

Use this to verify your server is running and accessible.

---

### What to Do Next

Your tests are set up and passing. Here's what you might do next:

- **Add more tools & agents** → Use the `ak-build` skill to iterate on your project — add new capabilities, then come back here to add tests for them.
- **Deploy to cloud** → Use the `ak-cloud-deploy` skill to deploy your tested agent to AWS or Azure.
- **Add guardrails** → Use the `ak-add-capabilities` skill to add input/output guardrails, tracing, or session persistence.
- **Connect a messaging platform** → Use the `ak-add-integration` skill to make your tested agent available on Slack, WhatsApp, or other channels.
