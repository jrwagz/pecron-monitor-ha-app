# Changelog

All notable changes to this app are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-25

### Added

- First release, wrapping
  [pecron-monitor](https://github.com/attractify-logan/pecron-monitor) v0.8.4.
- Several devices in one app, published to Home Assistant as MQTT discovery
  entities.
- Connection modes Automatic, Local only, Cloud only and Cloud REST only.
- MQTT broker settings taken from Home Assistant, with manual overrides.
- Import of each device's `tsl_cache` from a `pecron-monitor --setup` file.
- A custom AppArmor profile.
- Signed images for `amd64` and `aarch64`.
