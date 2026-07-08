# Helm runbook (Kubernetes)

You are installing the `usdsearch` Helm chart at `helm/usdsearch/`.

## H1: Verify prerequisites

- Kubernetes cluster with GPU nodes (min 1 NVIDIA GPU for embedding;
  +1 RTX for rendering if enabled)
- Helm 3+
- Storage-backend connection details (gathered in H2), one of:
  - **Public S3** — nothing (anonymous `omniverse-content-production`).
  - **Custom S3** — bucket name, region, and AWS credential env-var names.
  - **Storage API** — gRPC endpoint, base URI, and (if authenticated)
    token or OpenID client-credential env-var names.
  - **Nucleus** — server hostname/IP and `OV_USERNAME` / `OV_PASSWORD`
    env-var names.
- VLM API key env-var name if labeling/validation enabled
- Sufficient PV capacity (see `helm/usdsearch/values.yaml` for Redis,
  OpenSearch, Neo4j storage sizes)

The chart supports every backend the compose quickstart does **except
Local filesystem** — that lane is a single-host dev convenience (s3proxy
over a mounted directory) and has no Kubernetes equivalent. Point a
cluster at a real S3 bucket, Storage API service, or Nucleus server
instead.

The published USD Search images on `nvcr.io/nvidia/usdsearch` are
publicly pullable; **no NGC API key / docker-registry pull secret is
required for the default install.** Only create one if you've
re-mirrored the images to a private registry or are pulling pre-release
builds — see "Private registry" at the end of H5.

## H2: Required information

First ask **which storage backend** to index, then the backend-specific
follow-ups, then namespace.

### H2.0: Storage backend

Pose the question with this wording verbatim: "Which storage backend
should USD Search index?" Same two conceptual groups as the compose
branch, but **without** the Local filesystem option (no cluster
equivalent).

- **Header:** "Backend"
- **Options** (labels/descriptions verbatim; add the bracketed group
  prefix only for picker runtimes that need it):
  - A) **[Search a Public Asset library] Public S3** — Indexes NVIDIA's
    omniverse-content-production bucket - no credentials needed. Great
    for exploring sample USD assets.
  - B) **[Search Your Own Library] Custom S3 bucket** — Your own S3
    bucket. You'll need bucket name, region, and credentials (if
    relevant).
  - C) **[Search Your Own Library] Storage API** — Your own Storage API
    service. You'll need GRPC endpoint, Base URI, and credentials (if
    relevant).
  - D) **[Search Your Own Library] Nucleus (to be deprecated)** — NVIDIA
    Omniverse Nucleus server. Requires your own server hostname/IP plus
    `OV_USERNAME` / `OV_PASSWORD`. Note: Nucleus backend will be
    deprecated soon - S3 bucket is favorable.
- Free-form input is always available ("Type something else") — don't
  add an explicit "Other" option manually.

The selection sets `global.storage_backend_type` in H5
(`s3` / `storage_api` / `nucleus`; Public and Custom S3 both use `s3`).

### H2.1: Backend follow-ups

**Namespace** (ask for every backend): default `usdsearch` — or the
user's currently active namespace if they specified one.

- **A) Public S3** — no further questions; the anonymous public bucket
  is read-only. (H5 sets `authentication_enabled: false` and disables
  writes.)
- **B) Custom S3** — ask for:
  - Bucket name and region.
  - **AWS credential env-var names** (`AWS_ACCESS_KEY_ID`-shaped names
    only; never the raw values). Skip if the bucket is anonymous/public.
  - **Is the bucket read-only?**
    - A) **Writable** — Default. Workers upload thumbnails. Leaves
      `global.s3.allow_non_system_writes: true` (the chart default).
    - B) **Read-only** — Set `global.s3.allow_non_system_writes: false`
      in H5 so the thumbnail-generation worker short-circuits instead of
      attempting `PutObject` on every asset.
