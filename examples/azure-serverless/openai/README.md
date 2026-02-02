# Agent Kernel running OpenAI Agents SDK based agents in Azure Serverless (Functions)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using Azure Functions with Flex Consumption plan.

## Deployed Resources

This demo deploys the following Azure resources:

- **Azure Function App (Flex Consumption)** - Serverless compute platform running the Agent Kernel implementation
- **Azure Service Plan (FC1 SKU)** - Flex Consumption plan for cost-effective serverless execution
- **Azure Storage Account** - Required for Function App deployment and runtime
- **Azure API Management (APIM)** - API Gateway endpoint for the Function App
- **Azure Redis Cache** - In-memory data store for agent memory and session storage
- **Azure Application Insights** - Application performance monitoring and diagnostics
- **Azure Virtual Network** (optional) - Network isolation and security

## Architecture

The application consists of three specialized OpenAI agents:
- **Triage Agent** - Routes user questions to appropriate specialist agents
- **Math Agent** - Handles mathematical problems and calculations
- **History Agent** - Provides assistance with historical queries

Agent conversations and memory are persisted in Azure Redis Cache with the prefix `ak:openai:example:`.

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
openai_api_key = "your-openai-api-key"

# Publisher email for API Management (required for APIM creation)
publisher_email = "your-email@domain.com"
```

### Optional Variables (have defaults)
```hcl
# Azure region for deployment
region = "centralus"

# Naming configuration
product_alias = "demo"          # Used in resource names
env_alias = "dev"               # Environment identifier
module_name = "api"             # Module identifier

# Feature flags
create_redis_cluster = true     # Required for agent memory
create_cosmosdb_cluster = false # Alternative to Redis (not used in this example)

# Environment configuration
is_production = false           # Development environment settings
module_type = "python"          # Function runtime (python or nodejs)

# API Gateway configuration - defines the endpoints exposed through APIM
gateway_endpoints = [
  {
    function_name = "AgentFunction"  # Name of the Azure Function
    path          = "/chat"          # API path: /api/v1/chat
    method        = "POST"
  },
  {
    function_name = "AgentFunction"  # Same function, different endpoint
    path          = "/secondary"     # API path: /api/v1/secondary
    method        = "POST"
  }
]
```

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
   - `openai_api_key` - Your OpenAI API key

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
    "message": "What is the square root of 144?",
    "session_id": "user123"
  }'

# Send a history question
curl -X POST "${API_URL}/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tell me about the American Civil War",
    "session_id": "user123"
  }'

# Use the secondary endpoint (same functionality)
curl -X POST "${API_URL}/secondary" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Calculate 15 * 23",
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

## Agent Memory

This example uses Azure Redis Cache for agent memory storage. The configuration in `config.yaml` specifies:

```yaml
debug: true
session:
  type: redis
  redis:
    prefix: "ak:openai:example:"
```

All agent conversations and session data are automatically stored in Redis with the specified prefix, enabling persistent conversations across requests.

## Function Configuration

The Azure Function is configured with:

- **Runtime**: Python 3.11 on Linux
- **Plan**: Flex Consumption (FC1 SKU) for cost-effective serverless execution
- **Trigger**: HTTP trigger with function-level authentication
- **Authentication**: Function-level authentication with key-based access
- **Handler**: Defined in `main.py` using `AzureFunctions.handler`

## Monitoring and Logging

The deployment includes comprehensive monitoring:

- **Application Insights** - Function execution monitoring, request tracking, and custom telemetry
- **API Management Analytics** - API usage statistics, response times, and error rates
- **Function App Logs** - Detailed execution logs and error tracking

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

3. **Function App Deployment Issues**
   - Check Function App logs in the Azure Portal
   - Verify the deployment package (`dist.zip`) was created successfully
   - Ensure the function runtime matches the `module_type` setting

4. **API Management Access Issues**
   - Verify the publisher email is valid
   - Check API Management policies and backend configuration

### Known Issues

1. **API Management Service Contributor Role Assignment**
   - When creating the APIM resource, you may need the "API Management Service Contributor" role assignment with the correct scope
   - If deployment fails with permission errors related to APIM, ensure your account or service principal has this role at the resource group or subscription level
   - You can assign this role using: `az role assignment create --assignee <user-or-service-principal> --role "API Management Service Contributor" --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>`

## Performance Considerations

- **Flex Consumption Plan**: Automatically scales based on demand with pay-per-execution pricing
- **Cold Start**: First requests after idle periods may experience slight delays.
- **Redis Connection**: Connection pooling is handled automatically by the Agent Kernel
- **Memory Usage**: Monitor function memory consumption through Application Insights

## Security

- **Function Authentication**: Uses function-level authentication keys
- **API Management**: Provides additional security layers and rate limiting
- **Network Security**: Optional VNet integration for network isolation
- **Secrets Management**: Environment variables are securely managed by Azure Functions