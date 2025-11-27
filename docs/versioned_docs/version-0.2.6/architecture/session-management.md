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
        F[DynamoDB]
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
export AK_SESSION__TYPE=in_memory
```

- Fast, no setup required
- Data lost on restart
- Single-process only

### Redis (Production)

```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
```

- Persistent
- Multi-process/distributed
- Configurable TTL

### DynamoDB (AWS Serverless)

```bash
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
```

- Serverless, fully managed
- Auto-scaling
- AWS-native integration
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
- Use Redis for distributed/containerized deployments
- Use DynamoDB for AWS serverless deployments
- Monitor session storage size
