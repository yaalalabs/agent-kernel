---
sidebar_position: 2
---

# Execution Flow

How requests flow through Agent Kernel from user input to agent response.

## Request Lifecycle

```mermaid
graph TD
    A[User Request] --> B{Execution Mode}
    B -->|CLI| C[CLI Handler]
    B -->|API| D[REST API Handler]
    B -->|Lambda| E[Lambda Handler]
    
    C --> F[Runtime.get_agent]
    D --> F
    E --> F
    
    F --> G[Runtime.get_session]
    G --> H[Runner.run]
    H --> I[Framework Execution]
    I --> J[Update Session]
    J --> K[Return Response]
    
    style F fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

## Detailed Flow

### 1. Request Reception

The request enters through one of the execution modes:

- **CLI**: Interactive terminal input
- **REST API**: HTTP POST to `/api/v1/chat` endpoint
- **AWS Lambda**: Lambda event
- **MCP/A2A**: Protocol-specific request

### 2. Agent Resolution

```python
runtime = Runtime.get()
agent = runtime.get_agent(agent_name)
```

### 3. Session Management

```python
session = runtime.get_session(session_id)
# Loads existing session or creates new one
```

### 4. Agent Execution

```python
result = await agent.runner.run(agent, session, prompt)
```

### 5. Response Return

Result is formatted and returned to the user through the appropriate channel.

## Timing Diagram

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant API
    participant Runtime
    participant Agent
    participant Runner
    participant Framework
    participant Session
    participant Storage
    
    User->>API: POST /api/v1/chat
    API->>Runtime: get_agent("assistant")
    Runtime-->>API: Agent instance
    API->>Runtime: get_session("user-123")
    Runtime->>Storage: Load session
    Storage-->>Runtime: Session data
    Runtime-->>API: Session instance
    API->>Runner: run(agent, session, prompt)
    Runner->>Session: get framework state
    Session-->>Runner: Current state
    Runner->>Framework: Execute agent
    Framework-->>Runner: Result
    Runner->>Session: update state
    Session->>Storage: Persist
    Runner-->>API: Result
    API-->>User: JSON response
```

