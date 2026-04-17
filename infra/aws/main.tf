# Sagaz AWS Terraform Module
# Provisions: ECS (Fargate), RDS PostgreSQL, ElastiCache Redis

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  default = "us-east-1"
}

variable "name_prefix" {
  default = "sagaz"
}

provider "aws" {
  region = var.region
}

# VPC, ECS Cluster, RDS, ElastiCache resources would be declared here.
# This is a placeholder showing the expected module structure.
# See docs/guides/cloud-deployment.md for full configuration.

output "sagaz_endpoint" {
  value = "https://${var.name_prefix}.example.com"
}
