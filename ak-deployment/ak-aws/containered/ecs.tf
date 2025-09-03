module "ecs" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "6.3.0"

  cluster_name = "${var.product_alias}-${var.env_alias}-${var.module_name}"

  services = {
    app = {
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
          container_name   = "app"
          container_port   = var.ecs_container_port
        }
      }


      container_definitions = {
        app = {
          cpu                      = var.ecs_cpu
          memory                   = var.ecs_memory
          image                    = module.docker_image[0].docker_image_uri
          essential                = true
          readonly_root_filesystem = false
          port_mappings = [
            {
              name          = "app",
              containerPort = var.ecs_container_port,
              hostPort      = var.ecs_container_port,
              protocol      = "tcp",
              appProtocol   = "http"
            }
          ]
          enable_cloudwatch_logging = true
          environment = [
            for k, v in merge(var.environment_variables, {
              AK_REDIS_HOST   = local.redis_host,
              AK_REDIS_PORT   = tostring(local.redis_port),
              AK_REDIS_PREFIX = "${var.product_alias}:${var.env_alias}:${var.module_name}:"
            }) : {
              name  = k
              value = v
            }
          ]

          health_check = {
            command = ["CMD-SHELL", "curl -sf http://localhost:${var.ecs_container_port}${var.ecs_health_check_path} || exit 1"],
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
  name     = "${var.product_alias}-${var.env_alias}-tg"
  port     = var.ecs_container_port
  protocol = "HTTP"
  vpc_id   = local.vpc_id
  health_check {
    path                = var.ecs_health_check_path
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