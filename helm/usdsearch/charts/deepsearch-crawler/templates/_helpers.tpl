{{/*
Expand the name of the chart.
*/}}
{{- define "deepsearch-crawler.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/*
Release Name
*/}}
{{- define "deepsearch-crawler.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "deepsearch-crawler.fullname" -}}
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
{{- define "deepsearch-crawler.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "deepsearch-crawler.labels" -}}
helm.sh/chart: {{ include "deepsearch-crawler.chart" . }}
{{ include "deepsearch-crawler.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/component: "deepsearch-crawler"
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "deepsearch-crawler.selectorLabels" -}}
app.kubernetes.io/name: {{ include "deepsearch-crawler.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Main deployment labels
*/}}
{{- define "deepsearch-crawler.MainDeploymentlabels" -}}
{{ include "deepsearch-crawler.labels" . }}
deepsearch.deployment: main
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "deepsearch-crawler.deploymentSelectorlabels" -}}
{{ include "deepsearch-crawler.selectorLabels" . }}
deepsearch.deployment: deepsearch-crawler
{{- end -}}


{{/*
Create the name of the service account to use
*/}}
{{- define "deepsearch-crawler.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "deepsearch-crawler.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Docker image for the deepsearch crawler.
Defaults to the unified `usdsearch` image; honors `image.overwrite` and
per-service `image.name` overrides for backwards compatibility.
*/}}
{{- define "deepsearch-crawler.dockerImage" -}}
{{- if .Values.image.overwrite -}}
{{ .Values.image.overwrite }}
{{- else if .Values.image.name -}}
{{ .Values.global.registry }}/{{ .Values.image.name }}:{{ default .Chart.AppVersion .Values.image.tag }}
{{- else -}}
{{ include "deepsearch-global.usdsearchImage" . }}
{{- end -}}
{{- end -}}

{{/*
License agreement
*/}}
{{- define "deepsearch-crawler.license" -}}
  {{- if .Values.global.accept_eula }}
  {{- printf "%d" 1 }}
  {{- end }}
{{- end -}}

{{/*
Exclude strings
*/}}
{{- define "deepsearch-crawler.excludeIndexingStringsPatterns" -}}
{{- printf "['%s']" ( join "', '" (.Values.exclude_patterns | default .Values.global.exclude_patterns) ) -}}
{{- end -}}

{{/*
Crawler groups
*/}}
{{- define "deepsearch-crawler.crawlerGroups" -}}
{{- printf "['%s']" ( join "', '" (.Values.crawlerGroups) ) -}}
{{- end -}}

{{/*
Create a fully functional metrics service name
*/}}
{{- define "deepsearch-crawler.metrics" -}}
{{- (include "deepsearch-crawler.fullname" .) -}}-metrics
{{- end -}}
