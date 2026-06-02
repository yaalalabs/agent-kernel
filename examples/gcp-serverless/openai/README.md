# Agent Kernel running OpenAI Agents SDK based agents in GCP Serverless (Cloud Run)

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a serverless configuration using GCP Cloud Run with scale-to-zero capability.

## Deployed Resources

This demo deploys the following GCP resources:

- **Cloud Run Service** - Serverless container platform running the Agent Kernel implementation with scale-to-zero capability
- **API Gateway** - OpenAPI-based routing with versioned endpoints for the Cloud Run service
- **Artifact Registry** - Private container registry for storing the Docker image
- **Memorystore Redis** - In-memory data store for agent memory and session storage
- **VPC Network** - Virtual network with public and private subnets
- **Cloud NAT** - Network address translation for outbound internet access from private resources
- **VPC Access Connector** - Enables Cloud Run to access private resources in the VPC
- **Cloud Logging** - Built-in logging and monitoring

## Architecture

The application consists of three specialized OpenAI agents:
- **Triage Agent** - Routes user questions to appropriate specialist agents
- **Math Agent** - Handles mathematical problems and calculations
- **History Agent** - Provides assistance with historical queries

Agent conversations and memory are persisted in Memorystore Redis with the prefix `ak:openai:example:`.

The application also exposes custom endpoints:
- `GET /app` - Returns a custom response from the application
- `POST /app_info` - Returns application information

## Prerequisites

- GCP CLI (gcloud) configured with appropriate credentials and project access
- Terraform (`1.9.5` or higher) installed
- Docker installed (for local image building)
- An existing GCP project with appropriate permissions
- OpenAI API key with sufficient credits

## Configuration

Before deployment, you need to configure the following variables in `deploy/terraform.tfvars`:

### Required Variables (must be set)
```hcl
# GCP Project ID (must exist)
project_id = "your-gcp-project-id"

# OpenAI API Key for agent functionality
openai_api_key = "your-openai-api-key"

# GCP region for deployment
region = "us-central1"
```

### Optional Variables (have defaults)
```hcl
# Naming configuration
product_alias = "demo"          # Used in resource names
env_alias = "dev"               # Environment identifier
module_name = "api"             # Module identifier

# Feature flags
create_redis_cluster = true     # Required for agent memory
create_firestore_database = false # Alternative to Redis (not used in this example)

# Environment configuration
is_production = false           # Development environment settings

# Cloud Run configuration
cpu = "1"                       # CPU allocation
memory = "512Mi"                # Memory allocation
min_instance_count = 0         # Scale to zero (serverless)
max_instance_count = 10        # Maximum instances
timeout = 30                   # Request timeout in seconds

# API Gateway configuration
api_version = "v1"              # API version for endpoint path
api_base_path = "api"          # Base path segment for API
agent_endpoint = "chat"         # Default API endpoint name

# Custom gateway endpoints
gateway_endpoints = [
  {
    path           = "app"
    method         = "GET"
    overwrite_path = "/app"
  },
  {
    path           = "app_info"
    method         = "POST"
    overwrite_path = "/app_info"
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
   - `project_id` - Your GCP project ID
   - `region` - The GCP region to deploy to (e.g., `us-central1`)
   - `openai_api_key` - Your OpenAI API key or export it using the environment variable above

3. **Navigate to the deployment directory and run the deployment script:**
   ```bash
   cd deploy && ./deploy.sh
   ```
   
   For local development with locally built dependencies:
   ```bash
   cd deploy && ./deploy.sh local
   ```

## Usage

After successful deployment, you can interact with the agents through the API Gateway endpoint:

```bash
# Get the API URL from Terraform outputs
API_URL=$(terraform output -raw agent_invoke_url)

# Send a math question to the triage agent
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the square root of 144?",
    "session_id": "user123"
  }'

# Send a history question
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Tell me about the American Civil War",
    "session_id": "user123"
  }'

# Use the custom app endpoint
curl -X GET "$(terraform output -raw gateway_url)/api/v1/app"

