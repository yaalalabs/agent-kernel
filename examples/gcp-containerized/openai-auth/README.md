# Agent Kernel running OpenAI Agents SDK based agents in GCP Containerized (Cloud Run) with JWT Authentication

This package contains a demo of Agent Kernel running agents built with OpenAI Agents SDK, running them in a containerized configuration on GCP Cloud Run with always-on capability (min_instance_count≥1), Redis for session storage, and JWT authentication via API Gateway.

## Deployed Resources

This demo deploys the following GCP resources:

- **Cloud Run Service** - Fully managed container platform with always-on capability (min_instance_count defaults to 1)
- **API Gateway** - OpenAPI-based routing with versioned endpoints and JWT authorization support
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

Agent conversations and memory are persisted in Memorystore Redis with the prefix `ak:openai-cloudrun-auth:example:`.

The application also exposes custom endpoints:
- `GET /version` - Returns application version information
- `POST /app_info` - Returns application information

**JWT Authentication**: This example demonstrates JWT authorization at the API Gateway level. All requests to the API Gateway must include a valid JWT token in the `Authorization` header.

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
min_instance_count = 1         # Always-on (no cold starts)
max_instance_count = 10        # Maximum instances
timeout = 30                   # Request timeout in seconds

# API Gateway configuration
api_version = "v1"              # API version for endpoint path
api_base_path = "api"          # Base path segment for API
agent_endpoint = "chat"         # Default API endpoint name

# JWT Authorization configuration
authorizer = {
  issuer    = "https://accounts.google.com"                      # JWT issuer URL
  jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"      # JWKS endpoint
  audiences = ["your-client-id.apps.googleusercontent.com"]     # Expected JWT audiences
}

# Restrict direct Cloud Run access (force traffic through API Gateway)
allow_unauthenticated_invocation = false

