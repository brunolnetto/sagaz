# ---------------------------------------------------------------------------
# RDS PostgreSQL (saga + outbox storage)
#
# A custom parameter group is always created so switching outbox_mode to "cdc"
# only flips rds.logical_replication (a static parameter: the instance must be
# rebooted before it takes effect, see README).
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${local.prefix}-db"
  subnet_ids = local.data_subnet_ids

  tags = { Name = "${local.prefix}-db" }
}

resource "aws_db_parameter_group" "this" {
  name_prefix = "${local.prefix}-pg"
  family      = "postgres${split(".", var.db_engine_version)[0]}"
  description = "sagaz PostgreSQL parameters (outbox_mode=${var.outbox_mode})"

  # Require TLS for every client connection.
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  dynamic "parameter" {
    for_each = local.cdc_enabled ? [1] : []
    content {
      name         = "rds.logical_replication"
      value        = "1"
      apply_method = "pending-reboot"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

resource "aws_db_instance" "this" {
  identifier = "${local.prefix}-db"

  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  allocated_storage     = var.db_storage_gb
  max_allocated_storage = var.db_max_storage_gb > var.db_storage_gb ? var.db_max_storage_gb : null
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.this.name

  backup_retention_period    = var.db_backup_retention_days
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true
  apply_immediately          = var.db_apply_immediately

  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = var.db_skip_final_snapshot
  final_snapshot_identifier = "${local.prefix}-db-final-${random_id.final_snapshot.hex}"

  tags = { Name = "${local.prefix}-db" }
}