# Use the custom app_info endpoint
curl -X POST "$(terraform output -raw gateway_url)/api/v1/app_info"
```

## Outputs

The deployment provides the following outputs:

- `service_url` - Direct Cloud Run service URL
- `service_name` - Cloud Run service name
- `gateway_url` - API Gateway base URL
- `agent_invoke_url` - Full agent invocation URL via API Gateway
- `api_gateway_id` - API Gateway ID

## Agent Memory

This example uses Memorystore Redis for agent memory storage. The configuration in `config.yaml` specifies:

```yaml
debug: true
api:
  port: 8000
session:
  type: redis
  redis:
    prefix: "ak:openai:example:"
```

All agent conversations and session data are automatically stored in Redis with the specified prefix, enabling persistent conversations across requests.

## Cloud Run Configuration

The Cloud Run service is configured with:
- **Runtime**: Python container with scale-to-zero capability
- **Scaling**: `min_instance_count = 0` for true serverless behavior (scales to zero when idle)
- **CPU**: 1 vCPU (configurable)
- **Memory**: 512Mi (configurable)
- **Timeout**: 30 seconds (configurable)
- **Port**: 8000

## Monitoring and Logging

The deployment includes comprehensive monitoring:
- **Cloud Logging** - Automatic collection of Cloud Run logs and application logs
- **Cloud Monitoring** - Metrics for Cloud Run performance and resource utilization
- **API Gateway Logs** - API request tracking and error rates

Access these through the GCP Console to monitor your agent's performance and usage patterns.

## Clean Up

To remove all deployed resources:

```bash
cd deploy
terraform destroy
```

## Troubleshooting

### Common Issues

1. **Project Not Found**
   - Ensure the project ID specified in `terraform.tfvars` exists in your GCP account
   - Verify you have appropriate permissions on the project

2. **OpenAI API Key Issues**
   - Verify your OpenAI API key is valid and has sufficient credits
   - Check that the variable is properly set in `terraform.tfvars` or exported as an environment variable

3. **Cloud Run Deployment Issues**
   - Check Cloud Run logs in the GCP Console
   - Verify the Docker image was built and pushed successfully to Artifact Registry
   - Ensure the container port matches the configuration (default: 8000)

4. **Redis Connection Issues**
   - Verify the VPC Access Connector is properly configured
   - Check firewall rules allow traffic from Cloud Run to Redis
   - Ensure Redis instance is in the same region as Cloud Run

5. **API Gateway Issues**
   - Verify the OpenAPI specification is valid
   - Check API Gateway logs for routing errors
   - Ensure backend service URL is correct

## Performance Considerations

- **Scale-to-Zero**: With `min_instance_count = 0`, the service scales to zero when idle, eliminating idle costs but introducing cold starts (~1-3 seconds)
- **Cold Starts**: First requests after idle periods may experience slight delays
- **Redis Connection**: Connection pooling is handled automatically by the Agent Kernel
- **Memory Usage**: Monitor Cloud Run memory consumption through Cloud Monitoring
- **Cost Optimization**: Use scale-to-zero for development to minimize costs

## Security

- **Service Account**: Cloud Run uses a dedicated service account with least-privilege IAM roles
- **VPC Isolation**: Redis is deployed in a private subnet with no public IP
- **Private Google Access**: Enabled for private subnet resources to access Google APIs
- **Redis Authentication**: Memorystore Redis requires password-based authentication
- **TLS Encryption**: Redis connections use TLS for data in transit

## Cost Optimization

### Monthly Cost Estimate (us-central1)

**Cloud Run Pricing**:
- CPU: $0.00002400 per vCPU-second
- Memory: $0.00000250 per GiB-second
- Requests: $0.40 per million requests

**Additional Costs**:
- **VPC Connector**: ~$7/month per instance
- **Cloud NAT**: ~$1/month + $0.045/GB processed
- **Memorystore Redis** (Basic, 1GB): ~$35/month
- **API Gateway**: $3 per million calls
- **Artifact Registry**: $0.10/GB storage per month
- **Cloud Logging**: First 50 GB/month free, then $0.50/GB

### Cost-Saving Tips

1. **Use Scale-to-Zero for Development**
   ```hcl
   min_instance_count = 0  # No idle cost
   ```

2. **Right-Size Resources**
   - Monitor Cloud Run metrics to find optimal CPU/memory
   - Reduce timeout to minimum needed
   - Use smaller memory allocations when possible

3. **Clean Up Unused Resources**
   - Delete old container images from Artifact Registry
   - Remove unused Redis instances
   - Destroy test deployments when not needed
