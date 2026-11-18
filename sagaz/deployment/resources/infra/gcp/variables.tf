# -----------------------------------------------------------------------------
# Common
# -----------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project to deploy into."
  type        = string
}

variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "sagaz"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,19}$", var.name))
    error_message = "name must start with a letter, use only lowercase letters, digits and '-', and be at most 20 characters."
  }
}

variable "environment" {
  description = "Environment name (prod, staging, ...), used in resource names and labels."
  type        = string
  default     = "prod"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,9}$", var.environment))
    error_message = "environment must start with a letter, use only lowercase letters, digits and '-', and be at most 10 characters."
  }
}

variable "region" {
  description = "Region for Cloud Run, Cloud SQL, Memorystore and the subnet."
  type        = string
  default     = "us-central1"
}

variable "labels" {
  description = "Extra labels added to every labelled resource."
  type        = map(string)
  default     = {}
}

variable "deletion_protection" {
  description = "Protect the Cloud SQL instance and the worker pool from deletion. Defaults to false so `sagaz deploy teardown` (terraform destroy) works; set to true for production data."
  type        = bool
  default     = false
}

variable "enable_apis" {
  description = "Enable the required Google APIs (run, sqladmin, redis, secretmanager, servicenetworking, compute). APIs are never disabled on destroy."
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# Outbox worker (Cloud Run worker pool)
# -----------------------------------------------------------------------------

variable "image" {
  description = "Container image of the sagaz outbox worker, e.g. us-docker.pkg.dev/my-project/sagaz/worker:1.8.3."
  type        = string
}

variable "worker_count" {
  description = "Number of always-on worker instances (Cloud Run worker pool manual instance count)."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_count >= 1 && floor(var.worker_count) == var.worker_count
    error_message = "worker_count must be a whole number >= 1."
  }
}

variable "worker_cpu" {
  description = "vCPU per worker instance (Cloud Run CPU limit, e.g. \"1\", \"2\")."
  type        = string
  default     = "1"
}

variable "worker_memory" {
  description = "Memory per worker instance (Cloud Run memory limit, e.g. \"512Mi\", \"1Gi\")."
  type        = string
  default     = "512Mi"

  validation {
    condition     = can(regex("^[0-9]+(Mi|Gi)$", var.worker_memory))
    error_message = "worker_memory must look like \"512Mi\" or \"2Gi\"."
  }
}

variable "worker_command" {
  description = "Container entrypoint and arguments of the worker."
  type        = list(string)
  default     = ["python", "-m", "sagaz.core.outbox.worker"]
}

variable "worker_env" {
  description = "Extra plain environment variables for the worker (e.g. BATCH_SIZE, POLL_INTERVAL, MAX_RETRIES, WORKER_ID, LOG_LEVEL)."
  type        = map(string)
  default     = {}
}

variable "outbox_mode" {
  description = "Outbox publishing mode: \"polling\" or \"cdc\" (PostgreSQL logical replication; enables cloudsql.logical_decoding)."
  type        = string
  default     = "polling"

  validation {
    condition     = contains(["polling", "cdc"], var.outbox_mode)
    error_message = "outbox_mode must be \"polling\" or \"cdc\"."
  }
}

# -----------------------------------------------------------------------------
# Cloud SQL for PostgreSQL
# -----------------------------------------------------------------------------

variable "db_version" {
  description = "Cloud SQL database version."
  type        = string
  default     = "POSTGRES_16"
}

variable "db_edition" {
  description = "Cloud SQL edition. ENTERPRISE is required for the shared-core tiers (db-f1-micro, db-g1-small); PostgreSQL 16 defaults to ENTERPRISE_PLUS when unset."
  type        = string
  default     = "ENTERPRISE"

  validation {
    condition     = contains(["ENTERPRISE", "ENTERPRISE_PLUS"], var.db_edition)
    error_message = "db_edition must be ENTERPRISE or ENTERPRISE_PLUS."
  }
}

variable "db_tier" {
  description = "Cloud SQL machine tier (db-f1-micro, db-g1-small, db-custom-<vCPU>-<MiB>, ...). Shared-core tiers have no SLA."
  type        = string
  default     = "db-f1-micro"
}

variable "db_storage_gb" {
  description = "Initial SSD storage in GB (auto-resize is on)."
  type        = number
  default     = 10

  validation {
    condition     = var.db_storage_gb >= 10
    error_message = "db_storage_gb must be at least 10."
  }
}

variable "db_availability_type" {
  description = "ZONAL (single zone) or REGIONAL (high availability, roughly doubles the instance and storage price)."
  type        = string
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.db_availability_type)
    error_message = "db_availability_type must be ZONAL or REGIONAL."
  }
}

variable "db_name" {
  description = "Database created for sagaz."
  type        = string
  default     = "sagaz"
}

variable "db_user" {
  description = "Database user the worker connects as (password generated and stored in Secret Manager)."
  type        = string
  default     = "sagaz"
}

variable "db_backups_enabled" {
  description = "Enable automated daily backups (and point-in-time recovery)."
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# Memorystore for Redis (broker)
# -----------------------------------------------------------------------------

variable "redis_tier" {
  description = "Memorystore tier: BASIC (single node) or STANDARD_HA (replicated)."
  type        = string
  default     = "BASIC"

  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.redis_tier)
    error_message = "redis_tier must be BASIC or STANDARD_HA."
  }
}

variable "redis_memory_size_gb" {
  description = "Memorystore capacity in GB."
  type        = number
  default     = 1

  validation {
    condition     = var.redis_memory_size_gb >= 1 && var.redis_memory_size_gb <= 300
    error_message = "redis_memory_size_gb must be between 1 and 300."
  }
}

variable "redis_version" {
  description = "Memorystore Redis version."
  type        = string
  default     = "REDIS_7_2"
}

variable "redis_transit_encryption" {
  description = "Enable in-transit TLS (SERVER_AUTHENTICATION, port 6378). The worker then gets a rediss:// URL with ssl_cert_reqs=none because the Memorystore CA is not in the image trust store; see README."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------

variable "network" {
  description = "Existing VPC network (self link or id). null creates a dedicated VPC and subnet."
  type        = string
  default     = null
}

variable "subnetwork" {
  description = "Existing subnetwork (self link or id) in var.region for Direct VPC egress. Required when var.network is set."
  type        = string
  default     = null
}

variable "subnet_cidr" {
  description = "CIDR of the subnet created when var.network is null (Cloud Run Direct VPC egress takes IPs from it; /26 or larger)."
  type        = string
  default     = "10.10.0.0/24"
}

variable "create_private_service_access" {
  description = "Reserve a range and create the Private Service Access peering. Set to false when var.network already has a servicenetworking peering."
  type        = bool
  default     = true
}

variable "private_service_access_prefix_length" {
  description = "Prefix length of the range reserved for Private Service Access (Cloud SQL and Memorystore private IPs)."
  type        = number
  default     = 20
}
