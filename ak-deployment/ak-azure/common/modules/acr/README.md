# ACR Module

A Terraform module for building Docker container images and storing them in Azure Container Registry (ACR) for Azure Container Apps deployments.

## 📋 Overview

This module automates the complete Docker image lifecycle for containerized applications:

- 🏗️ Creates and manages Azure Container Registry with standardized naming and subscription-based suffixes
- 🐳 Builds Docker images from source code with automatic change detection
- 📦 Provides ready-to-use image URIs and authentication credentials for Container Apps deployments
- 🔍 Tracks source code changes to trigger automatic rebuilds
- 🔐 Enables admin access for seamless Docker registry authentication

Perfect for containerized workloads requiring automated image management with Azure Container Apps.

## 📋 Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.9.5 |
| Docker Provider | 3.6.2 |
| AzureRM Provider | >=4.57.0 |
| Docker | Latest |

## 🚀 Usage

### Basic Example

```hcl
module "api_container" {
  source = "yaalalabs/ak-common/azure//modules/acr"

  product_alias       = "myapp"
  env_alias           = "prod"
  module_name         = "api"
  source_path         = "src/api"
  resource_group_name = "myapp-prod-rg"
  region              = "eastus"
}

# Use the image URI in Container App
resource "azurerm_container_app" "api" {
  name                         = "myapp-prod-api-app"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  # Registry configuration for ACR
  registry {
    server               = module.api_container.login_server
    username             = module.api_container.admin_username
    password_secret_name = "acr-password"
  }

  # Secret for ACR password
  secret {
    name  = "acr-password"
    value = module.api_container.admin_password
  }

  template {
    container {
      name   = "api"
      image  = "${module.api_container.docker_image_uri}:latest"
      cpu    = 0.5
      memory = "1Gi"
    }
  }
}
```

### Multi-Environment Setup

```hcl
# Development environment
module "dev_container" {
  source = "yaalalabs/ak-common/azure//modules/acr"

  product_alias       = "myapp"
  env_alias           = "dev"
  module_name         = "worker"
  source_path         = "src/worker"
  resource_group_name = "myapp-dev-rg"
  region              = "eastus"
  enabled             = true
}

# Production environment
module "prod_container" {
  source = "../common/modules/acr"

  product_alias       = "myapp"
  env_alias           = "prod"
  module_name         = "worker"
  source_path         = "src/worker"
  resource_group_name = "myapp-prod-rg"
  region              = "eastus"
  enabled             = true
}
```

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `region` | Azure region for ACR deployment(Match with Resource Group name for cost Optimizations) | `string` | `"eastus"` | no |
| `product_alias` | Short identifier for the product (e.g., "myapp") | `string` | n/a | yes |
| `env_alias` | Environment identifier (e.g., "dev", "staging", "prod") | `string` | n/a | yes |
| `module_name` | Module/service name for resource identification | `string` | n/a | yes |
| `source_path` | Path to directory containing Dockerfile and source code | `string` | n/a | yes |
| `resource_group_name` | Name of the Azure resource group | `string` | n/a | yes |
| `enabled` | Enable or disable the module | `bool` | `true` | no |

## 📤 Outputs

| Name | Description | Example |
|------|-------------|---------|
| `docker_image_uri` | Complete ACR image URI for Container Apps deployment | `myappprodreg123abc.azurecr.io/myapp-prod-api` |
| `login_server` | ACR registry login server URL | `myappprodreg123abc.azurecr.io` |
| `admin_username` | ACR admin username for authentication | `myappprodreg123abc` |
| `admin_password` | ACR admin password for authentication (sensitive) | `***` |

## ✨ Features

### 🏗️ Automated Docker Build

- **Change Detection**: Monitors source files and triggers rebuilds automatically using SHA-based file tracking
- **Build Optimization**: Uses `no_cache = true` to ensure fresh builds with latest dependencies
- **Automatic Authentication**: Handles ACR authentication using admin credentials
- **Remote Registry Push**: Automatically pushes built images to ACR with `keep_remotely = true`

### 📦 Registry Management

- **Naming Convention**: Creates registries with pattern `{product_alias}{env_alias}{module_name}{subscription_suffix}`
- **Subscription Suffix**: Adds 6-character SHA1 hash of subscription ID to ensure global uniqueness
- **Basic SKU**: Uses cost-effective Basic SKU for standard workloads
- **Admin Access**: Enables admin user for simplified authentication workflows

### 🔒 Security

- **Private Registries**: All registries are private by default
- **Admin Authentication**: Provides admin username/password for secure access
- **Sensitive Outputs**: Admin password is marked as sensitive in Terraform state
- **Resource Group Integration**: Inherits location and security settings from existing resource group

## 📁 Source Directory Structure

Your source directory should contain a `Dockerfile` and application code:

```
src/
├── Dockerfile          # Required: Docker build instructions
├── requirements.txt    # Python dependencies (if applicable)
├── package.json        # Node.js dependencies (if applicable)
└── app/               # Application code
    ├── main.py
    └── utils.py
```

### Example Dockerfile for Python Container App

```dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Set the CMD to your application
CMD ["python", "-m", "app.main"]
```

## 🎯 Best Practices

1. **Use Multi-Stage Builds**: Reduce image size by using multi-stage Dockerfiles
2. **Pin Base Images**: Specify exact base image versions for reproducibility
3. **Minimize Layers**: Combine RUN commands to reduce image layers
4. **Use .dockerignore**: Exclude unnecessary files from build context (especially `__pycache__` folders)
5. **Tag Strategy**: The module automatically uses `:latest` tag - consider implementing versioning for production

## 🔍 Troubleshooting

### Build Fails with "No such file or directory"

**Issue**: Dockerfile not found in source_path
```
Error: Failed to build Docker image
```

**Solution**: Ensure your source_path contains a valid Dockerfile:
```bash
ls -la path/to/source/code/Dockerfile
```

### Registry Name Too Long

**Issue**: ACR registry name exceeds Azure limits
```
Error: Registry name must be between 5 and 50 characters
```

**Solution**: The module automatically handles this by:
- Removing special characters and converting to lowercase
- Adding subscription suffix for uniqueness
- Ensure `product_alias + env_alias + module_name` is reasonably short

### Authentication Errors

**Issue**: Container App cannot pull from ACR
```
Error: Failed to pull image
```

**Solution**: Ensure you're using the module outputs correctly:
```hcl
registry {
  server               = module.docker_image.login_server
  username             = module.docker_image.admin_username
  password_secret_name = "acr-password"
}

secret {
  name  = "acr-password"
  value = module.docker_image.admin_password
}
```

### File Changes Not Detected

**Issue**: Docker image not rebuilding after code changes
```
No changes detected in source files
```

**Solution**: The module tracks all files except `__pycache__`. Ensure:
- Files are actually changed (not just timestamps)
- No caching issues in your local Docker environment
- The `triggers` block is working with `dir_sha` changes

## 📚 Additional Resources

- [Azure Container Registry Documentation](https://docs.microsoft.com/en-us/azure/container-registry/)
- [Azure Container Apps](https://docs.microsoft.com/en-us/azure/container-apps/)
- [Docker Best Practices](https://docs.docker.com/build/building/best-practices/)

## 🔗 Related Modules

- [Container App Module](../../containerized/) - For complete Container Apps deployments

---

**Note**: This module requires Docker to be installed and running on the machine where Terraform is executed. The module uses the Docker provider to build and push images to ACR.