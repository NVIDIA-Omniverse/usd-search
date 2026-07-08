{{/*
Docker image for the rendering service.
Defaults to the unified `rendering-job` (Kit) image; honors per-sub-chart
`image.name` overrides for backwards compatibility.
*/}}
{{- define "rendering-service.dockerImage" -}}
{{- if .Values.image.name -}}
{{ default .Values.global.registry .Values.image.registry }}/{{ .Values.image.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) .Values.image.tag }}
{{- else -}}
{{ include "deepsearch-global.renderingJobImage" . }}
{{- end -}}
{{- end -}}

{{/*
Expand the name of the chart.
*/}}
{{- define "rendering-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "rendering-service.fullname" -}}
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
{{- define "rendering-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "rendering-service.labels" -}}
usdsearch.service.name: rendering-service
helm.sh/chart: {{ include "rendering-service.chart" . }}
{{ include "rendering-service.selectorLabels" . }}
{{- if .Values.global.appVersion }}
app.kubernetes.io/version: {{ .Values.global.appVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "rendering-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rendering-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "rendering-service.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "rendering-service.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Build a JSON array of Kit extra args from settings.kit_extra_args (map).
Output format: ["--key1=value1","--key2=value2"]
Usage: {{ include "rendering-service.kitExtraArgsJson" . }}
*/}}
{{- define "rendering-service.kitExtraArgsJson" -}}
{{- $args := list }}
{{- with .Values.settings.kit_extra_args }}
{{- range $k, $v := . }}
{{- $args = append $args (printf "--%s=%s" $k (toString $v)) }}
{{- end }}
{{- end }}
{{- toJson $args }}
{{- end }}
