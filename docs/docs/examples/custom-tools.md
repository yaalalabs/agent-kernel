---
sidebar_position: 3
---

# Custom Tools Example

Integrate custom tools with your agents.

## Complete Code

```python
from crewai import Agent as CrewAgent, Tool
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule
import requests

# Define custom tools
def search_wikipedia(query: str) -> str:
    """Search Wikipedia for information"""
    try:
        response = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + query
        )
        data = response.json()
        return data.get("extract", "No information found")
    except Exception as e:
        return f"Error: {str(e)}"

def calculate(expression: str) -> str:
    """Evaluate a mathematical expression"""
    try:
        result = eval(expression)
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {str(e)}"

def get_current_time() -> str:
    """Get current time"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Create tools
wikipedia_tool = Tool(
    name="search_wikipedia",
    description="Search Wikipedia for information about a topic",
    func=search_wikipedia
)

calculator_tool = Tool(
    name="calculate",
    description="Calculate mathematical expressions",
    func=calculate
)

time_tool = Tool(
    name="get_time",
    description="Get the current date and time",
    func=get_current_time
)

# Create agent with tools
assistant = CrewAgent(
    role="assistant",
    goal="Help users with information and calculations",
    backstory="""You are a helpful assistant with access to Wikipedia,
    a calculator, and the current time. Use your tools to provide accurate answers.""",
    tools=[wikipedia_tool, calculator_tool, time_tool],
    verbose=True,  # See tool usage
)

# Register with Agent Kernel
CrewAIModule([assistant])

if __name__ == "__main__":
    CLI.main()
```

## Running the Example

```bash
pip install agentkernel[crewai] requests
export OPENAI_API_KEY=sk-...
python custom_tools.py
```

## Example Session

```
Agent Kernel CLI
Available agents:
  - assistant

Type your message (or 'quit' to exit):
> What is quantum computing?

[assistant] Let me search for that information...
[Tool: search_wikipedia("quantum computing")]
[assistant] Quantum computing is a type of computation that harnesses...

> What is 15 * 27?

[assistant] Let me calculate that...
[Tool: calculate("15 * 27")]
[assistant] 15 * 27 = 405

> What time is it?

[assistant] Let me check...
[Tool: get_time()]
[assistant] The current time is 2025-10-16 14:30:00

> quit
Goodbye!
```

## Advanced Tools

### Database Tool

```python
def query_database(query: str) -> str:
    """Query a database"""
    import sqlite3
    conn = sqlite3.connect('data.db')
    cursor = conn.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    return str(results)

db_tool = Tool(
    name="query_database",
    description="Query the database",
    func=query_database
)
```

### API Integration Tool

```python
def call_external_api(endpoint: str, params: dict) -> str:
    """Call an external API"""
    response = requests.get(endpoint, params=params)
    return response.json()

api_tool = Tool(
    name="call_api",
    description="Call external API",
    func=call_external_api
)
```

### File Operations Tool

```python
def read_file(filepath: str) -> str:
    """Read content from a file"""
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

file_tool = Tool(
    name="read_file",
    description="Read content from a file",
    func=read_file
)
```

## Tool Security

Add validation and security:

```python
def safe_calculate(expression: str) -> str:
    """Safe calculator with validation"""
    # Whitelist allowed operations
    allowed_chars = set("0123456789+-*/().")
    if not all(c in allowed_chars or c.isspace() for c in expression):
        return "Error: Invalid characters in expression"
    
    try:
        # Limit expression length
        if len(expression) > 100:
            return "Error: Expression too long"
        
        result = eval(expression)
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {str(e)}"
```

## RBAC for Tools

Restrict tool access:

```python
admin_tool = Tool(
    name="delete_data",
    description="Delete data (admin only)",
    func=delete_data_func,
    required_roles=["admin"]
)

user_tool = Tool(
    name="read_data",
    description="Read data",
    func=read_data_func,
    required_roles=["user", "admin"]
)
```

## Next Steps

- [REST API Documentation](../api/rest-api)
- [Advanced Features](../advanced/memory-management)
- [Deployment Guide](../deployment/overview)
