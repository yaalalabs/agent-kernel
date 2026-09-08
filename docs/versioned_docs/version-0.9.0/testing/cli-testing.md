---
sidebar_position: 2
---

# CLI Testing

Interactive testing of CLI agents using the Agent Kernel Test framework.

## Test Class Overview

The `Test` class provides programmatic interaction with CLI agents:

```python
from agentkernel.test import Test, Mode

# Initialize test with CLI script path
test = Test("demo.py", match_threshold=0.5, mode=Mode.FALLBACK)
```

### Parameters
- `path`: Path to the Python CLI script (relative to current working directory)
- `match_threshold`: Matching threshold in the `[0.0, 1.0]` range (default: 0.5)
- `mode`: Test comparison mode - `Mode.SCORE`, `Mode.LLM`, or `Mode.FALLBACK`. If None, uses config value (default: None)

## Basic Usage

### Starting a Test Session

```python
import asyncio
from agentkernel.test import Test

async def run_test():
    test = Test("demo.py")
    await test.start()
    
    # Your test interactions here
    
    await test.stop()

# Run the test
asyncio.run(run_test())
```

### Sending Messages and Expecting Responses

```python
# Send a message to the CLI
response = await test.send("Who won the 1996 cricket world cup?")

# Verify the response using deterministic score matching
await test.expect(["Sri Lanka won the 1996 cricket world cup."])
```

## Test Comparison Modes

Agent Kernel supports three comparison modes for validating responses. Each mode maps to a
method on the configured `AKEvaluator` — see "Bring your own evaluator" below for the pluggable
interface.

### Score Mode

Deterministic, offline string-match scoring — no LLM call. The built-in evaluator (DeepEval)
uses `Scorer.quasi_exact_match_score`, a normalised whole-string equality check:

```python
from agentkernel.test import Test, Mode

# Initialize with score mode
test = Test("demo.py", match_threshold=0.8, mode=Mode.SCORE)

# Or use static comparison with multiple expected answers
await test.send("Who won the 1996 cricket world cup?")
Test.compare(
    actual=test.last_agent_response,
    expected=[
        "Sri Lanka won the 1996 cricket world cup",
        "Sri Lanka won the 1996 world cup",
        "The 1996 cricket world cup was won by Sri Lanka"
    ],
    threshold=0.8,
    mode=Mode.SCORE
)
```

**Note:** The `expected` parameter is a list. The test passes if the actual response's normalised
text exactly equals **any** of the expected values (score `1.0`); otherwise it scores `0.0` —
there is no partial credit, so a verbose-but-correct response that merely contains the expected
phrase does not match under score mode alone.

### Llm Mode

Uses LLM-as-judge evaluation for semantic similarity. The built-in evaluator (DeepEval) uses the
`GEval` metric, judging whether the actual response conveys the same information as the expected
answer. The rubric is written to give credit when `expected` is a short phrase or keyword embedded
in a longer, otherwise-correct response — llm mode (and the llm fallback in `fallback` mode) is the
intended way to match the verbose-but-correct case that score mode's exact match rejects:

```python
# Initialize with llm mode
test = Test("demo.py", mode=Mode.LLM)

# Use llm evaluation with multiple expected answers
await test.send("Who won the 1996 cricket world cup?")
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

**Llm Mode Behavior:** Compares the actual response against each expected answer (ground truth)
using an LLM rubric. Test passes if **any** comparison scores above the threshold. Unlike the
old judge mode, `expected` is required — there is no reference-free relevancy fallback.

**Note:** When multiple expected answers are provided, the test evaluates each one and passes if
**any** meets the threshold.

### Fallback Mode (Default)

Tries score matching first, falls back to llm evaluation if score fails:

```python
# Default fallback mode with multiple expected answers
test = Test("demo.py", mode=Mode.FALLBACK)

await test.send("Who won the 1996 cricket world cup?")
Test.compare(
    actual=test.last_agent_response,
    expected=[
        "Sri Lanka",
        "Sri Lanka won the 1996 cricket world cup",
        "The winner was Sri Lanka"
    ],
    user_input="Who won the 1996 cricket world cup?",
    threshold=0.5
)
```

**Note:** The `expected` parameter is a list of acceptable responses. Score matching is tried
against each expected value first. If all fail, llm evaluation is attempted against each expected
answer.

### Configuration-Based Mode

Set default mode via a `test-config.yaml` file (in the directory the tests run from, or the path in `AK_TEST_CONFIG_PATH_OVERRIDE`) instead of the constructor. Test configuration is separate from the application's `config.yaml` and is only loaded when the test harness runs:

```yaml
# test-config.yaml
mode: llm  # Options: score, llm, fallback
evaluator: deepeval  # Built-in short name, or a dotted path to your own AKEvaluator subclass
llm:
  model: gpt-4o-mini
  provider: openai
  embedding_model: text-embedding-3-small
```

```python
# Uses mode from config
test = Test("demo.py")
await test.send("Hello")
await test.expect(["Hello! How can I help?"])  # Uses configured mode
```

### Bring your own evaluator

Any dotted path to an `AKEvaluator` subclass works as `evaluator` in `test-config.yaml`:

```yaml
evaluator: my_evaluator.MyEvaluator   # resolves against my_evaluator.py next to your test file
```

Implement `score_based_evaluation(case)` and `llm_based_evaluation(case)`, both synchronous,
returning `AKEvaluationResult`. Raise `AKMetricNotSupported` from a method your backend can't
provide, and `AKEvaluationError` on a backend failure (missing credentials, transport error) —
never return a `0.0` for either. See `agentkernel.test.core.akevaluators` for the interface and
payload models, and [`examples/cli/custom-evaluator`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/custom-evaluator)
for a complete working example (a stdlib-only token-overlap scorer plus a raw `litellm` judge, no
DeepEval dependency at all).

## Advanced Features

### Custom Matching Configuration

```python
# Set threshold and mode during initialization
test = Test("demo.py", match_threshold=0.8, mode=Mode.SCORE)

