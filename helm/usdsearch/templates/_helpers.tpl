{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "deepsearch-global.releaseName" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "deepsearch-global.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Define Image Pull Secrets template
*/}}
{{- define "deepsearch-global.imagePullSecrets" -}}
{{- if or (.Values.global.imagePullSecrets) ( .Values.global.ngcImagePullSecretName ) -}}
imagePullSecrets:
{{- end -}}
{{- with .Values.global.imagePullSecrets -}}
{{- toYaml . | nindent 2 }}
{{- end -}}
{{- $names := list }}
{{- range $secret := .Values.global.imagePullSecrets }}
  {{- if eq (kindOf $secret) "string" }}
    {{- $names = append $names $secret }}
  {{- else if eq (kindOf $secret) "map" }}
    {{- with $secret.name }}
      {{- $names = append $names . }}
    {{- end}}
  {{- end }}
{{- end }}
  {{- if not (has .Values.global.ngcImagePullSecretName $names) }}
    {{- with .Values.global.ngcImagePullSecretName }}
  - name: {{ . }}
    {{- end -}}
  {{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "deepsearch-global.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "deepsearch-global.selectorLabels" -}}
app.kubernetes.io/name: {{ include "deepsearch-global.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "deepsearch-global.labels" -}}
helm.sh/chart: {{ include "deepsearch-global.chart" . }}
{{ include "deepsearch-global.selectorLabels" . }}
{{- if .Values.global.appVersion }}
app.kubernetes.io/version: {{ .Values.global.appVersion | quote }}
app-version: {{ .Values.global.appVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}


{{/*
Automatically infer crawler groups depending on the initial setup. If the setup was changes over the course of running service - Crawler needs to be recreated
*/}}
{{- define "deepsearch-global.crawlerGroups" -}}
{{- printf "[" -}}
{{- printf "'deepsearch-monitor'," -}}
{{- if gt (int .Values.ngsearch.microservices.indexing.replicas) 0 -}}
{{- printf "'indexing-service'," -}}
{{- end -}}
{{- if and (gt (int .Values.ngsearch.microservices.tagcrawler.replicas) 0) (ne .Values.global.storage_backend_type "s3") -}}
{{- printf "'tag-crawler-service'," -}}
{{- end -}}
{{- printf "]" -}}
{{- end -}}


{{/*
Unified container images.
Render the registry-qualified ref for one of the three unified images
published from this repo. The shared `global.appVersion` (stamped from the
latest `images-X.Y.Z` tag at package time) drives the tag for all three;
per-image `global.image.<name>.tag` overrides take precedence. Inside a
sub-chart context `.Chart.AppVersion` would be the sub-chart's own version,
so we deliberately go through `global.appVersion` instead.
*/}}
{{- define "deepsearch-global.unifiedImageTag" -}}
{{ .Values.global.appVersion | default "0.0.0-dev" }}
{{- end -}}

{{- define "deepsearch-global.usdsearchImage" -}}
{{ .Values.global.registry }}/{{ .Values.global.image.usdsearch.repository }}:{{ .Values.global.image.usdsearch.tag | default (include "deepsearch-global.unifiedImageTag" .) }}
{{- end -}}

{{- define "deepsearch-global.siglip2TritonImage" -}}
{{ .Values.global.registry }}/{{ .Values.global.image.siglip2_triton.repository }}:{{ .Values.global.image.siglip2_triton.tag | default (include "deepsearch-global.unifiedImageTag" .) }}
{{- end -}}

{{- define "deepsearch-global.renderingJobImage" -}}
{{ .Values.global.registry }}/{{ .Values.global.image.rendering_job.repository }}:{{ .Values.global.image.rendering_job.tag | default (include "deepsearch-global.unifiedImageTag" .) }}
{{- end -}}

{{- define "deepsearch-global.imagePullPolicy" -}}
{{ .Values.global.image.pullPolicy | default "IfNotPresent" }}
{{- end -}}


{{/*
For inline NGC key, create image pull secret
*/}}
{{- define "deepsearch-global.generatedImagePullSecret" -}}
{{- if .Values.global.ngcAPIKey }}
{{- printf "{\"auths\":{\"nvcr.io\":{\"username\":\"$oauthtoken\",\"password\":\"%s\"}}}" ( required "Please input NGC API Key: --set global.ngcAPIKey=<NGC API KEY>" .Values.global.ngcAPIKey ) | b64enc }}
{{- end }}
{{- end }}


{{- define "dictToCommaList" -}}
  {{- $values := list -}}
    {{- range $line := (splitList "\n" .) -}}
      {{- if $line -}}
        {{- $parts := (splitList ": " (trim $line)) -}}
        {{- if gt (len $parts) 1 -}}
          {{- $filter := (printf "%s=%s" (replace "\"" "" (index $parts 0)) (replace "\"" "" (index $parts 1)) )}}
          {{- $values = append $values $filter -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
  {{- join "," $values -}}
{{- end -}}

{{/*
Storage API Authentication Environment Variables
Generates environment variables for storage API authentication based on configuration
Usage: {{ include "deepsearch-global.storageApiAuth" . }}
*/}}
{{- define "deepsearch-global.storageApiAuth" -}}
{{- if eq .Values.global.storage_backend_type "storage_api" }}
{{- if .Values.global.storage_api.authentication.enabled }}
{{- if eq .Values.global.storage_api.authentication.type "token" }}
- name: STORAGE_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.storage_api.authentication.secret_name }}
      key: {{ .Values.global.storage_api.authentication.secret_key }}
{{- else if eq .Values.global.storage_api.authentication.type "openid" }}
- name: STORAGE_API_OPENID_TOKEN_URL
  value: "{{ ( required "Please input OpenID Token URL: --set global.storage_api.authentication.openid.token_url=<OPENID TOKEN URL>" .Values.global.storage_api.authentication.openid.token_url) }}"
- name: STORAGE_API_OPENID_GRANT_TYPE
  value: "{{ .Values.global.storage_api.authentication.openid.grant_type }}"
- name: STORAGE_API_OPENID_CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.storage_api.authentication.secret_name }}
      key: {{ .Values.global.storage_api.authentication.openid.client_id_secret_key }}
- name: STORAGE_API_OPENID_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.storage_api.authentication.secret_name }}
      key: {{ .Values.global.storage_api.authentication.openid.client_secret_secret_key }}
- name: STORAGE_API_OPENID_SCOPE
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.storage_api.authentication.secret_name }}
      key: {{ .Values.global.storage_api.authentication.openid.scope_secret_key }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}


