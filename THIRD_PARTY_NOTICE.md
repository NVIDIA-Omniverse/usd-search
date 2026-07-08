# Third-Party Notices

USD Search bundles the third-party Python packages listed below. License
text for each package is stored under `licenses/`.

Dependency trees enumerated (production deps only; test/dev groups excluded):

- root `uv.lock` (workspace members)
- `services/rendering-job/uv.lock`
- `services/asset-graph-builder/uv.lock`
- `services/siglip2-triton/docker/uv.lock`

Additional non-Python components (model weights, base images, vendored
binaries) are declared in `scripts/third_party_extras.json` and listed in
their own table below.

OS packages installed by the bundled images' `apt-get` layers — the
`usdsearch` runtime image (`python3.12`, `ca-certificates`, and their
dependency closure on top of the Ubuntu noble base) and the `siglip2-triton`
image (an `openssl` security bump on top of the Triton base) — are enumerated
automatically from each container and listed in the "Bundled OS packages"
table below.

## Regenerating this file

```
./scripts/generate_third_party_notice.sh
```

**176** unique `(package, version)` entries.

| Package | Version | License | Homepage | Sources | License text |
| --- | --- | --- | --- | --- | --- |
| `aioboto3` | 15.5.0 | Apache-2.0 | <https://pypi.org/project/aioboto3/> | workspace | [`licenses/aioboto3-15.5.0.txt`](licenses/aioboto3-15.5.0.txt) |
| `aiobotocore` | 2.25.1 | Apache-2.0 | <https://github.com/aio-libs/aiobotocore> | workspace | [`licenses/aiobotocore-2.25.1.txt`](licenses/aiobotocore-2.25.1.txt) |
| `aiofiles` | 25.1.0 | Apache-2.0 | <https://github.com/Tinche/aiofiles> | workspace | [`licenses/aiofiles-25.1.0.txt`](licenses/aiofiles-25.1.0.txt) |
| `aiohappyeyeballs` | 2.6.1 | PSF-2.0 | <https://github.com/aio-libs/aiohappyeyeballs> | asset-graph-builder, rendering-job, workspace | [`licenses/aiohappyeyeballs-2.6.1.txt`](licenses/aiohappyeyeballs-2.6.1.txt) |
| `aiohttp` | 3.13.5 | Apache-2.0 AND MIT | <https://github.com/aio-libs/aiohttp> | asset-graph-builder, rendering-job | [`licenses/aiohttp-3.13.5.txt`](licenses/aiohttp-3.13.5.txt) |
| `aiohttp` | 3.14.1 | Apache-2.0 AND MIT | <https://github.com/aio-libs/aiohttp> | workspace | [`licenses/aiohttp-3.14.1.txt`](licenses/aiohttp-3.14.1.txt) |
| `aiohttp-retry` | 2.9.1 | MIT | <https://github.com/inyutin/aiohttp_retry> | workspace | [`licenses/aiohttp-retry-2.9.1.txt`](licenses/aiohttp-retry-2.9.1.txt) |
| `aioitertools` | 0.13.0 | MIT | <https://aioitertools.omnilib.dev> | workspace | [`licenses/aioitertools-0.13.0.txt`](licenses/aioitertools-0.13.0.txt) |
| `aiomysql` | 0.3.2 | MIT | <https://pypi.org/project/aiomysql/> | rendering-job | [`licenses/aiomysql-0.3.2.txt`](licenses/aiomysql-0.3.2.txt) |
| `aiosignal` | 1.4.0 | Apache 2.0 | <https://github.com/aio-libs/aiosignal> | asset-graph-builder, rendering-job, workspace | [`licenses/aiosignal-1.4.0.txt`](licenses/aiosignal-1.4.0.txt) |
| `annotated-doc` | 0.0.4 | MIT | <https://github.com/fastapi/annotated-doc> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/annotated-doc-0.0.4.txt`](licenses/annotated-doc-0.0.4.txt) |
| `annotated-types` | 0.7.0 | MIT License | <https://github.com/annotated-types/annotated-types> | workspace | [`licenses/annotated-types-0.7.0.txt`](licenses/annotated-types-0.7.0.txt) |
| `anyio` | 4.13.0 | MIT | <https://anyio.readthedocs.io/en/latest/> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/anyio-4.13.0.txt`](licenses/anyio-4.13.0.txt) |
| `asgi-correlation-id` | 4.3.4 | MIT | <https://github.com/snok/asgi-correlation-id> | workspace | [`licenses/asgi-correlation-id-4.3.4.txt`](licenses/asgi-correlation-id-4.3.4.txt) |
| `asgiref` | 3.11.1 | BSD-3-Clause | <https://github.com/django/asgiref/> | workspace | [`licenses/asgiref-3.11.1.txt`](licenses/asgiref-3.11.1.txt) |
| `asteval` | 1.0.8 | MIT | <https://github.com/lmfit/asteval> | rendering-job | [`licenses/asteval-1.0.8.txt`](licenses/asteval-1.0.8.txt) |
| `async-lru` | 2.3.0 | MIT License | <https://github.com/aio-libs/async-lru> | rendering-job, workspace | [`licenses/async-lru-2.3.0.txt`](licenses/async-lru-2.3.0.txt) |
| `async-timeout` | 5.0.1 | Apache 2 | <https://github.com/aio-libs/async-timeout> | rendering-job, workspace | [`licenses/async-timeout-5.0.1.txt`](licenses/async-timeout-5.0.1.txt) |
| `attrs` | 26.1.0 | MIT | <https://www.attrs.org/> | asset-graph-builder, rendering-job, workspace | [`licenses/attrs-26.1.0.txt`](licenses/attrs-26.1.0.txt) |
| `authlib` | 1.7.2 | BSD-3-Clause | <https://github.com/authlib/authlib> | asset-graph-builder, rendering-job, workspace | [`licenses/authlib-1.7.2.txt`](licenses/authlib-1.7.2.txt) |
| `backoff` | 2.2.1 | MIT | <https://github.com/litl/backoff> | workspace | [`licenses/backoff-2.2.1.txt`](licenses/backoff-2.2.1.txt) |
| `boto3` | 1.40.61 | Apache-2.0 | <https://github.com/boto/boto3> | workspace | [`licenses/boto3-1.40.61.txt`](licenses/boto3-1.40.61.txt) |
| `botocore` | 1.40.61 | Apache-2.0 | <https://github.com/boto/botocore> | workspace | [`licenses/botocore-1.40.61.txt`](licenses/botocore-1.40.61.txt) |
| `cachetools` | 7.1.1 | MIT | <https://github.com/tkem/cachetools/> | rendering-job | [`licenses/cachetools-7.1.1.txt`](licenses/cachetools-7.1.1.txt) |
| `certifi` | 2023.7.22 | MPL-2.0 | <https://github.com/certifi/python-certifi> | asset-graph-builder | [`licenses/certifi-2023.7.22.txt`](licenses/certifi-2023.7.22.txt) |
| `certifi` | 2026.4.22 | MPL-2.0 | <https://github.com/certifi/python-certifi> | rendering-job, siglip2-triton, workspace | [`licenses/certifi-2026.4.22.txt`](licenses/certifi-2026.4.22.txt) |
| `cffi` | 2.0.0 | MIT | <https://github.com/python-cffi/cffi> | asset-graph-builder, rendering-job, workspace | [`licenses/cffi-2.0.0.txt`](licenses/cffi-2.0.0.txt) |
| `charset-normalizer` | 3.4.7 | MIT | <https://charset-normalizer.readthedocs.io/> | workspace | [`licenses/charset-normalizer-3.4.7.txt`](licenses/charset-normalizer-3.4.7.txt) |
| `click` | 8.3.2 | BSD-3-Clause | <https://github.com/pallets/click/> | workspace | [`licenses/click-8.3.2.txt`](licenses/click-8.3.2.txt) |
| `click` | 8.3.3 | BSD-3-Clause | <https://github.com/pallets/click/> | asset-graph-builder, rendering-job, siglip2-triton | [`licenses/click-8.3.3.txt`](licenses/click-8.3.3.txt) |
| `colorama` | 0.4.6 | BSD License | <https://github.com/tartley/colorama> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/colorama-0.4.6.txt`](licenses/colorama-0.4.6.txt) |
| `cryptography` | 49.0.0 | Apache-2.0 OR BSD-3-Clause | <https://pypi.org/project/cryptography/> | asset-graph-builder, rendering-job, workspace | [`licenses/cryptography-49.0.0.txt`](licenses/cryptography-49.0.0.txt) |
| `deprecated` | 1.3.1 | MIT | <https://github.com/laurent-laporte-pro/deprecated> | workspace | [`licenses/deprecated-1.3.1.txt`](licenses/deprecated-1.3.1.txt) |
| `distro` | 1.9.0 | Apache License, Version 2.0 | <https://github.com/python-distro/distro> | workspace | [`licenses/distro-1.9.0.txt`](licenses/distro-1.9.0.txt) |
| `elastic-transport` | 9.2.1 | Apache Software License | <https://github.com/elastic/elastic-transport-python> | workspace | [`licenses/elastic-transport-9.2.1.txt`](licenses/elastic-transport-9.2.1.txt) |
| `elasticsearch` | 9.3.0 | Apache-2.0 | <https://github.com/elastic/elasticsearch-py> | workspace | [`licenses/elasticsearch-9.3.0.txt`](licenses/elasticsearch-9.3.0.txt) |
| `envyaml` | 1.10.211231 | MIT | <https://github.com/thesimj/envyaml> | workspace | [`licenses/envyaml-1.10.211231.txt`](licenses/envyaml-1.10.211231.txt) |
| `events` | 0.5 | BSD | <http://github.com/pyeve/events> | workspace | [`licenses/events-0.5.txt`](licenses/events-0.5.txt) |
| `fastapi` | 0.125.0 | MIT | <https://github.com/fastapi/fastapi> | asset-graph-builder, rendering-job | [`licenses/fastapi-0.125.0.txt`](licenses/fastapi-0.125.0.txt) |
| `fastapi` | 0.136.0 | MIT | <https://github.com/fastapi/fastapi> | workspace | [`licenses/fastapi-0.136.0.txt`](licenses/fastapi-0.136.0.txt) |
| `fastapi-swagger` | 0.4.48 | MIT | <https://github.com/dantetemplar/fastapi-swagger> | workspace | [`licenses/fastapi-swagger-0.4.48.txt`](licenses/fastapi-swagger-0.4.48.txt) |
| `filelock` | 3.29.0 | MIT | <https://github.com/tox-dev/py-filelock> | siglip2-triton, workspace | [`licenses/filelock-3.29.0.txt`](licenses/filelock-3.29.0.txt) |
| `fire` | 0.7.1 | Apache-2.0 | <https://github.com/google/python-fire> | rendering-job, workspace | [`licenses/fire-0.7.1.txt`](licenses/fire-0.7.1.txt) |
| `frozenlist` | 1.8.0 | Apache-2.0 | <https://github.com/aio-libs/frozenlist> | asset-graph-builder, rendering-job, workspace | [`licenses/frozenlist-1.8.0.txt`](licenses/frozenlist-1.8.0.txt) |
| `fsspec` | 2026.3.0 | BSD-3-Clause | <https://github.com/fsspec/filesystem_spec> | workspace | [`licenses/fsspec-2026.3.0.txt`](licenses/fsspec-2026.3.0.txt) |
| `fsspec` | 2026.4.0 | BSD-3-Clause | <https://github.com/fsspec/filesystem_spec> | siglip2-triton | [`licenses/fsspec-2026.4.0.txt`](licenses/fsspec-2026.4.0.txt) |
| `googleapis-common-protos` | 1.74.0 | Apache 2.0 | <https://github.com/googleapis/google-cloud-python/tree/main/packages/googleapis-common-protos> | workspace | [`licenses/googleapis-common-protos-1.74.0.txt`](licenses/googleapis-common-protos-1.74.0.txt) |
| `greenlet` | 3.4.0 | MIT AND PSF-2.0 | <https://greenlet.readthedocs.io> | workspace | [`licenses/greenlet-3.4.0.txt`](licenses/greenlet-3.4.0.txt) |
| `grpcio` | 1.80.0 | Apache-2.0 | <https://grpc.io> | workspace | [`licenses/grpcio-1.80.0.txt`](licenses/grpcio-1.80.0.txt) |
| `h11` | 0.16.0 | MIT | <https://github.com/python-hyper/h11> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/h11-0.16.0.txt`](licenses/h11-0.16.0.txt) |
| `hf-xet` | 1.4.3 | Apache Software License | <https://github.com/huggingface/xet-core> | workspace | [`licenses/hf-xet-1.4.3.txt`](licenses/hf-xet-1.4.3.txt) |
| `hf-xet` | 1.5.0 | Apache Software License | <https://github.com/huggingface/xet-core> | siglip2-triton | [`licenses/hf-xet-1.5.0.txt`](licenses/hf-xet-1.5.0.txt) |
| `hiredis` | 3.3.1 | MIT | <https://github.com/redis/hiredis-py> | workspace | [`licenses/hiredis-3.3.1.txt`](licenses/hiredis-3.3.1.txt) |
| `httpcore` | 1.0.9 | BSD-3-Clause | <https://www.encode.io/httpcore/> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/httpcore-1.0.9.txt`](licenses/httpcore-1.0.9.txt) |
| `httptools` | 0.7.1 | MIT | <https://github.com/MagicStack/httptools> | workspace | [`licenses/httptools-0.7.1.txt`](licenses/httptools-0.7.1.txt) |
| `httpx` | 0.28.1 | BSD-3-Clause | <https://github.com/encode/httpx> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/httpx-0.28.1.txt`](licenses/httpx-0.28.1.txt) |
| `huggingface-hub` | 1.11.0 | Apache-2.0 | <https://github.com/huggingface/huggingface_hub> | workspace | [`licenses/huggingface-hub-1.11.0.txt`](licenses/huggingface-hub-1.11.0.txt) |
| `huggingface-hub` | 1.14.0 | Apache-2.0 | <https://github.com/huggingface/huggingface_hub> | siglip2-triton | [`licenses/huggingface-hub-1.14.0.txt`](licenses/huggingface-hub-1.14.0.txt) |
| `humanize` | 4.15.0 | MIT | <https://github.com/python-humanize/humanize> | workspace | [`licenses/humanize-4.15.0.txt`](licenses/humanize-4.15.0.txt) |
| `idna` | 3.18 | BSD-3-Clause | <https://github.com/kjd/idna> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/idna-3.18.txt`](licenses/idna-3.18.txt) |
| `importlib-metadata` | 8.7.1 | Apache-2.0 | <https://github.com/python/importlib_metadata> | workspace | [`licenses/importlib-metadata-8.7.1.txt`](licenses/importlib-metadata-8.7.1.txt) |
| `jinja2` | 3.1.6 | BSD License | <https://github.com/pallets/jinja/> | asset-graph-builder, rendering-job | [`licenses/jinja2-3.1.6.txt`](licenses/jinja2-3.1.6.txt) |
| `jiter` | 0.14.0 | MIT | <https://github.com/pydantic/jiter/> | workspace | [`licenses/jiter-0.14.0.txt`](licenses/jiter-0.14.0.txt) |
| `jmespath` | 1.1.0 | MIT | <https://github.com/jmespath/jmespath.py> | workspace | [`licenses/jmespath-1.1.0.txt`](licenses/jmespath-1.1.0.txt) |
| `joserfc` | 1.7.2 | BSD-3-Clause | <https://github.com/authlib/joserfc> | asset-graph-builder, rendering-job, workspace | [`licenses/joserfc-1.7.2.txt`](licenses/joserfc-1.7.2.txt) |
| `jsonpatch` | 1.33 | Modified BSD License | <https://github.com/stefankoegl/python-json-patch> | workspace | [`licenses/jsonpatch-1.33.txt`](licenses/jsonpatch-1.33.txt) |
| `jsonpointer` | 3.1.1 | Modified BSD License | <https://github.com/stefankoegl/python-json-pointer> | workspace | [`licenses/jsonpointer-3.1.1.txt`](licenses/jsonpointer-3.1.1.txt) |
| `kubernetes-asyncio` | 35.0.1 | Apache-2.0 | <https://pypi.org/project/kubernetes-asyncio/> | workspace | [`licenses/kubernetes-asyncio-35.0.1.txt`](licenses/kubernetes-asyncio-35.0.1.txt) |
| `langchain` | 1.3.11 | MIT | <https://docs.langchain.com/> | workspace | [`licenses/langchain-1.3.11.txt`](licenses/langchain-1.3.11.txt) |
| `langchain-classic` | 1.0.7 | MIT | <https://docs.langchain.com/> | workspace | [`licenses/langchain-classic-1.0.7.txt`](licenses/langchain-classic-1.0.7.txt) |
| `langchain-core` | 1.4.8 | MIT | <https://docs.langchain.com/> | workspace | [`licenses/langchain-core-1.4.8.txt`](licenses/langchain-core-1.4.8.txt) |
| `langchain-openai` | 1.1.16 | MIT | <https://docs.langchain.com/oss/python/integrations/providers/openai> | workspace | [`licenses/langchain-openai-1.1.16.txt`](licenses/langchain-openai-1.1.16.txt) |
| `langchain-protocol` | 0.0.18 | MIT | <https://github.com/langchain-ai/agent-protocol/tree/main/streaming> | workspace | [`licenses/langchain-protocol-0.0.18.txt`](licenses/langchain-protocol-0.0.18.txt) |
| `langchain-text-splitters` | 1.1.2 | MIT | <https://docs.langchain.com/> | workspace | [`licenses/langchain-text-splitters-1.1.2.txt`](licenses/langchain-text-splitters-1.1.2.txt) |
| `langgraph` | 1.2.6 | MIT | <https://docs.langchain.com/oss/python/langgraph/overview> | workspace | [`licenses/langgraph-1.2.6.txt`](licenses/langgraph-1.2.6.txt) |
| `langgraph-checkpoint` | 4.1.1 | MIT | <https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint> | workspace | [`licenses/langgraph-checkpoint-4.1.1.txt`](licenses/langgraph-checkpoint-4.1.1.txt) |
| `langgraph-prebuilt` | 1.1.0 | MIT | <https://github.com/langchain-ai/langgraph/tree/main/libs/prebuilt> | workspace | [`licenses/langgraph-prebuilt-1.1.0.txt`](licenses/langgraph-prebuilt-1.1.0.txt) |
| `langgraph-sdk` | 0.4.2 | MIT | <https://github.com/langchain-ai/langgraph/tree/main/libs/sdk-py> | workspace | [`licenses/langgraph-sdk-0.4.2.txt`](licenses/langgraph-sdk-0.4.2.txt) |
| `langsmith` | 0.8.18 | MIT | <https://smith.langchain.com/> | workspace | [`licenses/langsmith-0.8.18.txt`](licenses/langsmith-0.8.18.txt) |
| `markdown-it-py` | 4.0.0 | MIT License | <https://github.com/executablebooks/markdown-it-py> | workspace | [`licenses/markdown-it-py-4.0.0.txt`](licenses/markdown-it-py-4.0.0.txt) |
| `markdown-it-py` | 4.2.0 | MIT License | <https://github.com/executablebooks/markdown-it-py> | siglip2-triton | [`licenses/markdown-it-py-4.2.0.txt`](licenses/markdown-it-py-4.2.0.txt) |
| `markupsafe` | 3.0.3 | BSD-3-Clause | <https://github.com/pallets/markupsafe/> | asset-graph-builder, rendering-job | [`licenses/markupsafe-3.0.3.txt`](licenses/markupsafe-3.0.3.txt) |
| `mdurl` | 0.1.2 | MIT License | <https://github.com/executablebooks/mdurl> | siglip2-triton, workspace | [`licenses/mdurl-0.1.2.txt`](licenses/mdurl-0.1.2.txt) |
| `multidict` | 6.7.1 | Apache License 2.0 | <https://github.com/aio-libs/multidict> | asset-graph-builder, rendering-job, workspace | [`licenses/multidict-6.7.1.txt`](licenses/multidict-6.7.1.txt) |
| `neo4j` | 6.1.0 | Apache-2.0 AND Python-2.0 | <https://neo4j.com/> | workspace | [`licenses/neo4j-6.1.0.txt`](licenses/neo4j-6.1.0.txt) |
| `numpy` | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | <https://pypi.org/project/numpy/> | rendering-job, siglip2-triton, workspace | [`licenses/numpy-2.4.6.txt`](licenses/numpy-2.4.6.txt) |
| `openai` | 2.32.0 | Apache-2.0 | <https://github.com/openai/openai-python> | workspace | [`licenses/openai-2.32.0.txt`](licenses/openai-2.32.0.txt) |
| `opensearch-protobufs` | 0.19.0 | Apache-2.0 | <https://opensearch.org/> | workspace | [`licenses/opensearch-protobufs-0.19.0.txt`](licenses/opensearch-protobufs-0.19.0.txt) |
| `opensearch-py` | 3.1.0 | Apache-2.0 | <https://github.com/opensearch-project/opensearch-py> | workspace | [`licenses/opensearch-py-3.1.0.txt`](licenses/opensearch-py-3.1.0.txt) |
| `opentelemetry-api` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api> | workspace | [`licenses/opentelemetry-api-1.41.0.txt`](licenses/opentelemetry-api-1.41.0.txt) |
| `opentelemetry-exporter-otlp` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp> | workspace | [`licenses/opentelemetry-exporter-otlp-1.41.0.txt`](licenses/opentelemetry-exporter-otlp-1.41.0.txt) |
| `opentelemetry-exporter-otlp-proto-common` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-common> | workspace | [`licenses/opentelemetry-exporter-otlp-proto-common-1.41.0.txt`](licenses/opentelemetry-exporter-otlp-proto-common-1.41.0.txt) |
| `opentelemetry-exporter-otlp-proto-grpc` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-grpc> | workspace | [`licenses/opentelemetry-exporter-otlp-proto-grpc-1.41.0.txt`](licenses/opentelemetry-exporter-otlp-proto-grpc-1.41.0.txt) |
| `opentelemetry-exporter-otlp-proto-http` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/exporter/opentelemetry-exporter-otlp-proto-http> | workspace | [`licenses/opentelemetry-exporter-otlp-proto-http-1.41.0.txt`](licenses/opentelemetry-exporter-otlp-proto-http-1.41.0.txt) |
| `opentelemetry-instrumentation` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/opentelemetry-instrumentation> | workspace | [`licenses/opentelemetry-instrumentation-0.62b0.txt`](licenses/opentelemetry-instrumentation-0.62b0.txt) |
| `opentelemetry-instrumentation-aiohttp-client` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-aiohttp-client> | workspace | [`licenses/opentelemetry-instrumentation-aiohttp-client-0.62b0.txt`](licenses/opentelemetry-instrumentation-aiohttp-client-0.62b0.txt) |
| `opentelemetry-instrumentation-asgi` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-asgi> | workspace | [`licenses/opentelemetry-instrumentation-asgi-0.62b0.txt`](licenses/opentelemetry-instrumentation-asgi-0.62b0.txt) |
| `opentelemetry-instrumentation-fastapi` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-fastapi> | workspace | [`licenses/opentelemetry-instrumentation-fastapi-0.62b0.txt`](licenses/opentelemetry-instrumentation-fastapi-0.62b0.txt) |
| `opentelemetry-instrumentation-grpc` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-grpc> | workspace | [`licenses/opentelemetry-instrumentation-grpc-0.62b0.txt`](licenses/opentelemetry-instrumentation-grpc-0.62b0.txt) |
| `opentelemetry-instrumentation-httpx` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-httpx> | workspace | [`licenses/opentelemetry-instrumentation-httpx-0.62b0.txt`](licenses/opentelemetry-instrumentation-httpx-0.62b0.txt) |
| `opentelemetry-proto` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-proto> | workspace | [`licenses/opentelemetry-proto-1.41.0.txt`](licenses/opentelemetry-proto-1.41.0.txt) |
| `opentelemetry-sdk` | 1.41.0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-sdk> | workspace | [`licenses/opentelemetry-sdk-1.41.0.txt`](licenses/opentelemetry-sdk-1.41.0.txt) |
| `opentelemetry-semantic-conventions` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-semantic-conventions> | workspace | [`licenses/opentelemetry-semantic-conventions-0.62b0.txt`](licenses/opentelemetry-semantic-conventions-0.62b0.txt) |
| `opentelemetry-util-http` | 0.62b0 | Apache-2.0 | <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/util/opentelemetry-util-http> | workspace | [`licenses/opentelemetry-util-http-0.62b0.txt`](licenses/opentelemetry-util-http-0.62b0.txt) |
| `orjson` | 3.11.8 | MPL-2.0 AND (Apache-2.0 OR MIT) | <https://pypi.org/project/orjson/> | workspace | [`licenses/orjson-3.11.8.txt`](licenses/orjson-3.11.8.txt) |
| `orjson` | 3.11.9 | MPL-2.0 AND (Apache-2.0 OR MIT) | <https://pypi.org/project/orjson/> | asset-graph-builder, rendering-job | [`licenses/orjson-3.11.9.txt`](licenses/orjson-3.11.9.txt) |
| `ormsgpack` | 1.12.2 | Apache-2.0 OR MIT | <https://github.com/ormsgpack/ormsgpack> | workspace | [`licenses/ormsgpack-1.12.2.txt`](licenses/ormsgpack-1.12.2.txt) |
| `packaging` | 26.1 | Apache-2.0 OR BSD-2-Clause | <https://github.com/pypa/packaging> | workspace | [`licenses/packaging-26.1.txt`](licenses/packaging-26.1.txt) |
| `packaging` | 26.2 | Apache-2.0 OR BSD-2-Clause | <https://github.com/pypa/packaging> | siglip2-triton | [`licenses/packaging-26.2.txt`](licenses/packaging-26.2.txt) |
| `pillow` | 12.2.0 | MIT-CMU | <https://python-pillow.github.io> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/pillow-12.2.0.txt`](licenses/pillow-12.2.0.txt) |
| `prometheus-client` | 0.25.0 | Apache-2.0 AND BSD-2-Clause | <https://github.com/prometheus/client_python> | rendering-job, workspace | [`licenses/prometheus-client-0.25.0.txt`](licenses/prometheus-client-0.25.0.txt) |
| `prometheus-fastapi-instrumentator` | 7.1.0 | ISC | <https://github.com/trallnag/prometheus-fastapi-instrumentator> | rendering-job | [`licenses/prometheus-fastapi-instrumentator-7.1.0.txt`](licenses/prometheus-fastapi-instrumentator-7.1.0.txt) |
| `prometheus-fastapi-instrumentator` | 8.0.0 | ISC | <https://github.com/trallnag/prometheus-fastapi-instrumentator> | workspace | [`licenses/prometheus-fastapi-instrumentator-8.0.0.txt`](licenses/prometheus-fastapi-instrumentator-8.0.0.txt) |
| `propcache` | 0.4.1 | Apache-2.0 | <https://github.com/aio-libs/propcache> | workspace | [`licenses/propcache-0.4.1.txt`](licenses/propcache-0.4.1.txt) |
| `propcache` | 0.5.2 | Apache-2.0 | <https://github.com/aio-libs/propcache> | asset-graph-builder, rendering-job | [`licenses/propcache-0.5.2.txt`](licenses/propcache-0.5.2.txt) |
| `protobuf` | 6.33.6 | 3-Clause BSD License | <https://developers.google.com/protocol-buffers/> | workspace | [`licenses/protobuf-6.33.6.txt`](licenses/protobuf-6.33.6.txt) |
| `psutil` | 7.2.2 | BSD-3-Clause | <https://github.com/giampaolo/psutil> | rendering-job, workspace | [`licenses/psutil-7.2.2.txt`](licenses/psutil-7.2.2.txt) |
| `pycparser` | 3.0 | BSD-3-Clause | <https://github.com/eliben/pycparser> | asset-graph-builder, rendering-job, workspace | [`licenses/pycparser-3.0.txt`](licenses/pycparser-3.0.txt) |
| `pydantic` | 1.10.26 | MIT | <https://github.com/pydantic/pydantic> | asset-graph-builder, rendering-job | [`licenses/pydantic-1.10.26.txt`](licenses/pydantic-1.10.26.txt) |
| `pydantic` | 2.13.3 | MIT | <https://github.com/pydantic/pydantic> | workspace | [`licenses/pydantic-2.13.3.txt`](licenses/pydantic-2.13.3.txt) |
| `pydantic-core` | 2.46.3 | MIT | <https://github.com/pydantic> | workspace | [`licenses/pydantic-core-2.46.3.txt`](licenses/pydantic-core-2.46.3.txt) |
| `pydantic-settings` | 2.14.2 | MIT | <https://github.com/pydantic/pydantic-settings> | workspace | [`licenses/pydantic-settings-2.14.2.txt`](licenses/pydantic-settings-2.14.2.txt) |
| `pygments` | 2.20.0 | BSD-2-Clause | <https://pygments.org> | siglip2-triton, workspace | [`licenses/pygments-2.20.0.txt`](licenses/pygments-2.20.0.txt) |
| `pyinstrument` | 5.1.2 | BSD License | <https://github.com/joerick/pyinstrument> | workspace | [`licenses/pyinstrument-5.1.2.txt`](licenses/pyinstrument-5.1.2.txt) |
| `pyjwt` | 2.12.1 | MIT | <https://github.com/jpadilla/pyjwt> | rendering-job | [`licenses/pyjwt-2.12.1.txt`](licenses/pyjwt-2.12.1.txt) |
| `pymysql` | 1.1.3 | MIT | <https://pymysql.readthedocs.io/> | rendering-job | [`licenses/pymysql-1.1.3.txt`](licenses/pymysql-1.1.3.txt) |
| `pyparsing` | 3.3.2 | MIT | <https://github.com/pyparsing/pyparsing/> | workspace | [`licenses/pyparsing-3.3.2.txt`](licenses/pyparsing-3.3.2.txt) |
| `python-dateutil` | 2.9.0.post0 | Dual License | <https://github.com/dateutil/dateutil> | workspace | [`licenses/python-dateutil-2.9.0.post0.txt`](licenses/python-dateutil-2.9.0.post0.txt) |
| `python-dotenv` | 1.2.2 | BSD-3-Clause | <https://github.com/theskumar/python-dotenv> | workspace | [`licenses/python-dotenv-1.2.2.txt`](licenses/python-dotenv-1.2.2.txt) |
| `python-json-logger` | 4.1.0 | BSD-2-Clause | <https://nhairs.github.io/python-json-logger> | workspace | [`licenses/python-json-logger-4.1.0.txt`](licenses/python-json-logger-4.1.0.txt) |
| `python-multipart` | 0.0.28 | Apache-2.0 | <https://github.com/Kludex/python-multipart> | asset-graph-builder, rendering-job | [`licenses/python-multipart-0.0.28.txt`](licenses/python-multipart-0.0.28.txt) |
| `python-rapidjson` | 1.23 | MIT License | <https://github.com/python-rapidjson/python-rapidjson> | workspace | [`licenses/python-rapidjson-1.23.txt`](licenses/python-rapidjson-1.23.txt) |
| `pytinyexr` | 0.9.1 | MIT License | <https://github.com/syoyo/PyEXR> | workspace | [`licenses/pytinyexr-0.9.1.txt`](licenses/pytinyexr-0.9.1.txt) |
| `pytz` | 2026.1.post1 | MIT | <http://pythonhosted.org/pytz> | workspace | [`licenses/pytz-2026.1.post1.txt`](licenses/pytz-2026.1.post1.txt) |
| `pyyaml` | 6.0.3 | MIT | <https://pyyaml.org/> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/pyyaml-6.0.3.txt`](licenses/pyyaml-6.0.3.txt) |
| `redis` | 7.4.0 | MIT | <https://github.com/redis/redis-py> | rendering-job, workspace | [`licenses/redis-7.4.0.txt`](licenses/redis-7.4.0.txt) |
| `regex` | 2026.4.4 | Apache-2.0 AND CNRI-Python | <https://github.com/mrabarnett/mrab-regex> | workspace | [`licenses/regex-2026.4.4.txt`](licenses/regex-2026.4.4.txt) |
| `regex` | 2026.5.9 | Apache-2.0 AND CNRI-Python | <https://github.com/mrabarnett/mrab-regex> | siglip2-triton | [`licenses/regex-2026.5.9.txt`](licenses/regex-2026.5.9.txt) |
| `requests` | 2.33.1 | Apache-2.0 | <https://github.com/psf/requests> | workspace | [`licenses/requests-2.33.1.txt`](licenses/requests-2.33.1.txt) |
| `requests-toolbelt` | 1.0.0 | Apache 2.0 | <https://toolbelt.readthedocs.io/> | workspace | [`licenses/requests-toolbelt-1.0.0.txt`](licenses/requests-toolbelt-1.0.0.txt) |
| `rich` | 15.0.0 | MIT | <https://github.com/Textualize/rich> | siglip2-triton, workspace | [`licenses/rich-15.0.0.txt`](licenses/rich-15.0.0.txt) |
| `s3transfer` | 0.14.0 | Apache License 2.0 | <https://github.com/boto/s3transfer> | workspace | [`licenses/s3transfer-0.14.0.txt`](licenses/s3transfer-0.14.0.txt) |
| `safetensors` | 0.7.0 | Apache Software License | <https://github.com/huggingface/safetensors> | siglip2-triton, workspace | [`licenses/safetensors-0.7.0.txt`](licenses/safetensors-0.7.0.txt) |
| `sentry-sdk` | 2.58.0 | MIT | <https://github.com/getsentry/sentry-python> | workspace | [`licenses/sentry-sdk-2.58.0.txt`](licenses/sentry-sdk-2.58.0.txt) |
| `sentry-sdk` | 2.59.0 | MIT | <https://github.com/getsentry/sentry-python> | asset-graph-builder, rendering-job | [`licenses/sentry-sdk-2.59.0.txt`](licenses/sentry-sdk-2.59.0.txt) |
| `setuptools` | 82.0.1 | MIT | <https://github.com/pypa/setuptools> | asset-graph-builder, rendering-job, workspace | [`licenses/setuptools-82.0.1.txt`](licenses/setuptools-82.0.1.txt) |
| `shellingham` | 1.5.4 | ISC License | <https://github.com/sarugaku/shellingham> | siglip2-triton, workspace | [`licenses/shellingham-1.5.4.txt`](licenses/shellingham-1.5.4.txt) |
| `six` | 1.17.0 | MIT | <https://github.com/benjaminp/six> | workspace | [`licenses/six-1.17.0.txt`](licenses/six-1.17.0.txt) |
| `sniffio` | 1.3.1 | MIT OR Apache-2.0 | <https://github.com/python-trio/sniffio> | workspace | [`licenses/sniffio-1.3.1.txt`](licenses/sniffio-1.3.1.txt) |
| `sqlalchemy` | 2.0.49 | MIT | <https://www.sqlalchemy.org> | workspace | [`licenses/sqlalchemy-2.0.49.txt`](licenses/sqlalchemy-2.0.49.txt) |
| `starlette` | 0.50.0 | BSD-3-Clause | <https://github.com/Kludex/starlette> | asset-graph-builder, rendering-job | [`licenses/starlette-0.50.0.txt`](licenses/starlette-0.50.0.txt) |
| `starlette` | 1.3.1 | BSD-3-Clause | <https://github.com/Kludex/starlette> | siglip2-triton, workspace | [`licenses/starlette-1.3.1.txt`](licenses/starlette-1.3.1.txt) |
| `tenacity` | 9.1.4 | Apache 2.0 | <https://github.com/jd/tenacity> | workspace | [`licenses/tenacity-9.1.4.txt`](licenses/tenacity-9.1.4.txt) |
| `termcolor` | 3.3.0 | MIT | <https://github.com/termcolor/termcolor> | rendering-job, workspace | [`licenses/termcolor-3.3.0.txt`](licenses/termcolor-3.3.0.txt) |
| `tiktoken` | 0.12.0 | MIT | <https://pypi.org/project/tiktoken/> | workspace | [`licenses/tiktoken-0.12.0.txt`](licenses/tiktoken-0.12.0.txt) |
| `tokenizers` | 0.22.2 | Apache Software License | <https://github.com/huggingface/tokenizers> | siglip2-triton, workspace | [`licenses/tokenizers-0.22.2.txt`](licenses/tokenizers-0.22.2.txt) |
| `tqdm` | 4.67.3 | MPL-2.0 AND MIT | <https://pypi.org/project/tqdm/> | siglip2-triton, workspace | [`licenses/tqdm-4.67.3.txt`](licenses/tqdm-4.67.3.txt) |
| `transformers` | 5.5.4 | Apache 2.0 License | <https://github.com/huggingface/transformers> | workspace | [`licenses/transformers-5.5.4.txt`](licenses/transformers-5.5.4.txt) |
| `transformers` | 5.8.1 | Apache 2.0 License | <https://github.com/huggingface/transformers> | siglip2-triton | [`licenses/transformers-5.8.1.txt`](licenses/transformers-5.8.1.txt) |
| `tritonclient` | 2.41.0 | BSD | <https://developer.nvidia.com/nvidia-triton-inference-server> | workspace | [`licenses/tritonclient-2.41.0.txt`](licenses/tritonclient-2.41.0.txt) |
| `typer` | 0.24.1 | MIT | <https://github.com/fastapi/typer> | workspace | [`licenses/typer-0.24.1.txt`](licenses/typer-0.24.1.txt) |
| `typer` | 0.25.1 | MIT | <https://github.com/fastapi/typer> | siglip2-triton | [`licenses/typer-0.25.1.txt`](licenses/typer-0.25.1.txt) |
| `typing-extensions` | 4.15.0 | PSF-2.0 | <https://github.com/python/typing_extensions> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/typing-extensions-4.15.0.txt`](licenses/typing-extensions-4.15.0.txt) |
| `typing-inspection` | 0.4.2 | MIT | <https://github.com/pydantic/typing-inspection> | workspace | [`licenses/typing-inspection-0.4.2.txt`](licenses/typing-inspection-0.4.2.txt) |
| `urllib3` | 2.7.0 | MIT | <https://urllib3.readthedocs.io> | asset-graph-builder, rendering-job, siglip2-triton, workspace | [`licenses/urllib3-2.7.0.txt`](licenses/urllib3-2.7.0.txt) |
| `uuid-utils` | 0.14.1 | BSD-3-Clause | <https://github.com/aminalaee/uuid-utils> | workspace | [`licenses/uuid-utils-0.14.1.txt`](licenses/uuid-utils-0.14.1.txt) |
| `uvicorn` | 0.45.0 | BSD-3-Clause | <https://uvicorn.dev/> | workspace | [`licenses/uvicorn-0.45.0.txt`](licenses/uvicorn-0.45.0.txt) |
| `uvicorn` | 0.46.0 | BSD-3-Clause | <https://uvicorn.dev/> | asset-graph-builder, rendering-job | [`licenses/uvicorn-0.46.0.txt`](licenses/uvicorn-0.46.0.txt) |
| `websockets` | 15.0.1 | BSD-3-Clause | <https://github.com/python-websockets/websockets> | workspace | [`licenses/websockets-15.0.1.txt`](licenses/websockets-15.0.1.txt) |
| `websockets` | 16.0 | BSD-3-Clause | <https://github.com/python-websockets/websockets> | rendering-job | [`licenses/websockets-16.0.txt`](licenses/websockets-16.0.txt) |
| `wheel` | 0.47.0 | MIT | <https://github.com/pypa/wheel> | siglip2-triton | [`licenses/wheel-0.47.0.txt`](licenses/wheel-0.47.0.txt) |
| `wrapt` | 1.17.3 | BSD | <https://github.com/GrahamDumpleton/wrapt> | workspace | [`licenses/wrapt-1.17.3.txt`](licenses/wrapt-1.17.3.txt) |
| `xxhash` | 3.6.0 | BSD | <https://github.com/ifduyue/python-xxhash> | workspace | [`licenses/xxhash-3.6.0.txt`](licenses/xxhash-3.6.0.txt) |
| `yarl` | 1.23.0 | Apache-2.0 | <https://github.com/aio-libs/yarl> | asset-graph-builder, rendering-job, workspace | [`licenses/yarl-1.23.0.txt`](licenses/yarl-1.23.0.txt) |
| `zipp` | 3.23.1 | MIT | <https://github.com/jaraco/zipp> | workspace | [`licenses/zipp-3.23.1.txt`](licenses/zipp-3.23.1.txt) |
| `zstandard` | 0.25.0 | BSD-3-Clause | <https://github.com/indygreg/python-zstandard> | workspace | [`licenses/zstandard-0.25.0.txt`](licenses/zstandard-0.25.0.txt) |

