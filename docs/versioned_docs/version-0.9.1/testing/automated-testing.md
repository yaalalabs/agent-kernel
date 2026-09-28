---
sidebar_position: 3
---

# Automated Testing

Create automated test suites for your CLI agents using pytest and the Agent Kernel Test framework.

## pytest Integration

The Agent Kernel Test framework integrates seamlessly with pytest for automated testing:

```python
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

@pytest.mark.order(1)
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])

@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("Which country hosted the tournament?")
    await test_client.expect(["Co-hosted by India, Pakistan and Sri Lanka."])
```

## Test Comparison Modes

Agent Kernel supports three comparison modes for validating responses:

### Score Mode

Deterministic, offline string-match scoring — no LLM call. Behavior depends on the configured
evaluator: DeepEval (the default) uses `Scorer.quasi_exact_match_score`, a normalised whole-string
equality check, while Opik uses its `LevenshteinRatio` metric, a graded fuzzy-similarity score. See
[Built-in evaluators](./cli-testing#configuration-based-mode) for how to switch:

```python
from agentkernel.test import Test, Mode

@pytest.mark.order(1)
async def test_score_matching(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Use score mode with an 0.8 threshold
    # expected is a list - test passes if ANY match scores above threshold
    Test.compare(
        actual=test_client.last_agent_response,
        expected=[
            "Sri Lanka won the 1996 cricket world cup",
            "Sri Lanka won the 1996 world cup",
            "The 1996 cricket world cup was won by Sri Lanka"
        ],
        threshold=0.8,
        mode=Mode.SCORE
    )
```

**Note:** The `expected` parameter accepts a list of acceptable responses. With the default DeepEval
evaluator, the test passes if the actual response's normalised text exactly equals **any** of the
expected values (score `1.0`) — there is no partial credit. With the Opik evaluator, `LevenshteinRatio`
gives a graded similarity score instead, so a close-but-not-exact match can still clear the threshold.

### Llm Mode

Uses LLM-as-judge evaluation for semantic similarity. Both built-in evaluators use a `GEval` metric
here — DeepEval's `GEval` via an `LLMTestCase`, Opik's `GEval` via a single packed `output` string:

```python
@pytest.mark.order(2)
async def test_llm_evaluation(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Use llm mode for semantic evaluation
    # expected is a list - test passes if ANY has sufficient semantic similarity
    Test.compare(
        actual=test_client.last_agent_response,
        expected=[
            "Sri Lanka won the 1996 cricket world cup",
            "Sri Lanka was the winner of the 1996 world cup",
            "The 1996 cricket world cup was won by Sri Lanka"
        ],
        user_input="Who won the 1996 cricket world cup?",
        threshold=0.5,
        mode=Mode.LLM
    )
```

**Llm Mode Metrics:**
- Uses `GEval`, an LLM rubric judging whether the actual response conveys the same information as
  each expected answer, without penalizing extra detail beyond a short `expected` phrase. Passes if
  **any** exceeds threshold. `expected` is required.

**Note:** When multiple expected answers are provided, the llm evaluator compares against each one and passes if **any** score meets the threshold.

### Fallback Mode (Default)

Tries score matching first, falls back to llm evaluation:

```python
@pytest.mark.order(3)
async def test_fallback_mode(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Fallback mode (default) - multiple expected answers
    Test.compare(
        actual=test_client.last_agent_response,
        expected=[
            "Sri Lanka",
            "Sri Lanka won the 1996 cricket world cup",
            "The winner was Sri Lanka"
        ],
        user_input="Who won the 1996 cricket world cup?",
        threshold=0.5,
        mode=Mode.FALLBACK  # or None to use config default
    )
```

**Note:** With multiple expected answers, score mode tries each one and passes if **any** match exceeds the threshold. If all score matches fail, llm mode evaluates against each expected answer.

### Configuring Test Mode

Set the default mode via a `test-config.yaml` file in the directory the tests run from (a `test:` section in the application's `config.yaml` is ignored):

```yaml
# test-config.yaml
mode: fallback  # Options: score, llm, fallback
evaluator: deepeval  # Built-in short name ('deepeval' or 'opik'), or a dotted path to your own AKEvaluator subclass
llm:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```

Or via environment variables:

```bash
export AK_TEST__MODE=llm
export AK_TEST__LLM__MODEL=gpt-4o-mini
export AK_TEST__LLM__PROVIDER=openai
export AK_TEST__LLM__EMBEDDING_MODEL=text-embedding-3-small
```

### Using expect() with Mode

The `expect()` method uses the configured mode:

```python
@pytest.mark.order(1)
async def test_with_expect(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Uses mode from AKTestConfig (test-config.yaml / AK_TEST__MODE)
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])
```

## Required Dependencies

Add these dependencies to your test environment:

```bash
pip install pytest pytest-asyncio pytest-order
```

## Test Structure

### Session-Scoped Fixtures

Use session-scoped fixtures to maintain CLI state across multiple tests:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("demo.py", match_threshold=0.7)
    await test.start()
    try:
        yield test
    finally:
        await test.stop()
```

### Ordered Tests

Use `pytest-order` to ensure tests run in sequence for conversation flows:

```python
@pytest.mark.order(1)
async def test_greeting(test_client):
    await test_client.send("Hello!")
    await test_client.expect("Hello! How can I help you?")

@pytest.mark.order(2)
async def test_follow_up(test_client):
    await test_client.send("What's the weather like?")
    # This test depends on the previous interaction
```

## Multi-Agent Testing

Test CLI applications with multiple agents:

```python
@pytest.mark.order(1)
async def test_agent_switching(test_client):
    # Switch to general agent
    await test_client.send("!select general")
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect("Sri Lanka won the 1996 Cricket World Cup.")

@pytest.mark.order(2)
async def test_different_agent(test_client):
    # Test continues with the same session
    await test_client.send("Which countries hosted the tournament?")
    await test_client.expect("Co-hosted by India, Pakistan and Sri Lanka.")
```

## API Testing

For testing API endpoints alongside CLI agents:

```python
import asyncio
import subprocess
import sys
import pytest
import pytest_asyncio
from agentkernel.test import Test, Mode

@pytest_asyncio.fixture(scope="session")
async def api_server():
    # Start the API server
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(15)  # Wait for server to start
    
    try:
        yield "http://127.0.0.1:8000"
    finally:
        proc.terminate()
        proc.wait()

@pytest.mark.asyncio
async def test_api_endpoint(api_server):
    # Test API responses using the Test.compare method
    response = await make_api_call(api_server, "Who won the 1996 cricket world cup?")
    Test.compare(
        actual=response,
        expected=["Sri Lanka won the 1996 cricket world cup"],
        user_input="Who won the 1996 cricket world cup?",
        mode=Mode.LLM  # Use llm mode for API testing
    )
```

## Container Testing

Test containerized applications:

```python
import shutil
import subprocess
import httpx
import pytest

@pytest_asyncio.fixture(scope="session")
async def container_client():
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    
    image = "yaalalabs/ak-openai-demo:latest"
    port = 8000
    
    cmd = [
        "docker", "run", "--rm",
        "-e", f"OPENAI_API_KEY={os.environ.get('OPENAI_API_KEY')}",
        "-p", f"{port}:8000",
        image
    ]
    
    proc = subprocess.Popen(cmd)
    await asyncio.sleep(30)  # Wait for container to start
    
    try:
        yield f"http://localhost:{port}"
    finally:
        proc.terminate()
        proc.wait()
```

## Running Tests

### Basic Test Execution

```bash
# Run all tests
pytest

# Run specific test file
pytest test_demo.py

# Run with verbose output
pytest -v

# Run tests in parallel
pytest -n auto
```

### CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Agent Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: |
          pip install pytest pytest-asyncio pytest-order
          pip install -r requirements.txt
      
      - name: Run tests
        run: pytest tests/ -v
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## Test Configuration

### Test Mode Configuration

Configure the default test comparison mode in `test-config.yaml`. The file is resolved from the current working directory, or from the path in the `AK_TEST_CONFIG_PATH_OVERRIDE` environment variable. It is only loaded when the test harness runs; the application's `config.yaml` no longer carries a `test:` section (a leftover one is ignored):

```yaml
# test-config.yaml
mode: fallback  # Options: score, llm, fallback (default: fallback)
evaluator: deepeval  # Built-in short name ('deepeval' or 'opik'), or a dotted path to your own AKEvaluator subclass
llm:
  model: gpt-4o-mini  # LLM model for llm mode
  provider: openai  # LLM provider
  embedding_model: text-embedding-3-small  # Embedding model
```

Or via environment variables:

```bash
export AK_TEST__MODE=llm
export AK_TEST__LLM__MODEL=gpt-4o-mini
export AK_TEST__LLM__PROVIDER=openai
export AK_TEST__LLM__EMBEDDING_MODEL=text-embedding-3-small
```

### Custom Match Thresholds

Configure score matching for different test scenarios, on the `[0.0, 1.0]` scale:

```python
# More strict matching for exact responses
strict_test = Test("demo.py", match_threshold=0.9)

# More lenient for AI-generated content
lenient_test = Test("demo.py", match_threshold=0.6)
```

### Environment Variables

Set up test-specific environment variables:

```python
import os

@pytest.fixture(autouse=True)
def setup_test_env():
    os.environ["TEST_MODE"] = "true"
    os.environ["LOG_LEVEL"] = "DEBUG"
    yield
    # Cleanup after test
    del os.environ["TEST_MODE"]
```

## Best Practices

### Test Organization
- Group related tests in the same file
- Use descriptive test names
- Implement proper setup and teardown

### Assertions
- Use `Mode.SCORE` for exact string matching requirements
- Use `Mode.LLM` for semantic similarity validation
- Use `Mode.FALLBACK` (default) for robust validation
- Test both positive and negative cases
- Include edge cases and error conditions

### Test Mode Selection
- **Score Mode**: Best for deterministic outputs, exact formatting requirements
- **Llm Mode**: Best for AI-generated content, paraphrased responses
- **Fallback Mode**: Best for general use, provides flexibility

### Performance
- Use session-scoped fixtures for expensive setup
- Consider parallel test execution for independent tests
- Mock external dependencies when possible
- Note: Llm mode requires LLM calls, which may slow tests

### Maintenance
- Keep tests updated with agent changes
- Use version control for test scenarios
- Document test requirements and expectations
- Configure the llm model/provider based on your needs

## Troubleshooting

### Common Issues

**Tests hanging indefinitely:**
- Ensure CLI application doesn't require manual input
- Check for proper async/await usage
- Verify timeout settings

**Score matching failures:**
- Adjust match threshold based on response variability
- Check for extra whitespace or formatting
- Consider using `Mode.LLM` for AI-generated content
- Use Test.compare() for debugging

**Llm mode failures:**
- Ensure LLM API keys are configured (e.g., OPENAI_API_KEY)
- Check the llm configuration (model, provider, embedding_model)
- Verify threshold is appropriate (`[0.0, 1.0]` range)
- Ensure `expected` is provided — llm mode has no reference-free fallback

**Process cleanup issues:**
- Always use try-finally blocks
- Ensure subprocess termination
- Check for port conflicts in API tests

### Debug Mode

Enable debug output for troubleshooting:

Agent Kernel configures logging when the application loads its configuration (on first access, not at import). These settings apply to the application under test; set them in its environment or `config.yaml`:

**Using environment variables:**
```bash
export AK_LOGGING__AK__LEVEL=DEBUG  # Agent Kernel logger level
export AK_LOGGING__SYSTEM__LEVEL=DEBUG  # System/root logger level
```

**Using config.yaml:**
```yaml
logging:
  ak:
    level: DEBUG
  system:
    level: DEBUG
```

Or use pytest verbose output:
```bash
pytest -v -s test_file.py
```