{{/*
Storage API Basic Configuration Environment Variables
Generates basic storage API configuration environment variables
Usage: {{ include "deepsearch-global.storageApiConfig" . }}
*/}}
{{- define "deepsearch-global.storageApiConfig" -}}
{{- if eq .Values.global.storage_backend_type "storage_api" }}
- name: STORAGE_API_GRPC_ENDPOINT
  value: "{{ .Values.global.storage_api.grpc_endpoint }}"
- name: STORAGE_API_BASE_URI
  value: "{{ .Values.global.storage_api.base_uri }}"
- name: STORAGE_API_SSL
  value: "{{ .Values.global.storage_api.ssl }}"
- name: STORAGE_API_NOTIFICATION_SUBSCRIPTION_ENABLED
  value: "{{ .Values.global.storage_api.notification_subscription_enabled }}"
{{- if .Values.global.storage_api.notifications_grpc_endpoint }}
- name: STORAGE_API_NOTIFICATION_SERVICE_GRPC_ENDPOINT
  value: "{{ .Values.global.storage_api.notifications_grpc_endpoint }}"
{{- end }}
- name: STORAGE_API_IGNORE_FILE_FOLDER_API
  value: {{ .Values.global.storage_api.ignore_filefolder_api | quote }}
- name: STORAGE_API_RE_SCAN_TIMEOUT
  value: {{ .Values.global.storage_api.re_scan_timeout | quote }}
{{- if .Values.global.storage_api.thumbnail_metadata_fields }}
- name: STORAGE_API_THUMBNAIL_METADATA_FIELDS
  value: {{ .Values.global.storage_api.thumbnail_metadata_fields | toJson | quote }}
{{- end }}
- name: OV_USERNAME
  value: ""