## Bundled non-Python components

Items below are not Python packages and are tracked manually in
`scripts/third_party_extras.json`.

| Component | Version | License | Homepage | Sources | License text | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `google/siglip2-giant-opt-patch16-384` | main | Apache-2.0 | <https://huggingface.co/google/siglip2-giant-opt-patch16-384> | siglip2-triton | [`licenses/extras-google-siglip2-giant-opt-patch16-384-main.txt`](licenses/extras-google-siglip2-giant-opt-patch16-384-main.txt) | Pre-trained vision-language model weights; exported to ONNX and served by the siglip2-triton image. |
| `NVIDIA Omniverse Kit (kit-app-template)` | 110.1.1 | NVIDIA Software License Agreement | <https://github.com/NVIDIA-Omniverse/kit-app-template> | asset-graph-builder, rendering-job | [`licenses/extras-nvidia-omniverse-kit-kit-app-template-110.1.1.txt`](licenses/extras-nvidia-omniverse-kit-kit-app-template-110.1.1.txt) | Omniverse Kit kernel + extensions used by the rendering-job and asset-graph-builder images for USD rendering and scene-graph extraction. |
| `NVIDIA Triton Inference Server` | 26.05 | BSD-3-Clause | <https://github.com/triton-inference-server/server> | siglip2-triton | [`licenses/extras-nvidia-triton-inference-server-26.05.txt`](licenses/extras-nvidia-triton-inference-server-26.05.txt) | Base image (nvcr.io/nvidia/tritonserver:26.04-py3) used to serve the SigLIP2 ONNX model ensemble. |

