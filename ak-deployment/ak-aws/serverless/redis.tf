resource "aws_security_group" "redis" {
  name        = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-sg"
  description = "Security group for Redis cluster"
  vpc_id      = local.vpc_id

  ingress {
    from_port = 6379
    to_port   = 6379
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
  name       = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis-subnet"
  subnet_ids = local.subnet_ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.product_alias}-${var.env_alias}-${var.module_name}-redis"
  engine               = "redis"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  security_group_ids = [aws_security_group.redis.id]
  subnet_group_name    = aws_elasticache_subnet_group.redis.name

  tags = var.tags
}