- name: OV_PASSWORD
  value: ""
{{- end }}
{{- end }}

{{/*
Complete Storage API Environment Variables
Combines both configuration and authentication environment variables
Usage: {{ include "deepsearch-global.storageApiComplete" . }}
*/}}
{{- define "deepsearch-global.storageApiComplete" -}}
{{- include "deepsearch-global.storageApiConfig" . }}
{{- include "deepsearch-global.storageApiAuth" . }}
{{- end }}

{{/*
S3 Storage Authentication Environment Variables
Generates environment variables for S3 authentication based on configuration
Usage: {{ include "deepsearch-global.s3Auth" . }}
*/}}
{{- define "deepsearch-global.s3Auth" -}}
{{- if eq .Values.global.storage_backend_type "s3" }}
{{- if and .Values.global.s3.authentication_enabled .Values.global.s3.aws_credentials_secret_name (not .Values.global.s3proxy.enabled) }}
- name: S3_STORAGE_AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.s3.aws_credentials_secret_name }}
      key: AWS_ACCESS_KEY_ID
- name: S3_STORAGE_AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.s3.aws_credentials_secret_name }}
      key: AWS_SECRET_ACCESS_KEY
{{- end }}
{{- end }}
{{- end }}

{{/*
S3 Storage Configuration Environment Variables
Generates basic S3 configuration environment variables
Usage: {{ include "deepsearch-global.s3Config" . }}
*/}}
{{- define "deepsearch-global.s3Config" -}}
{{- if eq .Values.global.storage_backend_type "s3" }}
- name: S3_STORAGE_BUCKET_NAME
  value: "{{ .Values.global.s3.bucket_name }}"
{{- if .Values.global.s3.region_name }}
- name: S3_STORAGE_REGION_NAME
  value: "{{ .Values.global.s3.region_name }}"
{{- end }}
- name: S3_STORAGE_RE_SCAN_TIMEOUT
  value: {{ .Values.global.s3.re_scan_timeout | quote }}
{{- if .Values.global.s3proxy.enabled }}
- name: S3_STORAGE_AWS_ENDPOINT_URL
  value: "http://{{ .Release.Name }}-s3proxy-service.{{ .Release.Namespace }}.svc.cluster.local:80"
{{- else if .Values.global.s3.aws_endpoint_url }}
- name: S3_STORAGE_AWS_ENDPOINT_URL
  value: "{{ .Values.global.s3.aws_endpoint_url | default "" }}"
{{- end }}
- name: S3_STORAGE_ALLOW_SYSTEM_WRITES
  value: {{ .Values.global.s3.allow_system_writes | default "True" | quote }}
- name: S3_STORAGE_ALLOW_NON_SYSTEM_WRITES
  value: {{ .Values.global.s3.allow_non_system_writes | default "True" | quote }}
- name: OV_USERNAME
  value: ""
- name: OV_PASSWORD
  value: ""
{{- end }}
{{- end }}

{{/*
Complete S3 Storage Environment Variables
Combines both configuration and authentication environment variables
Usage: {{ include "deepsearch-global.s3Complete" . }}
*/}}
{{- define "deepsearch-global.s3Complete" -}}
{{- include "deepsearch-global.s3Config" . }}
{{- include "deepsearch-global.s3Auth" . }}
{{- end }}

{{/*
Nucleus Storage Authentication Environment Variables
Generates environment variables for Nucleus authentication based on configuration
Usage: {{ include "deepsearch-global.nucleusAuth" . }}
*/}}
{{- define "deepsearch-global.nucleusAuth" -}}
{{- if eq .Values.global.storage_backend_type "nucleus" }}
- name: OV_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ default .Values.global.nucleus.service_account_secret .Values.service_account_secret }}
      key: username
- name: OV_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ default .Values.global.nucleus.service_account_secret .Values.service_account_secret }}
      key: password
{{- end }}
{{- end }}