- **C) Storage API** — ask for:
  - **gRPC endpoint** (`global.storage_api.grpc_endpoint`) and **base
    URI** (`global.storage_api.base_uri` — the bucket/blob URL the
    Storage API fronts).
  - **SSL?** (`global.storage_api.ssl`, default false) — true if the
    gRPC endpoint uses TLS (`:443`).
  - **Authentication** — none, token, or OpenID. For token: the env-var
    **name** holding the token. For OpenID: the literal token URL +
    scope, plus the env-var **names** for client id and client secret.
    Never the raw values.
- **D) Nucleus** — ask for:
  - **Server** hostname or IP (`global.nucleus.server`). Do not suggest
    one.
  - **`OV_USERNAME` / `OV_PASSWORD`** env-var names (service-account
    credentials; never the raw values).

## H3: Optional features

Ask each as its own structured question:

- **VLM Labeling** — generates descriptions, materials, colours per
  asset. Requires an API key for any OpenAI-compatible server. Ask for
  the env-var name holding the key (e.g. `USDSEARCH_LLM_API_KEY`) and
  the model name. Configures `deepsearch.vision_endpoint.provider` and
  `deepsearch.vision_endpoint.metadata_model`.
- **VLM Validation** — server-side result validation, agents can pass
  `validate_results=true` for confidence scores. Shares the same LLM
  provider. Configures
  `ngsearch.microservices.search_rest_api.validation.enabled` and
  `ngsearch.microservices.search_rest_api.validation.provider`.
- **LLM query parsing** — parses free-text queries
  into structured filters via `POST /llm_parse/query` (filter discovery
  via `GET /llm_parse/fields`). **Enabled by default**
  (`ngsearch.microservices.search_rest_api.llm_parsing.enabled`; model
  override via `.llm_parsing.model`, env `USDSEARCH_LLM_PARSING_MODEL`;
  output-token cap via `.llm_parsing.max_tokens`, default 1024, env
  `USDSEARCH_LLM_PARSING_MAX_TOKENS`).
  Uses the same shared LLM provider/secret as the two features above by
  default — no extra key needed. To point it at its OWN endpoint, set
  `ngsearch.microservices.search_rest_api.llm_parsing.provider.{base_url,api_key}`
  (envs `USDSEARCH_LLM_PARSING_BASE_URL` / `USDSEARCH_LLM_PARSING_API_KEY`).
  Without a reachable LLM the `/llm_parse/*` endpoints return 503 and
  clients fall back to plain hybrid search, so it is safe to leave enabled.
  - **Custom filter catalog** — point parsing at a deployment-specific
    `search_fields.yaml` via `.llm_parsing.fields` (env
    `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH`).
  - **Corpus property grounding** — after indexing, run `/usd-property-catalog`
    to build a `usd_property_catalog.yaml` of the keys/values your corpus
    actually carries, then paste it into `.llm_parsing.property_catalog` (env
    `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH`). The parser then grounds
    the generic `usd_property` filter on real keys/values instead of guessing.
- **Asset Graph Service** — spatial queries + dependency tracking.
  Requires Neo4j, adds ~4 GB RAM. Default: enabled. Toggle via
  `asset_graph_service_deployment.enabled`.
- **Rendering mode** — rendering is **always on**; the question is
  *how* the workers render. Two modes:
  - **Per-job `k8s_renderer` (default)** — every render request spawns
    a short-lived Kit-renderer Job. No persistent rendering pods,
    scales to zero between requests. **Do not add any of the
    `rendering_service_deployment` / `rendering_service` /
    `k8s_renderer` / `plugin_worker.rendering_settings` keys** —
    leaving them at chart defaults gives this mode.
  - **Persistent `rendering_service` (opt-in)** — keeps a Kit-renderer
    deployment hot for lower per-request latency at the cost of
    always-on GPU reservation. Only switch when the user explicitly
    asks for it. Requires adding the four-key block documented in H5
    (the `rendering_service_deployment.enabled: true` line **and** the
    three `deepsearch.microservices` overrides). Setting just one of
    them silently breaks routing.

