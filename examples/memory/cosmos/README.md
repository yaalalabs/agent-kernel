# Agent Kernel running OpenAI Agents SDK based agents in Azure Serverless (Functions) with Azure Cosmos DB as agent memory

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using Azure Functions with Flex Consumption plan and Azure Cosmos DB for agent memory storage.

## Overview

This example demonstrates how to use Azure Cosmos DB as the memory backend for Agent Kernel agents. Unlike the Redis-based examples, this implementation uses Cosmos DB's NoSQL capabilities to persist agent conversations and session data, providing a fully managed, globally distributed database solution.

## Deployed Resources

This demo deploys the following Azure resources:

- **Azure Function App (Flex Consumption)** - Serverless compute platform running the Agent Kernel implementation
- **Azure Service Plan (FC1 SKU)** - Flex Consumption plan for cost-effective serverless execution
- **Azure Storage Account** - Required for Function App deployment and runtime
- **Azure API Management (APIM)** - API Gateway endpoint for the Function App
- **Azure Cosmos DB** - NoSQL database for agent memory and session storage
- **Azure Application Insights** - Application performance monitoring and diagnostics
- **Azure Virtual Network** (optional) - Network isolation and security

## Architecture

The application consists of three specialized OpenAI agents:
- **Triage Agent** - Routes user questions to appropriate specialist agents
- **Math Agent** - Handles mathematical problems and calculations
- **History Agent** - Provides assistance with historical queries

Agent conversations and memory are persisted in Azure Cosmos DB with the prefix `ak:openai:example:`, providing durable, scalable storage for agent sessions.

## Prerequisites

- Azure CLI configured with appropriate credentials and subscription access
- Terraform (`1.9.5` or higher) installed
- An existing Azure Resource Group
- OpenAI API key with sufficient credits

## Configuration

Before deployment, you need to configure the following variables in `deploy/terraform.tfvars`:

### Required Variables (must be set)
```hcl
# Azure Resource Group (must exist)
resource_group_name = "your-resource-group-name"

# OpenAI API Key for agent functionality
# Note: This can also be set via environment variable TF_VAR_openai_api_key
openai_api_key = "your-openai-api-key"

# Publisher email for API Management (required for APIM creation)
publisher_email = "your-email@domain.com"
```

### Optional Variables (have defaults)
```hcl
# Azure region for deployment
# Try to use the same region as your resource group to avoid cross-region issues and costs
region = "centralus"

# Naming configuration
product_alias = "demo"          # Used in resource names
env_alias = "memory"            # Environment identifier
module_name = "cosmos"          # Module identifier
```

### Gateway Endpoints Configuration

The deployment is pre-configured with two endpoints in `deploy/main.tf`:

```hcl
gateway_endpoints = [
  {
    function_name = "AgentFunction"  # Name of the Azure Function
    path          = "/chat"          # API path: /api/v1/chat
    method        = "POST"
  },
  {
    function_name = "CustomFunction"  # Same function, different endpoint
    path          = "/custom"         # API path: /api/v1/custom
    method        = "POST"
  }
]
```

You can modify these endpoints in `main.tf` to match your requirements. Note that the function JSON file name should be updated to accept the HTTP method you are using.

## Deployment Steps

1. **Configure environment variables:**
   ```bash
   # Set your OpenAI API key
   export TF_VAR_openai_api_key=<OPENAI_API_KEY>
   ```

2. **Update terraform.tfvars:**
   Edit `deploy/terraform.tfvars` and set the required variables:
   - `resource_group_name` - Your existing Azure Resource Group
   - `publisher_email` - Your email for API Management
   - `openai_api_key` - Your OpenAI API key (or use the environment variable above)

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
curl -X POST "${API_URL}/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "math",
    "message": "What is the square root of 144?",
    "session_id": "user123"
  }'

# Send a history question
curl -X POST "${API_URL}/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "history",
    "message": "Tell me about the American Civil War",
    "session_id": "user123"
  }'

# Use the custom endpoint (implemant yourself)
curl -X POST "${API_URL}/custom" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello server",
    "session_id": "user456"
  }'
```

## Outputs

The deployment provides the following outputs:

- `api_url` - The complete API URL with base path and version for accessing the service
- `api_management_gateway_url` - The API Management gateway URL
- `function_app_url` - The Function App default hostname
- `function_app_id` - Function App resource ID
- `function_app_name` - Function App name

## Agent Memory with Cosmos DB

This example uses Azure Cosmos DB for agent memory storage. The configuration in `src/config.yaml` specifies:

```yaml
logging:
  ak:
    level: DEBUG
session:
  type: cosmosdb
  cosmosdb:
    prefix: "ak:openai:example:"
