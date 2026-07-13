resource "aws_security_group" "valkey" {
  name        = "${var.product_alias}-${var.env_alias}-${var.module_name}-valkey-sg"
  description = "Security group for Valkey cluster"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = var.port
    to_port     = var.port
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

resource "aws_elasticache_subnet_group" "valkey" {
  name       = "${var.product_alias}-${var.env_alias}-${var.module_name}-valkey-subnet"
  subnet_ids = var.subnet_ids
}

# ElastiCache exposes the Valkey engine through the replication group resource
# (aws_elasticache_cluster only supports the "memcached" and "redis" engines).
# A single-node, cluster-mode-disabled replication group provides the same
# single-primary topology the Redis module's aws_elasticache_cluster does.
resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id = "${var.product_alias}-${var.env_alias}-${var.module_name}-valkey"
  description          = "Valkey cluster for ${var.product_alias}-${var.env_alias}-${var.module_name}"
  engine               = "valkey"
  engine_version       = var.engine_version
  node_type            = var.node_type
  num_cache_clusters   = var.node_count
  parameter_group_name = var.parameter_group_name
  port                 = var.port
  subnet_group_name    = aws_elasticache_subnet_group.valkey.name
  security_group_ids   = [aws_security_group.valkey.id]
  tags                 = var.tags
}