# Custom gateway endpoints
gateway_endpoints = [
  {
    path           = "version"
    method         = "GET"
    overwrite_path = "/version"
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
   - `authorizer.audiences` - Your Google OAuth client ID for JWT validation

3. **Navigate to the deployment directory and run the deployment script:**
   ```bash
   cd deploy && ./deploy.sh
   ```
   
   For local development with locally built dependencies:
   ```bash
   cd deploy && ./deploy.sh local
   ```

## Usage

After successful deployment, you can interact with the agents through the API Gateway endpoint with JWT authentication:

```bash
# Get the API URL from Terraform outputs
API_URL=$(terraform output -raw agent_invoke_url)

# Get a JWT token (example using Google OAuth)
# In production, your application should obtain this through OAuth flow
JWT_TOKEN="your-jwt-token-here"

# Send a math question to the triage agent with JWT authentication
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  -d '{
    "message": "What is the square root of 144?",
    "session_id": "user123"
  }'

# Send a history question
curl -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  -d '{
    "message": "Tell me about the American Civil War",
    "session_id": "user123"
  }'

# Use the custom version endpoint
curl -X GET "$(terraform output -raw gateway_url)/api/v1/version" \
  -H "Authorization: Bearer ${JWT_TOKEN}"

# Use the custom app_info endpoint
curl -X POST "$(terraform output -raw gateway_url)/api/v1/app_info" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${JWT_TOKEN}"
```

**Note**: Direct access to the Cloud Run service URL is blocked (`allow_unauthenticated_invocation = false`). All requests must go through the API Gateway with valid JWT authentication.

## Outputs

The deployment provides the following outputs:

- `service_url` - Direct Cloud Run service URL (requires authentication)
- `service_name` - Cloud Run service name
- `gateway_url` - API Gateway base URL
- `agent_invoke_url` - Full agent invocation URL via API Gateway
- `api_gateway_id` - API Gateway ID
- `authorizer_status` - JWT authorizer configuration status

## Agent Memory

This example uses Memorystore Redis for agent memory storage. The configuration in `config.yaml` specifies:

```yaml
debug: true
session:
  type: redis
  redis:
    prefix: "ak:openai-cloudrun-auth:example:"
```

All agent conversations and session data are automatically stored in Redis with the specified prefix, enabling persistent conversations across requests.

**Redis Environment Variables (Auto-injected when enabled)**:
- `AK_SESSION__REDIS__URL`: Complete Redis connection URL with authentication

## JWT Authentication

This example demonstrates JWT authorization at the API Gateway level:

### How JWT Authentication Works

1. **Client Request**: Client includes JWT token in `Authorization: Bearer <token>` header
2. **API Gateway Validation**: API Gateway validates the JWT token against the configured authorizer
3. **Token Verification**: Verifies issuer, audience, and signature using JWKS endpoint
4. **Forward to Cloud Run**: If valid, request is forwarded to Cloud Run service
5. **Direct Access Blocked**: Direct access to Cloud Run URL is blocked without authentication

### Authorizer Configuration

```hcl
authorizer = {
  issuer    = "https://accounts.google.com"                      # JWT issuer URL
  jwks_uri  = "https://www.googleapis.com/oauth2/v3/certs"      # JWKS endpoint
  audiences = ["your-client-id.apps.googleusercontent.com"]     # Expected JWT audiences
}
```

### Obtaining a JWT Token

For testing purposes, you can obtain a Google OAuth token:

```bash
# Get OAuth token
gcloud auth print-identity-token
```

In production, your application should implement proper OAuth 2.0 flow to obtain tokens from your identity provider.

## Cloud Run Configuration

The Cloud Run service is configured with:
- **Runtime**: Python container with always-on capability
- **Scaling**: `min_instance_count = 1` for always-on behavior (no cold starts)
- **CPU**: 1 vCPU (configurable)
- **Memory**: 512Mi (configurable)
- **Timeout**: 30 seconds (configurable)
- **Port**: 8000
- **Authentication**: Unauthenticated invocation blocked (API Gateway only)

**Key Difference from Serverless**: This module defaults to `min_instance_count = 1` (always-on, no cold starts), while the serverless module defaults to `min_instance_count = 0` (scale-to-zero). Both use Cloud Run, but with different scaling configurations.

## Monitoring and Logging

The deployment includes comprehensive monitoring:
- **Cloud Logging** - Automatic collection of Cloud Run logs and application logs
- **Cloud Monitoring** - Metrics for Cloud Run performance and resource utilization
- **API Gateway Logs** - API request tracking, authentication failures, and error rates

Access these through the GCP Console to monitor your agent's performance and usage patterns.

## Clean Up

To remove all deployed resources:

```bash
cd deploy
terraform destroy
```

## Troubleshooting

### Common Issues

1. **JWT Authentication Fails**
   - Verify the JWT token is valid and not expired
   - Check that the token's `iss` claim matches the configured `issuer`
   - Ensure the token's `aud` claim matches one of the configured `audiences`
   - Verify the JWKS endpoint is accessible

2. **Project Not Found**
   - Ensure the project ID specified in `terraform.tfvars` exists in your GCP account
   - Verify you have appropriate permissions on the project

3. **OpenAI API Key Issues**
   - Verify your OpenAI API key is valid and has sufficient credits
   - Check that the variable is properly set in `terraform.tfvars` or exported as an environment variable

4. **Cloud Run Deployment Issues**
   - Check Cloud Run logs in the GCP Console
   - Verify the Docker image was built and pushed successfully to Artifact Registry
   - Ensure the container port matches the configuration (default: 8000)

5. **Redis Connection Issues**
   - Verify the VPC Access Connector is properly configured
   - Check firewall rules allow traffic from Cloud Run to Redis
   - Ensure Redis instance is in the same region as Cloud Run

6. **API Gateway Issues**
   - Verify the OpenAPI specification is valid
   - Check API Gateway logs for authentication errors
   - Ensure backend service URL is correct

### Debugging JWT Issues

```bash
# Decode JWT to verify claims
echo ${JWT_TOKEN} | cut -d'.' -f2 | base64 -d | jq

# Check API Gateway logs for authentication failures
gcloud logging read "resource.type=api AND resource.labels.service=${GATEWAY_ID}" \
  --limit 20
```

## Performance Considerations

- **Always-On**: With `min_instance_count = 1`, the service maintains at least one instance running, eliminating cold starts but incurring idle costs
- **No Cold Starts**: Requests are processed immediately without startup latency
- **JWT Validation**: API Gateway validates JWTs on every request, adding minimal latency (~10-20ms)
- **Redis Connection**: Connection pooling is handled automatically by the Agent Kernel
- **Memory Usage**: Monitor Cloud Run memory consumption through Cloud Monitoring
- **Cost Optimization**: Use scale-to-zero (min_instance_count = 0) for development to minimize costs

## Security

- **JWT Authorization**: API Gateway validates JWT tokens before forwarding requests to Cloud Run
- **Service Account**: Cloud Run uses a dedicated service account with least-privilege IAM roles
- **VPC Isolation**: Redis is deployed in a private subnet with no public IP
- **Private Google Access**: Enabled for private subnet resources to access Google APIs
- **Redis Authentication**: Memorystore Redis requires password-based authentication
- **TLS Encryption**: Redis connections use TLS for data in transit
- **Direct Access Blocked**: Cloud Run service cannot be accessed directly without authentication

## Cost Optimization

### Monthly Cost Estimate (us-central1)

**Cloud Run Pricing**:
- CPU: $0.00002400 per vCPU-second
- Memory: $0.00000250 per GiB-second
- Requests: $0.40 per million requests

**Idle Cost with Always-On**:
```
With min_instance_count = 1:
- CPU idle: 1 vCPU × 730 hours/month × $0.000024 = $17.52/month
- Memory idle: 0.5 GiB × 730 hours/month × $0.0000025 = $0.91/month
- Total idle cost: ~$18.43/month (even with zero requests)
```

**Additional Costs**:
- **VPC Connector**: ~$7/month per instance
- **Cloud NAT**: ~$1/month + $0.045/GB processed
- **Memorystore Redis** (Basic, 1GB): ~$35/month
- **API Gateway**: $3 per million calls
- **Artifact Registry**: $0.10/GB storage per month
- **Cloud Logging**: First 50 GB/month free, then $0.50/GB

### Cost Comparison: Serverless vs Containerized

| Configuration | min_instances | Cloud Run (idle) | Cloud Run (requests) | Total/Month |
|---------------|---------------|-----------------|---------------------|-------------|
| Serverless (dev) | 0 | $0 | $3 | ~$3 |
| Containerized (dev) | 1 | $18 | $3 | ~$21 |
| Containerized (prod) | 2 | $36 | $10 | ~$46 |

### Cost-Saving Tips

1. **Use Scale-to-Zero for Development**
   ```hcl
   min_instance_count = 0  # No idle cost, but cold starts
   ```
   Consider using the serverless module for development to save costs.

2. **Right-Size Resources**
   - Monitor Cloud Run metrics to find optimal CPU/memory
   - Reduce timeout to minimum needed
   - Use smaller memory allocations when possible

3. **Optimize Redis Usage**
   - Use Redis Basic tier for development
   - Consider Redis Standard tier with HA for production
   - Monitor Redis memory usage and optimize data structures

4. **Clean Up Unused Resources**
   - Delete old container images from Artifact Registry
   - Remove unused Redis instances
   - Destroy test deployments when not needed

## When to Use Containerized vs Serverless

### Use Containerized (min_instance_count ≥ 1) when:
- You need guaranteed low latency without cold starts
- Your application has consistent, high traffic
- You're running in production environments
- You need predictable performance
- Cost is less critical than performance
- You need JWT authentication with always-on availability

### Use Serverless (min_instance_count = 0) when:
- You're developing or testing
- Your application has intermittent or low traffic
- Cost optimization is a priority
- You can tolerate occasional cold starts
- You're running in non-production environments
