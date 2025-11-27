---
sidebar_position: 4
---

# Memory Management

Agent Kernel supports pluggable memory backends for both short-term and long-term storage.

## Memory Architecture

```mermaid
graph TB
    subgraph "Short-term Memory"
        A[Session State]
        B[Conversation History]
        C[In-Memory Storage]
        D[Redis Storage]
        I[DynamoDB Storage]
    end
    
    subgraph "Long-term Memory (Future)"
        E[User Profiles]
        F[Knowledge Base]
        G[DynamoDB]
        H[MongoDB]
    end
    
    A --> C
    A --> D
    A --> I
    B --> C
    B --> D
    B --> I
    
    E --> G
    E --> H
    F --> G
    F --> H
    
    style A fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style E fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
```

## Short-term Memory

Managed via Session objects:

```python
# Conversation history stored in session
session.set("session_id", data)
```

**Storage Options:**
- In-memory (development)
- Redis (production)
- DynamoDB (AWS serverless)

## Long-term Memory

Available soon!

## Configuration

```bash
# Short-term (session) - Redis
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379

# Short-term (session) - DynamoDB
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
```
