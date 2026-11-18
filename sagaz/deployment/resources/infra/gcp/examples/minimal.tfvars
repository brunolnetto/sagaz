# Smallest deployment: one always-on worker, db-f1-micro Cloud SQL, 1 GB BASIC
# Memorystore, a dedicated VPC. Only project_id and image are required.
#
#   terraform init
#   terraform apply -var-file=examples/minimal.tfvars

project_id = "my-gcp-project"
image      = "us-docker.pkg.dev/my-gcp-project/sagaz/outbox-worker:1.8.3"

# Everything below repeats the defaults.
name        = "sagaz"
environment = "prod"
region      = "us-central1"

worker_count  = 1
worker_cpu    = "1"
worker_memory = "512Mi"

db_tier              = "db-f1-micro"
db_storage_gb        = 10
db_availability_type = "ZONAL"

redis_tier           = "BASIC"
redis_memory_size_gb = 1

outbox_mode = "polling"
