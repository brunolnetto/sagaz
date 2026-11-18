# ---------------------------------------------------------------------------
# Naming and placement
# ---------------------------------------------------------------------------

variable "name" {
  description = "Prefix for every resource name (lowercase letters, digits and hyphens)."
  type        = string
  default     = "sagaz"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,19}$", var.name))
    error_message = "name must start with a lowercase letter, contain only lowercase letters, digits and hyphens, and be at most 20 characters."
  }
}

variable "environment" {
  description = "Environment suffix appended to the name prefix (e.g. prod, staging)."
  type        = string
  default     = "prod"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,11}$", var.environment))
    error_message = "environment must contain only lowercase letters, digits and hyphens, and be at most 12 characters."
  }
}

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Extra tags applied to every resource."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Outbox worker (ECS Fargate)
# ---------------------------------------------------------------------------

variable "image" {
  description = "Container image of the sagaz outbox worker (built from the repository Dockerfile), e.g. ghcr.io/acme/sagaz:1.8.3."
  type        = string

  validation {
    condition     = length(trimspace(var.image)) > 0
    error_message = "image must be a non-empty container image reference."
  }
}

variable "worker_command" {
  description = "Command run by the worker container (overrides the image CMD)."
  type        = list(string)
  default     = ["python", "-m", "sagaz.core.outbox.worker"]
}

variable "worker_count" {
  description = "Number of outbox worker tasks."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_count >= 0 && floor(var.worker_count) == var.worker_count
    error_message = "worker_count must be a non-negative integer."
  }
}

variable "worker_cpu" {
  description = "Fargate CPU units per worker task (1024 = 1 vCPU)."
  type        = number
  default     = 256

  validation {
    condition     = contains([256, 512, 1024, 2048, 4096], var.worker_cpu)
    error_message = "worker_cpu must be one of 256, 512, 1024, 2048, 4096."
  }
}

variable "worker_memory" {
  description = "Memory (MiB) per worker task; must be a valid Fargate combination with worker_cpu (256 CPU -> 512/1024/2048)."
  type        = number
  default     = 512

  validation {
    condition     = var.worker_memory >= 512 && var.worker_memory <= 30720
    error_message = "worker_memory must be between 512 and 30720 MiB."
  }
}

variable "worker_cpu_architecture" {
  description = "CPU architecture of the Fargate tasks (X86_64 or ARM64). ARM64 is ~20% cheaper but needs an arm64 image; cost.json prices X86_64."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.worker_cpu_architecture)
    error_message = "worker_cpu_architecture must be X86_64 or ARM64."
  }
}

variable "worker_assign_public_ip" {
  description = "Give worker tasks a public IP so they can pull the image and reach AWS APIs from public subnets without a NAT gateway. Set false when subnet_ids are private subnets behind a NAT gateway or VPC endpoints."
  type        = bool
  default     = true
}

variable "worker_environment" {
  description = "Extra plain (non-secret) environment variables for the worker."
  type        = map(string)
  default     = {}
}

variable "batch_size" {
  description = "Outbox events fetched per batch (BATCH_SIZE)."
  type        = number
  default     = 100
}

variable "poll_interval" {
  description = "Seconds between outbox polls (POLL_INTERVAL)."
  type        = number
  default     = 1
}

variable "max_retries" {
  description = "Publish attempts before an event is dead-lettered (MAX_RETRIES)."
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention (days) for the worker log group."
  type        = number
  default     = 30
}

variable "outbox_mode" {
  description = "Outbox relay mode: polling (default) or cdc (PostgreSQL logical replication; sets rds.logical_replication = 1)."
  type        = string
  default     = "polling"

  validation {
    condition     = contains(["polling", "cdc"], var.outbox_mode)
    error_message = "outbox_mode must be \"polling\" or \"cdc\"."
  }
}

# ---------------------------------------------------------------------------
# Database (RDS PostgreSQL)
# ---------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_storage_gb" {
  description = "Allocated gp3 storage in GB."
  type        = number
  default     = 20

  validation {
    condition     = var.db_storage_gb >= 20
    error_message = "db_storage_gb must be at least 20."
  }
}

variable "db_max_storage_gb" {
  description = "Upper bound for storage autoscaling in GB (0 disables autoscaling)."
  type        = number
  default     = 0
}

variable "db_multi_az" {
  description = "Run RDS Multi-AZ (doubles instance and storage cost)."
  type        = bool
  default     = false
}

variable "db_engine_version" {
  description = "PostgreSQL engine version (16.x; the parameter group family is derived from the major version)."
  type        = string
  default     = "16.10"
}

variable "db_name" {
  description = "Database name."
  type        = string
  default     = "sagaz"
}

variable "db_username" {
  description = "Master username."
  type        = string
  default     = "sagaz"
}

variable "db_backup_retention_days" {
  description = "Automated backup retention in days (0 disables automated backups)."
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable RDS deletion protection. Defaults to false so `sagaz deploy teardown` / `terraform destroy` works; set true for production and flip it back to false before tearing down."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "Skip the final snapshot on destroy. false (default) keeps a final snapshot, which is billed until you delete it."
  type        = bool
  default     = false
}

variable "db_apply_immediately" {
  description = "Apply database modifications immediately instead of in the next maintenance window."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Broker (ElastiCache Redis)
# ---------------------------------------------------------------------------

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "redis_engine_version" {
  description = "Redis OSS engine version."
  type        = string
  default     = "7.1"
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

variable "vpc_id" {
  description = "Existing VPC to deploy into. null creates a small VPC (2 AZs, public subnets for workers, private subnets for RDS/ElastiCache)."
  type        = string
  default     = null
}

variable "subnet_ids" {
  description = "Subnets of vpc_id (at least 2, in different AZs) for workers, RDS and ElastiCache. Required when vpc_id is set."
  type        = list(string)
  default     = null
}

variable "vpc_cidr" {
  description = "CIDR of the VPC created when vpc_id is null."
  type        = string
  default     = "10.42.0.0/16"
}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window on deletion (0 deletes immediately so the stack can be redeployed with the same name)."
  type        = number
  default     = 0
}
