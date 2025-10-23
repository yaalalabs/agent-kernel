---
sidebar_position: 3
---

# Session Management

How Agent Kernel manages conversation state across interactions.

## Session Architecture

```mermaid
graph TB
    subgraph "Application"
        A[Multiple Requests]
    end
    
    subgraph "Session Manager"
        B[Session Cache]
        C[Session Factory]
    end
    
    subgraph "Storage"
        D[In-Memory Dict]
        E[Redis]
        F[Long-term DB]
    end
    
    A --> B
    B --> C
    C --> D
    C --> E
    C --> F
    
    style B fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

## Storage Options

### In-Memory (Development)

```bash
export AK_SESSION_STORAGE=in_memory
```

- Fast, no setup required
- Data lost on restart
- Single-process only

### Redis (Production)

```bash
export AK_SESSION_STORAGE=redis
export AK_REDIS_URL=redis://localhost:6379
```

- Persistent
- Multi-process/distributed
- Configurable TTL

## Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: First interaction
    Created --> Active: Subsequent interactions
    Active --> Active: More interactions
    Active --> Expired: Timeout/TTL
    Active --> Closed: Explicit close
    Expired --> [*]
    Closed --> [*]
```

## Best Practices

- Use unique session IDs per user conversation
- Configure appropriate TTL in production
- Use Redis for distributed deployments
- Monitor session storage size