## Bundled OS packages

Debian/Ubuntu packages installed (or upgraded) by the bundled images'
`apt-get` layers, plus their dependency closure — the `apt-get install`
steps in `docker/Dockerfile.usdsearch`'s runtime stage (on top of the Ubuntu
noble base) and `docker/Dockerfile.siglip2-triton` (on top of the Triton
base). The `Sources` column identifies the image each package belongs to.
Enumerated automatically from each container; license ids are inferred from
each package's `/usr/share/doc/<pkg>/copyright`.

| Package | Version | License | Homepage | Sources | License text |
| --- | --- | --- | --- | --- | --- |
| `ca-certificates` | 20260601~24.04.1 | GPL-2+, MPL-2.0 | <https://packages.ubuntu.com/search?keywords=ca-certificates> | usdsearch-runtime | [`licenses/os-ca-certificates-20260601-24.04.1.txt`](licenses/os-ca-certificates-20260601-24.04.1.txt) |
| `libexpat1` | 2.6.1-2ubuntu0.4 | MIT | <https://packages.ubuntu.com/search?keywords=libexpat1> | usdsearch-runtime | [`licenses/os-libexpat1-2.6.1-2ubuntu0.4.txt`](licenses/os-libexpat1-2.6.1-2ubuntu0.4.txt) |
| `libpython3.12-minimal` | 3.12.3-1ubuntu0.13 | Python-2.0 | <https://packages.ubuntu.com/search?keywords=libpython3.12-minimal> | usdsearch-runtime | [`licenses/os-libpython3.12-minimal-3.12.3-1ubuntu0.13.txt`](licenses/os-libpython3.12-minimal-3.12.3-1ubuntu0.13.txt) |
| `libpython3.12-stdlib` | 3.12.3-1ubuntu0.13 | Python-2.0 | <https://packages.ubuntu.com/search?keywords=libpython3.12-stdlib> | usdsearch-runtime | [`licenses/os-libpython3.12-stdlib-3.12.3-1ubuntu0.13.txt`](licenses/os-libpython3.12-stdlib-3.12.3-1ubuntu0.13.txt) |
| `libreadline8t64` | 8.2-4build1 | GPL-3+, GPL-2+, GFDL-NIV-1.3+, ISC-no-attribution, GPL-3 | <https://packages.ubuntu.com/search?keywords=libreadline8t64> | usdsearch-runtime | [`licenses/os-libreadline8t64-8.2-4build1.txt`](licenses/os-libreadline8t64-8.2-4build1.txt) |
| `libsqlite3-0` | 3.45.1-1ubuntu2.6 | public-domain, GPL-2+ | <https://packages.ubuntu.com/search?keywords=libsqlite3-0> | usdsearch-runtime | [`licenses/os-libsqlite3-0-3.45.1-1ubuntu2.6.txt`](licenses/os-libsqlite3-0-3.45.1-1ubuntu2.6.txt) |
| `media-types` | 10.1.0 | public-domain | <https://packages.ubuntu.com/search?keywords=media-types> | usdsearch-runtime | [`licenses/os-media-types-10.1.0.txt`](licenses/os-media-types-10.1.0.txt) |
| `netbase` | 6.4 | GPL-2 | <https://packages.ubuntu.com/search?keywords=netbase> | usdsearch-runtime | [`licenses/os-netbase-6.4.txt`](licenses/os-netbase-6.4.txt) |
| `openssl` | 3.0.13-0ubuntu3.11 | Apache-2.0, Artistic or GPL-1+, Artistic, GPL-1+ | <https://packages.ubuntu.com/search?keywords=openssl> | usdsearch-runtime | [`licenses/os-openssl-3.0.13-0ubuntu3.11.txt`](licenses/os-openssl-3.0.13-0ubuntu3.11.txt) |
| `python3.12` | 3.12.3-1ubuntu0.13 | Python-2.0 | <https://packages.ubuntu.com/search?keywords=python3.12> | usdsearch-runtime | [`licenses/os-python3.12-3.12.3-1ubuntu0.13.txt`](licenses/os-python3.12-3.12.3-1ubuntu0.13.txt) |
| `python3.12-minimal` | 3.12.3-1ubuntu0.13 | Python-2.0 | <https://packages.ubuntu.com/search?keywords=python3.12-minimal> | usdsearch-runtime | [`licenses/os-python3.12-minimal-3.12.3-1ubuntu0.13.txt`](licenses/os-python3.12-minimal-3.12.3-1ubuntu0.13.txt) |
| `readline-common` | 8.2-4build1 | GPL-3+, GPL-2+, GFDL-NIV-1.3+, ISC-no-attribution, GPL-3 | <https://packages.ubuntu.com/search?keywords=readline-common> | usdsearch-runtime | [`licenses/os-readline-common-8.2-4build1.txt`](licenses/os-readline-common-8.2-4build1.txt) |
| `tzdata` | 2026a-0ubuntu0.24.04.1 | public-domain, ICU | <https://packages.ubuntu.com/search?keywords=tzdata> | usdsearch-runtime | [`licenses/os-tzdata-2026a-0ubuntu0.24.04.1.txt`](licenses/os-tzdata-2026a-0ubuntu0.24.04.1.txt) |
