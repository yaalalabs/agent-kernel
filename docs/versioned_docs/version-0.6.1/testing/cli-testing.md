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
test = Test("demo.py", match_threshold=50, mode=Mode.FALLBACK)
```

### Parameters
- `path`: Path to the Python CLI script (relative to current working directory)
- `match_threshold`: Fuzzy matching threshold percentage (default: 50)
- `mode`: Test comparison mode - `Mode.FUZZY`, `Mode.JUDGE`, or `Mode.FALLBACK`. If None, uses config value (default: None)

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

# Verify the response using fuzzy matching
await test.expect(["Sri Lanka won the 1996 cricket world cup."])
```

## Test Comparison Modes

Agent Kernel supports three comparison modes for validating responses:

### Fuzzy Mode

Uses fuzzy string matching with configurable thresholds:

```python
from agentkernel.test import Test, Mode

# Initialize with fuzzy mode
test = Test("demo.py", match_threshold=80, mode=Mode.FUZZY)

# Or use static comparison with multiple expected answers
await test.send("Who won the 1996 cricket world cup?")
Test.compare(
    actual=test.last_agent_response,
    expected=[
        "Sri Lanka won the 1996 cricket world cup",
        "Sri Lanka won the 1996 world cup",
        "The 1996 cricket world cup was won by Sri Lanka"
    ],
    threshold=80,
    mode=Mode.FUZZY
)
```

**Note:** The `expected` parameter is a list. The test passes if the actual response fuzzy-matches **any** of the expected values above the threshold.

### Judge Mode

Uses LLM-based evaluation (Ragas) for semantic similarity:

```python
# Initialize with judge mode
test = Test("demo.py", mode=Mode.JUDGE)

# Use judge evaluation with multiple expected answers
await test.send("Who won the 1996 cricket world cup?")
Test.compare(
    actual=test.last_agent_response,
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

**Judge Mode Behavior:**
- With expected answers: Uses `answer_similarity` metric to compare against each expected answer (ground truth). Test passes if **any** similarity score exceeds threshold.
- Without expected answers: Uses `answer_relevancy` metric to check if answer is relevant to the question

**Note:** When multiple expected answers are provided, the test evaluates semantic similarity against each one and passes if **any** meets the threshold.

### Fallback Mode (Default)

Tries fuzzy matching first, falls back to judge evaluation if fuzzy fails:

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
    threshold=50
)
```

**Note:** The `expected` parameter is a list of acceptable responses. Fuzzy matching is tried against each expected value first. If all fail, judge evaluation is attempted against each expected answer.

### Configuration-Based Mode

Set default mode via configuration instead of constructor:

```yaml
# config.yaml
test:
  mode: judge  # Options: fuzzy, judge, fallback
  judge:
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

## Advanced Features

### Custom Matching Configuration

```python
# Set threshold and mode during initialization
test = Test("demo.py", match_threshold=80, mode=Mode.FUZZY)

# Or use static comparison with custom parameters
Test.compare(
    actual=response,
    expected=["Expected response"],
    user_input="User question",
    threshold=70,
    mode=Mode.JUDGE
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
- Use `Mode.FUZZY` for deterministic, exact outputs
- Use `Mode.JUDGE` for AI-generated content with paraphrasing
- Use `Mode.FALLBACK` (default) for robust validation

### Response Validation
- Use appropriate fuzzy matching thresholds (50-80% typical)
- Provide `user_input` when using judge mode for better evaluation
- Test with variations in expected responses
- Account for slight differences in AI model outputs

### Session Management
- Always call `start()` before sending messages
- Always call `stop()` to clean up processes
- Use try-finally blocks for proper cleanup

### Judge Mode Configuration
- Configure judge model/provider via `config.yaml` or environment variables
- Ensure LLM API keys are set (e.g., OPENAI_API_KEY)
- Note: Judge mode requires LLM calls which may slow down tests

## Example Test Session

```python
import asyncio
from agentkernel.test import Test

async def test_cricket_knowledge():
    test = Test("demo.py", match_threshold=60)
    
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

- `!h`, `!help` — Show help message
- `!ld`, `!load <module_name>` — Load agent module
- `!ls`, `!list` — List available agents
- `!n`, `!new` — Start a new session
- `!c`, `!clear` — Clear the current session memory
- `!s`, `!select <agent_name>` — Select an agent to run the prompt
- `!q`, `!quit` — Exit the program

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
