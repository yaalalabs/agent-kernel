{{/*
Expand the name of the chart.
*/}}
{{- define "agent-kernel.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name, truncated to the 63-char DNS label limit.
*/}}
{{- define "agent-kernel.fullname" -}}
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

{{- define "agent-kernel.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels. Pass (dict "root" $ "component" "<component>").
*/}}
{{- define "agent-kernel.labels" -}}
helm.sh/chart: {{ include "agent-kernel.chart" .root }}
{{ include "agent-kernel.selectorLabels" . }}
{{- with .root.Chart.AppVersion }}
app.kubernetes.io/version: {{ . | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{/*
Selector labels. Pass (dict "root" $ "component" "<component>").
*/}}
{{- define "agent-kernel.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-kernel.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
An application image reference, honoring the global registry override. Pass
(dict "root" $ "image" <the component's image block, may be empty>); repository and tag fall
back to the top-level image block.
*/}}
{{- define "agent-kernel.image" -}}
{{- $image := .image | default dict }}
{{- $repository := default .root.Values.image.repository $image.repository }}
{{- $tag := default .root.Values.image.tag $image.tag }}
{{- if .root.Values.global.imageRegistry }}
{{- printf "%s/%s:%s" .root.Values.global.imageRegistry $repository $tag }}
{{- else }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Connection URL for the in-cluster Valkey subchart (or the explicit override).
*/}}
{{- define "agent-kernel.valkeyUrl" -}}
{{- printf "valkey://%s-valkey:6379" .Release.Name }}
{{- end }}

{{/*
Connection URL for the in-cluster NATS subchart (or the explicit override).
*/}}
{{- define "agent-kernel.natsUrl" -}}
{{- printf "nats://%s-nats:4222" .Release.Name }}
{{- end }}

{{/*
The Strimzi cluster name (kafka.clusterName or a release-derived default).
*/}}
{{- define "agent-kernel.kafkaClusterName" -}}
{{- default (printf "%s-kafka" .Release.Name) .Values.kafka.clusterName | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Bootstrap servers for the in-cluster Strimzi cluster (or the explicit override).
*/}}
{{- define "agent-kernel.kafkaBootstrap" -}}
{{- if .Values.transport.kafka.bootstrapServers }}
{{- .Values.transport.kafka.bootstrapServers }}
{{- else }}
{{- printf "%s-kafka-bootstrap:9092" (include "agent-kernel.kafkaClusterName" .) }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding the WebSocket push token.
*/}}
{{- define "agent-kernel.pushTokenSecretName" -}}
{{- if .Values.wsGateway.auth.existingSecret }}
{{- .Values.wsGateway.auth.existingSecret }}
{{- else }}
{{- printf "%s-push-token" (include "agent-kernel.fullname" .) }}
{{- end }}
{{- end }}

{{/*
The namespace sandbox pods run in (sandboxWorker.sandboxPods.namespace or the release namespace).
*/}}
{{- define "agent-kernel.sandboxPodsNamespace" -}}
{{- default .Release.Namespace .Values.sandboxWorker.sandboxPods.namespace }}
{{- end }}

{{/*
Name of the sandbox worker's ServiceAccount ("default" when neither created nor named).
*/}}
{{- define "agent-kernel.sandboxWorkerServiceAccountName" -}}
{{- if .Values.sandboxWorker.serviceAccount.create }}
{{- default (printf "%s-sandbox-worker" (include "agent-kernel.fullname" .)) .Values.sandboxWorker.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.sandboxWorker.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the ServiceAccount assigned to sandbox pods (the app config's kubernetes.service_account).
*/}}
{{- define "agent-kernel.sandboxPodServiceAccountName" -}}
{{- default (printf "%s-sandbox-pod" (include "agent-kernel.fullname" .)) .Values.sandboxWorker.sandboxPods.serviceAccount.name }}
{{- end }}

{{/*
KEDA maxReplicaCount: explicit value, or partitions / input.noOfConsumers for the partitioned
transports (past that ceiling an extra replica finds no free partition), or 10 for sqs.
*/}}
{{- define "agent-kernel.kedaMaxReplicas" -}}
{{- if .Values.keda.maxReplicaCount }}
{{- .Values.keda.maxReplicaCount }}
{{- else if eq .Values.transport.type "nats" }}
{{- max 1 (div .Values.transport.nats.partitions .Values.transport.input.noOfConsumers) }}
{{- else if eq .Values.transport.type "kafka" }}
{{- max 1 (div .Values.kafka.partitions .Values.transport.input.noOfConsumers) }}
{{- else }}
{{- 10 }}
{{- end }}
{{- end }}