# Or use static comparison with custom parameters
Test.compare(
    actual=response,
    expected=["Expected response"],
    user_input="User question",
    threshold=0.7,
    mode=Mode.LLM
)
```

### Accessing Latest Response

```python
await test.send("Hello!")
latest_response = test.latest  # Contains the cleaned response without ANSI codes
```

### Prompt Detection

The Test class automatically detects CLI prompts using regex patterns:
- Captures prompts in format: `(agent_name) >> `
- Handles prompt changes during agent switching
- Strips ANSI escape sequences from responses

## Multi-Agent CLI Testing

For CLI applications with multiple agents:

```python
# Switch to a specific agent
await test.send("!select general")
await test.send("Who won the 1996 cricket world cup?")
await test.expect("Sri Lanka won the 1996 Cricket World Cup.")

# Switch to another agent
await test.send("!select math")
await test.send("What is 2 + 2?")
await test.expect("4")
```

## Error Handling

### Assertion Errors

```python
try:
    await test.expect("Expected response")
except AssertionError as e:
    print(f"Test failed: {e}")
    # The error includes both expected and actual responses
```

### Process Management

```python
# Ensure proper cleanup even if tests fail
test = Test("demo.py")
try:
    await test.start()
    # Your test code here
finally:
    await test.stop()  # Always stop the process
```

## Best Practices

### Development Testing
- Use interactive mode during development for quick validation
- Test edge cases and error conditions
- Verify agent switching functionality

### Test Mode Selection
- Use `Mode.SCORE` for deterministic, exact outputs
- Use `Mode.LLM` for AI-generated content with paraphrasing
- Use `Mode.FALLBACK` (default) for robust validation

### Response Validation
- Use appropriate score thresholds (0.5-0.8 typical, on the `[0.0, 1.0]` scale)
- Provide `user_input` when using llm mode for better evaluation
- Test with variations in expected responses
- Account for slight differences in AI model outputs

### Session Management
- Always call `start()` before sending messages
- Always call `stop()` to clean up processes
- Use try-finally blocks for proper cleanup

### Llm Mode Configuration
- Configure the llm model/provider via `test-config.yaml` or environment variables
- Ensure LLM API keys are set (e.g., OPENAI_API_KEY)
- Note: Llm mode requires LLM calls which may slow down tests

## Example Test Session

```python
import asyncio
from agentkernel.test import Test

async def test_cricket_knowledge():
    test = Test("demo.py", match_threshold=0.6)
    
    try:
        await test.start()
        
        # Test basic question - expected is a list
        await test.send("Who won the 1996 cricket world cup?")
        await test.expect(["Sri Lanka won the 1996 cricket world cup."])
        
        # Test follow-up question with multiple acceptable answers
        await test.send("Which country hosted the tournament?")
        await test.expect([
            "Co-hosted by India, Pakistan and Sri Lanka.",
            "India, Pakistan and Sri Lanka co-hosted the tournament."
        ])
        
        print("All tests passed!")
        
    finally:
        await test.stop()

if __name__ == "__main__":
    asyncio.run(test_cricket_knowledge())
```

### Session Persistence

Each CLI session maintains conversation history:

```
> My name is Alice
[general] Nice to meet you, Alice!

> What's my name?
[general] Your name is Alice.
```

### Debug Mode

Enable verbose logging:

```bash
export AK_LOGGING__AK__LEVEL=DEBUG
python my_agent.py
```

### Multi-turn Conversations

Test complex interactions:

```
> I need help with a project
[general] I'd be happy to help! What's your project about?

> It's about machine learning
[general] Great! What specific aspect of machine learning?

> Image classification
[general] Image classification is a common ML task...
```

## Commands

Available CLI commands:

- `!h`, `!help`: Show help message
- `!ld`, `!load <module_name>`: Load agent module
- `!ls`, `!list`: List available agents
- `!n`, `!new`: Start a new session
- `!c`, `!clear`: Clear the current session memory
- `!s`, `!select <agent_name>`: Select an agent to run the prompt
- `!q`, `!quit`: Exit the program

## Tips

- Test edge cases interactively
- Verify agent handoffs work correctly
- Check conversation context is maintained
- Test error scenarios
- Validate tool integrations

## Example Session

```
$ python my_agent.py

AgentKernel CLI (type !help for commands or !quit to exit):
Available agents:
  research
  write
  review

(research) >> !help
Available commands:
!h, !help - Show this help message
!ld, !load <module_name> - Load agent module
!ls, !list - List available agents
!n, !new - Start a new session
!c, !clear - Clear the current session memory
!s, !select <agent_name> - Select an agent to run the prompt
!q, !quit - Exit the program

(research) >> !ls
Available agents:
  research
  write
  review

(research) >> Find information about Python
Here's what I found about Python...

(research) >> !select write
(write) >> I'll help you create a summary...

(write) >> Great, can you review it?
I'll help you create a summary of the Python information...

(write) >> !select review
(review) >> Here's my review of the content...

(review) >> !new
(review) >> This is a new session now
How can I help you in this new session?

(review) >> !quit
```
