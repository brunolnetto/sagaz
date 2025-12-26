# Kubernetes Deployment Guide

Deploysagaz to Kubernetes with a local `kind` cluster or production environment.

## Prerequisites

- Docker installed and running
- `kubectl` configured
- For local: `kind` installed

## Quick Start (Local - kind)

### 1. Create Cluster

```bash
# Install kind (if needed)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# Create cluster
kind create cluster --namesagaz

# Verify
kubectl get nodes
```

### 2. Create Namespace & Secrets

```bash
kubectl create namespacesagaz
kubectl apply -f k8s/secrets-local.yaml
```

### 3. Deploy PostgreSQL

```bash
kubectl apply -f k8s/postgresql-local.yaml

# Wait for ready
kubectl wait --for=condition=ready pod -l app=postgresql -nsagaz --timeout=120s
```

### 4. Run Migrations

```bash
kubectl apply -f k8s/migration-job.yaml

# Check logs
kubectl logs -f job/sage-migration -nsagaz
```

### 5. Deploy RabbitMQ

```bash
kubectl apply -f k8s/rabbitmq.yaml

# Wait for ready
kubectl wait --for=condition=ready pod -l app=rabbitmq -nsagaz --timeout=120s
```

### 6. Build & Load Worker Image

```bash
# Build image
docker build -tsagaz-outbox-worker:latest .

# Load into kind
kind load docker-imagesagaz-outbox-worker:latest --namesagaz
```

### 7. Deploy Workers

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/outbox-worker.yaml

# Verify
kubectl get pods -nsagaz
```

---

## Verify Deployment

```bash
# All pods should be Running
kubectl get pods -nsagaz

# Expected output:
# NAME                            READY   STATUS      RESTARTS   AGE
# outbox-worker-xxx-xxx           1/1     Running     0          1m
# outbox-worker-xxx-yyy           1/1     Running     0          1m
# outbox-worker-xxx-zzz           1/1     Running     0          1m
# postgresql-xxx-xxx              1/1     Running     0          5m
# rabbitmq-xxx-xxx                1/1     Running     0          3m
#sagaz-migration-xxx              0/1     Completed   0          4m
```

---

## Access Services

### PostgreSQL

```bash
kubectl port-forward -nsagaz svc/postgresql 5433:5432

# Connect
psql postgresql://saga_user:saga_password@localhost:5433/saga_db
```

### RabbitMQ Management

```bash
kubectl port-forward -nsagaz svc/rabbitmq 15672:15672

# Open http://localhost:15672
# Username: saga
# Password: saga_password
```

---

## Scaling

### Manual Scaling

```bash
# Scale up
kubectl scale deployment outbox-worker --replicas=10 -nsagaz

# Scale down
kubectl scale deployment outbox-worker --replicas=3 -nsagaz
```

### Auto Scaling (HPA)

The deployment includes HPA configuration:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## Monitoring

### View Logs

```bash
# All workers
kubectl logs -nsagaz -l app=outbox-worker --tail=50

# Specific pod
kubectl logs -nsagaz outbox-worker-xxx-xxx -f
```

### Check Metrics

```bash
kubectl port-forward -nsagaz svc/outbox-worker-metrics 8000:8000
curl http://localhost:8000/metrics
```

---

## Troubleshooting

### Pod Not Starting

```bash
# Check events
kubectl describe pod -nsagaz <pod-name>

# Check logs
kubectl logs -nsagaz <pod-name> --previous
```

### Connection Issues

```bash
# Verify secrets
kubectl get secretsagaz-db-credentials -nsagaz -o yaml

# Test PostgreSQL connection
kubectl run -it --rm debug --image=postgres:16-alpine -nsagaz -- \
  psql postgresql://saga_user:saga_password@postgresql:5432/saga_db -c '\l'
```

### Image Pull Errors

```bash
# For kind, ensure image is loaded
kind load docker-imagesagaz-outbox-worker:latest --namesagaz

# Verify
docker exec -itsagaz-control-plane crictl images | grepsagaz
```

---

## Production Considerations

### 1. Use External PostgreSQL

```yaml
# secrets.yaml
data:
  connection-string: <base64-encoded-production-url>
```

### 2. Use Managed RabbitMQ/Kafka

Update broker credentials in secrets.

### 3. Enable Persistent Storage

```yaml
# postgresql.yaml
spec:
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "gp2"  # AWS EBS
        resources:
          requests:
            storage: 100Gi
```

### 4. Configure Resource Limits

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "512Mi"
  limits:
    cpu: "2000m"
    memory: "2Gi"
```

---

## Cleanup

```bash
# Delete all resources
kubectl delete namespacesagaz

# Delete kind cluster
kind delete cluster --namesagaz
```

---

## Related

- [Architecture Overview](../architecture/overview.md)
- [Benchmarking Guide](benchmarking.md)
- [K8s Topology Diagram](../architecture/diagrams/k8s-topology.md)
