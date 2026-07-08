{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "ngsearch.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "ngsearch.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "ngsearch.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
License agreement
*/}}
{{- define "ngsearch.license" -}}
  {{- if .Values.global.accept_eula }}
  {{- .Values.global.accept_eula }}
  {{- end }}
{{- end -}}

{{/*
Plugin config
*/}}
{{- define "ngsearch.plugin-config" -}}
  {{- toYaml .Values.plugins | indent 2 }}
{{- end -}}

{{/*
Create a fully functional metrics service name
*/}}
{{- define "ngsearch.metrics" -}}
{{- (include "ngsearch.fullname" .) -}}-metrics
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "ngsearch.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "ngsearch.labels" -}}
helm.sh/chart: {{ include "ngsearch.chart" . }}
{{ include "ngsearch.selectorLabels" . }}
{{- if .Values.global.appVersion }}
app.kubernetes.io/version: {{ .Values.global.appVersion | quote }}
{{- end }}
app.kubernetes.io/component: "ngsearch"
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "ngsearch.MainDeploymentlabels" -}}
{{ include "ngsearch.labels" . }}
ngsearch.deployment: main
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "ngsearch.MainDeploymentSelectorlabels" -}}
{{ include "ngsearch.selectorLabels" . }}
ngsearch.deployment: main
{{- end -}}


{{/*
Selector labels
*/}}
{{- define "ngsearch.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ngsearch.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "ngsearch.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "ngsearch.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
NGSearch Rest API docker image.
Defaults to the unified `usdsearch` image; honors per-service overrides
(microservices.search_rest_api.image.name) for backwards compatibility.
*/}}
{{- define "ngsearch.ngsearchRestAPIDockerImage" -}}
{{- $img := .Values.microservices.search_rest_api.image -}}
{{- if $img.name -}}
{{ default .Values.global.registry $img.registry }}/{{ $img.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) $img.tag }}
{{- else -}}
{{ include "deepsearch-global.usdsearchImage" . }}
{{- end -}}
{{- end -}}


{{/*
Indexing / storage / tag-crawler docker image.
Defaults to the unified `usdsearch` image; honors a sub-chart-level override
(top-level .Values.image.name) for backwards compatibility.
*/}}
{{- define "ngsearch.ngsearchDockerImage" -}}
{{- if .Values.image.name -}}
{{ .Values.global.registry }}/{{ .Values.image.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) .Values.image.tag }}
{{- else -}}
{{ include "deepsearch-global.usdsearchImage" . }}
{{- end -}}
{{- end -}}

{{/*
Exclude strings
*/}}

{{- define "ngsearch.excludeIndexingStringsPatterns" -}}
{{- printf "['%s']" ( join "', '" (.Values.exclude_patterns | default .Values.global.exclude_patterns) ) -}}
{{- end -}}

{{/*
Rest API Admin Access Key
*/}}
{{- define "ngsearch.admin.access_key" -}}
{{- if .Values.microservices.search_rest_api.admin_authentication.access_key }}
{{- .Values.microservices.search_rest_api.admin_authentication.access_key }}
{{- else }}
{{- $newKey := randAlphaNum 64 }}
{{- printf "%s" $newKey }}
{{- end }}
{{- end }}

{{/*
Service Type template
*/}}
{{- define "ngsearch.template.service.type" -}}
{{- if eq . "nodeport" }}
 {{- printf "NodePort" }}
{{- else if eq . "loadbalancer" }}
 {{- printf "LoadBalancer" }}
{{- else if eq . "ingress" }}
 {{- printf "ClusterIP" }}
{{- else }}
 {{- printf "%s" . }}
{{- end }}
{{- end }}

{{/*
Service Annotations template
*/}}
{{- define "ngsearch.template.service.annotations" -}}
  {{- with . }}
  annotations:
  {{- toYaml . | nindent 4}}
  {{- end }}
{{- end }}

{{/*
Service Loadbalancer source ranges template
*/}}
{{- define "ngsearch.template.service.loadBalancerSourceRanges" -}}
  {{- with . }}
  loadBalancerSourceRanges:
  {{- toYaml . | nindent 4}}
  {{- end }}
{{- end }}


{{- define "ngsearch.template.ingress.restAPI" -}}
{{- $fullName := index . 0 -}}
{{- $servicePort := index . 1 -}}
{{- $GitVersion := index . 2 -}}
{{- if semverCompare ">=1.20-0" $GitVersion }}
pathType: Prefix
{{- end }}
backend:
{{- if semverCompare ">=1.20-0" $GitVersion }}
  service:
    name: {{ $fullName }}-ngsearch-rest-api
    port:
      number: {{ $servicePort | default 8000 }}
{{- else }}
  serviceName: {{ $fullName }}-ngsearch-rest-api
  servicePort: {{ $servicePort | default 8000 }}
{{- end }}
{{- end -}}

{{- define "ngsearch.template.ingress.restAPIMulti" -}}
{{- $fullName := index . 0 -}}
{{- $name := index . 1 -}}
{{- $servicePort := index . 2 -}}
{{- $GitVersion := index . 3 -}}
{{- if semverCompare ">=1.20-0" $GitVersion }}
pathType: Prefix
{{- end }}
backend:
{{- if semverCompare ">=1.20-0" $GitVersion }}
  service:
    name: {{ $fullName }}-ngsearch-rest-api-{{ $name | replace "_" "-"}}
    port:
      number: {{ $servicePort | default 8000 }}
{{- else }}
  serviceName: {{ $fullName }}-ngsearch-rest-api-{{ $name | replace "_" "-"}}
  servicePort: {{ $servicePort | default 8000 }}
{{- end }}
{{- end -}}


{{/*
VLM API Key Secret Fields template
*/}}
{{- define "ngsearch.template.vlm.config" -}}
{{- $outer := . -}}
  {{- if .source.base_url }}
- name: {{ printf "%sBASE_URL" $outer.source.env_prefix }}
  value: {{ .source.base_url | quote }}
  {{- end }}
- name: {{ $outer.source.env_prefix }}API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .source.api_key_secret_name }}
      key: {{ .source.api_key_secret_field }}
{{- end -}}



{{/*
VLM API Key Secret name
*/}}
{{- define "ngsearch.template.vlm.apiKeySecretName" -}}
name: {{ .source.api_key_secret_name }}
{{- end -}}

{{/*
VLM API Key Secret value
*/}}
{{- define "ngsearch.template.vlm.apiKeySecretValue" -}}
{{- $message := (printf "Please provide '%s' API KEY: --set ngsearch.microservices.search_rest_api.validation.%s.api_key=<API KEY>" .vlm_type .vlm_type ) -}}
{{ .source.api_key_secret_field }}: {{ required $message (.source.api_key | toString | b64enc ) }}
{{- end -}}
