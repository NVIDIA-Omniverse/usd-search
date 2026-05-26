# 1.3.14
* base container update to: `nvcr.io/nvidia/distroless/python:3.13-v4.0.4-dev`
* dependency updates
* vulnerability fixes

# 1.3.13
* updated `search-utils` package

# 1.3.12
* dependency updates

# 1.3.11
* base container: `nvcr.io/nvidia/distroless/python:3.13-v4.0.2-dev`
* dependency updates

# 1.3.10
* `search-utils` version bump
* base container: `nvcr.io/nvidia/distroless/python:3.13-v3.1.3-dev`
* dependency updates

# 1.3.9
* `search-utils` version bump
* base container image updated to `nvcr.io/nvidia/distroless/python:3.13-v3.1.2-dev`
* dependency updates

# 1.3.8
* `search-utils` version bump

# 1.3.7
* `search-utils` version bump
* base container image updated to `nvcr.io/nvidia/distroless/python:3.13-v3.1.1-dev`

# 1.3.6
* vulnerability fixes

# 1.3.5
* dependency updates
* updated base container to `nvcr.io/nvidia/distroless/python:3.13-v3.0.13-dev`

# 1.3.4
* dependency updates
* updated base container to `nvcr.io/nvidia/distroless/python:3.13-v3.0.12`

# 1.3.3
* search-utils update to support notification APIs

# 1.3.2
* search-utils update to support OpenID based authentication for Sevan

# 1.3.1
* search-utils update to support using `ListStat` operation instead of `Enumerate`

# 1.3.0
* [OMPE-51346](https://jirasw.nvidia.com/browse/OMPE-51346) - storage API support
* updated base container to `"nvcr.io/nvidia/distroless/python:3.11-v3.4.11-dev"`
* updated some dependencies to address vulnerabilities

# 1.2.4
* `search-utils` version bump
* updated base container to `nvcr.io/nvidia/distroless/python:3.11-v3.4.9-dev` and updated some dependencies

# 1.2.3
* updated license headers

# 1.2.2
* updated base container to `nvcr.io/nvidia/distroless/python:3.11-v3.4.4-dev` and updated some dependencies

# 1.2.1
* bump search-utils version and remove unnecessary dependencies
* use local Nucleus in CI

# 1.2.0
* Updated pydantic version (>=2.0)

# 1.1.6
* switched to distroless base container

# 1.1.5
* added the possibility to exclude / include files based on a config

# 1.1.4
* relaxed typing_extensions version

# 1.1.3
* updated logging
* updated search-utils

# 1.1.2
* updated dependencies

# 1.1.1
* updated dependencies
* updated base docker container to use python 3.11

# 1.1.0
* updated ``search-utils`` to reflect changes in adding vision generated metadata

# 1.0.11
* updated ``search-utils`` to populate created by field for S3 buckets

# 1.0.10
* updated ``search-utils`` to include creation date for S3 buckets

# 1.0.9
* removed nested dependencies

# 1.0.8
* updated minimum ``search-utils`` version to ``1.2.19`` to include redis liveness check

# 1.0.7
* fix package versions in containers

# 1.0.6
* dependency updates

# 1.0.5
* dependency updates and vulnerability fixes

# 1.0.4
* update opentelemetry packages to fix vulnerability

# 1.0.3
* updated base python image
* updated open-telemetry dependencies
* updated search-utils dependency to use structured logging

# 1.0.2
* urllib3 vulnerability fix - ``BDSA-2023-2618``
* gated ``CVE-2023-4911`` libc-bin vulnerability (exception: [OM-111326](https://omniverse-jirasw.nvidia.com/browse/OM-111326))

# 1.0.1
* OM-110548 - added the possibility to skip processing items from the Redis Stream with too many attempts (no limit by default)
* removed PIL dependency
* updated CI to export coverage stats

# 1.0.0
* Initial public release

# 0.1.3
## Added
* security stages
* licensing extraction moved to the CI
* fixed package dependencies (added SWIPAT ticket numbers)

# 0.1.2
## Fixed
* tagging subscription recreation or exception raising on demand

# 0.1.1
## Updated
* Search utils dependency
* base CI pipeline version bump

# 0.1.0
## Added
Initial version
