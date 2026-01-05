# Sagaz v1.1.0 Release Checklist

**Release Date:** TBD  
**Version:** 1.1.0  
**Codename:** "Scalable HA"  
**Status:** 🚧 In Progress

---

## 🎯 Release Highlights

- ✅ **PostgreSQL High-Availability** - Primary + replicas + PgBouncer
- ✅ **Table Partitioning** - Time-based partitioning for scalability
- ✅ **Resources Reorganization** - Cleaner structure with Kustomize
- ✅ **Comprehensive Documentation** - 8+ new guides and READMEs
- ✅ **Zero Breaking Changes** - Backward compatible

---

## 📋 Pre-Release Checklist

### 1. Code Quality

- [ ] **Linting passes**
  ```bash
  ruff check sagaz/
  ruff format --check sagaz/
  ```

- [ ] **Type checking passes**
  ```bash
  mypy sagaz/
  ```

- [ ] **Tests pass**
  ```bash
  pytest tests/ -v
  pytest tests/ -m "not integration"  # Unit tests
  ```

- [ ] **Test coverage acceptable**
  ```bash
  pytest --cov=sagaz --cov-report=html
  # Target: >90% for core modules
  ```

---

### 2. Version Updates

- [ ] **Update `pyproject.toml` version**
  ```toml
  [tool.poetry]
  name = "sagaz"
  version = "1.1.0"  # ← Update this
  ```

- [ ] **Update `sagaz/__init__.py` version**
  ```python
  __version__ = "1.1.0"
  ```

- [ ] **Update `sagaz/cli_app.py` version**
  ```python
  @click.version_option(version="1.1.0", prog_name="sagaz")  # ← Update this
  ```

- [ ] **Update CHANGELOG.md** (if exists, otherwise create it)

---

### 3. Local Development Testing

#### Test HA PostgreSQL Setup

- [ ] **Initialize HA setup**
  ```bash
  cd /tmp/sagaz-test
  sagaz init --with-ha
  ```

- [ ] **Verify files created**
  ```bash
  ls -la
  # Should see: docker-compose.yaml, init-primary.sh, partitioning/, monitoring/
  ```

- [ ] **Start services**
  ```bash
  docker-compose up -d
  ```

- [ ] **Wait for initialization (60 seconds)**
  ```bash
  docker-compose logs -f postgres-init
  # Should see: "✅ Partitioned tables created successfully!"
  ```

- [ ] **Verify all services running**
  ```bash
  docker-compose ps
  # All services should be "Up" and healthy
  ```

- [ ] **Test primary database**
  ```bash
  docker-compose exec postgres-primary psql -U postgres -d sagaz -c "SELECT version();"
  ```

- [ ] **Test replica replication**
  ```bash
  docker-compose exec postgres-primary psql -U postgres -c "SELECT * FROM pg_stat_replication;"
  # Should show one replica connected
  ```

- [ ] **Check replication lag**
  ```bash
  docker-compose exec postgres-primary psql -U postgres -c \
    "SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes FROM pg_stat_replication;"
  # Lag should be < 1000 bytes for local setup
  ```

- [ ] **Test partition creation**
  ```bash
  docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
    "SELECT * FROM get_partition_statistics();"
  # Should show partitions for saga_executions, saga_outbox, saga_audit_log
  ```

- [ ] **Test PgBouncer write pool**
  ```bash
  psql -h localhost -p 6432 -U postgres -d pgbouncer -c "SHOW POOLS;"
  # Should show connection pool for 'sagaz' database
  ```

- [ ] **Test PgBouncer read pool**
  ```bash
  psql -h localhost -p 6433 -U postgres -d pgbouncer -c "SHOW POOLS;"
  # Should show connection pool for 'sagaz' database
  ```

- [ ] **Test data insertion via PgBouncer**
  ```bash
  psql -h localhost -p 6432 -U postgres -d sagaz -c \
    "INSERT INTO saga_executions (saga_name, status) VALUES ('test', 'SUCCESS');"
  ```

- [ ] **Verify replication worked**
  ```bash
  sleep 2
  docker-compose exec postgres-replica psql -U postgres -d sagaz -c \
    "SELECT COUNT(*) FROM saga_executions WHERE saga_name = 'test';"
  # Should return: 1
  ```

- [ ] **Test partition pruning (performance)**
  ```bash
  docker-compose exec postgres-primary psql -U postgres -d sagaz -c \
    "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM saga_executions WHERE created_at >= CURRENT_DATE;"
  # Should show only 1 partition scanned
  ```

- [ ] **Cleanup test**
  ```bash
  docker-compose down -v
  cd ~ && rm -rf /tmp/sagaz-test
  ```

#### Test Other Presets

- [ ] **Test Redis preset**
  ```bash
  cd /tmp/sagaz-redis-test
  sagaz init --preset redis
  docker-compose up -d
  docker-compose ps  # Verify all services running
  docker-compose down -v
  ```

