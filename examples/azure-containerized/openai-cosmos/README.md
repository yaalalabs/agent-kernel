# Agent Kernel running OpenAI Agents SDK based agents in Azure Container Apps with Azure Cosmos DB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a containerized configuration on Azure Container Apps using Azure Cosmos DB as agent memory.

## Deployed Resources

This demo deploys the following Azure resources:

- **Azure Container Apps Environment** - Serverless container hosting platform
- **Azure Container App** - Python application running the Agent Kernel implementation
- **Azure Container Registry (ACR)** - Private container registry for the application image
- **Azure API Management (APIM)** - API Gateway endpoint for the Container App service
- **Azure Cosmos DB** - NoSQL database for agent memory and session storage. We are using the [Azure Cosmos DB Table API](https://learn.microsoft.com/en-us/azure/cosmos-db/table/introduction) to store the session data.
- **Azure Log Analytics Workspace** - Centralized logging for Container Apps
- **Azure Application Insights** - Application performance monitoring and diagnostics
- **Azure Virtual Network** - Network isolation and security
- **Network Security Groups** - Network access control and security rules
- **Private DNS Zone** - Internal DNS resolution for Container Apps.

## Architecture

The application consists of three specialized OpenAI agents:
- **Triage Agent** - Routes user questions to appropriate specialist agents
- **Math Agent** - Handles mathematical problems and calculations
- **History Agent** - Provides assistance with historical queries

Agent conversations and memory are persisted in Azure Cosmos DB with the prefix `ak:openai:example:`.

## Prerequisites

- Azure CLI configured with appropriate credentials and subscription access
- Azure Subscription with permissions to create the above resources, along with the necessary roles.
- Terraform (`1.9.5` or higher) installed
- Docker installed (for local image building)
- An existing Azure Resource Group, whose ownership you have. (Make sure the resource group in the region you plan to deploy to exists.)

## Configuration

Before deployment, you need to configure the following variables in `deploy/terraform.tfvars`:

### Required Variables (must be set)
```hcl
# Azure Resource Group (must exist)
resource_group_name = "your-resource-group-name"

# OpenAI API Key for agent functionality
environment_variables = {
  OPENAI_API_KEY = "your-openai-api-key"
}

# Publisher email for API Management
publisher_email = "your-email@domain.com"
```

### Optional Variables (have defaults)
```hcl
# Azure region for deployment
region = "centralus"

# Naming configuration
product_alias = "ak-oai"        # Used in resource names
env_alias = "dev"               # Environment identifier
module_name = "examples"        # Module identifier

# Feature flags
create_redis_cluster = false    # Redis not needed for this example
create_cosmosdb_cluster = true  # Required for agent memory

# Environment configuration
is_production = false           # Development environment settings
product_display_name = "Demo Platform API"

# Container configuration
container_port = 8000
container_health_check_path = "/health"
package_path = "dist"

# API Gateway configuration
api_version = "v1"
gateway_endpoints = [
  {
    path           = "chat"     # API path: /api/v1/chat
    method         = "POST"
    overwrite_path = "/run"     # Forwards to container's /run endpoint
  }
]

# Resource tagging
tags = {
  "costcenter" = "agent-kernel"
}
```

## Deployment Steps

1. **Configure environment variables:**
   ```bash
   # Set your OpenAI API key
   export TF_VAR_openai_api_key=<OPENAI_API_KEY>
   ```
   The OpenAI API key is used to authenticate the agents to the OpenAI API. Terraform will pick up the value from the environment variable, and pass it to the container as an environment variable.

2. **Update terraform.tfvars:**
   Edit `deploy/terraform.tfvars` and set the required variables:
   - `resource_group_name` - Your existing Azure Resource Group
   - `region` - The Azure region to deploy to (e.g., `centralus`)
   - `publisher_email` - Your email for API Management

3. **Navigate to the deployment directory and run the deployment script:**
   ```bash
   cd deploy && ./deploy.sh
   ```
   
   For local development with locally built dependencies:
   ```bash
   cd deploy && ./deploy.sh local
   ```

## Usage

After successful deployment, you can interact with the agents through the API Management endpoint:

```bash
# Get the API URL from Terraform outputs
API_URL=$(terraform output -raw api_url)

# Send a math question to the triage agent
curl -X POST "${API_URL}/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the square root of 144?",
    "session_id": "user123"
  }'

# Send a history question
curl -X POST "${API_URL}/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tell me about the American Civil War",
    "session_id": "user123"
  }'
```

## Outputs

The deployment provides the following outputs:

- `api_url` - The full API Management gateway URL for accessing the service
- `api_base_url` - The base URL for the API Management service
- `gateway_endpoints` - List of configured gateway endpoints

## Agent Memory

This example uses Azure Cosmos DB for agent memory storage. The configuration in `config.yaml` specifies:

```yaml
logging:
  ak:
    level: DEBUG
session:
  type: cosmosdb
  cosmosdb:
    prefix: "ak:openai:example:"
```

All agent conversations and session data are automatically stored in Cosmos DB with the specified prefix, enabling persistent conversations across requests.

## Monitoring and Logging

The deployment includes comprehensive monitoring:

- **Application Insights** - Application performance monitoring, request tracking, and custom telemetry
- **Log Analytics** - Centralized logging from Container Apps and other Azure services
- **API Management Analytics** - API usage statistics, response times, and error rates

Access these through the Azure Portal to monitor your agent's performance and usage patterns.

## Clean Up

To remove all deployed resources:

```bash
cd deploy
terraform destroy
```

## Troubleshooting

### Common Issues

1. **Resource Group Not Found**
   - Ensure the resource group specified in `terraform.tfvars` exists in your Azure subscription
   - Verify you have appropriate permissions on the resource group

2. **OpenAI API Key Issues**
   - Verify your OpenAI API key is valid and has sufficient credits
   - Check that the environment variable is properly set in `terraform.tfvars`

3. **Container App Startup Issues**
   - Check Container App logs in the Azure Portal
   - Verify the application image was built and pushed successfully to ACR

4. **API Management Creation Issues**
  - For terraform to deploy the API Management service, you need to provide the following role assignments:
  - API Management Service Contributor, with a scope of the resource group (minimum required)

5. **API Management Access Issues**
   - Ensure the publisher email is valid
   - Check API Management policies and backend configuration