## H4: Build dependencies

```bash
cd helm/usdsearch/
helm dependency update .
```

## H5: Create Kubernetes secrets and generate the values file

Use the env-var names the user supplied to create or reference
Kubernetes secrets. Do not put raw secret values in shell history,
values files, or chat. If the user already has equivalent secrets,
record their names and skip creation.

Skip the AWS-credentials secret entirely if the user picked an
anonymous / public bucket — set `global.s3.authentication_enabled:
false` in the values file instead.

Example secret creation pattern (authenticated S3 + LLM key):

```bash
AWS_ACCESS_KEY_ID_ENV='<AWS_ACCESS_KEY_ID_ENV_NAME>'
AWS_SECRET_ACCESS_KEY_ENV='<AWS_SECRET_ACCESS_KEY_ENV_NAME>'
LLM_API_KEY_ENV='USDSEARCH_LLM_API_KEY'
NAMESPACE=usdsearch

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic deepsearch-s3-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=AWS_ACCESS_KEY_ID="${!AWS_ACCESS_KEY_ID_ENV}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${!AWS_SECRET_ACCESS_KEY_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -

# One shared LLM secret — used by both metadata workers and validation.
kubectl create secret generic usdsearch-llm-api-key-secret \
  --namespace "$NAMESPACE" \
  --from-literal=api-key="${!LLM_API_KEY_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Based on user's answers, render `my-usdsearch-config.yaml` with secret
names, not secret values:

```yaml
global:
  accept_eula: true
  storage_backend_type: s3
  s3:
    bucket_name: "<USER_BUCKET>"
    region_name: "<USER_REGION>"
    # For anonymous / public buckets, set these three:
    #   authentication_enabled: false
    #   allow_system_writes: false
    #   allow_non_system_writes: false
    # and omit aws_credentials_secret_name + the access-key fields entirely.
    aws_credentials_secret_name: "deepsearch-s3-credentials"
    # Only include the next line when the user said the bucket is read-only
    # (H2 question 4). Omit it otherwise — the chart defaults to `true`.
    allow_non_system_writes: false
  secrets:
    create:
      auth: false
      registry: false
  embedding_deployment:
    type: "triton_server"

deepsearch:
  vision_endpoint:
    provider:
      api_key_secret_name: "usdsearch-llm-api-key-secret"
      api_key_secret_field: "api-key"
      # base_url defaults to the shipped endpoint; override for other servers:
      # base_url: "https://api.openai.com/v1"
    metadata_model: "<USER_VLM_MODEL>"

ngsearch:
  microservices:
    search_rest_api:
      validation:
        enabled: true
        provider:
          api_key_secret_name: "usdsearch-llm-api-key-secret"
          api_key_secret_field: "api-key"
      # LLM query parsing (/llm_parse/*) — on by default,
      # shares the provider secret above. Set a model to override the
      # application default; set provider.{base_url,api_key} to run it on
      # its own endpoint instead of the shared one:
      # llm_parsing:
      #   enabled: true
      #   model: ""
      #   provider:
      #     base_url: ""   # e.g. http://internal-vllm:8000/v1
      #     api_key: ""    # creates usdsearch-llm-parsing-api-key-secret
      #   # post-index grounding: paste usd_property_catalog.yaml from
      #   # the /usd-property-catalog skill (mapping with a properties: list)
      #   property_catalog: ""

asset_graph_service_deployment:
  enabled: true
```

This default config uses **per-job `k8s_renderer` rendering** — the
chart's standard mode. Rendering itself is always on; workers spawn
short-lived Kit-renderer Jobs per request.

The `global:` block above is the **S3** form (Public or Custom). For
**Storage API** or **Nucleus**, swap in the matching `global:` block
below — the `deepsearch:` / `ngsearch:` / `asset_graph_service_deployment:`
sections are identical across backends.

### Storage API backend (option C)

Pre-create the auth secret only if the Storage API is authenticated. The
secret name/keys must match what the chart reads (`storage-api-credentials`
with key `token`, or `client_id` / `client_secret` / `scope` for OpenID).

```bash
NAMESPACE=usdsearch
# Token auth:
STORAGE_API_TOKEN_ENV='<STORAGE_API_TOKEN_ENV_NAME>'
kubectl create secret generic storage-api-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=token="${!STORAGE_API_TOKEN_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -

