---
sidebar_position: 3
---

# Multi-Agent Systems

Build collaborative agent systems with Open Agent Kernel (OAK).

## Architecture Patterns

### Supervisor Pattern

```mermaid
graph TB
    A[Supervisor Agent] --> B[Specialist 1]
    A --> C[Specialist 2]
    A --> D[Specialist 3]
    
    style A fill:#FF5E32,stroke:#fff,stroke-width:2px,color:#02284F
```

### Peer-to-Peer Pattern

```mermaid
graph LR
    A[Agent 1] <--> B[Agent 2]
    B <--> C[Agent 3]
    C <--> A
    
    style A fill:#FF5E32,stroke:#fff,stroke-width:2px,color:#02284F
    style B fill:#3F598A,stroke:#fff,stroke-width:2px,color:#fff
    style C fill:#3F598A,stroke:#fff,stroke-width:2px,color:#fff
```

### Pipeline Pattern

```mermaid
graph LR
    A[Agent 1] --> B[Agent 2]
    B --> C[Agent 3]
    C --> D[Agent 4]
    
    style A fill:#FF5E32,stroke:#fff,stroke-width:2px,color:#02284F
```

Support and documentation to be available soon!