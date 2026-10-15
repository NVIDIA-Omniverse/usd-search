# Performance & Scaling

Guidance for sizing and scaling a USD Search deployment, plus reference
benchmark numbers. For hardware/software minimums, see
[`support-matrix.md`](support-matrix.md); for the microservice breakdown
referenced below, see [`architecture.md`](architecture.md).

## Reference benchmark numbers

Test conditions: a 50 GB SimReady database, 50 concurrent users, 8 CPU
replicas (single-threaded each), 1 GPU, 0% acceptable failure rate.

**Text-based search** (requests/sec, avg latency, p99 latency):

| GPU | req/s | avg latency | p99 latency |
|---|---|---|---|
| H100 | 117.8 | 423 ms | 1300 ms |
| A10g | 91.0 | 548 ms | 1900 ms |

**Image-based search** (requests/sec, avg latency):

| GPU | req/s | avg latency |
|---|---|---|
| H100 | 53.4 | 932 ms |
| A10g | 10.2 | 4795 ms |

L40 and A100 fall between these two.

## Scaling stateless services

Search, embedding, indexing, and the Asset Graph Service are stateless and
scale horizontally. Scale a deployment directly:

```bash
kubectl scale --replicas=<desired number of CPU replicas> deployment <deployment name>-ngsearch-search-rest-api
```

Indexing/embedding plugins can also autoscale via the chart's Horizontal Pod
Autoscaler support — see `helm/usdsearch/README.md`'s "Horizontal Pod
Autoscaler" section — or increase per-plugin concurrency via
`n_concurrent_queue_workers` (see "Concurrent processing" in the same doc).

Rendering jobs scale with available GPU nodes: a rendering job only starts
once enough GPU resources are free on the cluster, so adding a GPU node
increases indexing throughput roughly linearly. Enabling persistent shader
caching for Rendering Jobs (see "Enable shader caching in Rendering jobs" in
`helm/usdsearch/README.md`) avoids re-computing the cache on every job and
meaningfully improves indexing speed.

## Scaling stateful components

OpenSearch, Redis, and Neo4j are stateful. They support vertical scaling
directly; OpenSearch additionally supports horizontal scaling by increasing
its replica count (`opensearch.replicas` in your values file, default `3`)
— see "Increase the number of OpenSearch replicas" in
`helm/usdsearch/README.md` if search latency is the bottleneck.

## Monitoring while scaling

Enable the built-in Grafana dashboards (`deployGrafanaDashboards=true`,
`deployServiceMonitors=true`) to observe resource usage and indexing
progress while you tune replica counts — see `helm/usdsearch/README.md`'s
Monitoring section for setup and dashboard names.
