---
sidebar_position: 1
---

# Testing Overview

Agent Kernel provides a comprehensive testing framework for testing CLI-based agents with both interactive and automated test capabilities.

## Testing Approaches

```mermaid
graph LR
    A[Testing] --> B[CLI Testing]
    A --> C[Automated Testing]
    A --> D[API Testing]
    
    B --> E[Interactive Development]
    C --> F[pytest Integration]
    D --> G[HTTP/A2A Testing]
```

## CLI Testing

Interactive testing of CLI agents using the `Test` class:

```python
from agentkernel.test import Test

# Create a test instance
test = Test("demo.py")
await test.start()

# Send messages and verify responses
await test.send("Who won the 1996 cricket world cup?")
await test.expect("Sri Lanka won the 1996 cricket world cup.")

await test.stop()
```

Best for:
- Development and debugging
- Interactive exploration
- Quick validation of agent responses

[Learn more →](./cli-testing)

## Automated Testing

pytest-based testing with async support:

```python
import pytest
import pytest_asyncio
from agentkernel.test import Test

@pytest_asyncio.fixture(scope="session")
async def test_client():
    test = Test("demo.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

@pytest.mark.asyncio
async def test_basic_question(test_client):
    await test_client.send("Hello!")
    await test_client.expect("Hello! How can I help you?")
```

Best for:
- Regression testing
- CI/CD pipelines
- Validation before deployment

[Learn more →](./automated-testing)

## Testing Framework Features

### Test Comparison Modes

Agent Kernel supports three comparison modes for validating agent responses:

#### Score Mode
Deterministic, offline string-match scoring (via DeepEval's `Scorer.quasi_exact_match_score`) with configurable thresholds:

```python
from agentkernel.test import Test, Mode

# Use score mode only
test = Test("demo.py", match_threshold=0.8)
await test.send("Who won the 1996 cricket world cup?")

# expected is a list - test passes if ANY match exceeds threshold
Test.compare(
    actual=test.last_agent_response,
    expected=["Sri Lanka won", "Sri Lanka won the 1996 cricket world cup"],
    threshold=0.8,
    mode=Mode.SCORE
)
```

**Note:** The `expected` parameter is a list. The test passes if the actual response's normalised text exactly equals **any** of the expected values (score `1.0`) — there is no partial credit.

#### Llm Mode
Uses LLM-as-judge evaluation (via DeepEval's `GEval`) for semantic similarity:

```python
# Use llm mode only - expected is a list
Test.compare(
    actual=test.last_agent_response,
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

**Note:** The `expected` parameter is a list. The test passes if the actual response has semantic similarity above the threshold with **any** of the expected answers.

`expected` is required in llm mode — `GEval` judges whether the actual response conveys the same information as each expected answer; there is no reference-free relevancy fallback.

#### Fallback Mode (Default)
Tries score matching first, falls back to llm evaluation if score fails:

```python
# Default fallback mode - multiple expected answers
Test.compare(
    actual=test.last_agent_response,
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

**Note:** The `expected` parameter is a list of acceptable responses. The test passes if **any** expected value matches (score or llm evaluation).

### Configuring Test Mode

Set the default test mode via a `test-config.yaml` file in the directory you run the tests from. Test configuration is separate from the application's `config.yaml` and is only loaded when the test harness runs (a `test:` section in `config.yaml` is ignored):

```yaml
# test-config.yaml
mode: fallback  # Options: score, llm, fallback
evaluator: deepeval  # Built-in short name, or a dotted path to your own AKEvaluator subclass
llm:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```

Use `AK_TEST_CONFIG_PATH_OVERRIDE` to load the file from a different path:

```bash
export AK_TEST_CONFIG_PATH_OVERRIDE=/path/to/test-config.yaml
```

Or via environment variables:

```bash
export AK_TEST__MODE=llm
export AK_TEST__LLM__MODEL=gpt-4o-mini
export AK_TEST__LLM__PROVIDER=openai
export AK_TEST__LLM__EMBEDDING_MODEL=text-embedding-3-small
```

### Session Management
Tests maintain persistent CLI sessions with proper prompt handling and ANSI escape sequence cleanup.

### Multi-Agent Support
Test different agent types within the same CLI application:

```python
await test.send("!select general")  # Switch to general agent
await test.send("Who won the 1996 cricket world cup?")
```

## Best Practices

- Use pytest fixtures for test setup and teardown
- Implement ordered tests for conversation flows
- Configure appropriate score matching thresholds
- Test agent selection commands when using multi-agent setups
- Include both positive and negative test cases
- Test session persistence and state management
