resource "aws_service_discovery_http_namespace" "this" {
  name        = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  description = "CloudMap namespace for ${var.product_alias}-${var.env_alias}-${var.module_name}"
  tags        = var.tags
}

resource "aws_iam_policy" "dynamodb_policy" {
  count       = var.create_dynamodb_memory_table == true ? 1 : 0
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
          local.dynamodb_memory_table_arn,
          "${local.dynamodb_memory_table_arn}/index/*"
        ]
      }
    ]
  })

  tags = var.tags
}
module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "6.10.0"

  cluster_name = "${var.product_alias}-${var.env_alias}-${var.module_name}"

  services = {
    (local.service_name) = {
      cpu                = var.ecs_cpu
      memory             = var.ecs_memory
      desired_count      = var.ecs_desired_count
      enable_autoscaling = false
      launch_type        = "FARGATE"
      platform_version   = "LATEST"
      subnet_ids         = local.subnet_ids
      security_group_ids = [aws_security_group.ecs_service.id]

      load_balancer = {
        service = {
          target_group_arn = aws_lb_target_group.app.arn
          container_name   = local.container_name
          container_port   = var.ecs_container_port
        }
      }

      service_connect_configuration = {
        namespace = aws_service_discovery_http_namespace.this.arn
        service = [
          {
            client_alias = {
              port     = var.ecs_container_port
              dns_name = local.container_name
            }
            port_name      = local.container_name
            discovery_name = local.container_name
          }
        ]
      }

      # Attach DynamoDB access to the task role if a memory table exists
      create_tasks_iam_role   = true
      tasks_iam_role_policies = var.create_dynamodb_memory_table ? {
        DynamoDB = var.create_dynamodb_memory_table ? aws_iam_policy.dynamodb_policy[0].arn : null
      } : {}

      container_definitions = {
        (local.container_name) = {
          cpu                    = var.ecs_cpu
          memory                 = var.ecs_memory
          image                  = module.docker_image[0].docker_image_uri
          essential              = true
          readonlyRootFilesystem = false
          
          # Command override - if provided, replaces the Docker image's CMD
          command = var.ecs_container_command
          
          portMappings = [
            {
              name          = local.container_name,
              containerPort = var.ecs_container_port,
              hostPort      = var.ecs_container_port,
              protocol      = "tcp",
            }
          ]
          enable_cloudwatch_logging = true
          environment               = [
            for k, v in merge(
              var.environment_variables,
              local.redis_url != null ? {
                AK_SESSION__REDIS__URL = local.redis_url
              } : {},
              local.dynamodb_memory_table_arn != null ? {
                AK_SESSION__DYNAMODB__TABLE_NAME = local.dynamodb_memory_table_name
              } : {},
              # Queue mode — inject queue URLs and response store table name
              var.enable_queue_mode ? {
                AK_EXECUTION__QUEUES__INPUT__URL                   = module.input_queue[0].queue_url
                AK_EXECUTION__QUEUES__OUTPUT__URL                  = module.output_queue[0].queue_url
                AK_EXECUTION__RESPONSE_STORE__DYNAMODB__TABLE_NAME = aws_dynamodb_table.response_store[0].name
              } : {}
            ) : {
              name  = k
              value = v
            }
          ]

          health_check = {
            command = ["CMD-SHELL", "curl -sf http://localhost:${var.ecs_container_port}${var.ecs_health_check_endpoint} || exit 1"],
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
    }
  }
}

resource "aws_security_group" "ecs_alb" {
  name        = "${var.product_alias}-${var.env_alias}-ecs-alb-sg"
  description = "ALB SG for ECS"
  vpc_id      = local.vpc_id
  ingress {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
    cidr_blocks = [local.vpc_cidr]
  }
  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs_service" {
  name        = "${var.product_alias}-${var.env_alias}-ecs-svc-sg"
  description = "ECS service SG"
  vpc_id      = local.vpc_id
  ingress {
    from_port = var.ecs_container_port
    to_port   = var.ecs_container_port
    protocol  = "tcp"
    security_groups = [aws_security_group.ecs_alb.id]
  }
  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "app" {
  name               = "${var.product_alias}-${var.env_alias}-${var.module_name}-alb"
  internal           = true
  load_balancer_type = "application"
  subnets            = local.subnet_ids
  security_groups = [aws_security_group.ecs_alb.id]
}

resource "aws_lb_target_group" "app" {
  name        = "${var.product_alias}-${var.env_alias}-tg"
  port        = var.ecs_container_port
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"
  health_check {
    path                = var.ecs_health_check_endpoint
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
    matcher             = "200-399"
  }
}


resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}