{{/*
Nucleus Storage Configuration Environment Variables
Generates basic Nucleus configuration environment variables
Usage: {{ include "deepsearch-global.nucleusConfig" . }}
*/}}
{{- define "deepsearch-global.nucleusConfig" -}}
{{- if eq .Values.global.storage_backend_type "nucleus" }}
- name: OV_SERVER
  value: {{ required "Please input Omniverse Nucleus server hostname or IP: --set global.nucleus.server=<Omniverse Nucleus server hostname or IP>" .Values.global.nucleus.server | quote }}
- name: NUCLEUS_DEPLOYMENT_LOOKUP
  value: "{{ .Values.global.nucleus.deployment_lookup | default "internal" }}"
- name: ASSERT_ADMIN_USER
  value: "{{ .Values.global.nucleus.assert_admin_user }}"
{{- if .Values.global.nucleus.skip_mounts }}
- name: SKIP_MOUNTS
  value: "{{ .Values.global.nucleus.skip_mounts | default "False" }}"
{{- end }}
{{- end }}
{{- end }}

{{/*
Complete Nucleus Storage Environment Variables
Combines both configuration and authentication environment variables
Usage: {{ include "deepsearch-global.nucleusComplete" . }}
*/}}
{{- define "deepsearch-global.nucleusComplete" -}}
{{- include "deepsearch-global.nucleusConfig" . }}
{{- include "deepsearch-global.nucleusAuth" . }}
{{- end }}

{{/*
Azure Storage Authentication Environment Variables
Generates environment variables for Azure authentication based on configuration
Usage: {{ include "deepsearch-global.azureAuth" . }}
*/}}
{{- define "deepsearch-global.azureAuth" -}}
{{- if eq .Values.global.storage_backend_type "azure" }}
{{- if .Values.global.azure.azure_credentials_secret_name }}
- name: AZURE_STORAGE_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.azure.azure_credentials_secret_name }}
      key: AZURE_STORAGE_ACCESS_KEY
- name: AZURE_STORAGE_ACCOUNT_NAME
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.azure.azure_credentials_secret_name }}
      key: AZURE_STORAGE_ACCOUNT_NAME
{{- end }}
{{- end }}
{{- end }}

{{/*
Azure Storage Configuration Environment Variables
Generates basic Azure configuration environment variables
Usage: {{ include "deepsearch-global.azureConfig" . }}
*/}}
{{- define "deepsearch-global.azureConfig" -}}
{{- if eq .Values.global.storage_backend_type "azure" }}
- name: AZURE_STORAGE_URL
  value: "{{ .Values.global.azure.url }}"
- name: AZURE_STORAGE_CONTAINER_NAME
  value: "{{ .Values.global.azure.container_name }}"
- name: AZURE_STORAGE_ALLOW_SYSTEM_WRITES
  value: {{ .Values.global.azure.allow_system_writes | default "True" | quote }}
- name: AZURE_STORAGE_ALLOW_NON_SYSTEM_WRITES
  value: {{ .Values.global.azure.allow_non_system_writes | default "True" | quote }}
- name: OV_USERNAME
  value: ""
- name: OV_PASSWORD
  value: ""
{{- end }}
{{- end }}

{{/*
Complete Azure Storage Environment Variables
Combines both configuration and authentication environment variables
Usage: {{ include "deepsearch-global.azureComplete" . }}
*/}}
{{- define "deepsearch-global.azureComplete" -}}
{{- include "deepsearch-global.azureConfig" . }}
{{- include "deepsearch-global.azureAuth" . }}
{{- end }}

{{/*
Search Backend Configuration Environment Variables
Generates ES/OpenSearch configuration environment variables for use in pod container env sections.
Usage: {{ include "deepsearch-global.searchBackendConfig" . }}
*/}}
{{- define "deepsearch-global.searchBackendConfig" -}}
{{- with .Values.global.search_backend_config }}
- name: OS_SERIALIZER
  value: {{ .serializer | default "orjson" | quote }}
- name: ES_HOST
  value: {{ .host | quote }}
- name: ES_PORT
  value: {{ .port | quote }}
- name: ES_PROTOCOL
  value: {{ .schema | default "http" | quote }}
- name: ES_NAME
  value: {{ .index_name | quote }}