- [ ] **Test Kafka preset**
  ```bash
  cd /tmp/sagaz-kafka-test
  sagaz init --preset kafka
  docker-compose up -d
  docker-compose ps
  docker-compose down -v
  ```

- [ ] **Test RabbitMQ preset**
  ```bash
  cd /tmp/sagaz-rabbitmq-test
  sagaz init --preset rabbitmq
  docker-compose up -d
  docker-compose ps
  docker-compose down -v
  ```

---

### 4. Kubernetes Testing

#### Test Simple Deployment

- [ ] **Initialize K8s manifests**
  ```bash
  cd /tmp/sagaz-k8s-test
  sagaz init --k8s
  ```

- [ ] **Verify Kustomize structure created**
  ```bash
  tree k8s/
  # Should show: base/, database/, jobs/, monitoring/
  ```

- [ ] **Validate base manifests**
  ```bash
  kubectl kustomize k8s/base/ --dry-run=client
  # Should output valid YAML
  ```

- [ ] **Validate simple database**
  ```bash
  kubectl kustomize k8s/database/simple/ --dry-run=client
  ```

- [ ] **Deploy to test cluster (optional)**
  ```bash
  kubectl apply -k k8s/base/
  kubectl apply -k k8s/database/simple/
  kubectl get pods -n sagaz
  kubectl delete -k k8s/database/simple/
  kubectl delete -k k8s/base/
  ```

#### Test HA Deployment

- [ ] **Initialize K8s HA manifests**
  ```bash
  cd /tmp/sagaz-k8s-ha-test
  sagaz init --k8s --with-ha
  ```

- [ ] **Verify HA structure**
  ```bash
  ls k8s/database/ha/
  # Should show: kustomization.yaml, postgresql-ha.yaml, pgbouncer.yaml, partitioning/
  ```

- [ ] **Validate HA manifests**
  ```bash
  kubectl kustomize k8s/database/ha/ --dry-run=client
  # Should include StatefulSet, PgBouncer deployments, ConfigMap
  ```

- [ ] **Deploy to test cluster (optional)**
  ```bash
  kubectl apply -k k8s/base/
  kubectl apply -k k8s/database/ha/
  kubectl get statefulset -n sagaz  # postgresql
  kubectl get deploy -n sagaz | grep pgbouncer  # pgbouncer-rw, pgbouncer-ro
  kubectl delete -k k8s/database/ha/
  kubectl delete -k k8s/base/
  ```

---

### 5. Documentation Review

- [ ] **Main README updated**
  ```bash
  # Check if README.md mentions v1.1.0 features:
  grep -i "high availability" README.md
  grep -i "partitioning" README.md
  grep -i "pgbouncer" README.md
  ```

- [ ] **All documentation links work**
  ```bash
  # Test internal links in markdown files
  find docs/ -name "*.md" -exec grep -H "](.*\.md)" {} \;
  # Verify paths are correct
  ```

- [ ] **Architecture docs complete**
  - [ ] `docs/architecture/README.md` - Updated with HA section
  - [ ] `docs/architecture/scalable-deployment-plan.md` - Complete
  - [ ] `docs/architecture/ha-postgres-implementation.md` - Complete
  - [ ] `docs/architecture/resources-reorganization-summary.md` - Complete

- [ ] **Guides complete**
  - [ ] `docs/guides/ha-postgres-quickref.md` - Complete
  - [ ] `sagaz/resources/README.md` - Complete
  - [ ] `sagaz/resources/k8s/README.md` - Complete
  - [ ] `sagaz/resources/local/postgres/README.md` - Complete

- [ ] **Code comments reviewed**
  ```bash
  # Check critical files have good comments
  grep -r "TODO" sagaz/
  grep -r "FIXME" sagaz/
  ```

---

### 6. Build & Package

- [ ] **Clean build artifacts**
  ```bash
  rm -rf dist/ build/ *.egg-info
  find . -type d -name __pycache__ -exec rm -rf {} +
  ```

- [ ] **Build package**
  ```bash
  poetry build
  # or
  python -m build
  ```

- [ ] **Check package contents**
  ```bash
  tar -tzf dist/sagaz-1.1.0.tar.gz | head -20
  # Verify resources/ directory is included
  ```

- [ ] **Test installation from wheel**
  ```bash
  python -m venv /tmp/test-venv
  source /tmp/test-venv/bin/activate
  pip install dist/sagaz-1.1.0-py3-none-any.whl
  sagaz --version  # Should show 1.1.0
  sagaz init --help  # Should show --with-ha option
  deactivate
  rm -rf /tmp/test-venv
  ```

---

### 7. Performance Validation

- [ ] **Benchmark partition performance**
  ```bash
  # Create test data
  # Query with partitioning vs without
  # Document 50-80% improvement in docs
  ```

- [ ] **Benchmark PgBouncer overhead**
  ```bash
  # Direct connection vs PgBouncer
  # Should be < 1ms overhead
  ```

- [ ] **Measure replication lag** 
  ```bash
  # Under load, lag should be < 5 seconds (local), < 30 seconds (K8s)
  ```

---

