# ---------------------------------------------------------------------------
# VPC (created only when var.vpc_id is null)
#
# Layout: 2 AZs, each with a public subnet (worker tasks, public IP, no inbound
# traffic allowed) and a private subnet without any route to the internet
# (RDS, ElastiCache). No NAT gateway, to keep the idle cost low; see README for
# the NAT alternative.
# ---------------------------------------------------------------------------

locals {
  create_vpc = var.vpc_id == null
  az_count   = 2

  vpc_id = local.create_vpc ? aws_vpc.this[0].id : var.vpc_id

  worker_subnet_ids = local.create_vpc ? aws_subnet.public[*].id : var.subnet_ids
  data_subnet_ids   = local.create_vpc ? aws_subnet.private[*].id : var.subnet_ids
}

data "aws_availability_zones" "available" {
  count = local.create_vpc ? 1 : 0
  state = "available"
}

resource "aws_vpc" "this" {
  count = local.create_vpc ? 1 : 0

  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  count = local.create_vpc ? 1 : 0

  vpc_id = aws_vpc.this[0].id
  tags   = { Name = "${local.prefix}-igw" }
}

resource "aws_subnet" "public" {
  count = local.create_vpc ? local.az_count : 0

  vpc_id                  = aws_vpc.this[0].id
  availability_zone       = data.aws_availability_zones.available[0].names[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false

  tags = { Name = "${local.prefix}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count = local.create_vpc ? local.az_count : 0

  vpc_id            = aws_vpc.this[0].id
  availability_zone = data.aws_availability_zones.available[0].names[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 100)

  tags = { Name = "${local.prefix}-private-${count.index}" }
}

resource "aws_route_table" "public" {
  count = local.create_vpc ? 1 : 0

  vpc_id = aws_vpc.this[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }

  tags = { Name = "${local.prefix}-public" }
}

resource "aws_route_table_association" "public" {
  count = local.create_vpc ? local.az_count : 0

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# Private subnets keep the VPC main route table (local routes only).

# ---------------------------------------------------------------------------
# Security groups (least privilege)
#   worker  -> db:5432, redis:6379, 443 (image pull, Secrets Manager, Logs); no inbound
#   db      <- worker:5432 only
#   redis   <- worker:6379 only
# ---------------------------------------------------------------------------

resource "aws_security_group" "worker" {
  name        = "${local.prefix}-worker"
  description = "sagaz outbox worker tasks"
  vpc_id      = local.vpc_id

  tags = { Name = "${local.prefix}-worker" }

  lifecycle {
    precondition {
      condition     = (var.vpc_id == null) == (var.subnet_ids == null)
      error_message = "vpc_id and subnet_ids must be set together (or both left null to create a VPC)."
    }
    precondition {
      condition     = var.subnet_ids == null || length(coalesce(var.subnet_ids, [])) >= 2
      error_message = "subnet_ids needs at least 2 subnets in different availability zones (RDS and ElastiCache subnet groups require it)."
    }
  }
}

resource "aws_security_group" "db" {
  name        = "${local.prefix}-db"
  description = "sagaz PostgreSQL (RDS)"
  vpc_id      = local.vpc_id

  tags = { Name = "${local.prefix}-db" }
}

resource "aws_security_group" "redis" {
  name        = "${local.prefix}-redis"
  description = "sagaz Redis (ElastiCache)"
  vpc_id      = local.vpc_id

  tags = { Name = "${local.prefix}-redis" }
}

resource "aws_vpc_security_group_egress_rule" "worker_to_db" {
  security_group_id            = aws_security_group.worker.id
  description                  = "PostgreSQL"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_egress_rule" "worker_to_redis" {
  security_group_id            = aws_security_group.worker.id
  description                  = "Redis"
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  referenced_security_group_id = aws_security_group.redis.id
}

resource "aws_vpc_security_group_egress_rule" "worker_https" {
  security_group_id = aws_security_group.worker.id
  description       = "HTTPS: image registry, Secrets Manager, CloudWatch Logs"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_worker" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from workers"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.worker.id
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_worker" {
  security_group_id            = aws_security_group.redis.id
  description                  = "Redis from workers"
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  referenced_security_group_id = aws_security_group.worker.id
}