# OR OpenID client-credentials auth:
OPENID_CLIENT_ID_ENV='<OPENID_CLIENT_ID_ENV_NAME>'
OPENID_CLIENT_SECRET_ENV='<OPENID_CLIENT_SECRET_ENV_NAME>'
kubectl create secret generic storage-api-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=client_id="${!OPENID_CLIENT_ID_ENV}" \
  --from-literal=client_secret="${!OPENID_CLIENT_SECRET_ENV}" \
  --from-literal=scope="<OPENID_SCOPE>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

`global:` block (swap for the S3 one). Token variant:

```yaml
global:
  accept_eula: true
  storage_backend_type: storage_api
  storage_api:
    grpc_endpoint: "<GRPC_HOST:PORT>"
    base_uri: "<BASE_URI>"          # e.g. https://acct.blob.core.windows.net/bucket
    ssl: true                        # true when the gRPC endpoint uses TLS (:443)
    authentication:
      enabled: true                  # omit the whole block for an unauthenticated endpoint
      type: token
      secret_name: storage-api-credentials
      secret_key: token
  secrets:
    create:
      auth: false
      registry: false
  embedding_deployment:
    type: "triton_server"
```

For **OpenID** instead of a token, replace the `authentication:` block with:

```yaml
    authentication:
      enabled: true
      type: openid
      secret_name: storage-api-credentials
      openid:
        token_url: "<OPENID_TOKEN_URL>"
        grant_type: client_credentials
        client_id_secret_key: client_id
        client_secret_secret_key: client_secret
        scope_secret_key: scope
```

### Nucleus backend (option D)

Pre-create the service-account secret (`deepsearch-service-account` with
keys `username` / `password`):

```bash
NAMESPACE=usdsearch
OV_USERNAME_ENV='<OV_USERNAME_ENV_NAME>'
OV_PASSWORD_ENV='<OV_PASSWORD_ENV_NAME>'
kubectl create secret generic deepsearch-service-account \
  --namespace "$NAMESPACE" \
  --from-literal=username="${!OV_USERNAME_ENV}" \
  --from-literal=password="${!OV_PASSWORD_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

`global:` block (swap for the S3 one):

```yaml
global:
  accept_eula: true
  storage_backend_type: nucleus
  nucleus:
    server: "<NUCLEUS_HOST_OR_IP>"
    # service_account_secret defaults to deepsearch-service-account (the name
    # of the secret created above) — override only if you used a different name.
  secrets:
    create:
      auth: false
      registry: false
  embedding_deployment:
    type: "triton_server"
```

### Persistent rendering-service (opt-in)

Only add this block when the user explicitly asks for a persistent
in-cluster renderer instead of per-job pods. All four keys must move
together — setting any one without the others leaves the routing
broken (workers dispatch to `k8s_renderer` while the
`rendering-service` deployment sits idle, or vice versa).

```yaml
rendering_service_deployment:
  enabled: true
deepsearch:
  microservices:
    rendering_service:
      enabled: true
    k8s_renderer:
      enabled: false
    plugin_worker:
      rendering_settings:
        renderer_type: rendering_service
```

Merge into the main values file under the existing top-level
`deepsearch:` block (don't introduce a second `deepsearch:` key —
YAML deduplicates and the second wins).

### Private registry (optional)

Only needed when re-mirroring images to a private registry or pulling
pre-release builds that aren't published publicly on NGC. The default
public NGC images do **not** require this.

```bash
kubectl create secret docker-registry usdsearch-registry \
  --namespace "$NAMESPACE" \
  --docker-server=<your-registry> \
  --docker-username='<user>' \
  --docker-password="${!REGISTRY_TOKEN_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then in `my-usdsearch-config.yaml`:

```yaml
global:
  registry: <your-registry>/<path>   # overrides default nvcr.io/nvidia/usdsearch
  ngcImagePullSecretName: "usdsearch-registry"
```

## H6: Dry-run, then install

```bash
helm install usdsearch . \
  --namespace usdsearch --create-namespace \
  -f my-usdsearch-config.yaml \
  --dry-run --debug
```

Verify the rendered output:
- The backend's auth secret has the correct keys (`deepsearch-s3-credentials`
  for S3, `storage-api-credentials` for Storage API, `deepsearch-service-account`
  for Nucleus)
- The storage connection-check hook job references the right backend
- Image pull secret is created

Then install for real:

```bash
helm install usdsearch . \
  --namespace usdsearch --create-namespace \
  -f my-usdsearch-config.yaml \
  --timeout 15m
```

## H7: Verify

```bash
kubectl get pods -n usdsearch
# The storage-check hook job is named after the backend type:
#   usdsearch-s3-storage-check | usdsearch-storage-api-storage-check |
#   usdsearch-nucleus-storage-check
kubectl logs job/usdsearch-s3-storage-check -n usdsearch
helm test usdsearch -n usdsearch
```

## H8: Set the API URL and return

Default service is `usdsearch-api-gateway` (ClusterIP). For local access:

```bash
kubectl port-forward svc/usdsearch-api-gateway -n usdsearch 8080:8080
```

Then `USD_SEARCH_API_URL=http://localhost:8080`. For external access,
override `api-gateway.service.type` to `NodePort` or `LoadBalancer`.

## Helm: source of truth

All configurable parameters live in `helm/usdsearch/values.yaml`. Read
that file for current defaults — do not rely on cached values.

| What you need | Where to look |
|---|---|
| All configurable parameters | `helm/usdsearch/values.yaml` |
| Storage backend selection + per-backend keys | `global.storage_backend_type` and the `global.{s3,storage_api,nucleus}` blocks in `helm/usdsearch/values.yaml` |
| Sub-chart dependency conditions | `helm/usdsearch/Chart.yaml` `dependencies[].condition` |
| Secrets creation (per backend) | `helm/usdsearch/templates/hooks/secrets.yaml` |
| S3 env vars injected into pods | grep `S3_STORAGE_` in `helm/usdsearch/charts/*/templates/` |
| API routes | `helm/usdsearch/templates/api_gateway_config_map.yaml` |
| Embedding service options | `global.embedding_deployment` |
| VLM provider config | `deepsearch.vision_endpoint` |
| Plugin enable/disable | `deepsearch.plugins` |
| Resource requests (GPU/RAM) | grep `resources:` in `helm/usdsearch/charts/*/templates/` |
| Crawler include/exclude | `deepsearch-crawler.crawler.extraConfig` |

## Helm: troubleshooting

- **Pre-install hook fails** → check the storage-check hook job for the
  active backend:
  `kubectl logs job/usdsearch-<s3|storage-api|nucleus>-storage-check -n usdsearch`
- **Image pull errors** → the public NGC images don't need a pull
  secret. If you do see `ErrImagePull` / `ImagePullBackOff`, check:
  network egress to `nvcr.io`, the tag actually exists at that path
  (`nvcr.io/nvidia/usdsearch/<image>:<tag>`), and `Chart.yaml`
  `appVersion` (or `global.appVersion` override) matches a published
  `images-X.Y.Z` tag. Only fall back to a pull secret if you've
  re-mirrored to a private registry — see "Private registry" in H5.
- **SignatureDoesNotMatch** → special chars in S3 secret not escaped;
  re-create the secret
- **Pods pending (GPU)** → check `nvidia.com/gpu` resources and
  tolerations on the node