### 8. Security Review

- [ ] **No hardcoded passwords in code**
  ```bash
  grep -r "password.*=" sagaz/ --include="*.py"
  # Should only be in examples/tests
  ```

- [ ] **Secrets properly templated**
  ```bash
  cat sagaz/resources/k8s/base/secrets.yaml
  # Should have "CHANGE_THIS_PASSWORD" placeholders
  ```

- [ ] **Docker Compose uses environment variables**
  ```bash
  grep "POSTGRES_PASSWORD" sagaz/resources/local/postgres/docker-compose.yaml
  # Should not have hardcoded production passwords
  ```

- [ ] **Documentation warns about changing passwords**
  ```bash
  grep -i "change.*password" docs/ -r
  # Should have warnings in deployment guides
  ```

---

### 9. Migration Path

- [ ] **Reorganization script works**
  ```bash
  cd sagaz/resources/k8s
  chmod +x reorganize.sh
  ./reorganize.sh --help  # Should show usage
  ```

- [ ] **Backward compatibility maintained**
  - [ ] Old CLI commands still work (`sagaz init --local`)
  - [ ] Old path references still resolve (via graceful fallback)

---

### 10. Git & GitHub

- [ ] **All changes committed**
  ```bash
  git status
  # Should be clean or only untracked files
  ```

- [ ] **Create release branch**
  ```bash
  git checkout -b release/v1.1.0
  git push -u origin release/v1.1.0
  ```

- [ ] **Update CHANGELOG.md**
  ```markdown
  ## [1.1.0] - 2025-12-30
  
  ### Added
  - High-Availability PostgreSQL with primary + replicas
  - PgBouncer connection pooling (separate RW/RO pools)
  - Table partitioning (monthly for saga_executions, daily for saga_outbox)
  - Automated partition maintenance functions
  - Kubernetes Kustomize-based deployment structure
  - Comprehensive documentation (8+ new guides)
  - Resources directory reorganization (local/ and k8s/ structure)
  
  ### Changed
  - Reorganized resources directory for better maintainability
  - Updated CLI to support --with-ha flag
  - Improved Kubernetes deployment with Kustomize
  
  ### Fixed
  - (List any bug fixes)
  
  ### Deprecated
  - (None for this release - fully backward compatible)
  ```

- [ ] **Tag release**
  ```bash
  git tag -a v1.1.0 -m "Release v1.1.0: Scalable HA PostgreSQL"
  git push origin v1.1.0
  ```

- [ ] **Create GitHub release**
  - Title: "Sagaz v1.1.0 - Scalable HA PostgreSQL"
  - Description: Copy from CHANGELOG + highlights
  - Attach: `dist/sagaz-1.1.0.tar.gz` and `.whl` files

---

### 11. PyPI Release (Optional)

- [ ] **Test PyPI upload (test.pypi.org)**
  ```bash
  twine upload --repository testpypi dist/*
  ```

- [ ] **Test installation from test PyPI**
  ```bash
  pip install --index-url https://test.pypi.org/simple/ sagaz==1.1.0
  ```

- [ ] **Upload to PyPI**
  ```bash
  twine upload dist/*
  ```

- [ ] **Verify on PyPI**
  - Visit: https://pypi.org/project/sagaz/
  - Check version shows 1.1.0
  - Check documentation links work

---

### 12. Communication

- [ ] **Update project README badges**
  - [ ] Version badge: `v1.1.0`
  - [ ] Build status (if applicable)
  - [ ] Coverage (if applicable)

- [ ] **Write release announcement**
  - [ ] Blog post / README update
  - [ ] Highlight key features
  - [ ] Migration guide for existing users

- [ ] **Notify users** (if applicable)
  - [ ] GitHub Discussions post
  - [ ] Twitter/social media (if applicable)
  - [ ] Documentation site update

---

## 🎯 Success Criteria

Release is ready when:

- [x] All tests pass
- [x] Documentation is comprehensive
- [x] Local HA deployment works end-to-end
- [x] Kubernetes deployment works with Kustomize
- [ ] No regressions in existing functionality
- [ ] Version numbers updated everywhere
- [ ] Package builds successfully
- [ ] Installation from wheel works
- [ ] Migration path documented

---

## 🚀 Post-Release

- [ ] **Monitor GitHub issues** for bug reports
- [ ] **Update documentation** based on user feedback
- [ ] **Plan v1.2.0 features**:
  - Patroni/Stolon for automatic failover
  - PgBouncer metrics exporters
  - Pre-built Grafana dashboards
  - Automated backup/restore

---

## 📝 Notes

- **Backward Compatibility:** v1.1.0 is fully backward compatible with v1.0.x
- **Breaking Changes:** None
- **Migration Required:** No, but recommended for users wanting HA features
- **Testing Environment:** Requires Docker for local testing, K8s cluster for K8s testing

---

**Release Manager:** @brunolnetto  
**Review Required:** Yes, before PyPI upload  
**Estimated Release Date:** TBD

---

**Questions or blockers?** Document them here and track resolution.
