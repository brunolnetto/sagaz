# ---------------------------------------------------------------------------
# Outbox worker on ECS Fargate
# ---------------------------------------------------------------------------

locals {
  worker_environment = merge(
    {
      BROKER_TYPE   = "redis"
      BATCH_SIZE    = tostring(var.batch_size)
      POLL_INTERVAL = tostring(var.poll_interval)
      MAX_RETRIES   = tostring(var.max_retries)
    },
    local.cdc_enabled ? {
      SAGAZ_OUTBOX_MODE = "cdc"
      SAGAZ_CDC_SOURCE  = "pg_logical"
    } : {},
    var.worker_environment,
  )
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/sagaz/${local.prefix}/outbox-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "this" {
  name = "${local.prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# --- IAM -------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: used by the ECS agent to pull the image, write logs and
# resolve the task's secrets. It can read only this stack's two secrets.
resource "aws_iam_role" "execution" {
  name               = "${local.prefix}-worker-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.redis_url.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-sagaz-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# Task role: identity of the worker process itself. sagaz needs no AWS API
# access; attach policies here if your saga steps do.
resource "aws_iam_role" "task" {
  name               = "${local.prefix}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# --- Task definition and service -------------------------------------------

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-outbox-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.worker_cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "outbox-worker"
      image     = var.image
      essential = true
      command   = var.worker_command

      environment = [
        for k in sort(keys(local.worker_environment)) : {
          name  = k
          value = local.worker_environment[k]
        }
      ]

      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
        { name = "REDIS_URL", valueFrom = aws_secretsmanager_secret.redis_url.arn },
      ]

      # The worker serves no HTTP endpoint (no metrics/health port); liveness
      # is the process itself, and ECS restarts the task if it exits.

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "outbox-worker"
        }
      }

      stopTimeout = 30
    }
  ])

  # The secret values must exist before a task can start.
  depends_on = [
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.redis_url,
  ]
}

resource "aws_ecs_service" "worker" {
  name            = "${local.prefix}-outbox-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = local.worker_subnet_ids
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = var.worker_assign_public_ip
  }

  depends_on = [
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy_attachment.execution_managed,
    aws_route_table_association.public,
  ]
}
