resource "aws_security_group" "redis" {
  name        = "${var.prefix}-redis-sg"
  description = "Security group for Redis cluster"
  vpc_id      = var.vpc_id

  ingress {
    from_port = var.port
    to_port   = var.port
    protocol  = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.prefix}-redis-subnet"
  subnet_ids = var.subnet_ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.prefix}-redis"
  engine               = "redis"
  node_type            = var.node_type
  num_cache_nodes      = var.node_count
  parameter_group_name = "default.redis7"
  port                 = var.port
  security_group_ids = [aws_security_group.redis.id]
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  tags                 = var.tags
}
