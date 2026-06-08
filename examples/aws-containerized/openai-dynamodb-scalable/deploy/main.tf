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
# Agent Runner image - built from dist-agent-runner/
# ---------------------------------------------------------------------------
module "agent_runner_image" {
  # Points to the local ECR module.
  # Switch to registry once published:
  source  = "yaalalabs/ak-common/aws//modules/ecr"
  version = "0.4.0"


  env_alias     = var.env_alias
  module_name   = "${var.module_name}-runner"
  product_alias = var.product_alias
  source_path   = "../dist-agent-runner"
}

module "containerized_agents" {
  source = "yaalalabs/ak-containerized/aws"
  version = "0.4.0"

  product_alias        = var.product_alias
  env_alias            = var.env_alias
  module_name          = var.module_name
  region               = var.region
  product_display_name = "OpenAI Agents - Scalable"

  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids

  # ---- REST Service image (Thread 1 + Thread 2) ----
  package_path       = "../dist-rest-service"
  container_type     = "ecs"
  ecs_container_port = 8000
  
  # Override the command to use the correct entrypoint
  # The ECR module adds a Lambda-style CMD, so we override it here
  ecs_container_command = ["python", "app_rest_service.py"]

  # ---- agent memory (session store) ----
  create_dynamodb_memory_table = true

  # ---- queue mode ----
  enable_queue_mode  = true
  queue_mode_type    = "async"
  
  # Enable autoscaling for Agent Runner (optional)
  enable_agent_runner_autoscaling = true
  

  # Agent Runner uses its own image (different CMD)
  agent_runner_image_uri = module.agent_runner_image.docker_image_uri
  
  # Override the command to use the correct entrypoint
  # The ECR module adds a Lambda-style CMD, so we override it here
  agent_runner_command = ["python", "app_agent_runner.py"]

  # SQS visibility timeout should exceed agent processing time
  sqs_input_visibility_timeout  = 120
  sqs_output_visibility_timeout = 60

  # Agent Runner Fargate sizing
  agent_runner_cpu           = 1024
  agent_runner_memory        = 2048
  agent_runner_desired_count = 1

  # Agent Runner Auto Scaling (optional)
  agent_runner_min_count         = 1    # Minimum tasks (can be 0 to scale to zero)
  agent_runner_max_count         = 10   # Maximum tasks
  agent_runner_backlog_target    = 10   # Target messages per task (scale up when exceeded)
  agent_runner_scale_in_cooldown = 120  # Wait 2min before scaling in again
  agent_runner_scale_out_cooldown = 30  # Wait 30s before scaling out again

  # Environment variables for both containers
  environment_variables = {
    OPENAI_API_KEY = var.openai_api_key
  }

  tags = {
    Example = "openai-dynamodb-scalable"
  }
}
