# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.7] - 2024-07-02
### Fixed
- fixed the bug, when rendering was not correct in case of multiple semantic labels

## [0.3.6] - 2023-11-24
### Fixed
- removed exact version in omni.replicator dependency

## [0.3.5] - 2023-08-29
### Fixed
- updated the code to accept the changed format of data from replicator/synthetic data sdk

## [0.3.4] - 2023-07-21
### Updated
- Replicator and Omni.warp versions update

## [0.3.3] - 2023-06-23
### Updated
- Farm metrics facility extension is pinned to `0.2.3` version


## [0.3.2] - 2023-05-22
### Fixed
- OM-89150: Updated tests
- Fixed a typo in class name

## [0.3.1] - 2023-04-13
### Fixed
- Updated extension dependencies
- Added some debug logging
- optimized some functionality

## [0.3.0] - 2023-04-12
### Added
- Kit 105.1+ support
- moved scene config to toml (yaml was problematic)
- dependency clean-up

## [0.2.7] - 2022-02-17
### Added
- Upgraded replicator.core to 1.7.6 to work with latest Kit 104.2

## [0.2.6] - 2022-12-21
### Added
- Bumped replicator dependency

## [0.2.5] - 2022-12-21
### Added
- timeouts on Replicator operations
- improved exception handling

## [0.2.4] - 2022-12-16
### Updated
- removed replicator hard dependency fix (version 1.6 now)
- added raising an exception in case Replicator could not initialize some sensors
- added prometheus metrics to track progress

## [0.2.3] - 2022-12-15
### Fixed
- Bug: rendering some assets resulted in an infinite loop

## [0.2.2] - 2022-12-12
### Added
- added rendering-setting labels to metrics

## [0.2.1] - 2022-12-05
### Added
- Redis client support
- Metrics
- code refactor / clean-up
- tests improvement
    - added rendering quality tests

## [0.2.0] - 2022-11-25
### Added
- updated Replicator dependency to the latest one to support Kit 104+
- Support for Kit 103.5 is dropped at this point (due to Replicator incompatibility)
- code clean-up

## [0.1.4] - 2022-11-25
### Added
- fixed a bug with infinite loop

## [0.1.3] - 2022-11-16
### Added
- added possibility to control image resolution
- added possibility to provide a list of sensor, for which data is required
- improved test coverage

## [0.1.2] - 2022-10-04
### Added
- update display options to not show the cameras in the view

## [0.1.1] - 2022-09-22
### Added
- bug fixes for existing camera view renderings

## [0.1.0] - 2022-09-20
### Added
- switch to using replicator.core instead of deprecated omni.synthetic_data
- support for HTTP transport together with WebSockets
- support for custom camera placement
- support for random camera placement
- bug fixes and improvements

## [0.0.13] - 2022-05-18
### Added
- error handling improvement:
    - when processing existing camera views
    - when scene fails to load
- updated Pillow dep to 9.1.0
- improved test coverage

## [0.0.12] - 2022-04-26
### Added
- pip dependencies update

## [0.0.11] - 2022-03-26
### Added
- batch rendering
- tests refactor

## [0.0.10] - 2022-03-07
### Added
- switched async stage closing to sync (due to random errors on TC)

## [0.0.9] - 2022-02-05
### Added
- removed hardcoded: /rtx/materialDb/syncLoads: True

## [0.0.8] - 2022-02-04
### Added
- logging improvements
- timeout on rendering novel camera views

## [0.0.7] - 2022-01-31
### Added
- support for Kit 103.1
- depth sensor switch to distance to image and distance to camera

## [0.0.6] - 2021-11-19
### Added
- bug fixes

## [0.0.5] - 2021-11-19
### Added
- fix rendering pipeline for stages with Y-ref up axis

## [0.0.4] - 2021-11-19
### Added
- multiple rendering pipeline fixes
- code clean-up

## [0.0.3] - 2021-11-19
### Added
- fix rendering when object is not normalized and its scale is higher than 1.

## [0.0.2] - 2021-11-15
### Added
- removed unused dependencies.

## [0.0.1] - 2021-11-15
### Added
- Initial version.
