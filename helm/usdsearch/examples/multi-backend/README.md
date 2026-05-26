#  Multi-backend example (experimental)

Each USD Search instance requires connecting to a single storage backend. It is, however, possible to setup multiple USD Search instances that share resources and are able to process various storage backends.

**NOTE**: This setup assumes that users of USD Search APIs have unlimited access to all backends and therefore access verification checks are disabled.

## Main USD Search instance installation

First the main USD Search instance needs to be installed. Please follow the [Installation documentation](../../README.md#deployment) for more information. 

Two additional parameters need to be passed to the installation script:

```bash
    --set ngsearch.microservices.search_rest_api.enable_access_verification=false \
```

**Note**: These parameters:
* disable access verification of USD Search APIs that is currently required to search multiple backends from a single API endpoint.

Below you can find an example of installation command for a case where storage backend is AWS S3 bucket:

```bash
helm install main usdsearch-1.2.0.tgz \
    --set global.accept_eula=true \
    --set global.storage_backend_type=s3 \
    --set global.s3.bucket_name=<AWS S3 bucket name> \
    --set global.s3.region_name=<AWS S3 bucket region>  \
    --set global.s3.aws_access_key_id=<AWS S3 access key ID> \
    --set global.s3.aws_secret_access_key=<AWS S3 secret access key> \
    --set global.s3.aws_credentials_secret_name="main-instance-aws-creds" \
    --set global.secrets.create.auth=true \
    --set global.secrets.create.registry=true \
    --set global.ngcAPIKey=$NGC_CLI_API_KEY \
    --set ngsearch.microservices.search_rest_api.enable_access_verification=false \
    --set api-gateway.image.pullSecrets={nvcr.io}
```

## Additional instance installation

Additional instances, connected to other storage backends, can then be installed with the following command.

```bash
helm install additional-1 usdsearch-1.2.0.tgz \
    --set global.accept_eula=true \
    --set global.storage_backend_type=s3 \
    --set global.s3.bucket_name=<AWS S3 bucket 2 name> \
    --set global.s3.region_name=<AWS S3 bucket 2 region>  \
    --set global.s3.aws_access_key_id=<AWS S3 access key ID for bucket 2> \
    --set global.s3.aws_secret_access_key=<AWS S3 secret access key for bucket 2> \
    --set global.s3.aws_credentials_secret_name="additional-1-instance-aws-creds" \
    --set global.secrets.create.auth=true \
    --set global.embedding_deployment.enabled=false \
    --set global.embedding_deployment.endpoint=main-deepsearch-embedding-inference.<namespace of the main helm chart>.svc.cluster.local:8001 \
    --set opensearch_deployment.enabled=false \
    --set api_gateway_deployment.enabled=false \
    --set neo4j_deployment.enabled=false \
    --set api_gateway_deployment.enabled=false \
    --set global.ngcImagePullSecretName=nvcr.io \
    --set ngsearch.microservices.search_rest_api.enable_access_verification=false \
    --set api-gateway.image.pullSecrets={nvcr.io}
```

**NOTE**: If the additional USD Search instance for the second backend is installed in the same namespace, then registry secret does not need to be created, hence it's name is set in the command as follows:

```bash 
    --set global.ngcImagePullSecretName=nvcr.io
```

If, on the other hand, the additional USD Search instance is created in a different namespace, then the appropriate registry secret needs to be created. Similar to the main deployment this could be achieved by using the following commandline arguments:

```bash
    --set global.secrets.create.registry=true \
    --set global.ngcAPIKey=$NGC_CLI_API_KEY \
```

**NOTE**: In this example the embedding service endpoint is set to be `main-deepsearch-embedding-inference.<installation namespace>.svc.cluster.local:8001`, which assumes that the main deployment is called `main` as in the example above. If the name of the deployment is changed - make sure the embedding service endpoint is set to `<main deployment name>-deepsearch-embedding-inference.<installation namespace>.svc.cluster.local:8001`


## Access

In the above configuration the USD Search instances share the same index, so both search services created by these two instances give the same result.

For example you can then connect to the main USD Search instance by port-forwarding the service to a localhost:

```bash
kubectl port-forward svc/main-api-gateway 8080:80
```

or by calling 
```
helm status main
```

and following the steps described in step 4.