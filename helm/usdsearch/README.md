# USD Search API

![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.3.1](https://img.shields.io/badge/AppVersion-1.3.1-informational?style=flat-square)

**Homepage:** <https://docs.omniverse.nvidia.com/services/latest/services/usd-search/overview.html>

# Requirements
| Repository | Name | Version |
|------------|------|---------|
| https://helm.neo4j.com/neo4j | neo4j | 2026.1.4 |
| https://opensearch-project.github.io/helm-charts/ | opensearch | 3.3.2 |
| https://opensearch-project.github.io/helm-charts/ | opensearch-dashboards | 3.5.0 |
| oci://registry-1.docker.io/bitnamicharts | deepsearch-explorer(nginx) | 22.5.3 |
| oci://registry-1.docker.io/bitnamicharts | api-gateway(nginx) | 22.5.3 |
| oci://registry-1.docker.io/bitnamicharts | redis | 25.3.2 |

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
		- [Alternative installation options](#alternative-installation-options-3)
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
		- [VLM services](#vlm-services)
			- [Anthropic](#anthropic)
			- [Azure OpenAI](#azure-openai)
			- [Google](#google)
			- [NVIDIA Inference Hub](#nvidia-inference-hub)
			- [Mistral AI](#mistral-ai)
			- [NVIDIA NIM](#nvidia-nim)
			- [OpenAI](#openai)
			- [Qwen](#qwen)
		- [Customization](#customization)
			- [Image prompt configuration](#image-prompt-configuration)
			- [Metadata fields configuration](#metadata-fields-configuration)
	- [VLM-based verification of results with respect to input query](#vlm-based-verification-of-results-with-respect-to-input-query)
		- [VLM services](#vlm-services-1)
			- [Anthropic](#anthropic-1)
			- [Azure OpenAI](#azure-openai-1)
			- [Google](#google-1)
			- [NVIDIA Inference Hub](#nvidia-inference-hub-1)
			- [Mistral AI](#mistral-ai-1)
			- [NVIDIA NIM](#nvidia-nim-1)
			- [OpenAI](#openai-1)
			- [Qwen](#qwen-1)
	- [Search Backend configuration](#search-backend-configuration)
		- [External OpenSearch instance](#external-opensearch-instance)
		- [OpenSearch authentication](#opensearch-authentication)
	- [OTEL Telemetry and Traces collection](#otel-telemetry-and-traces-collection)
		- [Trace collection](#trace-collection)
		- [Search telemetry collection](#search-telemetry-collection)
	- [Values](#values)
		- [Global settings](#global-settings)
	- [Embedding service settings](#embedding-service-settings)
	- [Asset Graph Service additional settings](#asset-graph-service-additional-settings)
	- [Other settings](#other-settings)
	- [Neo4j instance settings](#neo4j-instance-settings)
	- [Maintainers](#maintainers)
- [License](#license)
- [FAQ](#faq)
	- [USD assets organization best practices](#usd-assets-organization-best-practices)
	- [Image-based search best practices](#image-based-search-best-practices)
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

Generate your NGC helm and container registry API Key prior to fetch helm chart. See onboarding guide [here](https://docs.nvidia.com/ai-enterprise/deployment/spark-rapids-accelerator/latest/appendix-ngc.html).

Fetch the latest helm chart from the registry

```bash
helm fetch https://helm.ngc.nvidia.com/nvidia/usdsearch/charts/usdsearch-1.3.1.tgz \
	--username='$oauthtoken' \
	--password=<YOUR API KEY>
```

# Deployment

USD Search can be deployed to index data from an [AWS S3 bucket](#aws-s3), an [Omniverse Nucleus server](#omniverse-nucleus-server) or a broad range of other backends by utilizing [S3proxy functionality](#s3proxy). Detailed deployment commands can be found in the sections below.

## AWS S3

To deploy the USD Search Helm chart and connect it to an AWS S3 bucket for
indexing, run the following command:

```bash
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm upgrade <deployment name> usdsearch-1.3.1.tgz --install \
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
helm upgrade <deployment name> usdsearch-1.3.1.tgz --install \
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
helm upgrade <deployment name> usdsearch-1.3.1.tgz --install \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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
helm install <deployment name> usdsearch-1.3.1.tgz \
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

The following thumbnail file formats are supported: all formats supported by the [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) and GIF. When a thumbnail is a GIF file, it will be split into multiple frames using a fixed time offset (default: ``1000`` ms), configurable per plugin via the ``gif_offset_ms`` parameter of the ``thumbnail_to_embedding`` and ``thumbnail_to_vision_metadata`` plugins.

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

## VLM-based automatic captioning and tagging

Vision endpoint allows to automatically tag and caption various assets stored on the storage backend using an external Vision Language Model (VLM) service.

The following types of VLM services providers could be configured with the helm chart:
  * azure_openai
  * openai
  * anthropic
  * mistralai
  * google
  * nim
  * qwen
  * inference_hub

In order to select one VLM for the whole service globally you can pass the following command line parameter:

```bash
    --set deepsearch.vision_endpoint.vlm_service=<VLM service provider>
```

or specify `deepsearch.vision_endpoint.vlm_service` setting in the `my-usdsearch-config.yaml` file as follows:

```yaml
deepsearch:
  vision_endpoint:
    vlm_service: <VLM service provider>
 ```

__NOTE__: This setting can be overwritten for any USD Search API plugin (e.g. ``rendering_to_vision_metadata`` plugin) by passing the following command line arguments:
```bash
    --set deepsearch.plugins.rendering_to_vision_metadata.vision_endpoint.vlm_service=<VLM service provider>
```

Alternatively, for each plugin your can provide respective setting in the `my-usdsearch-config.yaml` file as follows:

```yaml
deepsearch:
  plugins:
    rendering_to_vision_metadata:
      vision_endpoint:
        vlm_service: <VLM service provider>
 ```

If no ``vision_endpoint`` setting is provided for the plugin, the global VLM configuration will be used.

For more information about the available USD Search API plugins, please refer to [Plugin Settings section](#plugin-settings).

### VLM services

Below you can find a list of VLM service providers with respective parameters that could be configured with USD Search API.

#### Anthropic

Anthropic VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Anthropic service, which could be done with the following command:
```bash
kubectl create secret generic anthropic-vlm-api-key-secret \
    --from-literal=api-key=<Anthropic API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.anthropic.api_key=<Anthropic API Key>
```

If it possible to customize various parameters of the Anthropic VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.anthropic.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
max_tokens: 2048
model: claude-3-5-sonnet-latest
temperature: 0
```
#### Azure OpenAI

Azure OpenAI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Azure OpenAI service, which could be done with the following command:
```bash
kubectl create secret generic azure-openai-vlm-api-key-secret \
    --from-literal=api-key=<Azure OpenAI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.azure_openai.api_key=<Azure OpenAI API Key>
```

If it possible to customize various parameters of the Azure OpenAI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.azure_openai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
api_version: 2025-03-01-preview
azure_deployment: gpt-4o-20241120
azure_endpoint: null
max_tokens: 2048
model: gpt-4o-20241120
temperature: 0
```
#### Google

Google Gemini VLM service endpoint configuration.

It is required to provide a secret with the API key for accessing Google Gemini service, which could be done with the following command:
```bash
kubectl create secret generic google-vlm-api-key-secret \
    --from-literal=api-key=<Google Gemini API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.google.api_key=<Google Gemini API Key>
```

If it possible to customize various parameters of the Google Gemini VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.google.parameters.<parameter name>=<parameter value>
```

For example, it is possible to customize the base URL for the Google Gemini VLM endpoint to the following:
```bash
    --set deepsearch.vision_endpoint.google.parameters.base_url=<target base URL>
```

The full list of parameters with pre-set default values can be found below:

```yaml
base_url: https://generativelanguage.googleapis.com/v1beta/openai
max_tokens: 2048
model: gemini-2.5-pro
temperature: 0
```
#### NVIDIA Inference Hub

Inference Hub VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Inference Hub service, which could be done with the following command:
```bash
kubectl create secret generic inference-hub-vlm-api-key-secret \
    --from-literal=api-key=<Inference Hub API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.inference_hub.api_key=<Inference Hub API Key>
```

If it possible to customize various parameters of the Inference Hub VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.inference_hub.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
max_tokens: 2048
model: azure/openai/gpt-5.1
temperature: 0
```
#### Mistral AI

Mistral AI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Mistral AI service, which could be done with the following command:
```bash
kubectl create secret generic mistralai-vlm-api-key-secret \
    --from-literal=api-key=<Mistral AI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.mistralai.api_key=<Mistral AI API Key>
```

If it possible to customize various parameters of the Mistral AI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.mistralai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
max_tokens: 1024
model: pixtral-large-latest
temperature: 0
```
#### NVIDIA NIM

NIM VLM endpoint configuration.

It is required to provide a secret with the API key for accessing NIM service, which could be done with the following command:
```bash
kubectl create secret generic nim-vlm-api-key-secret \
    --from-literal=api-key=<NIM API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.nim.api_key=<NIM API Key>
```

If it possible to customize various parameters of the NIM VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.nim.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
max_tokens: 2048
model: meta/llama-4-maverick-17b-128e-instruct
temperature: 0
```
#### OpenAI

OpenAI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing OpenAI service, which could be done with the following command:
```bash
kubectl create secret generic openai-vlm-api-key-secret \
    --from-literal=api-key=<OpenAI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.openai.api_key=<OpenAI API Key>
```

__NOTE__: Instead of relying on the OpenAI model, it is possible to provide on a custom VLM model endpoint, provided this custom VLM model has OpenAI API compatible interface. This could be achieved by appropriately setting the ``base_url`` parameter:

```bash
    --set deepsearch.vision_endpoint.openai.parameters.base_url=<your custom LLM model>
```

If it also possible to customize various other parameters of the OpenAI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.openai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
base_url: null
max_tokens: 2048
model: gpt-4o
temperature: 0
```
#### Qwen

Qwen VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Qwen service, which could be done with the following command:
```bash
kubectl create secret generic qwen-vlm-api-key-secret \
    --from-literal=api-key=<Qwen API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set deepsearch.vision_endpoint.qwen.api_key=<Qwen API Key>
```

If it possible to customize various parameters of the Qwen VLM endpoint. This can be done using the following command line arguments:

```bash
    --set deepsearch.vision_endpoint.qwen.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:

```yaml
max_tokens: 2048
model: qwen3-vl-235b-a22b-instruct
temperature: 0
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
Write a detailed analysis of the provided image of a 3D object or a scene.
Your analysis should focus on identifying key features, textures, colors, and any other notable characteristics visible from the images.

Based on your analysis, generate a JSON object that encapsulates the metadata about the 3D object.
This metadata should include searchable terms and keywords that accurately describe the object's visual aspects, such as shape, color, texture, and any unique features.
Additionally, craft a concise caption that summarizes the object's appearance and distinctive attributes.

Ensure that the JSON object is structured in a way that facilitates its inclusion in a searchable index, making the 3D object easily discoverable based on its visual characteristics.
The metadata should be comprehensive yet succinct, enabling efficient search and retrieval in a database or search engine context.

The JSON output should follow this structure:
{metadata_types}

with these field definitions:
{metadata_definitions}

Your analysis must strive to be as precise and comprehensive as possible, using only the visual information available in the provided thumbnails.
Assume the role of an intelligent vision system tasked with generating actionable metadata for cataloging or identification purposes.

```

#### Metadata fields configuration

Metadata fields extracted by the VLM-based auto-captioning system could be
adjusted to the target use-case by appropriately setting the
``deepsearch.vision_endpoint.metadata_fields`` parameter in the
``values.yaml`` file. This parameter is a list ``fields`` each of which
is required to to have the following settings:

  - **name**: name of the metadata field
  - **description**: description of the metadata field and some guidance for the VLM model on how this metadata field should be extracted.
  - **type**: type of the metadata field

The following represents the default configuration for the metadata fields:

```yaml
- description: a brief, descriptive title or caption for the object. The caption should be concise and informative, providing a general overview of the object's appearance, function, or significance. It should be written in clear, accessible language that is easy for users to understand and should accurately reflect the content and context of the object.
  name: caption
  type: str
- description: a list of potential search terms or phrases that someone could use to find this object using a text-based search engine. The terms should describe the object accurately, considering aspects such as its shape, material, style, color, and any distinctive features that might help in identifying it. All values should be returned comma-separated.
  name: queries
  type: list[str]
- description: a list of tags, keywords, and relevant phrases that accurately describe the object and would make it searchable using text. Consider aspects such as the object's form, material, color, function, style, and any notable or unique features that could help in identifying or categorizing the object for search purposes.
  name: tags
  type: list[str]
- description: a list of scene types that the object could be found in. Consider the context in which the object is typically used or displayed, such as a living room, kitchen, office, or outdoor setting.
  name: scene_type
  type: list[str]
- description: a list of colors that are present in the object. Consider the primary colors, secondary colors, and any other hues or shades that are visible in the object.
  name: colors
  type: list[str]
- description: a list of materials that the object is made of or composed of. Consider the primary materials, secondary materials, and any other substances or components that are used in the construction or fabrication of the object.
  name: materials
  type: list[str]
- description: a boolean value indicating whether the object is grayscale or monochromatic in appearance. If the object is primarily black, white, or shades of gray, set this value to true; otherwise, set it to false.
  name: grayscale
  type: bool
- description: a boolean value indicating whether the object has broken or missing textures that affect its appearance or quality. If the object displays unnatural red coloration or other visual artifacts that suggest texture issues, set this value to true; otherwise, set it to false.
  name: broken_textures
  type: bool
- description: a boolean value indicating whether the object is of good quality and suitable for use in a variety of applications. If the object is reasonably well-crafted, detailed, and visually appealing, set this value to true; otherwise, set it to false.
  name: good_quality
  type: bool
- description: a boolean value indicating whether the object is a simple geometric shape or blob with no distinctive features or characteristics. If the object lacks complexity, detail, or visual interest, set this value to true; otherwise, set it to false.
  name: geometric_shape
  type: bool
- description: a boolean value indicating whether the object is photorealistic in appearance, meaning that it closely resembles a real-world object or scene. If the object is highly detailed, textured, and realistic in its depiction, set this value to true; otherwise, set it to false.
  name: photorealistic
  type: bool
```

## VLM-based verification of results with respect to input query

VLM validation uses a Vision Language Model to verify that each search
result visually matches the input query. It compares the query against
the result's thumbnail and returns a match decision with confidence
score and reasoning.

The following types of VLM services providers could be configured with
the helm chart:
  * azure_openai
  * openai
  * anthropic
  * mistralai
  * google
  * nim
  * qwen
  * inference_hub

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

To set the VLM service provider, set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service=<VLM service provider>
```

or specify `ngsearch.microservices.search_rest_api.validation.vlm_service` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      validation:
        vlm_service: <VLM service provider>
```

To set the API key for the VLM service, set the following parameter:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.<VLM service provider>.api_key=<API key>
```

or specify `ngsearch.microservices.search_rest_api.validation.vlm_service.<VLM service provider>.api_key` setting in the `my-usdsearch-config.yaml` file as follows:
```yaml
ngsearch:
  microservices:
    search_rest_api:
      validation:
        vlm_service: <VLM service provider>
        api_key: <API key>
```

### VLM services

Below you can find a list of VLM service providers with respective parameters that could be configured with USD Search API.

#### Anthropic

Anthropic VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Anthropic service, which could be done with the following command:
```bash
kubectl create secret generic anthropic-vlm-api-key-secret \
    --from-literal=api-key=<Anthropic API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.anthropic.api_key=<Anthropic API Key>
```

If it possible to customize various parameters of the Anthropic VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.anthropic.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.anthropic.parameters.model=claude-3-5-sonnet-latest
```

#### Azure OpenAI

Azure OpenAI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Azure OpenAI service, which could be done with the following command:
```bash
kubectl create secret generic azure-openai-vlm-api-key-secret \
    --from-literal=api-key=<Azure OpenAI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.azure_openai.api_key=<Azure OpenAI API Key>
```

If it possible to customize various parameters of the Azure OpenAI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.azure_openai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * api_version
  * azure_endpoint
  * max_tokens
  * temperature
  * azure_deployment

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.azure_openai.parameters.model=gpt-4o-20241120
```

#### Google

Google Gemini VLM service endpoint configuration.

It is required to provide a secret with the API key for accessing Google Gemini service, which could be done with the following command:
```bash
kubectl create secret generic google-vlm-api-key-secret \
    --from-literal=api-key=<Google Gemini API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.google.api_key=<Google Gemini API Key>
```

If it possible to customize various parameters of the Google Gemini VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.google.parameters.<parameter name>=<parameter value>
```

For example, it is possible to customize the base URL for the Google Gemini VLM endpoint to the following:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.google.parameters.base_url=<target base URL>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature
  * base_url

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.google.parameters.model=gemini-2.5-pro
```

#### NVIDIA Inference Hub

Inference Hub VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Inference Hub service, which could be done with the following command:
```bash
kubectl create secret generic inference-hub-vlm-api-key-secret \
    --from-literal=api-key=<Inference Hub API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.inference_hub.api_key=<Inference Hub API Key>
```

If it possible to customize various parameters of the Inference Hub VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.inference_hub.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.inference_hub.parameters.model=gcp/google/gemini-3-flash-preview
```

#### Mistral AI

Mistral AI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Mistral AI service, which could be done with the following command:
```bash
kubectl create secret generic mistralai-vlm-api-key-secret \
    --from-literal=api-key=<Mistral AI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.mistralai.api_key=<Mistral AI API Key>
```

If it possible to customize various parameters of the Mistral AI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.mistralai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.mistralai.parameters.model=pixtral-large-latest
```

#### NVIDIA NIM

NIM VLM endpoint configuration.

It is required to provide a secret with the API key for accessing NIM service, which could be done with the following command:
```bash
kubectl create secret generic nim-vlm-api-key-secret \
    --from-literal=api-key=<NIM API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.nim.api_key=<NIM API Key>
```

If it possible to customize various parameters of the NIM VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.nim.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.nim.parameters.model=meta/llama-4-maverick-17b-128e-instruct
```

#### OpenAI

OpenAI VLM endpoint configuration.

It is required to provide a secret with the API key for accessing OpenAI service, which could be done with the following command:
```bash
kubectl create secret generic openai-vlm-api-key-secret \
    --from-literal=api-key=<OpenAI API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.openai.api_key=<OpenAI API Key>
```

__NOTE__: Instead of relying on the OpenAI model, it is possible to provide on a custom VLM model endpoint, provided this custom VLM model has OpenAI API compatible interface. This could be achieved by appropriately setting the ``base_url`` parameter:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.openai.parameters.base_url=<your custom LLM model>
```

If it also possible to customize various other parameters of the OpenAI VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.openai.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature
  * base_url

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.openai.parameters.model=gpt-4o
```

#### Qwen

Qwen VLM endpoint configuration.

It is required to provide a secret with the API key for accessing Qwen service, which could be done with the following command:
```bash
kubectl create secret generic qwen-vlm-api-key-secret \
    --from-literal=api-key=<Qwen API Key>
```

Alternatively, if such secret is not created in advance it is possible to automatically by providing the following command line arguments during the first helm installation:
```bash
    --set global.secrets.create.vlm=true \
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.qwen.api_key=<Qwen API Key>
```

If it possible to customize various parameters of the Qwen VLM endpoint. This can be done using the following command line arguments:

```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.qwen.parameters.<parameter name>=<parameter value>
```

The full list of parameters with pre-set default values can be found below:
  * model
  * max_tokens
  * temperature

For example, it is possible to customize the model parameter as follows:
```bash
    --set ngsearch.microservices.search_rest_api.validation.vlm_service.qwen.parameters.model=qwen3-vl-235b-a22b-instruct
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

* set the following parameters:
  * ``host`` - hostname of the OpenSearch instance (default: ``deepsearch-opensearch-cluster-master``)
  * ``port`` - port of the OpenSearch instance (default: ``9200``)
  * ``schema`` - schema of the OpenSearch instance (default: ``http``)
  * ``use_ssl`` - whether to use SSL for the OpenSearch instance (default: ``false``)
  * ``auth_secret_name`` - name of the secret that stores the authentication information for the OpenSearch instance. Please refer to [OpenSearch authentication](#opensearch-authentication) section for more information.
  * ``hosts`` - comma-separated list of additional OpenSearch instances to use for search (default: ``[]``)

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

### Search telemetry collection

Search service has the possibility to gather telemetry information about
searches executed by the users of the system. This information can
then be used to understand what queries are most frequently executed and also
allow to track down issues if inconsistency appears in the search
results.

Telemetry information includes:

 * Overall duration of request processing
 * Time spent waiting for response from the Search backend
 * Parsed version of the input query that is then converted to a request to
   OpenSearch service

__NOTE__: that no information about the user is stored in the system.

By default telemetry logging is switched off.  In order to enable telemetry collection, please set the following command line parameters during helm chart deployment:
```bash
    --set global.tracing.OTEL_SDK_DISABLED=false \
    --set ngsearch.microservices.search_rest_api.use_search_telemetry=true \
    --set ngsearch.microservices.search_rest_api.search_telemetry_stdout=true
```
You will then be able to see telemetry information being printed in the logs of the REST API service.

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
"1.3.1"
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

The following thumbnail file formats are supported: all formats supported by the [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) and GIF. When a thumbnail is a GIF file, it will be split into multiple frames using a fixed time offset (default: ``1000`` ms), configurable per plugin via the ``gif_offset_ms`` parameter of the ``thumbnail_to_embedding`` and ``thumbnail_to_vision_metadata`` plugins.

__NOTE__: These settings apply only to the **Nucleus** and **S3** storage backends. When using the **Storage API** backend, thumbnails are not resolved from the filesystem. Instead, the thumbnail URL is read directly from the asset metadata. The metadata field (or fields) that hold the thumbnail URL are controlled by the ``global.storage_api.thumbnail_metadata_fields`` setting. Please refer to the [Thumbnail retrieval](#thumbnail-retrieval) section for more information.
</td>
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
"-Xmx8192M -Xms8192M"
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
    memory: "16Gi"
limits:
    cpu: "3"
    memory: "16Gi"

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
