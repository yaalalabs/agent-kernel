# Agent Kernel with MCP enabled on ECS

This project demonstrates how to deploy an **Agent Kernel** running containerized agents on **AWS ECS** with **MCP (Model Context Protocol)** enabled.
Agents are exposed as MCP tools and can be accessed via both the **REST API** and the **MCP Client API**.

---

## Features

* Containerized Agent Kernel running on AWS ECS
* MCP server enabled and exposed via `/mcp` endpoint
* Supports CrewAI and OpenAI Agent SDK agents
* Agents automatically registered as MCP tools
* Redis-backed state (optional)

---

## Enabling MCP in Terraform

MCP support is enabled directly through the Terraform module by setting:

```hcl
enable_mcp_server = true
```

This automatically creates an MCP endpoint at:

```
/<api_base_path>/<api_version>/mcp
```

### Example `main.tf`

```hcl
# Containerized module configuration for deploying MCP in ECS
module "containered_agents" {
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.2.9"

  # Basic ECS configuration
  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  package_path         = "../dist"
  container_type       = "ecs"
  region               = var.region

  vpc_id             = "vpc-09033229d67314c1c"
  private_subnet_ids = [ "subnet-00e888e445f16d1b1","subnet-0ab5240262cd77119" ]

  product_display_name = "MCP Containerized Example"

  # Container & networking
  ecs_container_port   = 8000

  # Optional dependencies
  create_redis_cluster = true

  # Enable MCP server
  enable_mcp_server = true  # MCP endpoint => /<api_base_path>/<api_version>/mcp

  # Environment variables passed to the container
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }
}
```

---

## MCP Configuration (`config.yaml`)

In addition to Terraform, MCP must be enabled at the application level using `config.yaml`.

### Example `config.yaml`

```yaml
mcp:
  enabled: true
  expose_agents: true
  agents: ['*']
```

> **Endpoint**: The MCP server is always mounted at `/mcp` on the main API server — there is no `mcp.url` config. The full endpoint is `http://{api.host}:{api.port}/mcp`. Use `api.port` to change the port.

### Configuration Explanation

| Field              | Description                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------ |
| `enabled`          | Enables the MCP server                                                                           |
| `expose_agents`    | Automatically exposes agents as MCP tools                                                        |
| `agents`           | List of agent names to expose (`'*'` = all agents)                                               |
| `stateless_http`   | Stateless HTTP mode — each request is independent, no `Mcp-Session-Id` (default: `false`)        |


> **Both Terraform (`enable_mcp_server = true`) and `config.yaml` MCP settings are required** for MCP to work correctly.

---

## MCP Endpoint

Once deployed, the MCP endpoint will be available at:

```
https://<invoke-url>/<api_base_path>/<api_version>/mcp
```

Example:

```
https://<api-id>.execute-api.<region>.amazonaws.com/agents/api/v1/mcp
```

This endpoint supports MCP clients such as `fastmcp`.

---

## Agent Kernel Overview

This package contains a demo of **Agent Kernel** running agents built with:

* CrewAI
* OpenAI Agent SDK

Agents run in a single runtime and are exposed as **MCP tools**, allowing:

* Tool discovery
* Remote tool execution
* Structured agent interaction via MCP clients

Agents become MCP-accessible when:

```yaml
mcp:
  enabled: true
  expose_agents: true
```

---

## Local Development

### Install dependencies

```bash
./build.sh
```

### Install dependencies in development mode

```bash
./build.sh local
```

---

## Running the Server

```bash
python server.py
```

The server will start on:

```
http://localhost:8000
```

MCP endpoint:

```
http://localhost:8000/mcp
```

---

## Running Tests

```bash
uv run pytest -s
```

---

    