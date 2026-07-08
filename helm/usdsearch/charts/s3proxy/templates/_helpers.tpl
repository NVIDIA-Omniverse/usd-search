{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "s3proxy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "s3proxy.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "s3proxy.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
License agreement
*/}}
{{- define "s3proxy.license" -}}
  {{- if .Values.global.accept_eula }}
  {{- printf "%d" 1 }}
  {{- end }}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "s3proxy.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "s3proxy.labels" -}}
helm.sh/chart: {{ include "s3proxy.chart" . }}
{{ include "s3proxy.selectorLabels" . }}
{{- if .Values.global.appVersion }}
app.kubernetes.io/version: {{ .Values.global.appVersion | quote }}
{{- end }}
app.kubernetes.io/component: "s3proxy"
app.kubernetes.io/name: s3proxy
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "s3proxy.MainDeploymentlabels" -}}
{{ include "s3proxy.labels" . }}
s3proxy.deployment: main
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "s3proxy.MainDeploymentSelectorlabels" -}}
{{ include "s3proxy.selectorLabels" . }}
s3proxy.deployment: main
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "s3proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "s3proxy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
