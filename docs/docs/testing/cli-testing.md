---
sidebar_position: 2
---

# CLI Testing

Interactive testing of CLI agents using the Agent Kernel Test framework.

## Test Class Overview

The `Test` class provides programmatic interaction with CLI agents:

```python
from agentkernel.test import Test

# Initialize test with CLI script path
test = Test("demo.py", match_threshold=50)
```

### Parameters
- `path`: Path to the Python CLI script (relative to current working directory)
- `match_threshold`: Fuzzy matching threshold percentage (default: 50)

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
await test.expect("Sri Lanka won the 1996 cricket world cup.")
```

## Advanced Features

### Custom Matching Thresholds

```python
# Set threshold during initialization
test = Test("demo.py", match_threshold=80)

# Or use static comparison with custom threshold
Test.compare(actual_response, expected_response, threshold=70)
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

### Response Validation
- Use appropriate fuzzy matching thresholds
- Test with variations in expected responses
- Account for slight differences in AI model outputs

### Session Management
- Always call `start()` before sending messages
- Always call `stop()` to clean up processes
- Use try-finally blocks for proper cleanup

## Example Test Session

```python
import asyncio
from agentkernel.test import Test

async def test_cricket_knowledge():
    test = Test("demo.py", match_threshold=60)
    
    try:
        await test.start()
        
        # Test basic question
        await test.send("Who won the 1996 cricket world cup?")
        await test.expect("Sri Lanka won the 1996 cricket world cup.")
        
        # Test follow-up question
        await test.send("Which country hosted the tournament?")
        await test.expect("Co-hosted by India, Pakistan and Sri Lanka.")
        
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
export AK_LOG_LEVEL=DEBUG
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

- `quit` or `exit`: Exit CLI
- `clear`: Clear screen
- `agents`: List available agents
- `@agent_name message`: Direct message to specific agent

## Tips

- Test edge cases interactively
- Verify agent handoffs work correctly
- Check conversation context is maintained
- Test error scenarios
- Validate tool integrations

## Example Session

```
$ python my_agent.py

Agent Kernel CLI
Available agents:
  - research
  - write
  - review

> @research Find information about Python
[research] Here's what I found about Python...
[research transferred to write]

[write] I'll help you create a summary...

> Great, can you review it?
[write transferred to review]

[review] Here's my review of the content...

> quit
Goodbye!
```
