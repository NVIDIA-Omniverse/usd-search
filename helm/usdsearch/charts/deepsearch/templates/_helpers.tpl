{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "deepsearch.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "deepsearch.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "deepsearch.fullname" -}}
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
{{- define "deepsearch.license" -}}
  {{- if .Values.global.accept_eula }}
  {{- printf "%d" 1 }}
  {{- end }}
{{- end -}}

{{/*
Plugin config
*/}}
{{- define "deepsearch.plugin-config" -}}
  {{- toYaml .Values.plugins | indent 2 }}
{{- end -}}

{{/*
Create a fully functional metrics service name
*/}}
{{- define "deepsearch.metrics" -}}
{{- (include "deepsearch.fullname" .) -}}-metrics
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "deepsearch.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "deepsearch.labels" -}}
helm.sh/chart: {{ include "deepsearch.chart" . }}
{{ include "deepsearch.selectorLabels" . }}
{{- if .Values.global.appVersion }}
app.kubernetes.io/version: {{ .Values.global.appVersion | quote }}
{{- end }}
app.kubernetes.io/component: "deepsearch"
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
DeepSearch rendering job labels
*/}}
{{- define "deepsearch.renderingJobLabels" -}}
{{ include "deepsearch.labels" . }}
deepsearch.job-type: rendering
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "deepsearch.MainDeploymentlabels" -}}
{{ include "deepsearch.labels" . }}
deepsearch.deployment: main
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "deepsearch.MainDeploymentSelectorlabels" -}}
{{ include "deepsearch.selectorLabels" . }}
deepsearch.deployment: main
{{- end -}}

{{/*
Main deployment labels
*/}}
{{- define "deepsearch.EmbeddingDeploymentSelectorlabels" -}}
{{ include "deepsearch.selectorLabels" . }}
deepsearch.deployment: embedding
{{- end -}}


{{/*
Selector labels
*/}}
{{- define "deepsearch.selectorLabels" -}}
app.kubernetes.io/name: {{ include "deepsearch.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "deepsearch.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "deepsearch.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "deepsearch.renderingJobServiceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (printf "%s-%s" (include "deepsearch.fullname" .) "rendering" ) .Values.renderingJobServiceAccount.name }}
{{- else -}}
    {{ default "default" .Values.renderingJobServiceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "deepsearch.listerJobServiceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (printf "%s-%s" (include "deepsearch.fullname" .) "listing" ) .Values.listerJobServiceAccount.name }}
{{- else -}}
    {{ default "default" .Values.listerJobServiceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Docker image for the monitor / info-endpoint / plugin-worker pods.
Defaults to the unified `usdsearch` image; honors per-service overrides
(microservices.monitor.image.name) for backwards compatibility.
*/}}
{{- define "deepsearch.monitorDockerImage" -}}
{{- $img := .Values.microservices.monitor.image -}}
{{- if $img.name -}}
{{ default .Values.global.registry .Values.microservices.monitor.registry }}/{{ $img.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) $img.tag }}
{{- else -}}
{{ include "deepsearch-global.usdsearchImage" . }}
{{- end -}}
{{- end -}}

{{/*
Docker image for the k8s rendering Job template.
Defaults to the unified `rendering-job` (Kit) image.
*/}}
{{- define "deepsearch.k8sRendererDockerImage" -}}
{{- $img := .Values.microservices.k8s_renderer.image -}}
{{- if $img.name -}}
{{ default .Values.global.registry .Values.microservices.k8s_renderer.registry }}/{{ $img.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) $img.tag }}
{{- else -}}
{{ include "deepsearch-global.renderingJobImage" . }}
{{- end -}}
{{- end -}}


{{/*
Docker image for the embedding microservice (Triton Inference Server).
Defaults to the unified `siglip2-triton` image.
*/}}
{{- define "deepsearch.embeddingDockerImage" -}}
{{- $img := .Values.microservices.embedding.image -}}
{{- if $img.name -}}
{{ default .Values.global.registry .Values.microservices.embedding.registry }}/{{ $img.name }}:{{ default (include "deepsearch-global.unifiedImageTag" .) $img.tag }}
{{- else -}}
{{ include "deepsearch-global.siglip2TritonImage" . }}
{{- end -}}
{{- end -}}


{{/*
DeepSearch endpoint just for visualization
*/}}
{{- define "deepsearch.DeepSearchEmbeddingEndPoint" -}}
  {{- range $k, $v := .Values.microservices.embedding.service }}
    {{- if eq $v.type "ingress" }}
      {{- printf "\n      - %s: %s" ( $k ) ( $v.host ) }}
    {{- end }}
    {{- if eq (lower $v.type) "nodeport" }}
      {{- printf "\n      - %s: %s:%s" ( $k ) ( $.Values.global.nodeIP | default $.Values.nodeIP ) ( $v.nodeport | toString) }}
    {{- end }}
  {{- end }}
{{- end -}}


