---
sidebar_position: 1
---

# Architecture Overview

Understanding Agent Kernel's architecture helps you build robust, scalable AI agent systems.

## High-Level Architecture

```mermaid
graph TB
    subgraph "Application Layer"
        A[Your Agent Logic]
    end
    
    subgraph "Agent Kernel Layer"
        B[Module]
        C[Agent Wrapper]
        D[Runner]
        E[Session Manager]
        F[Runtime]
    end
    
    subgraph "Framework Layer"
        G[OpenAI Agents]
        H[CrewAI]
        I[LangGraph]
        J[Google ADK]
    end
    
    subgraph "Storage Layer"
        K[In-Memory]
        L[Redis]
    end
    
    subgraph "Execution Layer"
        O[CLI]
        P[REST API]
        Q[AWS Lambda]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    C --> F
    E --> F
    
    C --> G
    C --> H
    C --> I
    C --> J
    
    E --> K
    E --> L
    
    F --> O
    F --> P
    F --> Q
    
    style F fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

## Key Design Principles

### 1. Framework Agnostic

Agent Kernel provides a thin adapter layer that doesn't impose its own opinions on agent logic.

### 2. Minimal Overhead

The framework adds minimal latency and complexity - it's primarily orchestration and state management.

### 3. Production Ready

Built-in support for:
- Session persistence
- Multi-agent coordination
- Distributed deployment
- Error handling and retry
- Observability and tracing

### 4. Extensible

Easy to add:
- New framework adapters
- Custom storage backends
- Additional execution modes
- Custom middleware

## Component Interactions

```mermaid
sequenceDiagram
    participant U as User
    participant E as Execution Mode
    participant R as Runtime
    participant A as Agent
    participant Run as Runner
    participant S as Session
    participant F as Framework
    participant Store as Storage
    
    U->>E: Request
    E->>R: Get agent
    R-->>E: Agent instance
    E->>R: Get/create session
    R->>Store: Load session
    Store-->>R: Session data
    R-->>E: Session instance
    E->>Run: Execute
    Run->>S: Get state
    S-->>Run: Current state
    Run->>F: Framework execution
    F-->>Run: Result
    Run->>S: Update state
    S->>Store: Persist
    Run-->>E: Result
    E-->>U: Response
```

## Next Steps

- [Execution Flow](./execution-flow)
- [Session Management](./session-management)
- [Memory Management](./memory-management)
