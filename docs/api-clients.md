# Calling the REST API from code

Every USD Search feature is a REST call, and the OpenAPI spec each deployment
serves is the contract. Generate a client from that spec, or call the endpoints
directly with any HTTP library.

> [!WARNING]
> **`usd-search-client` is deprecated and not supported.** The Python package on
> PyPI (last release 1.3.0) was generated from the 1.3 API and does not match
> current servers. For example, from 1.5.0 on `POST /search_hybrid` reports a
> `name` score that the package's `SearchType` enum rejects, so the call raises
> a `ValidationError` instead of returning results. Generate a client for the
> server version you run (below), or call the REST API directly.

## Get the spec

Use the spec that matches the server you call:

- **From your deployment:** `<gateway>/docs/openapi.json`, next to the Swagger
  UI at `<gateway>/docs/`. This is always the exact version that deployment runs.
- **From the repo:** [`helm/usdsearch/docs/openapi.json`](../helm/usdsearch/docs/openapi.json)
  at the release tag you deploy (for example, `1.5.1`).

The spec is OpenAPI 3.1 and covers the search, info, and asset-graph APIs.
The hosted [API reference](https://nvidia-omniverse.github.io/usd-search/)
renders the latest release's spec.

## Generate a Python client

With [OpenAPI Generator](https://openapi-generator.tech) (Docker, no local
install):

```bash
curl -fsSL -o openapi.json "$USDSEARCH_URL/docs/openapi.json"

docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/local" \
  openapitools/openapi-generator-cli:v7.17.0 generate \
  -i /local/openapi.json -g python -o /local/usdsearch-client \
  --package-name usdsearch_client \
  --additional-properties=projectName=usdsearch-client,enumUnknownDefaultCase=true
```

The generator warns that its OpenAPI 3.1 support is in beta. The USD Search
spec generates and parses cleanly with it.

### Tolerate new enum values (recommended)

New releases can add enum values, such as a new `search_type`. A client
generated for an older version rejects any value it does not know.
`enumUnknownDefaultCase=true` adds an `UNKNOWN_DEFAULT_OPEN_API` member to each
enum, but the Python generator does not map unknown values to it. This step
does. Run it before installing:

```bash
python - usdsearch-client/usdsearch_client/models <<'EOF'
import pathlib, sys
hook = "    @classmethod\n    def _missing_(cls, value):\n        return cls.UNKNOWN_DEFAULT_OPEN_API\n\n"
for f in pathlib.Path(sys.argv[1]).glob("*.py"):
    t = f.read_text()
    if "UNKNOWN_DEFAULT_OPEN_API = " in t and "_missing_" not in t:
        f.write_text(t.replace("    @classmethod\n    def from_json", hook + "    @classmethod\n    def from_json", 1))
EOF
```

Unknown values then come back as `UNKNOWN_DEFAULT_OPEN_API` instead of raising
an error.

### Install

```bash
pip install ./usdsearch-client
```

### Example: hybrid search

```python
import usdsearch_client as usc

config = usc.Configuration(host="https://usdsearch.example.com")
# Set the credentials your deployment uses, for example:
# config.username, config.password = "user", "password"   # HTTP basic
# config.access_token = "<token>"                          # bearer
# config.api_key = {"APIKeyHeader": "<key>"}               # x-api-key header

with usc.ApiClient(config) as api:
    request = usc.DeepSearchSearchRequestV2(hybrid_text_query="red chair", limit=10)
    response = usc.AISearchApi(api).search_hybrid_post(request)
    for hit in response.hits:
        print(hit.rrf_score, hit.id)
```

The client sends these credentials only to the routes whose spec declares
authentication (search, images, download, asset graph). If your gateway
requires them on every route, including `/info/*` and `/llm_parse/*`, also set
a default header, for example
`api.set_default_header("Authorization", config.get_basic_auth_token())`.

Add `library=asyncio` to `--additional-properties` for an `async` client.

## Other languages

Change `-g` to any of OpenAPI Generator's
[generators](https://openapi-generator.tech/docs/generators), for example
`typescript-fetch`, `go`, `java`, or `csharp`. Check how the generated client
handles enum values it does not know: `typescript-fetch` passes them through
unchecked, while generators that validate enums may reject them unless
`enumUnknownDefaultCase=true` takes effect.

## Without a generated client

The API is plain JSON over HTTP:

```bash
curl -s -X POST "$USDSEARCH_URL/search_hybrid" \
  -H "Content-Type: application/json" \
  -d '{"hybrid_text_query": "red chair", "limit": 10}'
```

If your deployment requires authentication (for example, Nucleus-backed
deployments), add `-u user:password`, `-H "Authorization: Bearer <token>"` or
`-H "x-api-key: <key>"` to match it.

## Keeping clients compatible

- **Regenerate when you upgrade the server**, from the spec that version serves.
- **Expect additions in minor releases:** new endpoints, new optional request and
  response fields, and new enum values. Ignore fields you do not use, and do not
  fail on enum values you do not recognise.
