locals {
  rest_service_environment = merge(
    var.rest_service.environment_variables,
    var.redis_url != null ? {
      AK_SESSION__REDIS__URL = var.redis_url
    } : {},
    var.dynamodb_memory_table_arn != null ? {
      AK_SESSION__DYNAMODB__TABLE_NAME = var.dynamodb_memory_table_name
    } : {},
    # Queue mode — inject queue URLs and response store table name
    var.enable_queue_mode ? {
      AK_EXECUTION__QUEUES__INPUT__URL                   = var.input_queue_url
      AK_EXECUTION__QUEUES__OUTPUT__URL                  = var.output_queue_url
      AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = var.response_store_table_name
    } : {}
  )
}

# ---------- Service Discovery ----------

resource "aws_service_discovery_http_namespace" "this" {
  name        = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  description = "CloudMap namespace for ${var.product_alias}-${var.env_alias}-${var.module_name}"
  tags        = var.tags
}

# ---------- IAM Policies ----------

resource "aws_iam_policy" "dynamodb_policy" {
  count       = var.dynamodb_memory_table_arn != null ? 1 : 0
  name        = "${var.product_alias}-${var.env_alias}-${var.module_name}-dynamodb-policy"
  description = "Policy for DynamoDB access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          var.dynamodb_memory_table_arn,
          "${var.dynamodb_memory_table_arn}/index/*"
        ]
      }
    ]
  })

  tags = var.tags
}

# ---------- Security Groups ----------

resource "aws_security_group" "ecs_alb" {
  name        = "${var.product_alias}-${var.env_alias}-ecs-alb-sg"
  description = "ALB SG for ECS"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_security_group" "ecs_service" {
  name        = "${var.product_alias}-${var.env_alias}-ecs-svc-sg"
  description = "ECS service SG"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = var.rest_service.container_port
    to_port         = var.rest_service.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

# ---------- Load Balancer ----------

resource "aws_lb" "app" {
  name               = "${var.product_alias}-${var.env_alias}-${var.module_name}-alb"
  internal           = true
  load_balancer_type = "application"
  subnets            = var.subnet_ids
  security_groups    = [aws_security_group.ecs_alb.id]

  tags = var.tags
}

resource "aws_lb_target_group" "app" {
  name        = "${var.product_alias}-${var.env_alias}-tg"
  port        = var.rest_service.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path                = var.rest_service.health_check_endpoint
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200-399"
  }

  tags = var.tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }

  tags = var.tags
}

# ---------- ECS Service ----------

module "ecs_service" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "6.10.0"

  name           = var.service_name
  cluster_arn    = var.ecs_cluster_arn
  cpu            = var.rest_service.cpu
  memory         = var.rest_service.memory
  desired_count  = var.rest_service.desired_count
  launch_type    = "FARGATE"
  platform_version = "LATEST"
  subnet_ids     = var.subnet_ids
  security_group_ids = [aws_security_group.ecs_service.id]

  load_balancer = {
    service = {
      target_group_arn = aws_lb_target_group.app.arn
      container_name   = var.container_name
      container_port   = var.rest_service.container_port
    }
  }

  service_connect_configuration = {
    namespace = aws_service_discovery_http_namespace.this.arn
    service = [
      {
        client_alias = {
          port     = var.rest_service.container_port
          dns_name = var.container_name
        }
        port_name      = var.container_name
        discovery_name = var.container_name
      }
    ]
  }

  # Attach DynamoDB access to the task role if a memory table exists
  create_tasks_iam_role   = true
  tasks_iam_role_policies = var.dynamodb_memory_table_arn != null ? {
    DynamoDB = aws_iam_policy.dynamodb_policy[0].arn
  } : {}

  container_definitions = {
    (var.container_name) = {
      cpu                    = var.rest_service.cpu
      memory                 = var.rest_service.memory
      image                  = var.rest_service.image_uri
      essential              = true
      readonlyRootFilesystem = false

      # Command override - if provided, replaces the Docker image's CMD
      command = var.rest_service.command

      portMappings = [
        {
          name          = var.container_name,
          containerPort = var.rest_service.container_port,
          hostPort      = var.rest_service.container_port,
          protocol      = "tcp",
        }
      ]
      enable_cloudwatch_logging = true
      environment = [
        for k, v in local.rest_service_environment : {
          name  = k
          value = v
        }
      ]

      health_check = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:${var.rest_service.container_port}${var.rest_service.health_check_endpoint} || exit 1"],
        interval    = 30,
        timeout     = 5,
        retries     = 3,
        startPeriod = 10
      }
      log_configuration = {
        logDriver = "awslogs",
        options = {
          awslogs-group         = "/ecs/${var.product_alias}-${var.env_alias}-${var.module_name}",
          awslogs-region        = var.region,
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  }

  tags = var.tags
}
