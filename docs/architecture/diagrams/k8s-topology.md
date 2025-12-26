# Kubernetes Topology

Mermaid diagrams showing Kubernetes deployment architecture.

## Cluster Overview

```mermaid
flowchart TB
    subgraph K8S["Kubernetes Cluster"]
        subgraph NS["Namespace:sagaz"]
            
            subgraph Data["Data Layer"]
                PG[(PostgreSQL)]
                RMQ[RabbitMQ]
            end
            
            subgraph Workers["Worker Pool"]
                W1[Worker 1]
                W2[Worker 2]
                W3[Worker 3]
                WN[Worker N...]
            end
            
            subgraph Config["Configuration"]
                SEC[Secrets]
                CM[ConfigMap]
            end
            
            subgraph Jobs["Jobs"]
                MIG[Migration Job]
                BENCH[Benchmark Job]
            end
        end
    end
    
    W1 --> PG
    W2 --> PG
    W3 --> PG
    WN --> PG
    
    W1 --> RMQ
    W2 --> RMQ
    W3 --> RMQ
    WN --> RMQ
    
    SEC --> W1
    SEC --> W2
    SEC --> W3
    CM --> W1
    CM --> W2
    CM --> W3
    
    MIG --> PG
```

## Resource Dependencies

```mermaid
flowchart LR
    subgraph Secrets
        DB_SEC[sage-db-credentials]
        BROKER_SEC[sage-broker-credentials]
    end
    
    subgraph ConfigMaps
        WORKER_CM[outbox-worker-config]
        RMQ_CM[rabbitmq-config]
    end
    
    subgraph Services
        PG_SVC[postgresql:5432]
        RMQ_SVC[rabbitmq:5672]
        METRICS_SVC[outbox-worker-metrics:8000]
    end
    
    subgraph Deployments
        PG_DEPLOY[postgresql]
        RMQ_DEPLOY[rabbitmq]
        WORKER_DEPLOY[outbox-worker]
    end
    
    DB_SEC --> WORKER_DEPLOY
    BROKER_SEC --> WORKER_DEPLOY
    WORKER_CM --> WORKER_DEPLOY
    RMQ_CM --> RMQ_DEPLOY
    
    PG_DEPLOY --> PG_SVC
    RMQ_DEPLOY --> RMQ_SVC
    WORKER_DEPLOY --> METRICS_SVC
```

## Deployment Sequence

```mermaid
sequenceDiagram
    participant User
    participant kubectl
    participant K8s as Kubernetes
    
    User->>kubectl: create namespacesagaz
    kubectl->>K8s: Namespace created
    
    User->>kubectl: apply secrets-local.yaml
    kubectl->>K8s: Secrets created
    
    User->>kubectl: apply postgresql-local.yaml
    kubectl->>K8s: PostgreSQL deployed
    Note over K8s: Wait for PostgreSQL ready
    
    User->>kubectl: apply migration-job.yaml
    kubectl->>K8s: Migration runs
    Note over K8s: Schema created
    
    User->>kubectl: apply rabbitmq.yaml
    kubectl->>K8s: RabbitMQ deployed
    Note over K8s: Wait for RabbitMQ ready
    
    User->>kubectl: apply configmap.yaml
    kubectl->>K8s: ConfigMap created
    
    User->>kubectl: apply outbox-worker.yaml
    kubectl->>K8s: Workers deployed
    Note over K8s: Workers connect to DB & Broker
```

## Worker Pod Internals

```mermaid
flowchart TB
    subgraph Pod["outbox-worker-xxx-yyy"]
        subgraph Container["worker container"]
            PROCESS[Python Process]
            
            subgraph Probes["Health Probes"]
                LIVE[Liveness: python -c import sagaz]
                READY[Readiness: python -c import sagaz]
            end
        end
        
        subgraph Volumes
            TMP[/tmp emptyDir]
        end
        
        subgraph EnvVars["Environment"]
            DB_URL[DATABASE_URL]
            WORKER_ID[WORKER_ID = pod name]
            BROKER[RABBITMQ_URL]
            CONFIG[from ConfigMap]
        end
    end
    
    EnvVars --> Container
    TMP --> Container
```

## Horizontal Pod Autoscaler

```mermaid
flowchart LR
    subgraph HPA["HorizontalPodAutoscaler"]
        METRICS[Metrics Server]
        SCALE_UP[Scale Up Policy]
        SCALE_DOWN[Scale Down Policy]
    end
    
    subgraph Deploy["outbox-worker Deployment"]
        POD1[Pod 1]
        POD2[Pod 2]
        POD3[Pod 3]
        PODN[...Pod N]
    end
    
    METRICS --> |CPU > 70%| SCALE_UP
    SCALE_UP --> |+4 pods| Deploy
    
    METRICS --> |CPU < 50%| SCALE_DOWN
    SCALE_DOWN --> |-50%| Deploy
    
    POD1 --> METRICS
    POD2 --> METRICS
    POD3 --> METRICS
```

## Network Flow

```mermaid
flowchart TB
    subgraph External["External"]
        USER[User/Script]
    end
    
    subgraph Cluster["Kubernetes Cluster"]
        subgraph Services["ClusterIP Services"]
            PG_SVC[postgresql:5432]
            RMQ_SVC[rabbitmq:5672]
            RMQ_MGMT[rabbitmq:15672]
        end
        
        subgraph Pods
            PG[PostgreSQL Pod]
            RMQ[RabbitMQ Pod]
            W1[Worker Pod 1]
            W2[Worker Pod 2]
        end
    end
    
    USER -->|port-forward| PG_SVC
    USER -->|port-forward| RMQ_MGMT
    
    W1 --> PG_SVC --> PG
    W2 --> PG_SVC --> PG
    W1 --> RMQ_SVC --> RMQ
    W2 --> RMQ_SVC --> RMQ
```

## Manifest Files

| File | Resources Created |
|------|-------------------|
| `secrets-local.yaml` |sagaz-db-credentials,sagaz-broker-credentials |
| `configmap.yaml` |sagaz namespace, outbox-worker-config |
| `postgresql-local.yaml` | Deployment, Service |
| `migration-job.yaml` | Job |
| `rabbitmq.yaml` | ConfigMap, Deployment, Service |
| `outbox-worker.yaml` | Deployment, Service, ServiceAccount, PDB, HPA |
| `benchmark-job.yaml` | Job |
