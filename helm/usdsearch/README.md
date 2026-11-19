# USD Search API

![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.5.1](https://img.shields.io/badge/AppVersion-1.5.1-informational?style=flat-square)

**Homepage:** <https://github.com/NVIDIA-omniverse/usd-search>

# Requirements
| Repository | Name | Version |
|------------|------|---------|
| https://helm.neo4j.com/neo4j | neo4j | 2026.9.0 |
| https://opensearch-project.github.io/helm-charts/ | opensearch | 3.8.0 |
| https://opensearch-project.github.io/helm-charts/ | opensearch-dashboards | 3.5.0 |
| oci://registry-1.docker.io/bitnamicharts | deepsearch-explorer(nginx) | 22.5.3 |
| oci://registry-1.docker.io/bitnamicharts | api-gateway(nginx) | 22.5.3 |
| oci://registry-1.docker.io/bitnamicharts | redis | 28.2.3 |

# Overview

USD Search API is a collection of cloud-native microservices that enable developers, creators, and workflow specialists to efficiently search through vast collections of OpenUSD data, images, and other assets using natural language or image-based inputs.

With these production-ready microservices, developers can deploy USD Search API onto their own infrastructure. With USD Search API's artificial intelligence (AI) features, you can quickly locate untagged and unstructured 3D data and digital assets, saving time navigating unstructured, untagged 3D data. USD Search API is capable of searching and indexing 3D asset databases, as well as navigating complex 3D scenes to perform spatial searches, without requiring manual tagging of assets.

The document describes how USD Search API helm chart could be configured and installed on a kubernetes cluster and connected to a wide range of storage backends.

**NOTE**: USD Search API helm chart assumes that a Kubernetes cluster is already available and configured. Further, depending on the ingress controller and namespace, some changes may be required.

# Table of Contents

- [Prerequisites](#prerequisites)
- [Packages and Access](#packages-and-access)
- [Deployment](#deployment)
	- [AWS S3](#aws-s3)
		- [Alternative installation options](#alternative-installation-options)
		- [Additional parameters: re-scan frequency](#additional-parameters-re-scan-frequency)
	- [S3proxy](#s3proxy)
		- [Examples for Different Storage Backends](#examples-for-different-storage-backends)
			- [Any S3 compatible Storage Backend](#any-s3-compatible-storage-backend)
			- [Azure Blob Storage Backend](#azure-blob-storage-backend)
			- [Google Cloud Storage Backend](#google-cloud-storage-backend)
		- [Alternative installation options](#alternative-installation-options-1)
		- [Extra Java options](#extra-java-options)
	- [Omniverse Nucleus Server](#omniverse-nucleus-server)
		- [Alternative installation options](#alternative-installation-options-2)
			- [Nucleus API token](#nucleus-api-token)
		- [USD Search REST API Authentication](#usd-search-rest-api-authentication)
			- [Admin Access Key](#admin-access-key)
			- [Disable Access verification](#disable-access-verification)
	- [Omniverse Storage APIs](#omniverse-storage-apis)
		- [SSL support](#ssl-support)
		- [Authentication](#authentication)
		- [Thumbnail retrieval](#thumbnail-retrieval)
		- [Alternative installation options](#alternative-installation-options-3)
		- [Additional parameters: re-scan frequency](#additional-parameters-re-scan-frequency-1)
	- [API endpoint access](#api-endpoint-access)
	- [Monitoring](#monitoring)
- [Post-installation](#post-installation)
	- [Deployment status check](#deployment-status-check)
	- [Testing](#testing)
- [Uninstall](#uninstall)
	- [Rendering jobs clean-up](#rendering-jobs-clean-up)
	- [Secrets and persistent volumes clean-up](#secrets-and-persistent-volumes-clean-up)
- [Experimental](#experimental)
	- [Sample Explorer WebUI](#sample-explorer-webui)
	- [Admin tools (beta)](#admin-tools-beta)
		- [Re-indexing](#re-indexing)
		- [Storage backend listing](#storage-backend-listing)
	- [Rendering service](#rendering-service)
		- [Authentication](#authentication-1)
- [Advanced configuration](#advanced-configuration)
	- [Indexing path filtering](#indexing-path-filtering)
	- [Thumbnail indexing settings](#thumbnail-indexing-settings)
	- [Plugins](#plugins)
		- [Horizontal Pod Autoscaler](#horizontal-pod-autoscaler)
		- [Concurrent processing](#concurrent-processing)
	- [Rendering Job configuration](#rendering-job-configuration)
		- [Number of parallel rendering jobs](#number-of-parallel-rendering-jobs)
		- [Number of parallel rendering workers per rendering job](#number-of-parallel-rendering-workers-per-rendering-job)
		- [Rendering Job Timeout](#rendering-job-timeout)
		- [Additional configuration settings](#additional-configuration-settings)
			- [Annotations](#annotations)
			- [Tolerations](#tolerations)
		- [Resources](#resources)
	- [Persistence (experimental)](#persistence-experimental)
	- [USD properties search](#usd-properties-search)
	- [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging)
		- [LLM/VLM provider](#llmvlm-provider)
		- [Input budget and cache identity](#input-budget-and-cache-identity)
		- [Customization](#customization)
			- [Image prompt configuration](#image-prompt-configuration)
			- [Metadata fields configuration](#metadata-fields-configuration)
	- [VLM-based verification of results with respect to input query](#vlm-based-verification-of-results-with-respect-to-input-query)
		- [LLM/VLM provider](#llmvlm-provider-1)
	- [Search Backend configuration](#search-backend-configuration)
		- [External OpenSearch instance](#external-opensearch-instance)
		- [OpenSearch authentication](#opensearch-authentication)
	- [OTEL Telemetry and Traces collection](#otel-telemetry-and-traces-collection)
		- [Trace collection](#trace-collection)
		- [Search and asset-load telemetry collection](#search-and-asset-load-telemetry-collection)
	- [Values](#values)
		- [Global settings](#global-settings)
	- [Embedding service settings](#embedding-service-settings)
	- [Asset Graph Service additional settings](#asset-graph-service-additional-settings)
	- [Other settings](#other-settings)
	- [Redis instance settings](#redis-instance-settings)
	- [OpenSearch instance settings](#opensearch-instance-settings)
	- [Neo4j instance settings](#neo4j-instance-settings)
	- [Maintainers](#maintainers)
- [License](#license)
- [FAQ](#faq)
	- [USD assets organization best practices](#usd-assets-organization-best-practices)
	- [Image-based search best practices](#image-based-search-best-practices)
	- [Embedding service falls back to CPU with the GPU Operator installed](#embedding-service-falls-back-to-cpu-with-the-gpu-operator-installed)
	- [Redis Persistent Volume Claim](#redis-persistent-volume-claim)
	- [Microk8s CA certificate issues](#microk8s-ca-certificate-issues)
	- [Redis CrashLoopBackOff](#redis-crashloopbackoff)
	- [OpenSearch Persistent Volume Claim](#opensearch-persistent-volume-claim)
	- [Incorrect Service Registration Token with Omniverse Nucleus storage backend](#incorrect-service-registration-token-with-omniverse-nucleus-storage-backend)
	- [OpenSearch Virtual Memory (vm.max\_map\_count)](#opensearch-virtual-memory-vmmax_map_count)
	- [Storage backend connection](#storage-backend-connection)
	- [Search speed improvement](#search-speed-improvement)
		- [Increase the number of OpenSearch replicas](#increase-the-number-of-opensearch-replicas)
	- [Indexing speed improvement](#indexing-speed-improvement)
		- [Enable shader caching in Rendering jobs](#enable-shader-caching-in-rendering-jobs)
		- [Scale the cluster](#scale-the-cluster)
	- [Metrics are missing in Grafana with monitoring enabled](#metrics-are-missing-in-grafana-with-monitoring-enabled)
- [Get Help](#get-help)

# Prerequisites

Kubernetes cluster with the following features enabled:
* Role-based access control (RBAC) - required for creating GPU-based asset rendering jobs
* [NVIDIA k8s device plugin](https://github.com/NVIDIA/k8s-device-plugin) - required for execution of asset rendering jobs. Alternatively, [NVIDIA GPU-operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html) (which includes [NVIDIA k8s device plugin](https://github.com/NVIDIA/k8s-device-plugin)) could be used.

Optional:
* Metrics server - required for Horizontal Pod Autoscaling (HPA)
* [Prometheus Stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) - required for service monitoring
* Dynamic Persistent Volume provisioning - can be utilized by dependent helm charts (e.g. OpenSearch, Redis, Neo4j) in order to automatically provision required persistent volumes

Helm version is higher than ``3.0.0``. To check this run the following command

```bash
helm version
version.BuildInfo{Version:"v3.2.0", GitCommit:"e11b7ce3b12db2941e90399e874513fbd24bcb71", GitTreeState:"clean", GoVersion:"go1.13.10"}
```

# Packages and Access

This chart is listed in the [NGC catalog](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/usdsearch/helm-charts/usdsearch) and served from `helm.ngc.nvidia.com`; the container images it deploys come from `nvcr.io`. Fetching the chart needs an NGC API key. The images under `nvcr.io/nvidia/usdsearch` are public, so `global.imagePullSecrets` is only needed for an image served from a private registry.

Generate your NGC API key prior to fetch helm chart. See the [NGC user guide](https://docs.nvidia.com/ngc/gpu-cloud/ngc-user-guide/index.html) for how to create one.

Add the repository to list the available versions

```bash
helm repo add usdsearch https://helm.ngc.nvidia.com/nvidia/usdsearch \
	--username='$oauthtoken' \
	--password=<YOUR API KEY>
helm search repo usdsearch/usdsearch --versions
```

Or fetch a specific chart version from the registry

```bash
helm fetch https://helm.ngc.nvidia.com/nvidia/usdsearch/charts/usdsearch-1.5.1.tgz \
	--username='$oauthtoken' \
	--password=<YOUR API KEY>
```

> **Faster eval/prod cluster setup:** if you don't already have a Kubernetes
> cluster, NGC also publishes MicroK8s bare-metal quickstart scripts and a
> Terraform module for standing one up on AWS, under the same
> `nvidia/usdsearch` NGC resources referenced above. This chart's own
> instructions below assume a cluster already exists and don't cover
> provisioning one.

# Deployment

USD Search can be deployed to index data from an [AWS S3 bucket](#aws-s3), an [Omniverse Nucleus server](#omniverse-nucleus-server) or a broad range of other backends by utilizing [S3proxy functionality](#s3proxy). Detailed deployment commands can be found in the sections below.

## AWS S3

To deploy the USD Search Helm chart and connect it to an AWS S3 bucket for
indexing, run the following command:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --set global.accept_eula=true \
  --set global.storage_backend_type=s3 \
  --set global.s3.bucket_name=<S3 bucket name> \
  --set global.s3.region_name=<S3 bucket region>  \
  --set global.s3.aws_access_key_id=<AWS access key ID> \
  --set global.s3.aws_secret_access_key=<AWS secret access key>  \
  --set global.secrets.create.auth=true \
  --set global.secrets.create.registry=true \
  --set global.ngcAPIKey=<NGC API KEY> \
  --set api-gateway.image.pullSecrets={nvcr.io}
```

__NOTE__: Please refer to [NGC documentation](https://docs.nvidia.com/ngc/gpu-cloud/ngc-user-guide/index.html#generating-api-key) for generating the NGC API Key.

### Alternative installation options

The above command creates all required secrets on helm chart deployment,
which is done for convenience. It may, however, be not acceptable in some
deployment scenarios to pass credential information through helm chart
values. To address this issue it is possible to create kubernetes secret
with access information manually with the following command:

```bash
kubectl create secret generic deepsearch-s3-credentials \
  --from-literal=AWS_ACCESS_KEY_ID=<AWS access key ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<AWS secret access key>
```

Similarly, it is possible to create a registry access secret with the
following command:

```bash
kubectl create secret docker-registry nvcr.io \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<NGC API KEY> \
  --docker-email=<your-email>
```

With the above secrets created, the helm chart installation command can be
simplified to:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --set global.accept_eula=true \
  --set global.storage_backend_type=s3 \
  --set global.s3.bucket_name=<S3 bucket name> \
  --set global.s3.region_name=<S3 bucket region>  \
  --set api-gateway.image.pullSecrets={nvcr.io} \
  --set global.imagePullSecrets={nvcr.io}
```

### Additional parameters: re-scan frequency

USD Search re-scans the S3 bucket daily to detect new data while minimizing load. You can adjust the re-scan frequency by adding the following argument to the installation or upgrade command:

```bash
  --set global.s3.re_scan_timeout=<re scan timeout time in seconds>
```

**NOTE**: Setting this parameter too low may cause processing queues to grow faster than your USD Search instance can handle. It is recommended to monitor the processing queues in Grafana and adjust the parameter to prevent excessive queue growth.

## S3proxy

USD Search supports integration with an S3-compatible proxy, such as S3proxy, for indexing. By default, no specific image is configured for S3proxy (``image.repository.url`` is unset), allowing flexibility for users to choose their preferred image. However, the official [andrewgaul/s3proxy](https://hub.docker.com/r/andrewgaul/s3proxy/) image is recommended, as it is Apache-licensed, regularly updated.

To deploy the USD Search Helm chart with S3proxy, ensure that the s3proxy feature is enabled and configured in the ``values.yaml`` file or through Helm overrides. Below you will find commands to install S3proxy with different backends.

For more details on configuring different storage backends, refer to the official [S3proxy documentation](https://github.com/gaul/s3proxy/wiki/Storage-backend-examples) or consult the cloud provider documentation for AWS S3, Azure Blob Storage, and Google Cloud Storage.

### Examples for Different Storage Backends

#### Any S3 compatible Storage Backend

Using S3proxy functionality is it possible to seamlessly connect to any S3 compatible storage backends (e.g. Dell ObjectScale, DreamObjects, etc.)

```bash
helm upgrade <deployment name> usdsearch-1.5.1.tgz --install \
  --namespace <namespace> \
  --set global.s3proxy.enabled=true \
  --set global.accept_eula=true \
  --set global.s3.bucket_name=<your-bucket-name> \
  --set s3proxy.image.url=docker.io/andrewgaul/s3proxy:latest \
  --set s3proxy.jclouds.provider="s3" \
  --set s3proxy.jclouds.endpoint=<your-storage-backend-endpoint> \
  --set s3proxy.jclouds.identity=<your-storage-backend-identity> \
  --set s3proxy.jclouds.credential=<your-storage-backend-key> \
  --set global.ngcAPIKey=<NGC-API-KEY> \
  --set global.secrets.create.registry=true \
  --set global.secrets.create.auth=true \
  --set api-gateway.image.pullSecrets={nvcr.io}
```

#### Azure Blob Storage Backend

Using S3proxy functionality is it possible to seamlessly connect to Azure Blob Storage.

```bash
helm upgrade <deployment name> usdsearch-1.5.1.tgz --install \
  --namespace <namespace> \
  --set global.s3proxy.enabled=true \
  --set global.accept_eula=true \
  --set s3proxy.image.url=docker.io/andrewgaul/s3proxy:latest \
  --set global.s3.bucket_name=<your-bucket-name> \
  --set s3proxy.jclouds.provider="azureblob-sdk" \
  --set s3proxy.jclouds.endpoint="https://<azure-storage-account-name>.blob.core.windows.net/" \
  --set s3proxy.jclouds.identity=<your-storage-backend-identity> \
  --set s3proxy.jclouds.credential=<your-storage-backend-key> \
  --set global.ngcAPIKey=<NGC-API-KEY> \
  --set global.secrets.create.registry=true \
  --set global.secrets.create.auth=true \
  --set api-gateway.image.pullSecrets={nvcr.io}
```

#### Google Cloud Storage Backend

Using S3proxy functionality is it possible to seamlessly connect to Google Cloud Storage.

```bash
helm upgrade <deployment name> usdsearch-1.5.1.tgz --install \
  --namespace <namespace> \
  --set global.s3proxy.enabled=true \
  --set global.accept_eula=true \
  --set global.s3.bucket_name=<your-gcs-bucket-name> \
  --set s3proxy.image.url=docker.io/andrewgaul/s3proxy:latest \
  --set s3proxy.jclouds.provider="google-cloud-storage" \
  --set s3proxy.jclouds.endpoint="https://storage.googleapis.com" \
  --set s3proxy.jclouds.identity=<your-storage-backend-identity> \
  --set s3proxy.jclouds.credential=<your-storage-backend-key> \
  --set global.ngcAPIKey=<NGC-API-KEY> \
  --set global.secrets.create.registry=true \
  --set global.secrets.create.auth=true \
  --set api-gateway.image.pullSecrets={nvcr.io}
```

### Alternative installation options

Sample installation commands illustrated in the above sections create all
required secrets on helm chart deployment, which is done for convenience. It
may, however, be not acceptable in some deployment scenarios to pass
credential information through helm chart values. To address this issue it is
possible to create kubernetes secret with access information manually with the
following command:

```bash
kubectl create secret generic s3proxy-credentials \
  --from-literal=jclouds-identity=<your-storage-backend-identity> \
  --from-literal=jclouds-credential=<your-storage-backend-key> \
  --namespace <namespace>
```
It is also possible to create a registry access secret with the
following command:
```bash
kubectl create secret docker-registry nvcr.io \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<NGC API KEY> \
  --docker-email=<your-email> \
  --namespace <namespace>
```
With the above secrets created, the helm chart installation command can be
simplified to:
```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --namespace <namespace> \
  --set global.s3proxy.enabled=true \
  --set s3proxy.image.url=docker.io/andrewgaul/s3proxy:latest \
  --set global.accept_eula=true \
  --set global.storage_backend_type=s3 \
  --set global.s3.bucket_name=<your bucket name (depending on the provider)> \
  --set s3proxy.jclouds.provider="<your-storage-backend-provider>" \
  --set s3proxy.jclouds.endpoint="<your-storage-backend-endpoint>" \
  --set api-gateway.image.pullSecrets={nvcr.io} \
  --set global.imagePullSecrets={nvcr.io}
```

### Extra Java options

Additional Java options could be provided to the S3proxy container by setting the following value:

```bash
  --set s3proxy.extraJavaOpts=<additional java options>
```

For example in some cases it may be required to disable SSL verification by setting the following value:

```bash
  --set s3proxy.extraJavaOpts="-Djclouds.trust-all-certs=true -Djclouds.relax-hostname=true"
```

## Omniverse Nucleus Server

USD Search API service requires a service account with administrator rights
in order to index the content stored on the Nucleus server. It is possible
to use the main Nucleus service account, generated during the Nucleus
service installation time. Alternatively, it is possible to create a
dedicated service account for USD Search. For the exact steps on how such
account could be created please follow [this guide](https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/auth_user_mgmt.html#service-accounts).

When creating your own service account it is required to grant it admin
access. [This guide](https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/auth_user_mgmt.html#grant-admin-access) explains this process in detail.

After the service account's ``username`` and ``password`` are obtained, it
is possible to deploy the USD Search Helm chart and connect it to an
Omniverse Nucleus server for indexing, as follows:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
 --set global.accept_eula=true \
 --set global.storage_backend_type=nucleus \
 --set global.nucleus.server=<Omniverse Nucleus server hostname or IP> \
 --set global.nucleus.username=<Omniverse service account name> \
 --set global.nucleus.password=<Omniverse service account password> \
 --set global.secrets.create.auth=true \
 --set global.secrets.create.registry=true \
 --set global.ngcAPIKey=<NGC API KEY> \
 --set api-gateway.image.pullSecrets={nvcr.io} \
 --set deepsearch-crawler.crawler.extraConfig.exclude_patterns={"omniverse://[^\/]+/NVIDIA.*"}
```

__NOTE__: Please refer to
[NGC documentation](https://docs.nvidia.com/ngc/gpu-cloud/ngc-user-guide/index.html#generating-api-key)
for generating the NGC API Key.

__NOTE__: The `/NVIDIA` sample data mount is excluded from indexing by
default. To enable its indexing, remove the corresponding line from the
command. You can also customize URL patterns for indexing, as explained in
the [Indexing path filtering section](#indexing-path-filtering).

### Alternative installation options

The above command creates all required secrets on helm chart deployment,
which is done for convenience. It may, however, be not acceptable in some
deployment scenarios to pass credential information through helm chart
values. To address this issue it is possible to create kubernetes secret
with access information manually with the following command:

```bash
kubectl create secret generic deepsearch-service-account \
  --from-literal=username=<Omniverse service account name> \
  --from-literal=password=<Omniverse service account password>
```

Similarly, it is possible to create a registry access secret with the
following command:

```bash
kubectl create secret docker-registry nvcr.io \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<NGC API KEY> \
  --docker-email=<your-email>
```

With the above secrets created, the helm chart installation command can be
simplified to:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --set global.accept_eula=true \
  --set global.storage_backend_type=nucleus \
  --set global.nucleus.server=<Omniverse Nucleus server hostname or IP> \
  --set deepsearch-crawler.crawler.extraConfig.exclude_patterns={"omniverse://[^\/]+/NVIDIA.*"}
  --set api-gateway.image.pullSecrets={nvcr.io} \
  --set global.imagePullSecrets={nvcr.io}
```

#### Nucleus API token

Instead of using service account it is possible to rely on
[Nucleus API token](https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/api_tokens.html).
To do so, you need to input ``$omni-api-token`` as the username and the API
token value as the password. Additionally you need to pass the following
parameter to disable permissions check that is not required for Nucleus API
tokens:

```bash
  --set global.nucleus.assert_admin_user='false'
```

### USD Search REST API Authentication

By default, when connected to an Omniverse Nucleus server, search service verifies that the user has access to retrieved assets before returning them. Therefore, in order to access search functionality, it is required to provide with one of the following authentication methods:

* service account ``username`` / ``password`` pair
	* alternatively is it possible to rely on [Nucleus API token](https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/api_tokens.html) and provide ``$omni-api-token`` as the ``username`` and the API token value as the ``password``.

* [Nucleus connection token](https://docs.omniverse.nvidia.com/nucleus/latest/config-and-info/auth_user_mgmt.html#authentication) that is generated by the client library.

#### Admin Access Key

At service deploy time it is possible to configure admin access key that allows by-passing this access verification step by setting the ``access_key`` configuration parameter as follows:

```bash
	--set ngsearch.microservices.search_rest_api.admin_authentication.access_key=<some key value>
```
when this field is left unset the access key will be auto-generated and stored in a configmap on the kubernetes cluster. To retrieve the value of this key you can run the following:

```bash
export NAMESPACE=<deployment namespace>
export HELM_NAME=<deployment name>
echo $(kubectl get cm $HELM_NAME-ngsearch-env-config -n $NAMESPACE -o "jsonpath={.data.DEEPSEARCH_BACKEND_ADMIN_ACCESS_KEY}")
```

Alternatively it is possible to run the following command:

```bash
helm status <deployment name>
```

which will show some information about the deployment and the list of useful commands. The value of Admin access key will be printed there as part of `Accessing USD Search` section.

#### Disable Access verification

If access verification is not desired it is possible to disable it by providing the following argument to the installation or upgrade command:

```bash
	--set ngsearch.microservices.search_rest_api.enable_access_verification=false
```

## Omniverse Storage APIs

To deploy the USD Search Helm chart and connect it to an Omniverse Storage API for
indexing, run the following command:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --set global.accept_eula=true \
  --set global.storage_backend_type=storage_api \
  --set global.storage_api.grpc_endpoint=<Storage API gRPC endpoint> \
  --set global.storage_api.base_uri=<Storage API base URI> \
  --set global.secrets.create.registry=true \
  --set api-gateway.image.pullSecrets={nvcr.io} \
  --set global.imagePullSecrets={nvcr.io}
```

__NOTE__: Please refer to [Omniverse Storage API documentation](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/omniverse/collections/storage_apis) for more information about the Storage API.

### SSL support

If the Storage API is configured to use SSL, set this to true.
This is used to enable SSL for the Storage API connection.

```bash
  --set global.storage_api.ssl=true
```

### Authentication

If Omniverse Storage APIs are configured to use authentication, it is possible to authenticate with the Storage API using either a token or OpenID. To do so, please set the following parameters:
  * authentication.enabled=true
  * authentication.type=token or authentication.type=openid
  * authentication.token=<Storage API token>
  * authentication.openid.token_url=<OpenID token URL>
  * authentication.openid.client_id=<OpenID client ID>
  * authentication.openid.client_secret=<OpenID client secret>

it is then required to add the following command line arguments during helm chart deployment for token authentication:
```bash
  --set global.secrets.create.auth=true
  --set global.storage_api.authentication.enabled=true \
  --set global.storage_api.authentication.type=token \
  --set global.storage_api.authentication.token=<Storage API token> \
  --set global.secrets.create.auth=true \
```
and for OpenID authentication:
```bash
  --set global.secrets.create.auth=true
  --set global.storage_api.authentication.enabled=true \
  --set global.storage_api.authentication.type=openid \
  --set global.storage_api.authentication.openid.token_url=<OpenID token URL> \
  --set global.storage_api.authentication.openid.client_id=<OpenID client ID> \
  --set global.storage_api.authentication.openid.client_secret=<OpenID client secret> \
```

### Thumbnail retrieval

When using the Storage API backend, thumbnails are not resolved from the filesystem (the ``deepsearch.thumbnail_settings`` configuration does not apply). Instead, the service reads the thumbnail URL directly from a field in the asset's metadata.

By default the field named ``thumbnail_url`` is used. You can override this with an ordered list of field names; the first field present in the asset metadata whose value is a non-empty string is used as the thumbnail URL:

```bash
  --set global.storage_api.thumbnail_metadata_fields[0]=thumbnail_url
```

or via a values file:

```yaml
global:
  storage_api:
    thumbnail_metadata_fields:
      - thumbnail_url
```

### Alternative installation options

The above command creates all required secrets on helm chart deployment,
which is done for convenience. It may, however, be not acceptable in some
deployment scenarios to pass credential information through helm chart
values. To address this issue it is possible to create kubernetes secret
with access information manually with the following command:

```bash
kubectl create secret generic deepsearch-storage-api-credentials \
  --from-literal=token=<Storage API token>
```

Similarly, it is possible to create a registry access secret with the
following command:

```bash
kubectl create secret docker-registry nvcr.io \
  --docker-server=nvcr.io \
  --docker-username='$oauthtoken' \
  --docker-password=<NGC API KEY> \
  --docker-email=<your-email>
```

With the above secrets created, the helm chart installation command can be
simplified to:

```bash
helm install <deployment name> usdsearch-1.5.1.tgz \
  --set global.accept_eula=true \
  --set global.storage_backend_type=storage_api \
  --set global.storage_api.grpc_endpoint=<Storage API gRPC endpoint> \
  --set global.storage_api.base_uri=<Storage API base URI> \
  --set global.storage_api.ssl=true \
  --set global.storage_api.authentication.enabled=true \
  --set global.storage_api.authentication.type=token \
  --set global.storage_api.authentication.secret_name=storage-api-credentials \
  --set global.storage_api.authentication.token=<Storage API token> \
  --set api-gateway.image.pullSecrets={nvcr.io} \
  --set global.imagePullSecrets={nvcr.io}
```

### Additional parameters: re-scan frequency

USD Search performs a full re-scan of the Storage API backend daily to detect new data while minimizing load. You can adjust the re-scan frequency by adding the following argument to the installation or upgrade command:

```bash
  --set global.storage_api.re_scan_timeout=<re scan timeout time in seconds>
```

Setting this parameter to ``-1`` (or any other non-positive value) disables periodic re-scans, so the backend is scanned only once at startup.

**NOTE**: This parameter only applies when ``global.storage_api.notification_subscription_enabled`` is ``false`` (the default). When notification subscription is enabled, changes are picked up from the Storage API notification stream instead and no periodic re-scan is performed, so the value is ignored.

**NOTE**: Setting this parameter too low may cause processing queues to grow faster than your USD Search instance can handle. It is recommended to monitor the processing queues in Grafana and adjust the parameter to prevent excessive queue growth.

### Additional parameters: thumbnail style

By default (``storage_api``), thumbnails are resolved by reading the thumbnail URL directly from the asset metadata field(s) named in ``global.storage_api.thumbnail_metadata_fields``. To instead resolve thumbnails from the conventional Nucleus ``.thumbs/<width>x<height>/<filename>[.auto].png`` sibling path, set:

```bash
  --set global.storage_api.thumbnail_style=nucleus
```

## API endpoint access

All the USD Search functionality is unified under a single API gateway. API Gateway service configuration. By default the ClusterIP service type is used, however, it is possible to override this and make the endpoint publicly accessible. Please refer to [NGINX helm chart service configuration](https://github.com/bitnami/charts/blob/main/bitnami/nginx/README.md#traffic-exposure-parameters) for a complete list of settings.

Below you can find several sample configurations for the API gateway endpoint, depending on the desired service type, and instructions on how to access it:

*  **ClusterIP** (default) - If the ClusterIP service type is used, you can access the API externally via port-forwarding from the Kubernetes cluster as described below. For internal access, use the service name directly.

	API Gateway port-forward example:

	```bash
	kubectl port-forward -n <NAMESPACE> svc/<deployment name>-api-gateway 8080:80
	```
	The endpoint should then be accessible at ``http://localhost:8080``.

* **NodePort** - You can specify the NodePort service type to make the endpoint publicly accessible using the Kubernetes cluster’s external IP. Typically, NodePort values must be in the >30000 range. To enable this, use the following command line arguments:

	```bash
		--set api-gateway.service.type=NodePort \
		--set api-gateway.service.nodePorts.http=<NodePort value>
	```
	the service will then be accessible at ``http://<external cluster IP>:<NodePort value>``

	**NOTE**: Please refer to [Kubernetes documentation](https://kubernetes.io/docs/concepts/services-networking/service/#type-nodeport) more information about NodePort type services.

* **Ingress** - You can enable Ingress to make the service available at a specified hostname. This requires an Ingress controller to be set up, and you may need to specify an Ingress class that matches your controller. Use the following command line arguments to configure it:

	```bash
		--set api-gateway.ingress.enabled=true \
		--set api-gateway.ingress.hostname=<service hostname> \
        --set api-gateway.ingress.ingressClassName=<ingress class name, e.g. 'nginx'>
	```
	the service will then be accessible at ``http://<service hostname>``

* **HTTPProxy** - If your cluster runs [Contour](https://projectcontour.io/) rather than an Ingress controller, the same endpoint can be exposed through a Contour ``HTTPProxy`` object. The hostname is composed as ``<host>.<domain>``:

	```bash
		--set httpProxy.enabled=true \
		--set httpProxy.fqdn.host=<host label, e.g. 'usdsearch'> \
		--set httpProxy.fqdn.domain=<domain name, e.g. 'example.com'>
	```
	the service will then be accessible at ``http://<host>.<domain>``

	TLS, CORS, edge authorization and route timeouts are configured from the same ``httpProxy`` section. Setting ``httpProxy.tls.certManager.enabled=true`` additionally creates a cert-manager ``Certificate`` for that hostname.

## Monitoring

The USD Search Helm chart includes monitoring functionality that sets up metrics collection and pre-configured dashboards for tracking background indexing progress and the overall system state. This requires the Prometheus Operator and Grafana with dashboard provisioning. You can use the [Kube Prometheus Stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) to meet these requirements. To enable monitoring, provide the following command line arguments:

```bash
	--set deployGrafanaDashboards=true \
	--set deployServiceMonitors=true
```
With the above flag enabled the metrics will be automatically scraped by Prometheus service (part of Prometheus stack) and visualized in Grafana as `USD Search / Plugin Processing Dashboard` and `USD Search / Metadata Indexing and Crawler Dashboard` dashboards.

# Post-installation

## Deployment status check

After the helm chart is installed you can check the state of the deployment as follows:

```bash
helm status <deployment name>
```

This command should print the following to the standard output:

```bash
NAME: <deployment name>
LAST DEPLOYED: <deployment time>
NAMESPACE: <deployment namespace>
STATUS: deployed
REVISION: 1
NOTES:
  ...
```

It will also show some useful commands for checking the following:
* General deployment information (e.g. deployment name and namespace)
* Storage backend information
* USD Search API service information
* USD Search API service access information
* Couple of useful commands to check pod status
* Clean-up commands configured specifically for the deployment

## Testing

The first installation of deployment may take some time, as all the containers will be pulled from the registry. Subsequent installations, however, will be faster.

In order to verify that deployment is successful and the services are working as expected it is possible to run the following

```bash
helm test <deployment name>
```

For a successful deployment this should print the following to standard output:

```bash
...
TEST SUITE:     <deployment name>-ags-api-verification
Last Started:   Fri Nov  8 12:01:47 2024
Last Completed: Fri Nov  8 12:01:52 2024
Phase:          Succeeded
TEST SUITE:     <deployment name>-database-search-api-verification
Last Started:   Fri Nov  8 12:01:53 2024
Last Completed: Fri Nov  8 12:01:59 2024
Phase:          Succeeded
TEST SUITE:     <deployment name>-s3-storage-check
Last Started:   Fri Nov  8 12:01:59 2024
Last Completed: Fri Nov  8 12:02:10 2024
Phase:          Succeeded
...
```

In case some of these test return a `Failed` status, please refer to the following resources for debugging the deployment:
* [Frequently asked questions](#faq) section
* Kubernetes [application debugging guide](https://kubernetes.io/docs/tasks/debug/debug-application/)

# Uninstall

To uninstall the USD Search API deployment, run the following command:

```bash
helm uninstall <deployment name>
```

## Rendering jobs clean-up

Rendering jobs created during deployment are not automatically removed on helm uninstall and may occupy resources on the cluster. In order to remove them run the following command:

```bash
kubectl delete jobs \
	-l 'app.kubernetes.io/instance=<deployment name>,deepsearch.job-type=rendering' \
	--field-selector status.successful=0
```

This command only removes those jobs are running or failed execution. Successfully terminated jobs do not occupy any resources on the kubernetes cluster and would be automatically removed after 1 hour, so it is not necessary to clean them up. Nevertheless, in some cases it may be preferred to remove those jobs as well, which could be done with the following command:

```bash
kubectl delete jobs \
	-l 'app.kubernetes.io/instance=<deployment name>,deepsearch.job-type=rendering' \
	--field-selector status.successful=1
```

## Secrets and persistent volumes clean-up

Secrets and persistent volume claims (PVCs) are not automatically removed on helm uninstall. They are retained in case the instance needs to be re-created. In some cases it could be desired to remove them as well (e.g. in case a clean install from scratch is desired). The following set of commands could be used to achieve this:

* Secrets:
```bash
kubectl delete secrets $(kubectl get secrets \
	-l 'app.kubernetes.io/instance=<deployment name>' \
	-o custom-columns=":metadata.name" | awk '{print}' ORS=' ')
```

* Persistent volume claims (PVCs):

```bash
kubectl delete pvc $(kubectl get pvc \
	-l 'app.kubernetes.io/instance=<deployment name>' \
	-o custom-columns=":metadata.name" | awk '{print}' ORS=' ')
kubectl delete pvc data-neo4j-0
```

# Experimental

## Sample Explorer WebUI

In order to quickly get started and experiment with USD Search APIs we provide a sample explorer web app that illustrates a way how USD Search APIs could be accessed.

In you order to enable it you need to run the following command to generate WebUI setup configuration:

```bash
echo 'deepsearch_explorer_deployment:
  enabled: true

deepsearch-explorer:
  image:
    registry: docker.io
    repository: bitnamilegacy/nginx
    tag: latest

  initContainers:
    - name: git-clone-and-build
      image: node:18-alpine
      command:
        - /bin/sh
        - -c
      args:
        - |
          apk add --no-cache git
          git clone -b ${GIT_REF} ${GIT_REPO_URL} /source && cd /source && cd ${SUB_PATH}
          npm install && npm ci --production=false && npm run build
          cp -r build/* /app/
      env:
        - name: GIT_REPO_URL
          value: "https://github.com/NVIDIA-Omniverse/usdsearch-client.git"
        - name: GIT_REF
          value: "main"
        - name: SUB_PATH
          value: "./web"
      volumeMounts:
        - name: app-volume
          mountPath: /app

  extraVolumeMounts:
    - name: app-volume
      mountPath: /app
      readOnly: true

  extraVolumes:
    - name: app-volume
      emptyDir:
        medium: Memory' > sample-webui.yaml
```

Then you need to add this configuration to you helm installation command as follows:
```bash
helm install ... -f sample-webui.yaml
```

## Admin tools (beta)

We have added some administrative tools that allow performing different actions with USD Search API. You can find the list of available tools below.

### Re-indexing

Re-indexing allows you to trigger priority processing of the assets on the storage backend:

```bash
kubectl exec -it $(kubectl get pods -l deepsearch.service.name=info-endpoint -o jsonpath='{.items[0].metadata.name}') -- \
    python -m usdsearch.admin.tools reindex <path>
```

By default this would attempt re-indexing those assets from the given path that have non-Ok statuses.

In order to learn about additional configuration options that re-indexing tool supports please refer to its help, which can be accessed as follows:
```bash
kubectl exec -it $(kubectl get pods -l deepsearch.service.name=info-endpoint -o jsonpath='{.items[0].metadata.name}') -- \
    python -m usdsearch.admin.tools reindex --help
```

### Storage backend listing

Storage backend listing allows you to see the content on the certain path on the storage backend. It can be executed as follows:

```bash
kubectl exec -it $(kubectl get pods -l deepsearch.service.name=info-endpoint -o jsonpath='{.items[0].metadata.name}') -- \
    python -m usdsearch.admin.tools ls <path>
```

In order to learn about additional configuration options that re-indexing tool supports please refer to its help, which can be accessed as follows:
```bash
kubectl exec -it $(kubectl get pods -l deepsearch.service.name=info-endpoint -o jsonpath='{.items[0].metadata.name}') -- \
    python -m usdsearch.admin.tools ls --help
```

## Rendering service

Rendering service can be deployed as an alternative to creating rendering jobs on demand. This has the following advantages:
- allows service administrators to better control resource utilization.
- improves rendering throughput as rendering service caches both shader and
  rendering data throughout the lifetime of the rendering service pod.
- no need for RBAC creation as the service is created by helm chart (not by worker pods)

In order to deploy the rendering service, the following additional parameters need to be set:

```bash
  --set rendering_service_deployment.enabled=true \
  --set deepsearch.microservices.rendering_service.enabled=true \
  --set deepsearch.microservices.k8s_renderer.enabled=false \
  --set deepsearch.microservices.plugin_worker.rendering_settings.renderer_type=rendering_service \
  --set deepsearch.rbac.create=false
```

The rendering service can also be hosted externally (e.g. on NVCF) in which case the following parameters need to be set:

```bash
  --set rendering_service_deployment.enabled=false \
  --set deepsearch.microservices.rendering_service.settings.rendering_service_url=<rendering service URL>
```

### Authentication

If the rendering service endpoint is protected with an API key - it can be provided via a kubernetes secret as follows:

```bash
  --set global.secrets.create.rendering_service=true \
  --set deepsearch.microservices.rendering_service.authentication.enabled=true \
  --set deepsearch.microservices.rendering_service.authentication.api_key=<rendering service API key> \
```

alternatively, it is possible to create the secret manually with the following command:

```bash
  kubectl create secret generic rendering-service-api-key-secret \
    --from-literal=api-key=<rendering service API key> \
    --namespace <namespace>
```

and then set the following parameter:

```bash
  --set global.secrets.create.rendering_service=false \
  --set deepsearch.microservices.rendering_service.authentication.enabled=true \
  --set deepsearch.microservices.rendering_service.authentication.api_key_secret_name=rendering-service-api-key-secret \
  --set deepsearch.microservices.rendering_service.authentication.api_key_secret_field=api-key
```

# Advanced configuration

**NOTE**: Changing the settings provided below is typically not required for a standard installation of USD Search. These settings, however, allow customizing the deployment and tuning it for the particular use-case and infrastructure.

Below several additional parameters that allow customizing USD Search service are described. For convenience, instead of providing them all as command line arguments, it is recommended to pass them to the installation command as a configuration file as follows:

```bash
helm install .... -f my-usdsearch-config.yaml
```
where `my-usdsearch-config.yaml` file can have the following additional settings.

## Indexing path filtering

By default USD Search indexes the all the assets that can be found on the server. It is, however, possible to explicitly define which URL patterns should be included in indexing and which should be excluded. The URL definition supports [python regex syntax](https://docs.python.org/3/library/re.html). In order to include / exclude some of the file patterns - it is possible to specify the following in the `my-usdsearch-config.yaml` file:

```yaml
deepsearch-crawler:
  crawler:
    extraConfig:
      include_patterns:
      - <.*regexp of the folder that needs to be included.*>
      exclude_patterns:
      - <.*regexp of the folder that needs to be excluded.*>
```

## Thumbnail indexing settings

Configuration for how the service locates thumbnail files for each asset.

There are two modes for specifying which files are considered thumbnails:

* **Without ``filepath_patterns``** (default) — thumbnails are resolved using
  ``relative_location`` and ``suffixes``. For each asset the service looks
  for files matching:

  ```
  {folder_name}/{relative_location}/256x256/{file_name}{suffix}.png
  ```

  where ``{folder_name}`` and ``{file_name}`` are derived from the original
  asset path, and each value in ``suffixes`` is tried in order. For example,
  the default configuration:

  ```yaml
  thumbnail_settings:
    relative_location: ".thumbs"
    suffixes:
      - ""
      - ".auto"
  ```

  will search for both ``{folder_name}/.thumbs/256x256/{file_name}.png``
  and ``{folder_name}/.thumbs/256x256/{file_name}.auto.png``, and use all
  available thumbnails for indexing.

* **With ``filepath_patterns``** — the service matches thumbnail files against
  the provided list of regex patterns instead. Each pattern may reference
  ``{folder_name}`` and ``{file_name}`` (populated from the original asset
  path at runtime). All patterns are tried and all matching thumbnails are
  used for indexing. For example:

  ```yaml
  thumbnail_settings:
    filepath_patterns:
      # Numbered thumbnails: asset.png1, asset.png2, ...
      - "{folder_name}/\\.thumbs/256x256/{file_name}\\.png(?:\\d+)$"
      # Standard and auto thumbnails: asset.png, asset.auto.png
      - "{folder_name}/\\.thumbs/256x256/{file_name}(\\.auto)?\\.png$"
      # Thumbnails stored in a sibling folder named "previews"
      - "{folder_name}/previews/{file_name}\\.png$"
  ```

The following thumbnail file formats are supported: all formats supported by the [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) and GIF. When a thumbnail is a GIF file, it will be split into multiple frames by sampling every Nth frame (default: every frame), capped at a maximum number of frames (default: ``512``), configurable per plugin via the ``gif_sampling_mode`` (``fixed`` = every Nth frame, or ``uniform`` = ``gif_max_frames`` frames spread evenly across the GIF), ``gif_frame_sample_frequency``, and ``gif_max_frames`` parameters of the ``thumbnail_to_embedding`` and ``thumbnail_to_vision_metadata`` plugins.

__NOTE__: These settings apply only to the **Nucleus** and **S3** storage backends. When using the **Storage API** backend, thumbnails are not resolved from the filesystem. Instead, the thumbnail URL is read directly from the asset metadata. The metadata field (or fields) that hold the thumbnail URL are controlled by the ``global.storage_api.thumbnail_metadata_fields`` setting. Please refer to the [Thumbnail retrieval](#thumbnail-retrieval) section for more information.

## Plugins

USD Search API service is built as a collection of plugins. These plugins are designed to focus on specific task that are outlined below:
* **asset_graph_generation**
		- extracts USD prim structure and metadata from USD assets
	* supports USD asset formats (``.usd``, ``.usda``, ``.usdc``, ``.usdz``)
	* extracts all dependencies of a USD stage and stores it as a graph in Neo4j database
	* extracts asset properties, please refer to [USD properties search](#usd-properties-search) section for more details on how the functionality could be configured for different use-cases.
	* **enabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.asset_graph_generation.active=False
		```


* **image_to_embedding**
		- extracts CLIP embeddings from image data
	* supports all the image file formats supported by [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#) and [.exr file format](https://openexr.com/en/latest/)
	* **enabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.image_to_embedding.active=False
		```


* **image_to_vision_metadata**
		- uses VLM configured in [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section to automatically generate captions and tags from images
	* supports all the image file formats supported by [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#) and [.exr file format](https://openexr.com/en/latest/)
	* requires VLM to be properly configured, please refer to [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section for more information
	* **disabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.image_to_vision_metadata.active=True
		```


* **rendering_to_embedding**
		- renders USD assets from multiple views and extracts CLIP embeddings from these renderings
	* supports USD asset formats (``.usd``, ``.usda``, ``.usdc``, ``.usdz``)
	* **enabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.rendering_to_embedding.active=False
		```


* **rendering_to_vision_metadata**
		- renders USD assets from multiple views and uses VLM configured in [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section to automatically generate captions and tags from renderings of these assets
	* supports USD asset formats (``.usd``, ``.usda``, ``.usdc``, ``.usdz``)
	* requires VLM to be properly configured, please refer to [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section for more information
	* **disabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.rendering_to_vision_metadata.active=True
		```


* **thumbnail_generation**
		- renders USD asset and uploads rendered image to the storage backend to serve as asset thumbnail
	* supports USD asset formats (``.usd``, ``.usda``, ``.usdc``, ``.usdz``)
	* **enabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.thumbnail_generation.active=False
		```


* **thumbnail_to_embedding**
		- extracts CLIP embeddings from thumbnails of assets
	* any asset type is supported, provided this asset has a thumbnail
	* currently thumbnails are expected to be in the Omniverse Nucleus format:
		* the thumbnail images should be found in the ``.thumbs/256x256/`` folder next to the asset.
		* they should have image should have either ``<original asset name>.png`` or ``<original asset name>.auto.png`` name.
	* **enabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.thumbnail_to_embedding.active=False
		```


* **thumbnail_to_vision_metadata**
		- uses VLM configured in [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section to automatically generate captions and tags from thumbnails of assets
	* any asset type is supported, provided this asset has a thumbnail
	* currently thumbnails are expected to be in the Omniverse Nucleus format:
		* the thumbnail images should be found in the ``.thumbs/256x256/`` folder next to the asset.
		* they should have image should have either ``<original asset name>.png`` or ``<original asset name>.auto.png`` name.
	* requires VLM to be properly configured, please refer to [VLM-based automatic captioning and tagging](#vlm-based-automatic-captioning-and-tagging) section for more information
	* **disabled** by default, if not required - could be disabled by providing the following command line argument during helm installation:
		```bash
		  --set deepsearch.plugins.thumbnail_to_vision_metadata.active=True
		```



### Horizontal Pod Autoscaler

Each of the plugins is deployed as a separate k8s deployment that could be horizontally scaled. By default this functionality is disabled to avoid occupying to many resources. In order to enable it, one could add the following to individual plugin configuration.

```yaml
hpa:
  enabled: true
  minReplicas: <desired minimum number of replicas (default 1) >
  maxReplicas: <desired maximum number of replicas (default 1) >
  targetCPUUtilizationPercentage: <desired target CPU utilization (default 80) >
```

for example for ``image_to_embedding`` plugin the configuration can look like this:

```yaml
deepsearch:
  # ...
  plugins:
    # ...
    image_to_embedding:
      hpa:
        enabled: true
        minReplicas: 1
        maxReplicas: 5
        targetCPUUtilizationPercentage: 80
```

### Concurrent processing

Some plugins may rely on external services and do not do a lot of processing themselves. In order to increase throughput it is possible to increase concurrency for each plugin by setting ``n_concurrent_queue_workers`` parameter to the desired value. For those plugins that require USD Asset rendering this value is set to ``256`` by default, others have this parameter set to ``1``.

Adjusting the value of this parameter may increase throughput and can be done as in the following example:

```yaml
deepsearch:
  # ...
  plugins:
    # ...
    thumbnail_to_embedding:
      n_concurrent_queue_workers: 8
```

## Rendering Job configuration

For rendering USD asset USD Search API rely on rendering jobs that are scheduled by Kubernetes on demand. If needed - rendering Job configuration could be adjusted.

### Number of parallel rendering jobs

USD Search relies on kubernetes native scheduling functionality for scheduling rendering jobs depending on the availability of the resources on the kubernetes cluster. In some cases, however, (e.g. when working with Omniverse Nucleus server backend) it could be desired to limit the number of parallel rendering jobs created in order to control the load that is imposed on the storage backend.

To do so, one could use the ``maxRenderingJobsCount`` parameter, which could be provided to the helm installation command via the following command line argument:

```bash
 --set deepsearch.microservices.k8s_renderer.maxRenderingJobsCount=<max number of parallel rendering jobs>
```

or by modifying the ``my-usdsearch-config.yaml`` file as follows:

```yaml
deepsearch:
  microservices:
    k8s_renderer:
      maxRenderingJobsCount: <max number of parallel rendering jobs>
```

If this parameter is left unset - no limit on the number of rendering jobs will be applied.

### Number of parallel rendering workers per rendering job

USD relies on Omniverse Kit for rendering USD assets. By default only one Kit instance is created per GPU (rendering job). It is, however, possible to increase the number of parallel Kit workers that would process assets on a single GPU to improve throughput.

To do so, one could use the ``n_parallel_kit_workers`` parameter, which could be provided to the helm installation command via the following command line argument:

```bash
 --set deepsearch.microservices.k8s_renderer.n_parallel_kit_workers=<number of parallel Kit workers>
```

or by modifying the ``my-usdsearch-config.yaml`` file as follows:

```yaml
deepsearch:
  microservices:
    k8s_renderer:
      n_parallel_kit_workers: <number of parallel Kit workers>
```

### Rendering Job Timeout

By default, the rendering job timeout is set to 1 hour. This can be adjusted by setting the `activeDeadlineSeconds` parameter as follows:

```bash
 --set deepsearch.microservices.k8s_renderer.activeDeadlineSeconds=<max amount of time that is allocated for job execution>
```

or by modifying the ``my-usdsearch-config.yaml`` file as follows:

```yaml
deepsearch:
  microservices:
    k8s_renderer:
      activeDeadlineSeconds: <max amount of time that is allocated for job execution>
```

### Additional configuration settings

#### Annotations

Additional optional annotations of the Rendering Job pod can be configured by setting the `render_job_pod_annotations` parameter as follows:

```bash
 --set deepsearch.microservices.k8s_renderer.render_job_pod_annotations.<annotation name>=<annotation value>
```

or by modifying the ``my-usdsearch-config.yaml`` file as follows:

```yaml
deepsearch:
  microservices:
    k8s_renderer:
      render_job_pod_annotations:
        <annotation name>: <annotation value>
```

If this parameter is left unset - no additional annotations will be applied to the Rendering Job pod.

Please refer to the [Kubernetes documentation](https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/) for more information on how to use annotations

#### Tolerations

Additional optional tolerations of the Rendering Job pod can be configured by modifying the ``my-usdsearch-config.yaml`` file as follows:

```yaml
deepsearch:
  microservices:
    k8s_renderer:
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
```

Please refer to the [Kubernetes documentation](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) for more information on how to use tolerations

### Resources

Resource requests and limits for each individual rendering job could be adjusted by updating the ``resources`` parameter in the  ``deepsearch.microservices.k8s_renderer`` section in ``my-usdsearch-config.yaml`` file. The default settings for resource requests and limits for the job are outlined below:

```yaml
requests:
    memory: "30Gi"
    cpu: "4"
    nvidia.com/gpu: "1"
limits:
    memory: "30Gi"
    cpu: "11"
    nvidia.com/gpu: "1"

```

## Persistence (experimental)

Rendering job is using Omniverse Kit to render USD assets. When doing rendering Omniverse Kit saves some information in cache to make processing more efficient. This information includes shader cache, which takes between 100 and 300 seconds to compute. By default cache it created as a memory volume that is preserved during the lifetime of the job and is removed after it has completed.

In order to optimize processing it is, however, possible to persist this cached information, so that subsequent runs of the job are faster. In order to achieve
this it is required to appropriately configure ``deepsearch.persistence`` section.

For each of these cache locations there are several set-up options that are controlled by setting the type of cache:

<ul>
  <li> <b>emptyDir</b>: creates the cache volume that is available only through out the lifetime of the job. It does not keep cache information during between the runs, which reduces performance as every time shaders need to be re-complied and shader cache re-created. </li>
  <li> <b>pvc</b>: creates PVC to for caching the data, which allows it to be preserved between execution, which in turn improves the speed of sub-sequent rendering runs. When using pvc persistence type it is possible to provide a custom PVC name by setting <em>persistentVolumeClaim.claimName</em> accordingly. Alternatively, it is possible to set <em>pvc.createPvc</em> to <em>true</em> in which case PVC will be automatically created on demand.
    <ul>
       <li> <b>NOTE</b>: In case of a custom PVC setup - it is important to make sure it is set with <em>accessModes: [ReadWriteMany]</em> so that multiple workers are able to access it. Not all storage classes support this setting (e.g. in AWS EFS storage class is required), so it is important to make sure that an appropriate storage class is used. </li>
    </ul>
  <li> <b>hostPath</b>: uses local host storage to store cache information
    <ul>
       <li> <b>NOTE</b>: when using local storage, the target directory <em>hostPath.path</em> has to be manually created on the host machine.
    </ul>
</ul>

**NOTE**: This is an experimental feature. Some functionality may not be supported in case of the heterogenous GPU setup.

## USD properties search

Asset Graph Search (AGS) component allows searching various properties
defined as part of USD files. By default all the properties that are have
the ``semantic:`` prefix are indexed, however it is possible to customize
this behavior as follows:

```yaml
plugins:
  asset_graph_generation:
    indexed_property_prefixes: "<custom_prefix_1>:,<custom_prefix_2>:"
```

Here ``<custom_prefix_1>``, ``<custom_prefix_2>`` are the prefixes of USD
properties that should be indexed. One could provide multiple prefixes
separated by commas.

Alternatively, it is possible to specify the list of property names that
should be indexed as follows:

```yaml
plugins:
  asset_graph_generation:
    indexed_properties: "<property_name1>,<property_name2>,<property_name3>"
```

Here `<property_name1>`,`<property_name2>`,`<property_name3>` is the list
of property names that should be indexed. One could provide multiple
property names separated by commas. If ``indexed_properties`` parameter
remains unset - all the properties with the prefixes defined above are
indexed.

__NOTE__: Only the properties from the default prims inside a USD stage
are indexed and searchable.

### Tuning the kit-worker sidecar

Graph construction runs Kit in a ``kit-worker`` sidecar next to the plugin
worker. The chart adds that container whenever ``requires_kit_worker`` is
set (the default for this plugin), and everything about it — image,
command, resources, memory watchdog, build timeout, caches — is configured
under ``kit_worker``:

```yaml
plugins:
  asset_graph_generation:
    requires_kit_worker: true
    kit_worker:
      resources:
        requests: {cpu: 4, memory: 10Gi}
        limits: {cpu: 8, memory: 20Gi}
      memory_limit_mb: 17000     # soft watchdog, below limits.memory
      timeout_seconds: 3600      # wall clock for one graph build
      client_timeout_margin: 120 # plugin waits this much longer than the builder
      cache:
        enabled: true
        mount_path: /cache
        medium: ""               # "" = node disk, "Memory" = tmpfs
        size_limit: 20Gi         # emptyDir hard limit: exceeding it evicts the pod
        max_size: ""             # cache budget; "" = 75% of size_limit, 0 = off
        cleanup_threshold: 0.8   # evict down to this fraction of max_size
        gc_interval_seconds: 60
      shm_size: 1Gi
      env: []
```

Each value can be set on its own — e.g.
``--set deepsearch.plugins.asset_graph_generation.kit_worker.resources.limits.memory=32Gi``.
That is the reason ``kit_worker`` is a map and not an entry in
``sidecar_containers``: Helm merges maps but replaces lists wholesale, so a
list entry cannot be tuned one field at a time. ``sidecar_containers``
remains available for *additional* sidecars; putting a ``kit-worker`` entry
there while ``requires_kit_worker`` is set is rejected at render time
(it would produce two containers with the same name).

__Out-of-memory kills__ (container exit code 137) are the most common
asset-graph failure. Two things control them:

* ``resources.limits.memory`` — the hard ceiling. A stage that needs more
  than this gets the container killed by the kernel, which takes the
  in-flight request down with it.
* ``memory_limit_mb`` — a soft watchdog *below* that ceiling. The builder
  kills Kit itself when it is crossed and records
  ``graph_construction_oom`` for that one asset, so the failure is
  attributable and the sidecar keeps serving. Recommended: 80-90% of the
  hard limit.

Memory demand also scales with ``n_concurrent_queue_workers``, which
becomes the number of Kit processes sharing the sidecar
(``N_PARALLEL_PROCESSES``) — raise concurrency and memory together.

__Build timeout__: ``timeout_seconds`` bounds a single graph build (default
``1800``). The plugin's HTTP client automatically gets
``timeout_seconds + client_timeout_margin``, so a build that runs long
surfaces as the builder's own timeout — carrying a
``graph_construction_timeout`` status — rather than an opaque client-side
one.

__Asset cache__: builds download USD layers into ``cache.mount_path`` and
reuse them across builds, which roughly halves the time of a warm build.
The client library never evicts from that directory, so the graph builder
does: every ``gc_interval_seconds`` it checks usage and, once it exceeds
``max_size``, removes least-recently-used files down to
``cleanup_threshold`` of it. ``size_limit`` is the kubelet's hard limit on
the volume and evicts the *whole plugin-worker pod*, so ``max_size`` must
stay below it (the chart refuses to render otherwise), leaving headroom for
what builds download between two checks. When raising ``size_limit``, leave
``max_size`` empty and the budget follows.

### Sidecar / package metadata (opt-in)

The graph builder can pick up metadata that ships next to a USD file — a
per-asset ``<stem>.json`` sidecar, or a package-level ``.metadata/*.json``
bundle rooted at a manifest file above it — and merge it into the same
``usd_properties`` bag SimReady custom-layer metadata already lands in. On a
key collision the sidecar value always wins: it is merged in last, after
native USD prim properties and SimReady custom-layer metadata, and later
sources within the catalog itself win over earlier ones. See
``docs/plans/sidecar-package-metadata.md`` for the full design and
``services/asset-graph-builder/graph_builder/sidecar_metadata.py`` for the
implementation.

Unset by default (no-op). Set ``kit_worker.sidecar_metadata_catalog`` to a
full sidecar-metadata YAML document — the same shape as the example SimReady
catalog that ships alongside the module at
``graph_builder/sidecar_metadata.simready.yaml`` (``package_root_max_depth``
+ ``sources: [...]``) — and the chart renders it into a ``ConfigMap``, mounts
it into the ``kit-worker`` sidecar, and points ``SIDECAR_METADATA_CONFIG_PATH``
at it. No custom image required. The example below is that shipped SimReady
catalog verbatim — deliberately minimal, proving the mechanism end-to-end
against ``data/simready_sample/apple_a01_usd_bom`` with a single per-asset
``<stem>.json`` sidecar source. Package-level files — the package manifest,
``root_usds.json``, ``packaging.bom.json``, the conformance report — are
intentionally out of scope here (see the header comment in
``graph_builder/sidecar_metadata.simready.yaml``); a deployment that wants
one adds a ``location: package_root`` source for it using the same
``flatten`` / ``list_membership`` / ``array_match_flatten`` extract kinds,
no code change required:

```yaml
plugins:
  asset_graph_generation:
    kit_worker:
      sidecar_metadata_catalog:
        package_root_max_depth: 6
        sources:
          # Per-asset flat sidecar: <stem>.json next to <stem>.usd, e.g.
          # sm_apple_a01_01.json next to sm_apple_a01_01.usd — author,
          # license, category, qcode, rigid_body_count, asset_extents, mass.
          - name: asset_sidecar
            location: sibling
            filename: "{stem}.json"
            prefix: "sidecar_"
            extract:
              kind: flatten
```

A ``SIDECAR_METADATA_CONFIG_PATH`` set directly under ``kit_worker.env``
still works and takes precedence over the chart-mounted path above (env
entries there are appended after the chart-set ones) — useful for pointing
at a catalog baked into a custom ``asset-graph-builder`` image instead.

## VLM-based automatic captioning and tagging

### LLM/VLM provider

Vision endpoint allows to automatically tag and caption various assets stored on the storage backend using an external Vision Language Model (VLM) service.

For more information about the available USD Search API plugins, please refer to [Plugin Settings section](#plugin-settings).

All LLM/VLM access goes through ONE OpenAI-compatible provider. Set the
endpoint once here (`provider.base_url` -> `USDSEARCH_LLM_BASE_URL`) and the
key via the referenced secret (`provider.api_key` -> `USDSEARCH_LLM_API_KEY`).
Point `base_url` at any OpenAI-API-compatible server. Examples:
  NVIDIA Inference Hub (default): base_url: "https://inference-api.nvidia.com"
  OpenAI:                         base_url: "https://api.openai.com/v1"
  Azure OpenAI:                   base_url: "https://<resource>.openai.azure.com/openai/deployments/<deployment>"
  Self-hosted vLLM / LiteLLM:     base_url: "http://my-vllm.internal:8000/v1"

Example — configure the provider at install time (the api_key lands in the
`usdsearch-llm-api-key-secret` secret created by the chart):

  helm install usdsearch ./helm/usdsearch \
    ... \
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.provider.api_key=<API key> \
    --set deepsearch.vision_endpoint.provider.base_url=<OpenAI-compatible base URL> \
    --set deepsearch.vision_endpoint.metadata_model=<model id>

Default provider settings:

```yaml
api_key: ""
api_key_secret_field: api-key
api_key_secret_name: usdsearch-llm-api-key-secret
base_url: https://inference-api.nvidia.com
env_prefix: USDSEARCH_LLM_
```

### Input budget and cache identity

Request-size limits for VLM metadata generation. A metadata request sends at
most ``max_images`` uniformly sampled views (first and last view always kept),
shrinks each image so neither edge exceeds ``max_px`` pixels (never upscaled),
and keeps the encoded image payload under ``max_request_bytes`` (resolution
is reduced first, views are dropped only if the set still cannot fit).
The limits are deliberately global rather than per plugin: one
monitor-crawler computes the cache identity for every metadata worker, so
all processes must resolve identical settings (``VLM_MAX_IMAGES``,
``VLM_IMAGE_MAX_PX``, ``VLM_MAX_REQUEST_BYTES`` on the workers and crawlers).

``deepsearch.vision_endpoint.metadata_revision`` (``VLM_METADATA_REVISION``)
is an OPTIONAL output-contract revision and is **empty by default**: the
metadata cache identity is then the asset hash alone, exactly as before
these settings existed, so upgrading never reprocesses unchanged assets on
its own and earlier metadata stays searchable next to newer output. Set any
non-empty value (for example ``metadata-v2-png512``) to opt a deployment in:
the revision and the three limits above then join the cache identity, and
changing any of them makes unchanged assets eligible for reprocessing. Bump
the revision after a model, prompt or schema change when the corpus should
be regenerated, and plan the resulting VLM load on a large corpus first.

Default request limits (`metadata_revision` defaults to empty):

```yaml
max_images: 16
max_px: 512
max_request_bytes: 8388608
```

### Customization

It is possible to customize the type of information extracted by the VLM-based auto-captioning system. There are two ways how this can be achieved:

1. By providing a custom image prompt.
2. By providing a custom list of metadata fields.

Each of the above is described in the following sections.

#### Image prompt configuration

Image prompt provided to the VLM-based auto-captioning system is fully
customizable and can be controlled by setting
``deepsearch.vision_endpoint.image_prompt`` parameter in the
``values.yaml`` file. Below is the default configuration for the image
prompt, however it could be adjusted to better fit the needs of the
specific use case.

__NOTE__: there are two fields defined in the prompt: ``{metadata_types}``
and ``{metadata_definitions}``. Those get populated with the respective values
defined in ``deepsearch.vision_endpoint.metadata_fields`` parameter.

```text
You are an indexing engine for USD Search, a 3D-asset search engine used across
robotics & simulation, synthetic data generation, industrial / warehouse /
logistics, autonomous driving, digital twins, and games & film.

You are shown one or more rendered views of a SINGLE 3D asset. Nobody reads your
output: every word you emit is either a keyword-search term or a filter value.
Optimize purely for retrieval — capture EVERY distinctive term a real user might
type to find exactly this asset. Imagine a robotics engineer, an SDG pipeline, a
warehouse digital-twin team, and a game artist all searching for it, and cover
the terms each of them would use. Distinctive breadth, zero filler.

## How to analyze
1. The images are multiple views of the same asset. Aggregate evidence across ALL
   views: a part occluded in one view may be clear in another; text may be legible
   in only one view. Report what at least one view clearly shows; reconcile
   contradictions in favor of the clearer view.
2. Identify the object as specifically as possible (not "vehicle" but "counterbalance forklift").
3. Note its clearly visible parts, function, materials, dominant colors,
   real-world scale, condition, and mechanical traits.
4. Transcribe visible text ONLY if every character is clearly legible in some view.
5. Brainstorm the keywords, synonyms, part names, and domain terms each kind of
   user would type to find it.

## Output format (JSON object with exactly these fields)
{metadata_types}

## Field definitions
{metadata_definitions}

## Rules
- Output ONLY a valid JSON object with every field above — no prose, no markdown.
- The renders are low resolution. Describe only what you can clearly resolve:
  prefer omission over inference. Never invent brands, text, part details, or
  function; never reconstruct partially legible text or infer branding from a
  logo shape or color scheme.
- When a field can't be determined: use null for category, style, scale, and
  state (never force a wrong value); "unknown" for object_type; and an empty
  list `[]` for environment, colors, materials, physical_attributes, and
  visible_text. Do not guess. caption, queries, and tags must ALWAYS describe
  what IS visible, at whatever specificity the renders support (for a bare
  primitive: "gray box-shaped object", tags like cube, box, gray).
- Every list is ordered most→least relevant.
- Be specific over generic. Never emit filler that matches almost every asset:
  "3d model", "asset", "object", "mesh", "render", or near-universal phrases.
- Use lowercase for queries, tags, object_type, environment, colors, materials,
  physical_attributes (captions and verbatim visible_text keep natural casing).
- Fields with allowed lists (style, scale, state, physical_attributes items —
  and category where the deployment defines a list) take values ONLY from
  those lists, verbatim; null beats a wrong pick.
- Queries and tags are the most important fields: phrase them exactly the way
  real users search — thorough, with synonyms, part names, and domain terms.

```

#### Metadata fields configuration

Configuration of metadata fields extracted by the VLM-based auto-captioning
system, controlled by the ``deepsearch.vision_endpoint.metadata_fields``
parameter. The default mirrors the schema shipped with the package
(``packages/llm-client/llm_client/metadata/metadata_fields.yaml``); edit it
per deployment as needed. Below is the default configuration:

```yaml
- description: |
    A concise, specific title (5-12 words) naming the object precisely. Format: "[distinguishing adjectives] [specific object name]". Examples: "Counterbalance warehouse forklift", "Galvanized steel pallet rack", "Articulated 6-axis industrial robot arm", "Weathered red shipping container", "Ergonomic mesh office chair", "Stainless commercial kitchen prep table".
  name: caption
  type: str
- description: |
    The single most specific common noun for the object (lowercase), e.g. "forklift", "pallet rack", "conveyor belt", "office chair", "fire extinguisher", "traffic cone", "robot gripper", "cardboard box", "transformer", "hand drill". Prefer the precise term over a generic one ("sectional sofa", not "furniture").
  name: object_type
  type: str
- description: |
    Short search phrases a person would actually type into a search box to find this asset — aim for 5-10 (at least 3 required; even a bare primitive supports shape/color phrases like "gray cube"), lowercase, ordered most generic first. Start with the plain object name, then common synonyms, then the few most distinctive qualified phrasings: "forklift", "fork truck", "warehouse forklift", "yellow counterbalance forklift". Each phrase 1-4 words, written the way users search — no full sentences, no catalog or engineering jargon, and no generic filler ("3d model", "asset", "object", "prop"). These phrases are matched directly by keyword search.
  max_items: 10
  min_items: 3
  name: queries
  type: list[str]
- description: |
    Lowercase keywords a user might actually search, ordered most→least relevant — aim for 8-15 (at least 3 required). Cover: the object name + synonyms (forklift, lift truck, fork truck); specific type/variant (counterbalance, reach truck, pallet jack); clearly visible parts and part-level features (forks, mast, overhead guard, cab, hydraulics); brand or model text ONLY if clearly legible; and domain/industry terms (warehouse, logistics, material handling). Be thorough, include synonyms, and use the words users type — not catalog or engineering jargon. Never pad with generic filler ("3d model", "asset", "object", "mesh", "prop") or attributes you cannot clearly see; for bare primitives and abstract assets, shape and color terms (cube, box, sphere, gray) count as valid tags.
  max_items: 15
  min_items: 3
  name: tags
  type: list[str]
- description: |
    Typical real-world settings where this asset is found (lowercase, 0-5), e.g. "warehouse", "factory floor", "loading dock", "office", "retail store", "hospital", "kitchen", "construction site", "outdoor", "urban street", "residential interior", "laboratory".
  max_items: 5
  name: environment
  type: list[str]
- description: |
    Dominant colors, most→least prominent (max 5). Simple searchable names: red, orange, yellow, green, blue, purple, pink, brown, black, white, gray, beige, gold, silver. Add a modifier only when distinctive (dark_gray, safety_yellow).
  max_items: 5
  name: colors
  type: list[str]
- description: |
    Apparent materials, primary→secondary (max 5). Common terms: steel, aluminum, metal, wood, plastic, glass, fabric, leather, rubber, concrete, stone, ceramic, cardboard, paper, foam, carbon_fiber, chrome, brass, composite. Only materials you can clearly identify at this resolution — when unsure between specific metals, say "metal".
  max_items: 5
  name: materials
  type: list[str]
- allowed_values:
    - realistic
    - stylized
    - low_poly
    - cad
    - scanned
  description: |
    The dominant REPRESENTATION style — how the asset is rendered/authored, not its design aesthetic (aesthetic terms like "industrial", "modern", "vintage" belong in tags). realistic covers photorealistic. Choose exactly ONE from the allowed list; use null if truly undeterminable.
  name: style
  nullable: true
  type: str
- allowed_values:
    - tiny
    - small
    - medium
    - large
    - huge
  description: |
    Approximate real-world size class. Choose exactly ONE: tiny (fits in a hand), small (desktop), medium (human-scale / furniture), large (vehicle / machine), huge (building / structure); use null if the size cannot be judged.
  name: scale
  nullable: true
  type: str
- allowed_values:
    - new
    - used
    - worn
    - damaged
  description: |
    Apparent condition. Choose exactly ONE — new (clean / like-new), used (visibly in service), worn (heavy wear, weathering, or dirt), damaged (broken or missing parts); use null if condition cannot be judged.
  name: state
  nullable: true
  type: str
- allowed_values:
    - articulated
    - has_moving_parts
    - wheeled
    - deformable
    - stackable
    - graspable
    - openable
    - foldable
    - transparent
    - emissive
    - reflective
    - mounted
    - modular
  description: |
    Functional / mechanical traits relevant to simulation and robotics (lowercase, 0-6), only from the allowed list. Rigid is the default — tag only what deviates from a plain static rigid object, and only traits clearly evident in the views.
  max_items: 6
  name: physical_attributes
  type: list[str]
- description: |
    Text on the asset that is CLEARLY LEGIBLE at the provided resolution (verbatim, 0-6 short strings): labels, brand names, model numbers, signage, warnings. If you cannot read every character of a string, omit it entirely — never reconstruct partial text or infer branding from a logo shape or color scheme. Empty list if none. Legible text is a strong, unique search signal (e.g. brand, "EXIT", load ratings, hazard labels); invented text is the worst kind of index pollution.
  max_items: 6
  name: visible_text
  type: list[str]
```

## VLM-based verification of results with respect to input query

VLM validation uses a Vision Language Model to verify that each search
result visually matches the input query. It compares the query against
the result's thumbnail and returns a match decision with confidence
score and reasoning.

Defaults are filter mode, 50 concurrent provider calls per API
process, and one asset view per verdict.

To enable validation of search results, set the following parameter to true:
```bash
    --set ngsearch.microservices.search_rest_api.validation.enabled=true
```

or specify `ngsearch.microservices.search_rest_api.validation.enabled` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      validation:
        enabled: true
```

To set the maximum number of concurrent requests to the VLM service, set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.validation.max_concurrent_requests=<number of concurrent requests>
```

or specify `ngsearch.microservices.search_rest_api.validation.max_concurrent_requests` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      validation:
        max_concurrent_requests: <number of concurrent requests>
```

Against a self-hosted vLLM engine set `max_tries: 2`: the engine closes an
idle keep-alive connection after 5 s, and a verdict burst that starts
about 5 s after the previous one can reuse a connection the server is
closing; with a single try that transient error fails the whole
validated request with a 503 (measured on 3 of 10 requests), with two
tries it is one backoff retry.

`image_max_px` caps the longest edge of every image sent to the VLM. The
default 0 sends the stored 1024-px thumbnail as is; `image_max_px: 448`
sends the evaluated 448-px view at about a quarter of the prompt tokens
per verdict, and changes the verdict cache identity.

`image_format: jpeg` sends those images as JPEG (quality 90) instead of
PNG: 55-85 % less image-encoding CPU per verdict at 448 px and a fraction of the upload.
It also changes the verdict cache identity.

`image_cache.dir` keeps each asset view prepared once (decoded, fitted to
`image_max_px`, re-encoded) on a disk volume the chart mounts there,
instead of once per check: byte-identical, on by default and bounded
by `image_cache.max_mb` and `image_cache.min_free_mb`.

### Prepared-view cache

Prepared asset views kept across checks
(-> USDSEARCH_VISION_VALIDATION_IMAGE_CACHE_*). Before each check the
API decodes the asset's stored thumbnail, fits it to image_max_px and
re-encodes it, most of a check's API CPU; with the cache that is done
once per stored image. Kept views are byte-identical to preparing them
per check and are not part of the verdict cache identity. On by
default: the chart mounts the `validationImageCacheDir` volume at
`dir` (by default an emptyDir of `max_mb` + 25 % + 512 MiB, counted
in the API's `resources` ephemeral-storage), so it works with a
read-only root filesystem. Set `dir: ""` to turn it off. Give it a
directory of its own (other settings' directories in it are
removed). The views stay under `max_mb`, the cache never writes below
`min_free_mb` free on the disk, and nothing is evicted: past either,
views are prepared per check. `memory_mb` adds a per-process
in-memory LRU, in front of `dir` or alone (0 = off). The cache fills
as checks run; to fill it up front, run
`nice -n 10 python -m deepsearch_api.validation.warm_image_cache` in
each replica after it starts; it stops when the cache is full.

Default `ngsearch.microservices.search_rest_api.validation.image_cache`:

```yaml
dir: /var/tmp/usdsearch-validation-images
max_mb: 2048
min_free_mb: 1024
memory_mb: 0
```

Volume backing `validation.image_cache.dir`, mounted there unless that
is `""`. Empty (the default) is a disk-backed emptyDir sized from
`validation.image_cache.max_mb` (`max_mb` + 25 % + 512 MiB: 3 GiB at the
default 2048), which lasts as long as the pod. Set it to any pod volume
source to use another volume, for example a persistentVolumeClaim that
keeps the views across restarts; make it larger than that size:
```yaml
validationImageCacheDir:
  persistentVolumeClaim:
    claimName: usdsearch-validation-images
```

Default `ngsearch.microservices.search_rest_api.validationImageCacheDir`: `{}`.

### LLM/VLM provider

Per-result VLM validation runs on the same shared OpenAI-compatible
provider (`provider.api_key` -> `USDSEARCH_LLM_API_KEY`, `provider.base_url`
-> `USDSEARCH_LLM_BASE_URL`). The stack ships pointed at a default endpoint
(NVIDIA Inference Hub); point `base_url` at any OpenAI-API-compatible server
to use a different one.

Example — enable validation and configure the provider at install time:

  helm install usdsearch ./helm/usdsearch \
    ... \
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.enabled=true \
    --set ngsearch.microservices.search_rest_api.validation.provider.api_key=<API key> \
    --set ngsearch.microservices.search_rest_api.validation.provider.base_url=<Base URL> \
    --set ngsearch.microservices.search_rest_api.validation.model=<model id>

Default provider settings:

```yaml
api_key: ""
api_key_secret_field: api-key
api_key_secret_name: usdsearch-llm-api-key-secret
base_url: https://inference-api.nvidia.com
env_prefix: USDSEARCH_LLM_
```

## Search Backend configuration

By default an instance of OpenSearch is deployed as part of the USD Search API
helm chart. The following parameters can be set to configure the search backend:
 * ``index_name`` - name of the search index prefix (default: ``my-usdsearch-instance-index``). In practice there will be 2 indexes created in the Search Backend (OpenSearch):
   * ``<index_name>-ver5.0`` - stores embedding data and is the main index, where search is being executed
   * ``<index_name>-ver4.0-image-cache`` - non-indexed data storage for assets' renderings.
 * ``number_of_shards`` - number of shards of search indices (default: ``3``). Please refer to [OpenSearch documentation](https://opensearch.org/blog/optimize-opensearch-index-shard-size/) for more information about the number of shards selection.

   __NOTE__: The ``number_of_shards`` value can only be set during the first installation of the USD Search API helm chart. If the index is already created on the OpenSearch instance - changing this parameter in the helm chart would have no effect. In order to modify this parameter after installation, you need to create a new OpenSearch index with the correct amount of shards and apply re-indexing as described in [OpenSearch documentation](https://opensearch.org/blog/optimize-opensearch-index-shard-size/).

### External OpenSearch instance

If you wish to rely on your own instance of OpenSearch (external to the USD Search API helm chart), you can do the following:
* disable creation of the default OpenSearch instance by setting the following command line argument during helm chart deployment:
```bash
  --set opensearch_deployment.enabled=false
```

* set the following parameters, all of them under ``global.search_backend_config``:
  * ``host`` - hostname of the OpenSearch instance, without a scheme or port (default: ``deepsearch-opensearch-cluster-master``)
  * ``port`` - port of the OpenSearch instance (default: ``9200``; managed services usually listen on ``443``)
  * ``schema`` - scheme used to build the OpenSearch URL (default: ``http``)
  * ``use_ssl`` - whether to connect over TLS (default: ``false``); set it together with ``schema: https``
  * ``auth_secret_name`` - name of the secret that stores the authentication information for the OpenSearch instance. Please refer to [OpenSearch authentication](#opensearch-authentication) section for more information.
  * ``hosts`` - comma-separated list of additional OpenSearch instances to use for search (default: ``[]``)
  * ``http_compress`` - gzip request bodies (default: ``false``); leave it off unless nothing between the services and the cluster rewrites them

The cluster must provide the k-NN plugin, because the main index is created with ``index.knn`` enabled and queried with ``knn``
clauses, and the credentials must be able to create and manage indexes matching ``<index_name>-*`` and read and write their
documents. Only HTTP basic authentication is supported: requests are not SigV4-signed, so AWS IAM access alone does not work.
On Amazon OpenSearch Service, use the domain endpoint as ``host`` with ``port: 443``, ``schema: https`` and ``use_ssl: true``,
and enable fine-grained access control, then map a dedicated user holding those privileges into the secret above; the
domain's master user grants administrative access well beyond these indexes. Where
``index.knn.derived_source.enabled`` defaults to on, vectors are rebuilt from the k-NN index instead of ``_source``; the
services warn when they find it on the main index.

### OpenSearch authentication

In order to authenticate with OpenSearch cluster a kubernetes secret that stores a subset of the following parameters can be created:
 * username
 * password

The name of the secret can be specified by providing the following command line argument during helm chart deployment:
```bash
  --set global.search_backend_config.auth_secret_name=<secret-name>
```
Please refer to [OpenSearch authentication](https://docs.opensearch.org/docs/latest/security/authentication-backends/authc-index/) for more information about different authentication possibilities within OpenSearch. If any of these parameters are not required for the chosen authentication method, they don't need to be set within a secret.

__NOTE__: By default there is no authentication enabled on the test OpenSearch instance that can be deployed with the USD Search API helm chart. Therefore, when using the test installation a secret with these parameters does not need to be created and the following variable can be left unchanged. Authentication on the test OpenSearch instance can be enabled if one needs it, as the test OpenSearch endpoint is exposed on the internal k8s network, so if there are other services running in the cluster they can also access it.

## OTEL Telemetry and Traces collection

### Trace collection

By default trace collection is disabled. Is it optionally possible to enable
trace collection for USD Search REST API and AGS
services. In order to do so, please set `OTEL_SDK_DISABLED` to "false" and `OTEL_TRACES_EXPORTER` to "true" and provide a valid `OTEL_EXPORTER_OTLP_ENDPOINT` URL as follows:

```bash
  --set global.tracing.OTEL_SDK_DISABLED=false \
  --set global.tracing.OTEL_TRACES_EXPORTER=true \
  --set global.tracing.OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318
```

### Search and asset-load telemetry collection

Search service has the possibility to gather telemetry information about
searches executed by the users of the system, and about the assets they
download. This information can then be used to understand what queries are
most frequently executed, which assets are being loaded, and also allow to
track down issues if inconsistency appears in the search results.

Search telemetry information includes:

 * Overall duration of request processing
 * Time spent waiting for response from the Search backend
 * Parsed version of the input query that is then converted to a request to
   OpenSearch service

Asset-load telemetry (one event per `/download/asset` request) includes:

 * The URL of the asset that was requested
 * Whether the call actually downloaded data or only previewed the bundle size
 * Bundle contents — file count, total bytes, and what was skipped or failed
 * A timing breakdown: dependency resolution, size check, collection, and the
   overall request duration

See [`docs/asset-download.md`](../../docs/asset-download.md) for the full
field list and how to read it.

__NOTE__: both event types record the identity of the caller — the username
from the bearer token, basic-auth credentials, or API key, or `anonymous`
when the request carries none. If you do not want user identities in your
logs, leave telemetry switched off (`use_search_telemetry=false`, the
default); there is no separate setting for the username field.

By default telemetry logging is switched off.  In order to enable telemetry collection, please set the following command line parameters during helm chart deployment:
```bash
    --set global.tracing.OTEL_SDK_DISABLED=false \
    --set ngsearch.microservices.search_rest_api.use_search_telemetry=true \
    --set ngsearch.microservices.search_rest_api.search_telemetry_stdout=true
```
You will then be able to see telemetry information being printed in the logs of the REST API service.

__NOTE__: telemetry never leaves the cluster USD Search runs in. Each event
is written as a line to the REST API container's log stream and nothing else
— the service does not send it to NVIDIA or to any other external
destination, and the chart deploys no component that would. Until you
collect those logs the events live only as long as the container's log
buffer does, and they are lost on restart or rotation.

Retaining or analysing them is therefore your responsibility: point
whichever log collector your cluster already runs (Fluent Bit, Fluentd,
Vector, Promtail, and so on) at the REST API pods, and forward the records
to your own destination. That collector is configured separately and is not
part of this chart. Events are emitted as single-line JSON, so most
collectors can parse them without a custom rule.

## Values

For convenience, configurable values of this Helm Chart are outlined in the sections below.

### Global settings
<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.accept_eula</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td>

Set the following to true to indicate your acceptance of EULA.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.appVersion</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"1.5.1"
</pre>
</div>
			</td>
			<td>

Default tag for the unified container images defined in ``global.image``.
Defaults to the latest published image set so local installs pull real
tags from NGC. CI overrides this at chart-package time from the latest
``images-X.Y.Z`` tag (same value as the chart ``appVersion``). Per-image
``global.image.<name>.tag`` overrides take precedence; this field is the
shared fallback so all three unified images track the same release by
default.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.dnsConfig</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
searches: []

</pre>
</div>
			</td>
			<td>

Additional optional DNS configuration parameters can be passed using the
following parameter:</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.embedding_deployment</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
endpoint: ""
triton_server:
    ssl:
        enabled: false
    headers: {}
authentication:
    enabled: false
    token:
    secret_key: token
    secret_name: embedding-service-secret

</pre>
</div>
			</td>
			<td>

Embedding service instance is deployed with USD Search API Helm
chart by default. It can be disabled, but in that case an alternative
endpoint must be provided.
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.enable_structured_logging</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td> Enable structured logging that could then be collected from container standard output and forward to any system for keeping log data </td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.image</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
pullPolicy: IfNotPresent
usdsearch:
    repository: usdsearch
    tag: ""
siglip2_triton:
    repository: siglip2-triton
    tag: ""
rendering_job:
    repository: usdsearch-kit-workflows
    tag: ""
graph_builder:
    repository: usdsearch-graph-builder
    tag: ""

</pre>
</div>
			</td>
			<td>

Unified container images for the USD Search stack. Every Helm-deployed pod
runs one of three images published from this repo on each `images-X.Y.Z`
tag at ``{{ global.registry }}/<repository>:<tag>``:

 * ``usdsearch`` — combined Python image (deepsearch-api, info-endpoint,
   monitor / plugin workers, asset-graph-service, deepsearch-crawler,
   ngsearch indexers, ...).
 * ``siglip2_triton`` — Triton Inference Server with the SigLIP2 ONNX
   model bundled.
 * ``rendering_job`` — GPU-accelerated Omniverse Kit image. Reused for the
   asset-graph-builder sidecar via ``MODE=graph-builder``.

The ``tag`` defaults to the chart ``appVersion`` (set on each
``images-X.Y.Z`` release). Per-service ``image.{name,tag}`` values still
take precedence when set, so existing overrides keep working.
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.imagePullSecrets</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
null
</pre>
</div>
			</td>
			<td>

Kubernetes secret that stores authentication information for pulling images
from the registry.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.ngcAPIKey</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
null
</pre>
</div>
			</td>
			<td>

It is possible to provide NGC API Key on the first deployment of the helm
chart, such that the appropriate docker registry pull secret is created.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.ngcAPIKeySecretName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"ngc-api"
</pre>
</div>
			</td>
			<td>

It is possible to provide NGC API Key on the first deployment of the helm
chart, such that the appropriate docker registry pull secret is created.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.ngcImagePullSecretName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"nvcr.io"
</pre>
</div>
			</td>
			<td>

As an alternative to the ``imagePullSecrets`` field, it is possible to
provide the name for the docker container secret.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.nodeIP</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td>

Please specify (preferably) the hostname or the IP of the Kubernetes
cluster node, where USD Search API helm chart is running. This address will
be used for service registration when using NodePort services.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.omniverse_discovery</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: false

</pre>
</div>
			</td>
			<td>

Register the USD Search REST APIs with an Omniverse Discovery Service
(auto-discovery-service 1.3.0 or later).

When enabled, the API gateway:
  * serves the Capabilities REST API ``GET /v1beta/services``, listing every
    public USD Search API as ``usdsearch.<api>`` version ``v1`` at the gateway
    route prefix it is served under (for example ``usdsearch.search_hybrid`` →
    ``/search_hybrid``, ``usdsearch.asset_graph.prims`` →
    ``/asset_graph/usd/prims``);
  * annotates its Service with ``discovery.omniverse.nvidia.com/enabled: "true"``
    so a Discovery Service watching this namespace picks it up;
  * adds ``discovery.omniverse.nvidia.com/base-path`` to the HTTPProxy when
    ``httpProxy.path`` is not ``/``, so the external catalog URL carries the prefix.

The Discovery Service must watch this release's namespace (its
``config.kubeNamespace``). Clients find the APIs by endpoint name: the catalog
entry itself is named after the gateway Service (``<release>-api-gateway``).

Toggling this value restarts the gateway. Other changes to its routes on an
existing release, such as ``asset_graph_service_deployment.enabled``, do not:
run ``kubectl rollout restart deployment/<release>-api-gateway`` so it
serves, and advertises, the new routes.
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.registry</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"nvcr.io/nvidia/usdsearch"
</pre>
</div>
			</td>
			<td>

Container Registry root URL</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.secrets</div></td>
			<td><div style="white-space: nowrap;">
object
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "annotations": {
    "helm.sh/hook": "pre-install,pre-upgrade",
    "helm.sh/hook-weight": "-5",
    "helm.sh/resource-policy": "keep"
  },
  "create": {
    "auth": false,
    "embedding": false,
    "explorer_ui": false,
    "ngc_api": false,
    "registry": false,
    "rendering_service": false,
    "vlm": false
  }
}
</pre>
</div>
			</td>
			<td>

Auto-generated secrets configuration. By setting the respective field in the
``create`` section to ``true`` it is possible to create authentication and
container registry secrets on helm chart deployment.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.storage_backend_type</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"s3"
</pre>
</div>
			</td>
			<td>

Set the desired storage backend type. Supported options are the following:

 * s3 - AWS S3 bucket storage
 * nucleus - Omniverse Nucleus Server
 * storage_api - Omniverse Storage API (beta functionality). Please refer to [Omniverse Storage API](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/omniverse/collections/storage_apis) for more information.
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">global.url_mapping</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "encode_public_paths": false,
  "inbound_only": false,
  "mode": "off",
  "rules": []
}
</pre>
</div>
			</td>
			<td>

Public asset URLs. By default the API speaks the same URLs the crawler
indexed (e.g. `s3://bucket/key`). Set this to publish a different form —
typically `https://` for an S3-backed deployment — while everything
internally (the search index, the asset graph, storage access) keeps using
the original one.

Modes:

 * `off` (default) — no translation; responses are byte-identical to before.
 * `s3_https` — derive the mapping from the configured S3 bucket, i.e.
   `s3://<bucket>/` becomes `https://<bucket>.s3.<region>.amazonaws.com/`
   (or `<aws_endpoint_url>/<bucket>/` for a custom endpoint). No rules to write.
 * `rules` — spell the prefixes out yourself, for a CDN, a Nucleus web
   gateway, or several storage roots:

```yaml
  url_mapping:
    mode: rules
    rules:
      - internal: "s3://my-assets/"
        public: "https://assets.example.com/"
      - internal: "omniverse://nucleus.internal/"
        public: "https://viewer.example.com/omni/"
```

Requests accept **either** form at all times, so clients holding previously
returned `s3://` URLs keep working. Set `inbound_only: true` to accept the
public form without emitting it yet (useful when rolling the change out).

__NOTE__: this changes how an asset is *addressed*, not who may read it. A
published `https://` URL for a private bucket is not fetchable without
credentials — signing such links is the client application's job. Use
`GET /download/asset` to retrieve bytes through the API.

A rule set whose reverse mapping would be ambiguous (overlapping prefixes) is
rejected at startup rather than applied half-way.

An internal URL's path is a raw storage key and may hold characters that are
not legal in an `https://` path — a space, most often. Incoming URLs are
always percent-decoded, so the correctly escaped form resolves. Set
`encode_public_paths: true` to *emit* the escaped form as well; it is opt-in
because it changes the exact URL string published for those assets.
</td>
		</tr>
</table>

## Embedding service settings

The following parameters describe embedding service configuration settings:

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.affinity</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{}
</pre>
</div>
			</td>
			<td>  Embedding service affinity.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.replicas</div></td>
			<td><div style="white-space: nowrap;">
int
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
1
</pre>
</div>
			</td>
			<td>  Number of replicas of the embedding service.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.resources</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
requests:
    nvidia.com/gpu: 1
    cpu: 2
    memory: 7Gi
limits:
    nvidia.com/gpu: 1
    cpu: 4
    memory: 15Gi

</pre>
</div>
			</td>
			<td>

Resources that are allocated for embedding deployment

__NOTE__: Embedding service could rely on either CPU or GPU. Using GPU, however, significantly speeds up inference.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.runtimeClassName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td>  Optional RuntimeClass for the embedding pod. Empty (default) leaves the field unset, so the cluster's default RuntimeClass applies. Set it (e.g. `nvidia`) to force a specific GPU RuntimeClass when multiple are defined on the cluster (`kubectl get runtimeclass`).</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.tmpDir</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
emptyDir:
    medium: Memory
    sizeLimit: 256Mi

</pre>
</div>
			</td>
			<td>

Configuration of the temporary directory for the service. By default, it is
set to use Memory medium.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.embedding.tolerations</div></td>
			<td><div style="white-space: nowrap;">
tpl/array
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
[]
</pre>
</div>
			</td>
			<td>  Embedding service tolerations.</td>
		</tr>
	</tbody>
</table>

## Asset Graph Service additional settings

The following parameters allow configuring the Asset Graph Search (AGS) deployment:

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">asset-graph-service.graphdb.n_workers</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
5
</pre>
</div>
			</td>
			<td>

Number of parallel workers that would be writing data to Neo4j.
Increasing this number results in faster processing, but will in turn
require scaling the Neo4j instance.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">asset-graph-service.graphdb.textIndexProperties</div></td>
			<td><div style="white-space: nowrap;">
list
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
[]
</pre>
</div>
			</td>
			<td>

Prim property names (e.g. ``semantic:labels:class``) that also get a
Neo4j TEXT index, which speeds up substring (``CONTAINS``) queries. AGS's
own filters never use TEXT indexes, and keeping them up to date slows
every asset write (badly so on NFS-backed Neo4j storage), so the default
is none. At startup AGS creates the listed indexes and drops every other
per-property TEXT index.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">asset-graph-service.sentry_dsn</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td>  Sentry Data Source Name. By default this field is unset, however it is possible to configure it to an appropriate DSN value to be able to collect events that are associated with the AGS deployment.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">asset_graph_service_deployment.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
true
</pre>
</div>
			</td>
			<td>  trigger to enable Asset Graph Service (AGS) helm chart deployment</td>
		</tr>
	</tbody>
</table>

## Other settings

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">api_gateway_deployment.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
true
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">asset_graph_service_deployment.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
true
</pre>
</div>
			</td>
			<td>  trigger to enable Asset Graph Service (AGS) helm chart deployment</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch-crawler.resources</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
requests:
    cpu: 1
    memory: 10Gi
limits:
    cpu: 1
    memory: 10Gi

</pre>
</div>
			</td>
			<td>

Default USD Search Crawler resource requests and limits</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.monitor</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "replicas": 1
}
</pre>
</div>
			</td>
			<td>

Configuration of the Monitor service that runs in the
background and indexes data on the storage backend
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.microservices.omni_writer</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
replicas: 1

</pre>
</div>
			</td>
			<td>

Configuration of the Writer service</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deepsearch.thumbnail_settings</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
relative_location: ".thumbs"
suffixes:
    - ""
    - ".auto"
filepath_patterns:

</pre>
</div>
			</td>
			<td>

Configuration for how the service locates thumbnail files for each asset.

There are two modes for specifying which files are considered thumbnails:

* **Without ``filepath_patterns``** (default) — thumbnails are resolved using
  ``relative_location`` and ``suffixes``. For each asset the service looks
  for files matching:

  ```
  {folder_name}/{relative_location}/256x256/{file_name}{suffix}.png
  ```

  where ``{folder_name}`` and ``{file_name}`` are derived from the original
  asset path, and each value in ``suffixes`` is tried in order. For example,
  the default configuration:

  ```yaml
  thumbnail_settings:
    relative_location: ".thumbs"
    suffixes:
      - ""
      - ".auto"
  ```

  will search for both ``{folder_name}/.thumbs/256x256/{file_name}.png``
  and ``{folder_name}/.thumbs/256x256/{file_name}.auto.png``, and use all
  available thumbnails for indexing.

* **With ``filepath_patterns``** — the service matches thumbnail files against
  the provided list of regex patterns instead. Each pattern may reference
  ``{folder_name}`` and ``{file_name}`` (populated from the original asset
  path at runtime). All patterns are tried and all matching thumbnails are
  used for indexing. For example:

  ```yaml
  thumbnail_settings:
    filepath_patterns:
      # Numbered thumbnails: asset.png1, asset.png2, ...
      - "{folder_name}/\\.thumbs/256x256/{file_name}\\.png(?:\\d+)$"
      # Standard and auto thumbnails: asset.png, asset.auto.png
      - "{folder_name}/\\.thumbs/256x256/{file_name}(\\.auto)?\\.png$"
      # Thumbnails stored in a sibling folder named "previews"
      - "{folder_name}/previews/{file_name}\\.png$"
  ```

The following thumbnail file formats are supported: all formats supported by the [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) and GIF. When a thumbnail is a GIF file, it will be split into multiple frames by sampling every Nth frame (default: every frame), capped at a maximum number of frames (default: ``512``), configurable per plugin via the ``gif_sampling_mode`` (``fixed`` = every Nth frame, or ``uniform`` = ``gif_max_frames`` frames spread evenly across the GIF), ``gif_frame_sample_frequency``, and ``gif_max_frames`` parameters of the ``thumbnail_to_embedding`` and ``thumbnail_to_vision_metadata`` plugins.

__NOTE__: These settings apply only to the **Nucleus** and **S3** storage backends. When using the **Storage API** backend, thumbnails are not resolved from the filesystem. Instead, the thumbnail URL is read directly from the asset metadata. The metadata field (or fields) that hold the thumbnail URL are controlled by the ``global.storage_api.thumbnail_metadata_fields`` setting. Please refer to the [Thumbnail retrieval](#thumbnail-retrieval) section for more information.
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">deployPrometheusRules</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td>

PrometheusRule alerts for the indexing pipeline (items dropped from a stream
after exhausting their retries, and a stream whose oldest unacknowledged entry
blocks trimming) can be deployed as part of this helm chart.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">maintenance</div></td>
			<td><div style="white-space: nowrap;">
yaml
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enable: false

</pre>
</div>
			</td>
			<td>

Maintenance mode disables all background indexing services while keeping the
API and databases operational.

This mode is useful when you want to perform maintenance on the system (e.g.
resizing / clean-up of redis, opensearch, etc.)
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.indexing</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "replicas": 1
}
</pre>
</div>
			</td>
			<td>

Storage backend indexing configuration
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.search_rest_api.default_search_size</div></td>
			<td><div style="white-space: nowrap;">
int
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
64
</pre>
</div>
			</td>
			<td>

Number of search results that are returned by the NGSearch Search Service by
default, when using non-paginated search functionality. This value can be
overridden from the input search query using the ``max`` prefix.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.search_rest_api.enable_access_verification</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
true
</pre>
</div>
			</td>
			<td>

In order to verify that client application has access to view certain assets
all search results are verified with the Storage backend. While this functionality
is crucial for Omniverse Nucleus servers with fine-grained access. It may
not be required for AWS S3 bucket or in the cases when all users have
access to all the assets on the storage backend. In that case it is
possible to switch off this functionality by setting the following parameter
to false, which would also decrease the time for processing search request.
__NOTE__: This functionality checks both the permissions and existence of the asset.
If immediate reflection of asset deletions in the API is required,
please enable this functionality.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.search_rest_api.hpa</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: false
maxReplicas: 5
minReplicas: 1
targetCPUUtilizationPercentage: 80
targetMemoryUtilizationPercentage: 90

</pre>
</div>
			</td>
			<td>

Horizontal Pod Autoscaler configuration for the search-rest-api deployment. By default it is disabled. In order to enable it, please set the following parameter to true:
```bash
    --set ngsearch.microservices.search_rest_api.hpa.enabled=true
```

To set the maximum number of replicas for the search-rest-api deployment, set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.hpa.maxReplicas=<number of replicas>
```

To set the minimum number of replicas for the search-rest-api deployment, set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.hpa.minReplicas=<number of replicas>
```
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.search_rest_api.llm_parsing</div></td>
			<td><div style="white-space: nowrap;">
yaml
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
system prompt + filter catalog shipped in the app image, reproduced inline below
</pre>
</div>
			</td>
			<td>

LLM query parsing: parses free-text queries into
structured filters via `POST /llm_parse/query` (+ `GET /llm_parse/fields`
for filter discovery). Runs on the same shared LLM provider as
validation; when disabled or unreachable the endpoints return 503 and
clients fall back to plain hybrid search.

`prompt` (string) and `fields` (list) are the live system-prompt template
and filter catalog the chart mounts and the API loads — helm values take
priority, so what you see here is exactly what deploys (`$catalog` /
`$today` are substituted at runtime). They reproduce the copies shipped in
the application image verbatim; set `prompt: ""` / `fields: null` to fall
back to those in-image copies. `fields` is where deployment-specific
filters (e.g. SimReady physics properties) are configured. The inline
defaults are kept in sync with the in-image copies by
ci/helm/tests/unit/test_llm_parsing_defaults_sync.sh.

LLM query parsing is disabled by default because it requires an external
LLM connection. To enable it, set the following parameter to true:
```bash
    --set ngsearch.microservices.search_rest_api.llm_parsing.enabled=true
```

or specify `ngsearch.microservices.search_rest_api.llm_parsing.enabled` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      llm_parsing:
        enabled: true
```

To choose the model used for parsing (empty keeps the application
default), set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.llm_parsing.model=<model id>
```

or specify `ngsearch.microservices.search_rest_api.llm_parsing.model` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      llm_parsing:
        model: <model id>
```

`max_tokens` caps the parser's output tokens (default 1536; empty keeps
the application default). Raise it if structured output gets truncated on
large field catalogs:
```bash
    --set ngsearch.microservices.search_rest_api.llm_parsing.max_tokens=2048
```

By default llm_parsing shares the one OpenAI-compatible provider used by
`validation` and `deepsearch.vision_endpoint` (`USDSEARCH_LLM_API_KEY` /
`USDSEARCH_LLM_BASE_URL`) — leave `provider.base_url`/`provider.api_key`
empty to keep that. To point LLM query parsing at its OWN endpoint
(e.g. a cheaper/faster model on a different server) set the `provider`
block below: a non-empty `base_url` and/or `api_key` overrides just that
field for the parsing role (-> `USDSEARCH_LLM_PARSING_BASE_URL` /
`USDSEARCH_LLM_PARSING_API_KEY`), and the chart provisions a dedicated
secret for the key.

Example — enable LLM query parsing on its own endpoint at install time:

  helm install usdsearch ./helm/usdsearch \
    ... \
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.llm_parsing.enabled=true \
    --set ngsearch.microservices.search_rest_api.llm_parsing.model=<model id> \
    --set ngsearch.microservices.search_rest_api.llm_parsing.provider.api_key=<API key> \
    --set ngsearch.microservices.search_rest_api.llm_parsing.provider.base_url=<Base URL>
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.search_rest_api.search_telemetry_stdout</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.storage</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "replicas": 1
}
</pre>
</div>
			</td>
			<td>

Storage service configuration
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.storage_cron</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "replicas": 1
}
</pre>
</div>
			</td>
			<td>

Storage Cron Job configuration
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">ngsearch.microservices.tagcrawler</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "replicas": 1
}
</pre>
</div>
			</td>
			<td>

Storage backend tag-crawler configuration
</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">rendering_service_deployment</div></td>
			<td><div style="white-space: nowrap;">
yaml
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: false

</pre>
</div>
			</td>
			<td>

Rendering service deployment configuration.</td>
		</tr>
	</tbody>
</table>

## Redis instance settings

Configuration for the default Redis instance, which gets deployed when ``redis_deployment.enabled`` is set to ``true``.

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.architecture</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"standalone"
</pre>
</div>
			</td>
			<td>

Redis architecture type</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.auth</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: False

</pre>
</div>
			</td>
			<td>

Redis authentication</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.commonConfiguration</div></td>
			<td><div style="white-space: nowrap;">
tpl/array
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="tpl">
redis.commonConfiguration: |
  appendonly yes
  save ""
  databases 32
</pre>
</div>
			</td>
			<td>

Redis common configuration</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.image.repository</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"bitnamilegacy/redis"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.master</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
disableCommands: []
persistence:
    enabled: True
    size: 64Gi
resources:
    limits:
        memory: 10Gi
        ephemeral-storage: 2Gi
        cpu: 1000m

</pre>
</div>
			</td>
			<td>

Redis master configuration</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis.replica</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
replicaCount: 0

</pre>
</div>
			</td>
			<td>

Redis additional replica count</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">redis_deployment</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: true

</pre>
</div>
			</td>
			<td>

A Redis instance can be deployed as part of USD Search API helm chart.
Set ``enabled: false`` if you wish to use your own instance.
</td>
		</tr>
	</tbody>
</table>

## OpenSearch instance settings

Configuration for the default OpenSearch cluster, which gets deployed when ``opensearch_deployment.enabled`` is set to ``true``.

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.config."opensearch_dashboards.yml"</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"server.name: dashboards\nserver.host: \"0.0.0.0\"\nserver.ssl.enabled: false\nopensearch.ssl.verificationMode: none\nopensearch.username: kibanaserver\nopensearch.password: kibanaserver\nopensearch.requestHeadersWhitelist: [authorization, securitytenant]\nopensearch.hosts: [\"http://deepsearch-opensearch-cluster-master:9200\"]\n"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.extraEnvs[0].name</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"DISABLE_SECURITY_DASHBOARDS_PLUGIN"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.extraEnvs[0].value</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"true"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.annotations</div></td>
			<td><div style="white-space: nowrap;">
object
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{}
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.hosts[0].host</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.hosts[0].paths[0].backend.serviceName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.hosts[0].paths[0].backend.servicePort</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
""
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.hosts[0].paths[0].path</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"/"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.ingressClassName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"nginx"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.ingress.labels</div></td>
			<td><div style="white-space: nowrap;">
object
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{}
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch-dashboards.opensearchHosts</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"http://deepsearch-opensearch-cluster-master:9200"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.clusterName</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"deepsearch-opensearch-cluster"
</pre>
</div>
			</td>
			<td>

Default opensearch cluster name</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.config."opensearch.yml"</div></td>
			<td><div style="white-space: nowrap;">
tpl/array
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="tpl">
opensearch.config."opensearch.yml": |
  network.host: 0.0.0.0
  #knn.algo_param.index_thread_qty: 8
  plugins:
    security:
      disabled: true

</pre>
</div>
			</td>
			<td>

Default opensearch deployment configuration</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.extraEnvs[0].name</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"DISABLE_INSTALL_DEMO_CONFIG"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.extraEnvs[0].value</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"true"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.masterService</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"deepsearch-opensearch-cluster-master"
</pre>
</div>
			</td>
			<td>

 Default opensearch master service name</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.opensearchJavaOpts</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"-Xmx4096M -Xms4096M"
</pre>
</div>
			</td>
			<td>

 Default opensearch Java options</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.persistence</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: true
size: 100Gi

</pre>
</div>
			</td>
			<td>

Default opensearch persistent configuration</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.replicas</div></td>
			<td><div style="white-space: nowrap;">
int
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
3
</pre>
</div>
			</td>
			<td>

Default number of OpenSearch replicas.

The larger is the number of replicas - the higher is availability of the
service (that is more search requests can be processed in parallel) however,
as a drawback - more resources will be occupied.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.resources</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
requests:
    cpu: "2"
    memory: "8Gi"
limits:
    cpu: "3"
    memory: "8Gi"

</pre>
</div>
			</td>
			<td>

Default opensearch resource requests per replica</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.sysctl</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: false

</pre>
</div>
			</td>
			<td>

Set optimal sysctl's through securityContext. This requires privilege. Can be disabled if
the system has already been pre-configured. (Ex: https://www.elastic.co/guide/en/elasticsearch/reference/current/vm-max-map-count.html)
Also see: https://kubernetes.io/docs/tasks/administer-cluster/sysctl-cluster/</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch.sysctlInit</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
{
  "enabled": false
}
</pre>
</div>
			</td>
			<td>

Set optimal sysctl's through privileged initContainer.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch_dashboards_deployment.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">opensearch_deployment</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
enabled: true

</pre>
</div>
			</td>
			<td>

By default an OpenSearch instance is deployed as part of the USD Search API
helm chart. It is, however, possible to rely on a separately installed instance
of OpenSearch. To do so, you can set the following command line argument during
helm chart deployment:

```bash
  --set opensearch_deployment.enabled=false
```
</td>
		</tr>
	</tbody>
</table>

## Neo4j instance settings

Configuration for the default Neo4j instance, which gets deployed when ``neo4j_deployment.enabled`` is set to ``true``.

<table>
	<thead>
		<th>Key</th>
		<th>Type</th>
		<th>Default</th>
		<th>Description</th>
	</thead>
	<tbody>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.config</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
server.config.strict_validation.enabled: "false"
server.memory.heap.initial_size: "8000m"
server.memory.heap.max_size: "8000m"

</pre>
</div>
			</td>
			<td>  Neo4j configuration settings</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.env.NEO4J_PLUGINS</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"[\"graph-data-science\", \"apoc\"]"
</pre>
</div>
			</td>
			<td>  Neo4j plugins configuration</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.fullnameOverride</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"neo4j"
</pre>
</div>
			</td>
			<td>  Name of the Neo4j instance </td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.livenessProbe.exec.command[0]</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"/bin/sh"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.livenessProbe.exec.command[1]</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"-c"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.livenessProbe.exec.command[2]</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"USER=$(cat /config/neo4j-auth/NEO4J_AUTH | cut -d'/' -f1)\nPASS=$(cat /config/neo4j-auth/NEO4J_AUTH | cut -d'/' -f2)\ncypher-shell --non-interactive -u \"$USER\" -p \"$PASS\" \"RETURN 1\" || exit 1\n"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.neo4j</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
name: neo4j
password: "password"
resources:
    requests:
        cpu: "4000m"
        memory: "14Gi"
    limits:
        cpu: "4000m"
        memory: "14Gi"

</pre>
</div>
			</td>
			<td>  Neo4j authentication and resource settings</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.serviceMonitor.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
false
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.services</div></td>
			<td><div style="white-space: nowrap;">
map
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="yaml">
neo4j:
    enabled: true
    annotations: {}
    spec:
        type: ClusterIP

</pre>
</div>
			</td>
			<td>  Neo4j service settings</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.volumes.data.defaultStorageClass.accessModes[0]</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"ReadWriteOnce"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.volumes.data.defaultStorageClass.requests.storage</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"100Gi"
</pre>
</div>
			</td>
			<td></td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j.volumes.data.mode</div></td>
			<td><div style="white-space: nowrap;">
string
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
"defaultStorageClass"
</pre>
</div>
			</td>
			<td>

**REQUIRED**: specify a volume mode to use for data
Valid values are:
  * share
  * selector
  * defaultStorageClass
  * volume
  * volumeClaimTemplate
  * dynamic

To get up-and-running quickly, for development or
testing, use ``defaultStorageClass`` for a dynamically
provisioned volume of the default storage class.</td>
		</tr>
		<tr>
			<td><div style="width: 150px; overflow-wrap: break-word;">neo4j_deployment.enabled</div></td>
			<td><div style="white-space: nowrap;">
bool
</div></td>
			<td>
				<div style="width: 300px;">
<pre lang="json">
true
</pre>
</div>
			</td>
			<td>  trigger to enable Neo4j helm chart deployment</td>
		</tr>
	</tbody>
</table>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| NVIDIA |  | <https://www.nvidia.com/en-us/> |

# License

GOVERNING TERMS:

If you download the software and materials as available from the NVIDIA AI product portfolio, use is governed by the NVIDIA Software License Agreement (found at https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) and the Product-Specific Terms for NVIDIA AI Products (found at https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-ai-products/); except for the model which is governed by the NVIDIA AI Foundation Models Community License Agreement (found at https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-ai-foundation-models-community-license-agreement/.

If you download the software and materials as available from the NVIDIA Omniverse portfolio, use is governed by the NVIDIA Software License Agreement (found at https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/) and the Product-Specific Terms for NVIDIA Omniverse (found at NVIDIA Agreements | Enterprise Software | Product Specific Terms for Omniverse); except for the model which is governed by the NVIDIA AI Foundation Models Community License Agreement (found at https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-ai-foundation-models-community-license-agreement/.

# FAQ

## USD assets organization best practices

USD Search API service indexes individual assets that are stored on the storage backend. As described in [Plugins](#plugins) section multiple asset formats are supported.

When it comes to USD assets, USD Search API service operates on the file level, so the whole USD asset / scene is indexed as a whole. If one has a large USD scene with multiple smaller prims baked in, only the overarching USD scene will be indexed as it would be the only actual file stored on the storage backend. Therefore, in case finding smaller objects that the scene is composed of is desired (e.g. in the case of doing in-scene search or finding scenes that contain specific objects), those individual objects should be:
* stored on the storage backend as individual USD assets,
* referenced in the main scene, instead of being baked into it.

## Image-based search best practices

USD Search API relies on the [SigLIP2 model](https://huggingface.co/google/siglip2-giant-opt-patch16-384) to extract embedding from images. SigLIP2 model operates on RGB images of shape ``384x384``, therefore to achieve the best accuracy the input images should be squared and have at least ``384x384`` size.

If images have different dimensions - they will be rescaled such that the minimum of height and width is equal to ``384`` and then center-cropping will be applied to make sure aspect ratio is preserved and the SigLIP2 model receives a squared input.

## Embedding service falls back to CPU with the GPU Operator installed

If the embedding service container starts on CPU even though the NVIDIA GPU Operator is installed on the cluster, the two most common causes are:

1. **NVIDIA GPU driver version mismatch.** The driver must be version ``595.58.03`` or higher. Verify the installed driver and upgrade it if it is older. The embedding image is built on Triton 26.10 (CUDA 13.4): R615 drivers run it natively, older supported drivers through CUDA forward compatibility (logged as ``CUDA Forward Compatibility mode ENABLED`` at startup).

2. **Multiple RuntimeClasses defined on the cluster.** When the driver is correct, the GPU may not be exposed because more than one RuntimeClass is defined and the wrong one is selected by default. List the available RuntimeClasses with:

   ```bash
   kubectl get runtimeclass
   ```

   If several are present, override the default one for the embedding pod by setting the ``deepsearch.microservices.embedding.runtimeClassName`` parameter to the GPU RuntimeClass (e.g. ``nvidia``):

   ```bash
     --set deepsearch.microservices.embedding.runtimeClassName=nvidia
   ```

## Redis Persistent Volume Claim

USD Search API relies on [Redis](https://redis.io/) for all internal caching and uses the official [Redis Helm chart](https://artifacthub.io/packages/helm/bitnami/redis>) for installation, which itself relies on the Persistent Volume Claim mechanism. For the Redis installation provided with USD Search API, a Persistent Volume is required that would be then claimed by Redis. An example configuration is shown below for a Persistent Volume that uses storage on the local file system.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
name: sample-pv-name
spec:
accessModes:
- ReadWriteOnce
capacity:
  storage: 100Gi
local:
  path: /var/lib/omni/volumes/001
nodeAffinity:
  required:
    nodeSelectorTerms:
    - matchExpressions:
    - key: kubernetes.io/hostname
    operator: In
    values:
    - "node-name"
persistentVolumeReclaimPolicy: Retain
volumeMode: Filesystem
```

For more information on different types of Persistent Volumes and their setup procedures, please refer to the [official Kubernetes documentation](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).

## Microk8s CA certificate issues

When using a microk8s cluster it may happen that some pods (e.g. <deployment name>-deepsearch-worker-thumb-gen-bg-...) would crash with the following error:

```bash
  File "/usr/local/lib/python3.13/site-packages/monitor/src/monitor_worker.py", line 640, in task_processor
    raise Exception("Unexpected error: %s", str(exc)) from exc
Exception: ('Unexpected error: %s', "Cannot connect to host <some IP>:443 ssl:True [SSLCertVerificationError: (1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: CA cert does not include key usage extension (_ssl.c:1032)')]")
```

This is a known issue with the microk8s server: https://github.com/canonical/microk8s/issues/4864.

Please refer to the fix suggested in [this post](https://github.com/canonical/microk8s/issues/4864#issuecomment-2654714836) to manually generate certificates and update your micork8s cluster.

**NOTE**: For a quick test it is possible to provide the following parameter to the helm chart deployment that disables SSL verification of CA kubernetes certificate:

```bash
  --set deepsearch.microservices.k8s_renderer.verify_k8s_ssl_cert=false
```
this, however, is strictly not recommended for production environments.

## Redis CrashLoopBackOff

In rare cases it could happen that Redis appendonly file ends up in a corrupted state. In this case the following line will be printed in the logs of the redis pod:

```
Bad file format reading the append only file: make a backup of your AOF file, then use ./redis-check-aof --fix ....
```

This may happen if the node that is running redis got unexpectedly terminated or has run out of space.

In order to fix this issue, please execute the following set of commands.

**NOTE**: The steps below assume that there is only a single instance of USD Search API installed in a provided namespace. If that is not the case the way ``REDIS_STATEFULSET_NAME`` and ``REDIS_POD_NAME`` are computed need to be updated.

```bash
# prepare some settings
export NAMESPACE=<namespace where USD Search API is running>
export REDIS_AOF_FILE_NAME=<corrupted file name from the Redis log>
# get the name of the statefulset that is controlling Redis
export REDIS_STATEFULSET_NAME=$(kubectl get statefulset -n $NAMESPACE -o custom-columns=":metadata.name" | grep redis)
# get the name of the pod running Redis
export REDIS_POD_NAME=$(kubectl get pods -n $NAMESPACE -o custom-columns=":metadata.name" | grep redis)
# patch Redis statefulset to sleep (to exit crashbackloop)
kubectl patch statefulset -n $NAMESPACE $REDIS_STATEFULSET_NAME -p '{"spec": {"template": {"spec":{"containers":[{"name": "redis","args": ["-c", "sleep 1000000000"]}]}}}}'
# give k8s 5 seconds to restart redis
sleep 5
# fix corrupted redis file
kubectl exec -it -n $NAMESPACE $REDIS_POD_NAME -- redis-check-aof --fix /data/appendonlydir/$REDIS_AOF_FILE_NAME
# revert statefulset patching
kubectl patch statefulset -n $NAMESPACE $REDIS_STATEFULSET_NAME -p '{"spec": {"template": {"spec":{"containers":[{"name": "redis","args": ["-c", "/opt/bitnami/scripts/start-scripts/start-master.sh"]}]}}}}'
# delete running container to make sure it restarts
kubectl delete pods $REDIS_POD_NAME
```

## OpenSearch Persistent Volume Claim

When using the instance of OpenSearch provided with the USD Search API helm chart, the [official OpenSearch Helm chart](https://opensearch.org/docs/latest/install-and-configure/install-opensearch/helm/) will be used for installation.
This Helm chart by default installs a 3-Node OpenSearch instance and requires Persistent Volume storage. Creation of Persistent Volumes can be done in the exactly same way as described in the previous section.

## Incorrect Service Registration Token with Omniverse Nucleus storage backend

When configuring USD Search API, a failure to register with the Nucleus Discovery service will happen if the provided Nucleus registration token is incorrect. If this occurs, the following error may be displayed:

```bash
Deployment: internal registration failed: DENIED
```

To solve this issue, the correct service registration token needs to be provided and can be located in the following subfolder within the Nucleus Docker Compose installation location:

```bash
base_stack/secrets/svc_reg_token
```

## OpenSearch Virtual Memory (vm.max_map_count)

On some systems, the value of the kernel parameter ``vm.max_map_count`` may be too low for OpenSearch. If this is the case, it is required to update the default value for ``vm.max_map_count`` to at least ``262144``, as described in the [OpenSearch installation documentation](https://opensearch.org/docs/1.1/opensearch/install/important-settings/).

To check the current value, run this command:

```bash
cat /proc/sys/vm/max_map_count
```

To increase the value, add the following line to ``/etc/sysctl.conf``:

```
vm.max_map_count=262144
```

Then run the following to reload and apply the settings change.

```
sudo sysctl -p
```

## Storage backend connection

Helm chart installation assumes that storage backend (AWS S3 bucket or Omniverse Nucleus Server) is available before installation and valid credential information is provided.

For convenience we have included a helm pre-installation hook that checks the backend connection before installing of the helm chart.

If storage backend is not available, then depending on the backend type, one of the following errors will be printed during execution of helm install command:

```bash
Error: INSTALLATION FAILED: failed pre-install: 1 error occurred:
	* job test-nucleus-storage-check failed: BackoffLimitExceeded
```

or

```bash
Error: INSTALLATION FAILED: failed pre-install: 1 error occurred:
	* job test-s3-storage-check failed: BackoffLimitExceeded
```

It could happen that connection with the storage backend is broken after helm chart is installed. This could occur if the storage backend is unreachable for some reason. In this case, you may notice that many pods enter the ``CrashLoopBackOff`` state. To confirm that the issue is indeed related to the storage backend connection, you can do one of the following:

1. run helm test which will verify storage backend connection as follows:

   ```bash
   helm test <deployment name>
   ```

2. check the logs of any pod that entered ``CrashLoopBackOff`` and if you see ConnectionError messages - that would mean that storage backend is for some reason unavailable.

## Search speed improvement

In case slow search speeds are encountered, it is possible to do several optimizations from the helm chart level.

### Increase the number of OpenSearch replicas

If the cluster permits - it is possible to increase the number of OpenSearch replicas that is used. By default the helm chart is set to use ``3`` replicas, which we found to be sufficient in our experiments, however, this parameter could be overwritten. Therefore, it is recommended to check ``opensearch.replicas`` setting in ``my-usdsearch-config.yaml`` and adjust it according the amount of available resources. Alternatively it is possible to set the desired number of OpenSearch replicas as a command line argument as follows:

```bash
	--set opensearch.replicas=<desired number of OpenSearch replicas>
```

## Indexing speed improvement

In case slow indexing speeds are encountered, it is possible to do several optimizations from the helm chart level.

### Enable shader caching in Rendering jobs

By default Rendering Jobs are using memory medium for shader cache, which is only available during the lifetime of a job and therefore such cache needs to be re-calculated for each rendering job, which adds a significant overhead. Please refer to [Rendering Job configuration](#rendering-job-configuration) section for more information on how to setup persistence.

### Scale the cluster

Rendering jobs only get allocated, when enough resources are available on the cluster. So adding  a node with more GPUs will linearly increase indexing speed.

## Metrics are missing in Grafana with monitoring enabled

It could happen that Prometheus metrics do not appear in Grafana installed by [Kube Prometheus Stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack). The most common reason for such behavior is that Prometheus operator may not be configured to monitor all namespaces on the kubernetes cluster. In order to let Prometheus monitor all namespaces set the following in Kube Prometheus stack configuration:

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorSelector: {}
    serviceMonitorNamespaceSelector: {}
```

# Get Help

Enterprise Support

Get access to knowledge base articles and support cases or [submit a ticket](https://www.nvidia.com/en-us/data-center/products/ai-enterprise-suite/support/).
