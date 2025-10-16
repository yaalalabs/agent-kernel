---
sidebar_position: 3
---

# Automated Testing

Create automated test scenarios for your agents.

## Test Framework

```python
from agentkernel.test import TestRunner

runner = TestRunner("my_agent.py")
results = runner.run_tests("test_scenarios.yaml")

if results.all_passed:
    print("All tests passed!")
else:
    print(f"Failed: {results.failed_count}")
```

## Test Scenarios File

`test_scenarios.yaml`:

```yaml
scenarios:
  - name: "Basic greeting"
    agent: "assistant"
    inputs:
      - message: "Hello!"
    expectations:
      - contains: ["hello", "hi", "greetings"]
      - not_contains: ["error"]
  
  - name: "Math calculation"
    agent: "math"
    inputs:
      - message: "What is 15 + 27?"
    expectations:
      - contains: ["42"]
      - response_time_ms: 5000
  
  - name: "Multi-turn conversation"
    agent: "assistant"
    session_id: "test-session-1"
    inputs:
      - message: "My favorite color is blue"
      - message: "What is my favorite color?"
    expectations:
      - contains: ["blue"]
```

## Expectations

### String Matching

```yaml
expectations:
  - contains: ["keyword1", "keyword2"]
  - not_contains: ["error", "fail"]
  - exact: "Exact expected response"
  - regex: "\\d+ \\+ \\d+ = \\d+"
```

### Response Time

```yaml
expectations:
  - response_time_ms: 5000  # Max 5 seconds
```

### Status

```yaml
expectations:
  - status: "success"  # or "error"
```

## Running Tests

### Command Line

```bash
ak-test --scenarios test_scenarios.yaml --agent my_agent.py
```

### Python Script

```python
from agentkernel.test import TestRunner

runner = TestRunner("my_agent.py")
results = runner.run_tests("test_scenarios.yaml")

for result in results.scenarios:
    print(f"{result.name}: {'PASS' if result.passed else 'FAIL'}")
    if not result.passed:
        print(f"  Reason: {result.failure_reason}")
```

### CI/CD Integration

```yaml
# GitHub Actions
name: Test Agents
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: pip install agentkernel[test]
      - name: Run tests
        run: ak-test --scenarios tests/scenarios.yaml
```

## Test Reports

Generate test reports:

```bash
ak-test --scenarios test_scenarios.yaml --report html --output report.html
```

## Advanced Testing

### Setup/Teardown

```yaml
setup:
  - clear_sessions
  - initialize_data

scenarios:
  # ... your tests

teardown:
  - cleanup_data
```

### Mocking

```python
from agentkernel.test import mock_llm_response

@mock_llm_response("Mocked response")
def test_agent():
    # Test with mocked LLM
    pass
```

### Parallel Execution

```bash
ak-test --scenarios test_scenarios.yaml --parallel 4
```

## Best Practices

- Test critical user flows
- Include edge cases
- Test error handling
- Use meaningful test names
- Keep scenarios simple
- Run tests in CI/CD
- Monitor test performance
- Update tests with changes

## Example Test Suite

```yaml
name: "Agent Test Suite"
version: "1.0"

setup:
  - clear_sessions

scenarios:
  - name: "Greeting"
    agent: "assistant"
    inputs:
      - message: "Hi"
    expectations:
      - contains: ["hello", "hi"]
  
  - name: "Math"
    agent: "math"
    inputs:
      - message: "10 + 5"
    expectations:
      - contains: ["15"]
  
  - name: "Context retention"
    agent: "assistant"
    session_id: "context-test"
    inputs:
      - message: "Remember: my ID is 12345"
      - message: "What is my ID?"
    expectations:
      - contains: ["12345"]
  
  - name: "Error handling"
    agent: "assistant"
    inputs:
      - message: "!!invalid!!"
    expectations:
      - status: "success"
      - not_contains: ["exception", "traceback"]

teardown:
  - clear_sessions
```
