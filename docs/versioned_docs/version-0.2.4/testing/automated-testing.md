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
    await test_client.expect("Sri Lanka won the 1996 cricket world cup.")

@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("Which country hosted the tournament?")
    await test_client.expect("Co-hosted by India, Pakistan and Sri Lanka.")
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
from agentkernel.test import Test

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
    Test.compare(response, "Sri Lanka won the 1996 cricket world cup.")
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
- Use appropriate fuzzy matching thresholds
- Test both positive and negative cases
- Include edge cases and error conditions

### Performance
- Use session-scoped fixtures for expensive setup
- Consider parallel test execution for independent tests
- Mock external dependencies when possible

### Maintenance
- Keep tests updated with agent changes
- Use version control for test scenarios
- Document test requirements and expectations

## Troubleshooting

### Common Issues

**Tests hanging indefinitely:**
- Ensure CLI application doesn't require manual input
- Check for proper async/await usage
- Verify timeout settings

**Fuzzy matching failures:**
- Adjust match threshold based on response variability
- Check for extra whitespace or formatting
- Consider using Test.compare() for debugging

**Process cleanup issues:**
- Always use try-finally blocks
- Ensure subprocess termination
- Check for port conflicts in API tests

### Debug Mode

Enable debug output for troubleshooting:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or use pytest verbose output
pytest -v -s test_file.py
```
