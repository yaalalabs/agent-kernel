---
sidebar_position: 1
---

# Deployment Overview

Agent Kernel supports multiple deployment modes for different use cases.

## Deployment Modes

```mermaid
graph TB
    A[Agent Kernel Application] --> B{Deployment Mode}
    B --> C[Local/CLI]
    B --> D[REST API]
    B --> E[AWS Lambda]
    B --> F[AWS ECS/Fargate]
    B --> G[MCP Server]
    B --> H[A2A Server]
    
    style A fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

## Quick Comparison

| Mode | Best For | Scalability | Cold Start | Cost | Fault Tolerance |
|------|----------|-------------|------------|------|-----------------|
| **Local/CLI** | Development, testing | N/A | Instant | Free | Manual restart |
| **REST API** | Web apps, APIs | Manual scaling | Instant | Server costs | Manual |
| **AWS Lambda** | Variable load | Auto-scaling | 1-3s | Pay per use | **High** - Auto-retry, multi-AZ |
| **AWS ECS** | Consistent load | Auto-scaling | Instant | Running containers | **Very High** - Multi-AZ, auto-recovery |
| **MCP Server** | AI integrations | Manual | Instant | Server costs | Manual |
| **A2A Server** | Agent networks | Manual | Instant | Server costs | Manual |

## Local Development

Uses `agentkernel.CLI` module.

```bash
python my_agent.py
```

- Interactive CLI
- Instant feedback
- No deployment needed

[Learn more →](./local)

## REST API Server

Uses `agentkernel.RESAPI` module.

```
python my_agent.py
```


- HTTP endpoints
- Easy integration
- Self-hosted

[Learn more →](../api/rest-api)

## AWS Serverless

Uses Agent Kernel terraform modules

```bash
# Configure the modules and run
terraform init && terraform apply
```

- Lambda functions
- API Gateway
- Auto-scaling
- Pay per request

[Learn more →](./aws-serverless)

## AWS Containerized

Uses Agent Kernel terraform modules

```bash
# Configure the modules and run
terraform init && terraform apply
```

- ECS Fargate
- Application Load Balancer
- Consistent performance
- Lower latency

[Learn more →](./aws-containerized)

## Choosing a Deployment Mode

### Development
→ **Local/CLI**: Fast iteration, no setup

### Small Web App
→ **REST API**: Simple, self-hosted

### Variable Traffic
→ **AWS Lambda**: Auto-scales, pay per use

### High Traffic
→ **AWS ECS**: Consistent performance

### AI Integration
→ **MCP/A2A**: Protocol-based integration

## Fault Tolerance Considerations

Agent Kernel provides different levels of fault tolerance depending on your deployment mode:

### Production-Grade Fault Tolerance

**AWS ECS/Fargate** offers the highest level of fault tolerance:
- Multi-AZ task distribution for zone-level failures
- Automatic task replacement on failures
- Health check-based routing
- Configurable auto-scaling
- Rolling deployments with zero downtime
- Application Load Balancer with health monitoring

[Learn more about ECS fault tolerance →](./aws-containerized#fault-tolerance)

**AWS Lambda** provides built-in fault tolerance:
- Serverless architecture with automatic scaling
- Multi-AZ execution by default
- Automatic retry on failures
- No infrastructure management
- Inherently resilient to hardware failures

[Learn more about serverless fault tolerance →](./aws-serverless#fault-tolerance)

### State Persistence

Both production deployment modes support resilient state management:
- **DynamoDB**: Multi-AZ replication, automatic backups, 99.999% SLA
- **Redis**: Cluster mode with automatic failover, replication

[Learn more about fault tolerance →](../core-concepts/fault-tolerance)

## Next Steps

- [Local Deployment](./local)
- [AWS Serverless](./aws-serverless)
- [AWS Containerized](./aws-containerized)
- [Fault Tolerance](../core-concepts/fault-tolerance)
- [Configuration](../core-concepts/configuration)
