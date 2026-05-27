#  Deployment example with Explorer Web UI (experimental)

In order to quickly get started and experiment with USD Search APIs we provide a sample explorer web app that illustrates a way how USD Search APIs could be accessed.

In you order to enable it you need to additionally provide the [explorer-ui-sample-config.yaml](./explorer-ui-sample-config.yaml) configuration at helm chart installation / upgrade time as follows:

```bash
helm install ... -f ./explorer-ui-sample-config.yaml
```

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
    --set api-gateway.image.pullSecrets={nvcr.io} \
    --set deepsearch_explorer_deployment.enabled=true \
    -f explorer-ui-sample-config.yaml