```

## Function Configuration

The Azure Function is configured with:

- **Runtime**: Python 3.11 on Linux
- **Plan**: Flex Consumption (FC1 SKU) for cost-effective serverless execution
- **Trigger**: HTTP trigger with function-level authentication
- **Authentication**: Function-level authentication with key-based access
- **Handler**: Defined in `main.py` using `AzureFunctions.handler`
- **Memory Backend**: Cosmos DB (configured in `config.yaml`)

## Monitoring and Logging

The deployment includes comprehensive monitoring:

- **Application Insights** - Function execution monitoring, request tracking, and custom telemetry
- **API Management Analytics** - API usage statistics, response times, and error rates
- **Function App Logs** - Detailed execution logs and error tracking
- **Cosmos DB Metrics** - Request units (RU) consumption, latency, and throughput monitoring

Access these through the Azure Portal to monitor your agent's performance and usage patterns.

## Clean Up

To remove all deployed resources:

```bash
cd deploy
terraform destroy
```

**Note**: Cosmos DB data will be permanently deleted. Ensure you have backups if needed.

## Troubleshooting

### Common Issues

1. **Resource Group Not Found**
   - Ensure the resource group specified in `terraform.tfvars` exists in your Azure subscription
   - Verify you have appropriate permissions on the resource group

2. **OpenAI API Key Issues**
   - Verify your OpenAI API key is valid and has sufficient credits
   - Check that the variable is properly set in `terraform.tfvars`
   - Alternatively, export the variable: `export TF_VAR_openai_api_key=<OPENAI_API_KEY>`

3. **Function App Deployment Issues**
   - Check Function App logs in the Azure Portal
   - Verify the deployment package (`dist.zip`) was created successfully
   - Ensure the function runtime matches the Python version

4. **Cosmos DB Connection Issues**
   - Verify the Cosmos DB account was created successfully
   - Check that the Function App has the necessary permissions to access Cosmos DB
   - Review Application Insights for connection error details

5. **API Management Access Issues**
   - Check if the user have nessary permissions to APIM dataplane and managementplane operations
   - Check API Management policies and backend configuration
   - Ensure the Function App is accessible from APIM

### Known Issues

1. **API Management Service Contributor Role Assignment**
   - When creating the APIM resource, you may need the "API Management Service Contributor" role assignment
   - If deployment fails with permission errors, ensure your account has this role at the resource group or subscription level
   - Assign the role using: 
     ```bash
     az role assignment create \
       --assignee <user-or-service-principal> \
       --role "API Management Service Contributor" \
       --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>
     ```

2. **Cosmos DB Throughput Limits**
   - Default deployment uses provisioned throughput
   - Monitor RU consumption in Azure Portal
   - Consider switching to serverless mode for development/testing


## Performance Considerations

- **Flex Consumption Plan**: Automatically scales based on demand with pay-per-execution pricing
- **Cold Start**: First requests after idle periods may experience slight delays
- **Cosmos DB Latency**: Single-digit millisecond latency for reads and writes
- **Request Units (RU)**: Monitor RU consumption to optimize costs
- **Connection Pooling**: Cosmos DB connections are managed automatically by the Agent Kernel
- **Memory Usage**: Monitor function memory consumption through Application Insights

## Cost Optimization

- **Serverless Cosmos DB**: Consider using serverless mode for development and low-traffic scenarios
- **Autoscale**: Enable autoscale for production workloads with variable traffic
- **TTL (Time-to-Live)**: Configure TTL on Cosmos DB containers to automatically expire old sessions
- **Regional Deployment**: Deploy in a single region for development to minimize costs

## Security

- **Function Authentication**: Uses function-level authentication keys
- **API Management**: Provides additional security layers and rate limiting
- **Cosmos DB Access**: Managed through Azure RBAC and connection strings
- **Network Security**: Optional VNet integration for network isolation
- **Secrets Management**: Environment variables are securely managed by Azure Functions
- **Encryption**: Data is encrypted at rest and in transit by default

## Comparison with Redis Memory Backend

| Feature | Cosmos DB | Redis |
|---------|-----------|-------|
| **Data Model** | Document-based NoSQL | Key-value store |
| **Persistence** | Durable, replicated | In-memory with optional persistence |
| **Scalability** | Automatic, global | Manual scaling |
| **Latency** | Single-digit ms | Sub-millisecond |
| **Cost** | Pay per RU or serverless | Pay per instance size |
| **Best For** | Long-term storage, complex queries | High-speed caching, temporary data |

Choose Cosmos DB when you need:
- Reduced cost
- Long-term persistence of agent conversations
- Global distribution and high availability
- Complex querying capabilities
- Automatic scaling without manual intervention

Choose Redis when you need:
- Ultra-low latency access
- Simple key-value operations
- Cost-effective caching for temporary data
