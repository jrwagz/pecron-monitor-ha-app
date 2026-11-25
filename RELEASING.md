# Releasing

The [Release workflow](.github/workflows/release.yaml) builds and signs the
images, tags the commit, publishes a GitHub release and opens a pull request.
**Users get the release when that pull request is merged**, not before: Home
Assistant requires the image to exist before `version` changes on `main`.

A published version never changes. To fix a release, publish a new version.

## One-time setup

- In the repository settings, under *Actions > General*, enable
  **Allow GitHub Actions to create and approve pull requests**.
- Before merging the **first** release pull request, make the container
  packages public (*Profile > Packages > package > Package settings > Change
  visibility*): `pecron-monitor-ha-app`, `amd64-pecron-monitor-ha-app` and
  `aarch64-pecron-monitor-ha-app`. While they are private, installs fail.

## Steps

1. On `main`, add a `## [X.Y.Z]` section to
   [`pecron_monitor_ha_app/CHANGELOG.md`](pecron_monitor_ha_app/CHANGELOG.md)
   and merge it. Leave `version` in `config.yaml` alone.
2. Run the workflow from `main`: *Actions > Release > Run workflow*, or
   `gh workflow run release.yaml --ref main -f version=X.Y.Z`.

   It stops before building unless the version is SemVer (without `+build`
   metadata), has a changelog section, is greater than `version` in
   `config.yaml` (or equal to it while no `v*` git tag exists) and is not
   already published. It then runs the CI checks, including the smoke test,
   before it pushes anything.
3. Review the pull request "Release X.Y.Z to users". It sets `version` and, the
   first time, `image`. Add `breaking_versions` now if needed (see below).
4. Workflows do not start on a pull request opened by GitHub Actions. **Close
   and reopen it** to run CI.
5. Merge it. Home Assistant offers the update to users.

## `breaking_versions`

Add the version to `breaking_versions` in `config.yaml`, in the release pull
request, when users must act or check something before updating: an option was
renamed, removed or became required, entity IDs or MQTT topics changed, stored
state is not carried over, or a pecron-monitor update changes how devices
behave. Home Assistant then does not update the app across that version
automatically. Describe the action to take in the changelog.

```yaml
breaking_versions:
  - "0.2.0"
```

## Changes to `config.yaml` are visible before a release

Home Assistant reads `config.yaml` from `main`. Once a release has set `image`,
a schema or option change merged to `main` is visible to **new installs**
immediately, while they still get the previous image. Release soon after
merging such a change.

For the same reason, to test a local copy of the app folder on Home Assistant,
comment out `image` in the copy. Otherwise the published image is pulled
instead of building your copy.

## Recovering from a failed release

Nothing reaches users until the pull request is merged.

### Failure before the manifest is published

Fix the cause, then run the workflow again with the same version. Per-arch
tags from the failed attempt are overwritten.

### Failure after the manifest is published

A new run, and re-running the build or manifest jobs, are refused because
`ghcr.io/jrwagz/pecron-monitor-ha-app:X.Y.Z` exists. If in doubt, release the
next patch version instead. Otherwise finish by hand, from the step that failed.

- **Tag and GitHub release, or pull request job failed:** fix the cause and use
  **Re-run failed jobs**. If that fails because a step already half happened, use
  the commands below.
- **Manifest signing failed:** the later jobs did not run. Releasing the next
  patch version is preferred. To sign by hand instead, install
  [Cosign](https://docs.sigstore.dev/cosign/system_config/installation/) and
  log in to `ghcr.io` with a token that has `write:packages`. Keyless signing
  records **your own identity, including your email address, in a public
  transparency log**, not the workflow's identity.

  ```bash
  image=ghcr.io/jrwagz/pecron-monitor-ha-app
  digest=$(docker buildx imagetools inspect "$image:X.Y.Z" --format '{{.Manifest.Digest}}')
  cosign sign "$image@$digest"
  ```

  Then do the following steps.
- **Git tag and GitHub release** (use the commit the workflow ran on; skip the
  command if the release exists):

  ```bash
  python3 .github/scripts/release.py notes X.Y.Z > /tmp/notes.md
  gh release create vX.Y.Z --target <commit-sha> --title vX.Y.Z --notes-file /tmp/notes.md
  ```

- **Pull request.** If the branch `release/vX.Y.Z` was already pushed, only the
  last command is needed:

  ```bash
  git switch -c release/vX.Y.Z origin/main
  python3 .github/scripts/release.py bump X.Y.Z
  git commit -m "Release X.Y.Z to users" pecron_monitor_ha_app/config.yaml
  git push origin release/vX.Y.Z
  gh pr create --base main --head release/vX.Y.Z --title "Release X.Y.Z to users" --body "Merging this releases X.Y.Z to users."
  ```
