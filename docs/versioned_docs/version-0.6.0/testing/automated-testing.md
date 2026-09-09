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

### Fuzzy Mode

Uses fuzzy string matching with configurable thresholds:

```python
from agentkernel.test import Test, Mode

@pytest.mark.order(1)
async def test_fuzzy_matching(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Use fuzzy mode with 80% threshold
    # expected is a list - test passes if ANY match exceeds threshold
    Test.compare(
        actual=test_client.last_agent_response,
        expected=[
            "Sri Lanka won the 1996 cricket world cup",
            "Sri Lanka won the 1996 world cup",
            "The 1996 cricket world cup was won by Sri Lanka"
        ],
        threshold=80,
        mode=Mode.FUZZY
    )
```

**Note:** The `expected` parameter accepts a list of acceptable responses. The test passes if the actual response matches **any** of the expected values above the threshold.

### Judge Mode

Uses LLM-based evaluation (Ragas) for semantic similarity:

```python
@pytest.mark.order(2)
async def test_judge_evaluation(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Use judge mode for semantic evaluation
    # expected is a list - test passes if ANY has sufficient semantic similarity
    Test.compare(
        actual=test_client.last_agent_response,
        expected=[
            "Sri Lanka won the 1996 cricket world cup",
            "Sri Lanka was the winner of the 1996 world cup",
            "The 1996 cricket world cup was won by Sri Lanka"
        ],
        user_input="Who won the 1996 cricket world cup?",
        threshold=50,  # Converted to 0.5 on 0.0-1.0 scale
        mode=Mode.JUDGE
    )
```

**Judge Mode Metrics:**
- With expected answers: Uses `answer_similarity` metric against each expected answer. Passes if **any** exceeds threshold.
- Without expected answers: Uses `answer_relevancy` metric (requires `user_input`)

**Note:** When multiple expected answers are provided, the judge evaluates similarity against each one and passes if **any** score meets the threshold.

### Fallback Mode (Default)

Tries fuzzy matching first, falls back to judge evaluation:

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
        threshold=50,
        mode=Mode.FALLBACK  # or None to use config default
    )
```

**Note:** With multiple expected answers, fuzzy mode tries each one and passes if **any** match exceeds the threshold. If all fuzzy matches fail, judge mode evaluates against each expected answer.

### Configuring Test Mode

Set the default mode via configuration:

```yaml
# config.yaml
test:
  mode: fallback  # Options: fuzzy, judge, fallback
  judge:
    model: gpt-4o-mini
    provider: openai
    embedding_model: text-embedding-3-small
```

Or environment variables:

```bash
export AK_TEST__MODE=judge
export AK_TEST__JUDGE__MODEL=gpt-4o-mini
export AK_TEST__JUDGE__PROVIDER=openai
export AK_TEST__JUDGE__EMBEDDING_MODEL=text-embedding-3-small
```

### Using expect() with Mode

The `expect()` method uses the configured mode:

```python
@pytest.mark.order(1)
async def test_with_expect(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    # Uses mode from AKConfig.get().test.mode
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
    test = Test("demo.py", match_threshold=70)
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
        mode=Mode.JUDGE  # Use judge mode for API testing
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

Configure the default test comparison mode:

```yaml
# config.yaml
test:
  mode: fallback  # Options: fuzzy, judge, fallback (default: fallback)
  judge:
    model: gpt-4o-mini  # LLM model for judge mode
    provider: openai  # LLM provider
    embedding_model: text-embedding-3-small  # Embedding model
```

Or via environment variables:

```bash
export AK_TEST__MODE=judge
export AK_TEST__JUDGE__MODEL=gpt-4o-mini
export AK_TEST__JUDGE__PROVIDER=openai
export AK_TEST__JUDGE__EMBEDDING_MODEL=text-embedding-3-small
```

### Custom Match Thresholds

Configure fuzzy matching for different test scenarios:

```python
# More strict matching for exact responses
strict_test = Test("demo.py", match_threshold=90)

# More lenient for AI-generated content
lenient_test = Test("demo.py", match_threshold=60)
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
- Use `Mode.FUZZY` for exact string matching requirements
- Use `Mode.JUDGE` for semantic similarity validation
- Use `Mode.FALLBACK` (default) for robust validation
- Test both positive and negative cases
- Include edge cases and error conditions

### Test Mode Selection
- **Fuzzy Mode**: Best for deterministic outputs, exact formatting requirements
- **Judge Mode**: Best for AI-generated content, paraphrased responses
- **Fallback Mode**: Best for general use, provides flexibility

### Performance
- Use session-scoped fixtures for expensive setup
- Consider parallel test execution for independent tests
- Mock external dependencies when possible
- Note: Judge mode requires LLM calls, which may slow tests

### Maintenance
- Keep tests updated with agent changes
- Use version control for test scenarios
- Document test requirements and expectations
- Configure judge model/provider based on your needs

## Troubleshooting

### Common Issues

**Tests hanging indefinitely:**
- Ensure CLI application doesn't require manual input
- Check for proper async/await usage
- Verify timeout settings

**Fuzzy matching failures:**
- Adjust match threshold based on response variability
- Check for extra whitespace or formatting
- Consider using `Mode.JUDGE` for AI-generated content
- Use Test.compare() for debugging

**Judge mode failures:**
- Ensure LLM API keys are configured (e.g., OPENAI_API_KEY)
- Check judge configuration (model, provider, embedding_model)
- Verify threshold is appropriate (0-100 range, converted to 0.0-1.0)
- Ensure `user_input` is provided when using answer_relevancy

**Process cleanup issues:**
- Always use try-finally blocks
- Ensure subprocess termination
- Check for port conflicts in API tests

### Debug Mode

Enable debug output for troubleshooting:

Agent Kernel auto-configures logging on import. To enable debug logging, use environment variables or configuration files:

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