- name: BACKEND_TYPE
  value: {{ .backend_type | quote }}
- name: NUMBER_OF_SHARDS
  value: {{ .number_of_shards | quote }}
{{- if .max_chunk_size }}
- name: MAX_CHUNK_BYTES
  value: {{ .max_chunk_size | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Search Backend Authentication Environment Variables
Generates environment variables for ES/OpenSearch authentication from a secret.
Usage: {{ include "deepsearch-global.searchBackendAuth" . }}
*/}}
{{- define "deepsearch-global.searchBackendAuth" -}}
{{- with .Values.global.search_backend_config }}
{{- if .auth_secret_name }}
- name: ES_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: username
      optional: true
- name: ES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: password
      optional: true
- name: ES_CLOUD_ID
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: cloud_id
      optional: true
- name: ES_BEARER_AUTH
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: bearer_auth
      optional: true
- name: ES_OPAQUE_ID
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: opaque_id
      optional: true
- name: ES_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .auth_secret_name }}
      key: api_key
      optional: true
{{- end }}
{{- if .hosts }}
- name: ES_HOSTS
  value: {{ .hosts }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Complete Search Backend Environment Variables (pod env format)
Combines configuration and authentication environment variables for use in pod container env sections.
Usage: {{ include "deepsearch-global.searchBackendComplete" . }}
*/}}
{{- define "deepsearch-global.searchBackendComplete" -}}
{{- include "deepsearch-global.searchBackendConfig" . }}
{{- include "deepsearch-global.searchBackendAuth" . }}
{{- end }}

{{/*
Search backend readiness init container.
Polls NGSearchStorageClient until backend_ready is set, blocking pod startup until
the search backend (OpenSearch) is available.
Usage: {{- include "deepsearch-global.searchBackendCheck" (dict "ctx" . "image" $image "fullName" $fullName) | nindent 8 }}
*/}}
{{- define "deepsearch-global.searchBackendCheck" -}}
{{- $ctx := .ctx -}}
{{- $image := .image -}}
{{- $fullName := .fullName -}}
- name: search-backend-check
  securityContext:
    {{- toYaml $ctx.Values.securityContext | nindent 4 }}
  image: {{ $image }}
  imagePullPolicy: {{ $ctx.Values.imagePullPolicy }}
  command:
  - python
  - -c
  - |
    from storage.src.client import NGSearchStorageClient
    import asyncio
    async def init_task():
      while True:
        try:
          client = await NGSearchStorageClient.get_service()
          async with client as client_context:
            await client_context.client.backend_ready.wait()
            print("search backend is ready")
            break
        except Exception as e:
          print(e)
          await asyncio.sleep(1)
    asyncio.run(init_task())
  envFrom:
    - configMapRef:
        name: {{ $fullName }}-env-config
  env:
  {{- if eq $ctx.Values.global.storage_backend_type "nucleus" }}
    {{- include "deepsearch-global.nucleusComplete" $ctx | nindent 4 }}
  {{- else if eq $ctx.Values.global.storage_backend_type "s3" }}
    {{- include "deepsearch-global.s3Complete" $ctx | nindent 4 }}
  {{- else if eq $ctx.Values.global.storage_backend_type "azure" }}
    {{- include "deepsearch-global.azureComplete" $ctx | nindent 4 }}
  {{- else if eq $ctx.Values.global.storage_backend_type "storage_api" }}
    {{- include "deepsearch-global.storageApiComplete" $ctx | nindent 4 }}
  {{- end }}
    {{- include "deepsearch-global.searchBackendComplete" $ctx | nindent 4 }}
  resources:
    requests:
      cpu: 200m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 128Mi
{{- end }}

{{/*
Data Loader Output URL
Constructs the OpenSearch output URL, appending the output index if configured.
Usage: {{ include "deepsearch-global.dataLoaderOutputURL" . }}
*/}}
{{- define "deepsearch-global.dataLoaderOutputURL" -}}
{{- $baseURL := printf "%s://%s:%s" .Values.global.search_backend_config.schema .Values.global.search_backend_config.host (toString .Values.global.search_backend_config.port) -}}
{{- $baseURL -}}
{{- end }}
