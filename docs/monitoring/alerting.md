# Sagaz Alerting Guide

This guide explains how to load the Sagaz AlertManager rules template and
integrate it with your Prometheus / AlertManager / Grafana stack.

## Quick start

### 1. Copy the rules file

```bash
cp docs/monitoring/alertmanager-rules.yml /etc/prometheus/rules/sagaz.yml
```

### 2. Reference it from `prometheus.yml`

```yaml
rule_files:
  - "/etc/prometheus/rules/sagaz.yml"
```

### 3. Reload Prometheus

```bash
curl -X POST http://localhost:9090/-/reload
```

Prometheus will now evaluate the Sagaz alert expressions every minute.

---

## Alerts reference

All alert names follow the `Sagaz<Condition>` convention.

| Alert | Severity | Threshold | Window |
|-------|----------|-----------|--------|
| `SagazCompensationRateHigh` | warning | > 5 % of executions | 5 min |
| `SagazSagaFailureRateHigh` | critical | > 1 % failure rate | 15 min |
| `SagazExecutionLatencyHigh` | warning | p99 > 5 s | 5 min |
| `SagazDLQDepthHigh` | warning | DLQ depth > 100 | 2 min |
| `SagazOutboxLagHigh` | warning | pending events > 500 | 10 min |

Every alert carries three annotations that AlertManager templating can use:

| Annotation | Description |
|------------|-------------|
| `summary` | One-line description shown in notification subjects |
| `description` | Full context for on-call engineers |
| `runbook_url` | Link to the operational runbook |

---

## Tuning thresholds

The thresholds in `alertmanager-rules.yml` are conservative defaults.
Edit the `expr` and `for` fields to match your SLOs:

```yaml
# Example: tighten compensation-rate threshold to 2 %
- alert: SagazCompensationRateHigh
  expr: |
    (
      rate(saga_compensations_total[5m])
      /
      rate(saga_execution_total[5m])
    ) > 0.02   # <-- change here
  for: 5m
```

---

## DLQ alerts

The `SagazDLQDepthHigh` alert fires when the `sagaz_dlq_depth` gauge
(incremented by `OutboxWorker` each time an event is dead-lettered) exceeds 100.

When this alert fires:

1. Run `sagaz dlq list` to inspect events in the DLQ.
2. Fix the root cause (e.g. broker connectivity, schema mismatch).
3. Run `sagaz dlq replay --all` to re-queue the events.
4. Optionally run `sagaz dlq purge --older 7d` to remove stale entries.

See [Dead Letter Queue pattern](../patterns/dead-letter-queue.md) for
full details.

---

## AlertManager routing example

```yaml
# alertmanager.yml
route:
  group_by: [alertname, team]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: default

  routes:
    - match:
        team: platform
        severity: critical
      receiver: pagerduty-platform
    - match:
        team: platform
        severity: warning
      receiver: slack-platform

receivers:
  - name: default
    slack_configs:
      - api_url: "<YOUR_SLACK_WEBHOOK>"
        channel: "#alerts"

  - name: pagerduty-platform
    pagerduty_configs:
      - service_key: "<YOUR_PD_KEY>"

  - name: slack-platform
    slack_configs:
      - api_url: "<YOUR_SLACK_WEBHOOK>"
        channel: "#platform-alerts"
```

---

## Related documentation

- [Dead Letter Queue pattern](../patterns/dead-letter-queue.md)
- [Outbox pattern](../patterns/optimistic-sending.md)
- [Observability reference](OBSERVABILITY_REFERENCE.md)
- [AlertManager rules file](alertmanager-rules.yml)
