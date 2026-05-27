{{/*
Docker image for AGS.
Defaults to the unified `usdsearch` image; honors per-sub-chart `image.name`
overrides for backwards compatibility.
*/}}
{{- define "asset-graph-service.dockerImage" -}}
{{- if .Values.image.name -}}
{{ default .Values.global.registry .Values.image.registry }}/{{ .Values.image.name }}:{{ default .Chart.AppVersion .Values.image.tag }}
{{- else -}}
{{ include "deepsearch-global.usdsearchImage" . }}
{{- end -}}
{{- end -}}

{{- define "asset-graph-service.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Expand the name of the chart.
*/}}
{{- define "asset-graph-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "asset-graph-service.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asset-graph-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asset-graph-service.labels" -}}
helm.sh/chart: {{ include "asset-graph-service.chart" . }}
{{ include "asset-graph-service.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asset-graph-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asset-graph-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "asset-graph-service.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "asset-graph-service.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}


{{/*
Service Annotations template
*/}}
{{- define "asset-graph-service.template.service.annotations" -}}
  {{- with . }}
  annotations:
  {{- toYaml . | nindent 4}}
  {{- end }}
{{- end }}


{{- define "asset-graph-service.defaultVerifyAccessEndpoint" -}}
{{- printf "http://%s-ngsearch-ngsearch-rest-api:8000/v2/authorization/verify_access" .Release.Name }}
{{- end }}

{{- define "asset-graph-service.defaultVerifyAccessEnabled" -}}
{{- if (eq .Values.global.storage_backend_type "s3") }}
{{- printf "false" }}
{{- else }}
{{- printf "true" }}
{{- end }}
{{- end }}
