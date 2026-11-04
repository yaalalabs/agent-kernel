# ---------------------------------------------------------------------------
# Shared security groups for the aws-containerized weekly integration tests (#823)
#
# Long-lived, never destroyed by CI (security groups are free; ECS is not). Each weekly run
# re-applies this stack and passes the IDs into every aws-containerized example, which then skips
# creating its own. Rules mirror the SGs the ak-containerized module creates when none are given
# (ak-deployment/ak-aws/containerized/modules/rest-service and modules/agent-runner).
# ---------------------------------------------------------------------------

data "aws_vpc" "base" {
  id = var.vpc_id
}

locals {
  tags = {
    Purpose   = "ak-weekly-integration-tests"
    ManagedBy = ".github/ci-infra/aws-containerized-shared-sgs"
  }
}

resource "aws_security_group" "alb" {
  name        = "${var.prefix}-ecs-alb-sg"
  description = "Shared ALB SG for aws-containerized weekly integration tests"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.base.cidr_block]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "ecs_service" {
  name        = "${var.prefix}-ecs-svc-sg"
  description = "Shared ECS service SG for aws-containerized weekly integration tests"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "agent_runner" {
  name        = "${var.prefix}-agent-runner-sg"
  description = "Shared Agent Runner SG for aws-containerized weekly integration tests - egress only (queue-polling)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}
