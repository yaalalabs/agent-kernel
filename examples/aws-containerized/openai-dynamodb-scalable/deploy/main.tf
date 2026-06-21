provider "aws" {
  region = var.region
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.11.0"
    }
    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }
  }
  required_version = ">= 1.9.5"
}

data "aws_ecr_authorization_token" "token" {}
data "aws_caller_identity" "current" {}

provider "docker" {
  registry_auth {
    address  = format("%v.dkr.ecr.%v.amazonaws.com", data.aws_caller_identity.current.account_id, var.region)
    username = data.aws_ecr_authorization_token.token.user_name
    password = data.aws_ecr_authorization_token.token.password
  }
}

# ---------------------------------------------------------------------------
# Containerized Agents Deployment
# ---------------------------------------------------------------------------
module "containerized_agents" {
  # When using from registry:
  source  = "yaalalabs/ak-containerized/aws"
  version = "0.5.1"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "OpenAI Agents - Scalable"

  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids


  # ---- REST Service Configuration ----
  # In queue mode, this service handles HTTP requests and manages the queue interaction
  rest_service = {
    package_path          = "../dist-rest-service"
    cpu                   = 256
    memory                = 512
    desired_count         = 1
    container_port        = 8000
    health_check_endpoint = "/health"
    # Override the Docker CMD to specify the correct entrypoint
    command = ["python", "app_rest_service.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # ---- Agent Memory (Session Store) ----
  # DynamoDB table to store agent conversation history and state
  create_dynamodb_memory_table = true

  # ---- Queue Mode ----
  # Enable queue-based execution for scalable, async processing
  enable_queue_mode = true
  queue_mode_type   = "sync" # "async" | "sync"

  # ---- Queue Configuration ----
  # SQS queues for request/response handling
  queue_config = {
    # Optional: customize queue names
    input_queue_name  = "input-queue"  # Default
    output_queue_name = "output-queue" # Default

    # Input queue settings (requests from REST service to agent runner)
    input_queue_visibility_timeout        = 120 # Should be >= agent processing time
    input_queue_message_retention_seconds = 1800
    input_queue_max_receive_count         = 3
    input_queue_create_dlq                = true

    # Output queue settings (responses from agent runner to REST service)
    output_queue_visibility_timeout        = 60
    output_queue_message_retention_seconds = 1800
    output_queue_max_receive_count         = 3
    output_queue_create_dlq                = true

    # Shared settings
    sqs_managed_sse_enabled   = true
    max_message_size          = 262144 # 256 KB
    receive_wait_time_seconds = 0      # Long polling disabled
  }

  # ---- Agent Runner Configuration ----
  # Separate ECS service that processes messages from the input queue
  # This runs the actual agent logic
  agent_runner = {
    cpu           = 1024
    memory        = 2048
    desired_count = 1
    # Provide package_path to build a separate Docker image for agent runner
    package_path = "../dist-agent-runner"
    # Override the Docker CMD to specify the correct entrypoint
    command = ["python", "app_agent_runner.py"]
    environment_variables = {
      OPENAI_API_KEY = var.openai_api_key
    }
  }

  # ---- Agent Runner Auto Scaling ----
  # Scale based on queue depth (BacklogPerTask metric)
  scaling_config = {
    enabled = true

    # Scaling limits
    min_count = 1  # Minimum tasks (can be 0 to scale to zero)
    max_count = 10 # Maximum tasks

    # Scaling behavior
    backlog_target = 10 # Target messages per task (scale up when exceeded)
    # Lower values = more aggressive scaling
    # Example: backlog_target = 5 means scale up when >5 msgs per task

    # Cooldown periods (prevent flapping)
    scale_in_cooldown  = 120 # Wait 2min before scaling in again
    scale_out_cooldown = 30  # Wait 30s before scaling out again
  }

  tags = {
    Example     = "openai-dynamodb-scalable"
    Environment = var.env_alias
  }
}
