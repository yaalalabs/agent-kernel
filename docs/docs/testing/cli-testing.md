---
sidebar_position: 2
---

# CLI Testing

Interactive testing using the built-in CLI.

## Starting CLI

```python
from agentkernel.cli import CLI

if __name__ == "__main__":
    CLI.main()
```

Run:

```bash
python my_agent.py
```

## CLI Interface

```
Agent Kernel CLI
Available agents:
  - general
  - math
  - code

Type your message (or 'quit' to exit):
> Hello!

[general] Hi! How can I help you today?

> What is 2 + 2?

[math] 2 + 2 = 4

> quit
Goodbye!
```

## Features

### Agent Selection

CLI automatically routes to appropriate agent or lets you choose:

```
> @math What is 5 + 3?
[math] 5 + 3 = 8
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
