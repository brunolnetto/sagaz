# Smallest useful stack: 1 worker (0.25 vCPU / 0.5 GB), db.t4g.micro,
# cache.t4g.micro, new VPC without NAT gateway.
#
#   terraform init
#   terraform apply -var-file=examples/minimal.tfvars

image       = "ghcr.io/example/sagaz:latest"
name        = "sagaz"
environment = "dev"
region      = "us-east-1"

worker_count  = 1
worker_cpu    = 256
worker_memory = 512

db_instance_class = "db.t4g.micro"
db_storage_gb     = 20
db_multi_az       = false

redis_node_type = "cache.t4g.micro"

outbox_mode = "polling"

tags = {
  owner = "platform"
}
