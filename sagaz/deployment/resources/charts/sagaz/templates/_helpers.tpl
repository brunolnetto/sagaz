{{/*
Chart name, truncated to the 63 characters Kubernetes names allow.
*/}}
{{- define "sagaz.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. The release name is used as-is when it already
contains the chart name (e.g. `helm install sagaz ...`).
*/}}
{{- define "sagaz.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sagaz.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sagaz.labels" -}}
helm.sh/chart: {{ include "sagaz.chart" . }}
{{ include "sagaz.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: outbox-worker
app.kubernetes.io/part-of: sagaz
{{- end }}

{{- define "sagaz.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sagaz.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "sagaz.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sagaz.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "sagaz.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag | toString) }}
{{- end }}

{{/* True ("true") when the worker consumes a PostgreSQL logical replication slot. */}}
{{- define "sagaz.pgLogical" -}}
{{- if and (eq .Values.outbox.mode "cdc") (eq .Values.outbox.cdc.source "pg_logical") }}true{{ end }}
{{- end }}

{{/* Environment variable the worker reads the broker URL from. */}}
{{- define "sagaz.brokerEnvName" -}}
{{- $names := dict "redis" "REDIS_URL" "kafka" "KAFKA_BOOTSTRAP_SERVERS" "rabbitmq" "RABBITMQ_URL" }}
{{- get $names .Values.broker.type }}
{{- end }}

{{/* Secret + key holding each credential. */}}
{{- define "sagaz.databaseSecretName" -}}
{{- default (include "sagaz.fullname" .) .Values.database.existingSecret }}
{{- end }}
{{- define "sagaz.databaseSecretKey" -}}
{{- if .Values.database.existingSecret }}{{ .Values.database.existingSecretKey }}{{ else }}database-url{{ end }}
{{- end }}
{{- define "sagaz.brokerSecretName" -}}
{{- default (include "sagaz.fullname" .) .Values.broker.existingSecret }}
{{- end }}
{{- define "sagaz.brokerSecretKey" -}}
{{- if .Values.broker.existingSecret }}{{ .Values.broker.existingSecretKey }}{{ else }}broker-url{{ end }}
{{- end }}
{{- define "sagaz.cdcDsnSecretName" -}}
{{- default (include "sagaz.fullname" .) .Values.outbox.cdc.pgLogical.existingSecret }}
{{- end }}
{{- define "sagaz.cdcDsnSecretKey" -}}
{{- if .Values.outbox.cdc.pgLogical.existingSecret }}{{ .Values.outbox.cdc.pgLogical.existingSecretKey }}{{ else }}cdc-dsn{{ end }}
{{- end }}
{{- define "sagaz.hasCdcDsn" -}}
{{- if and (include "sagaz.pgLogical" .) (or .Values.outbox.cdc.pgLogical.dsn .Values.outbox.cdc.pgLogical.existingSecret) }}true{{ end }}
{{- end }}

{{/* True when the chart must create its own Secret. */}}
{{- define "sagaz.createSecret" -}}
{{- $cdcDsn := and (include "sagaz.pgLogical" .) .Values.outbox.cdc.pgLogical.dsn (not .Values.outbox.cdc.pgLogical.existingSecret) }}
{{- if or (not .Values.database.existingSecret) (not .Values.broker.existingSecret) $cdcDsn }}true{{ end }}
{{- end }}

{{/*
Cross-field validation that the JSON schema cannot express. Included by the
Deployment so that every render (install, upgrade, template, lint) runs it.
*/}}
{{- define "sagaz.validate" -}}
{{- if not (or .Values.database.url .Values.database.existingSecret) }}
{{- fail "sagaz: set database.url or database.existingSecret (PostgreSQL holding the outbox)" }}
{{- end }}
{{- if not (or .Values.broker.url .Values.broker.existingSecret) }}
{{- fail "sagaz: set broker.url or broker.existingSecret (the message broker events are published to)" }}
{{- end }}
{{- if include "sagaz.pgLogical" . }}
{{- if ne (int .Values.replicaCount) 1 }}
{{- fail (printf "sagaz: outbox.mode=cdc with outbox.cdc.source=pg_logical requires replicaCount=1 (got %v): a PostgreSQL replication slot accepts a single consumer, and per-pod slots would each receive every event and publish it once per pod" .Values.replicaCount) }}
{{- end }}
{{- end }}
{{- if and .Values.autoscaling.enabled (ne .Values.outbox.mode "polling") }}
{{- fail "sagaz: autoscaling.enabled is supported in outbox.mode=polling only; set replicaCount instead" }}
{{- end }}
{{- if and (eq .Values.outbox.mode "cdc") (eq .Values.outbox.cdc.source "debezium") }}
{{- if and (ne .Values.broker.type "kafka") (not .Values.outbox.cdc.debezium.bootstrapServers) }}
{{- fail "sagaz: outbox.cdc.source=debezium needs outbox.cdc.debezium.bootstrapServers (the Kafka Debezium writes to) when broker.type is not kafka" }}
{{- end }}
{{- if and (eq .Values.broker.type "kafka") .Values.outbox.cdc.debezium.bootstrapServers }}
{{- fail "sagaz: with broker.type=kafka the Debezium source reads the broker's Kafka (one KAFKA_BOOTSTRAP_SERVERS); leave outbox.cdc.debezium.bootstrapServers empty" }}
{{- end }}
{{- end }}
{{- if and .Values.podDisruptionBudget.enabled (not (kindIs "invalid" .Values.podDisruptionBudget.minAvailable)) (not (kindIs "invalid" .Values.podDisruptionBudget.maxUnavailable)) }}
{{- fail "sagaz: set only one of podDisruptionBudget.minAvailable / podDisruptionBudget.maxUnavailable" }}
{{- end }}
{{- end }}