{{/*
Elastic Search endpoint
*/}}
{{- define "deepsearch.ESEndPoint" -}}
  {{- with .Values.microservices.elastic_search }}
    {{- if eq .type "ingress" }}
        {{- printf ( .host ) }}
    {{- end }}
    {{- if eq (lower .type) "nodeport" }}
    {{- printf "%s:%s" ($.Values.global.nodeIP | default $.Values.nodeIP) (.nodeport | toString) }}
    {{- end }}
  {{- end }}
{{- end -}}

{{/*
Crawler receiving websocket
*/}}
{{- define "deepsearch.farmRecevierEndPoint" -}}
  {{- with .Values.microservices.plugin_worker.service }}
    {{- if .endpoint_override.enabled }}
      {{- printf "http://%s:%s" (.endpoint_override.host) (.endpoint_override.port | toString) }}
    {{- else }}
      {{- if eq .type "ingress" }}
      {{- printf "http://%s:80" (.host) }}
      {{- end }}
        {{- if eq (lower .type) "nodeport" }}
      {{- printf "http://%s:%s" ( $.Values.global.nodeIP | default $.Values.nodeIP ) (.nodeport | toString) }}
      {{- end }}
    {{- end}}
  {{- end}}
{{- end}}


{{/*
Exclude strings
*/}}

{{- define "deepsearch.excludeIndexingStringsPatterns" -}}
{{- printf "['%s']" ( join "', '" (.Values.exclude_patterns | default .Values.global.exclude_patterns) ) -}}
{{- end -}}

{{/*
Service Type template
*/}}
{{- define "deepsearch.template.service.type" -}}
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
{{- define "deepsearch.template.service.annotations" -}}
  {{- with . }}
  annotations:
  {{- toYaml . | nindent 4}}
  {{- end }}
{{- end }}

{{/*
VLM API Key Secret Fields template
*/}}
{{- define "deepsearch.template.vlm.config" -}}
{{- $outer := . -}}
{{- if .source -}}
  {{- $base_url := ( .source.base_url | default .default.base_url ) }}
  {{- if $base_url }}
- name: {{ printf "%sBASE_URL" ( $outer.source.env_prefix | default $outer.default.env_prefix ) }}
  value: {{ $base_url | quote }}
  {{- end }}
- name: {{ $outer.source.env_prefix | default $outer.default.env_prefix }}API_KEY
{{- else -}}
  {{- if .default.base_url }}
- name: {{ printf "%sBASE_URL" $outer.default.env_prefix }}
  value: {{ .default.base_url | quote }}
  {{- end }}
- name: {{ $outer.default.env_prefix }}API_KEY
{{- end }}
  valueFrom:
    secretKeyRef:
  {{- if .source }}
      name: {{ .source.api_key_secret_name | default .default.api_key_secret_name }}
      key: {{ .source.api_key_secret_field | default .default.api_key_secret_field }}
  {{- else }}
      name: {{ .default.api_key_secret_name }}
      key: {{ .default.api_key_secret_field }}
  {{- end -}}
{{- end -}}

{{/*
VLM API Key Secret name
*/}}
{{- define "deepsearch.template.vlm.apiKeySecretName" -}}
{{- if .source -}}
name: {{ .source.api_key_secret_name | default .default.api_key_secret_name }}
{{- else -}}
name: {{ .default.api_key_secret_name }}
{{- end -}}
{{- end -}}

{{/*
VLM API Key Secret value
*/}}
{{- define "deepsearch.template.vlm.apiKeySecretValue" -}}
{{- $message := (printf "Please provide '%s' API KEY: --set deepsearch.vision_endpoint.%s.api_key=<API KEY>" .vlm_type .vlm_type ) -}}
{{- if .source -}}
{{ .source.api_key_secret_field | default .default.api_key_secret_field }}: {{ required $message (.source.api_key | default .default.api_key | toString | b64enc ) }}
{{- else -}}
{{ .default.api_key_secret_field }}: {{ required $message .default.api_key | toString | b64enc }}
{{- end -}}
{{- end -}}

{{/*
Service Loadbalancer source ranges template
*/}}
{{- define "deepsearch.template.service.loadBalancerSourceRanges" -}}
  {{- with . }}
  loadBalancerSourceRanges:
  {{- toYaml . | nindent 4}}
  {{- end }}
{{- end }}


{{/*
HTTP service liveness check
*/}}
{{- define "deepsearch.template.service.httpLivenessCheck" -}}
- name: {{ .name }}
  {{- with .securityContext }}
  securityContext:
    {{- toYaml . | nindent 4 }}
  {{- end}}
  image: {{ .image }}
  imagePullPolicy: {{ .imagePullPolicy | default "IfNotPresent" }}
  {{- with .resources }}
  resources:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  command:
  - python
  - -c
  - |
    import requests, time, os
    ready = False
    while not ready:
      try:
        requests.get("{{ .endpoint }}")
        ready = True
      except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError):
        print('{{ .name }} service at "{{ .endpoint }}" endpoint is not ready')
        time.sleep(2)
    print('{{ .name }} service at "{{ .endpoint }}" endpoint is ready')
{{- end }}
