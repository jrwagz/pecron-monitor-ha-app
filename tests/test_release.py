"""The release workflow's preconditions and file edits (.github/scripts/release.py)."""

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / ".github/scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0] - 2027-01-01

### Added

- Second.

## 0.1.0

- First.

[0.2.0]: https://example.com
"""


def registry(returncode=1, stderr=None):
    def run(args, **_kwargs):
        text = f"ERROR: {args[-1]}: not found\n" if stderr is None else stderr
        return subprocess.CompletedProcess(args, returncode, "", text)

    return run


@pytest.fixture
def repo(tmp_path):
    app = tmp_path / "pecron_monitor_ha_app"
    app.mkdir()
    (app / "config.yaml").write_text('name: x\nversion: "0.1.0"\nslug: x\n')
    (app / "CHANGELOG.md").write_text(CHANGELOG)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def tag(repo, name):
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(
        [*git, "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "c"],
        check=True,
    )
    subprocess.run([*git, "-c", "tag.gpgsign=false", "tag", name], check=True)


@pytest.mark.parametrize("version", ["0.1.0", "10.20.30", "1.0.0-rc.1", "1.0.0-alpha-2"])
def test_semver_accepted(version):
    release.parse(version)


@pytest.mark.parametrize(
    "version", ["", "1.0", "v1.0.0", "01.0.0", "1.0.0+build", "1.0.0-01", "1.0.0-", "1.0.0\n"]
)
def test_semver_rejected(version):
    with pytest.raises(release.ReleaseError):
        release.parse(version)


def test_precedence_follows_semver():
    ordered = [
        "1.0.0-1",
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0",
        "1.0.1",
        "1.2.0",
        "1.10.0",
        "2.0.0",
    ]
    assert sorted(reversed(ordered), key=release.parse) == ordered


def test_first_release_may_equal_the_config_version(repo):
    assert release.main(["validate", "0.1.0"], repo, registry()) == 0


def test_after_a_release_the_version_must_increase(repo, capsys):
    tag(repo, "v0.0.9")
    assert release.main(["validate", "0.1.0"], repo, registry()) == 1
    assert "greater than" in capsys.readouterr().err
    assert release.main(["validate", "0.2.0"], repo, registry()) == 0


def test_lower_version_is_refused(repo):
    config = repo / release.CONFIG
    config.write_text('version: "0.3.0"\n')
    assert release.main(["validate", "0.2.0"], repo, registry()) == 1


def test_existing_git_tag_is_refused(repo, capsys):
    tag(repo, "v0.2.0")
    assert release.main(["validate", "0.2.0"], repo, registry()) == 1
    assert "already exists" in capsys.readouterr().err


def test_missing_changelog_heading_is_refused(repo, capsys):
    assert release.main(["validate", "0.3.0"], repo, registry()) == 1
    assert "heading" in capsys.readouterr().err


def test_heading_must_match_the_whole_version(repo):
    with pytest.raises(release.ReleaseError):
        release.notes("## [0.2.0-rc.1]\n\n- x\n", "0.2.0")


@pytest.mark.parametrize(
    "run",
    [
        registry(returncode=0),
        registry(stderr="denied: permission_denied"),
        registry(stderr="dial tcp: i/o timeout"),
    ],
    ids=["published", "denied", "network"],
)
def test_manifest_check_fails_closed(repo, run):
    assert release.main(["validate", "0.2.0"], repo, run) == 1
    assert release.main(["manifest-absent", "0.2.0"], repo, run) == 1


def test_manifest_unknown_means_absent(repo):
    run = registry(stderr="MANIFEST_UNKNOWN: manifest unknown")
    assert release.main(["manifest-absent", "0.2.0"], repo, run) == 0


def test_notes_are_one_section():
    assert release.notes(CHANGELOG, "0.2.0") == "### Added\n\n- Second.\n"
    assert release.notes(CHANGELOG, "0.1.0") == "- First.\n"


def test_empty_section_is_refused():
    with pytest.raises(release.ReleaseError, match="empty"):
        release.notes("## [1.0.0]\n\n## [0.9.0]\n\n- x\n", "1.0.0")


def test_bump_sets_version_and_adds_image_once():
    original = (ROOT / release.CONFIG).read_text()
    first = release.bump(original, "0.2.0")
    second = release.bump(first, "0.3.0")
    for text, version in ((first, "0.2.0"), (second, "0.3.0")):
        data = yaml.safe_load(text)
        assert data["version"] == version
        assert data["image"] == release.IMAGE
        assert text.count("\nimage:") == 1
    expected = yaml.safe_load(original) | {"version": "0.3.0", "image": release.IMAGE}
    assert yaml.safe_load(second) == expected


def test_the_repository_changelog_covers_the_current_version():
    version = release.config_version((ROOT / release.CONFIG).read_text())
    assert release.notes((ROOT / release.CHANGELOG).read_text(), version)


def test_the_guard_checks_the_image_the_workflow_publishes():
    """A mismatch would make every "already published" check pass silently."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yaml").read_text())["jobs"]
    owner = yaml.safe_load((ROOT / "repository.yaml").read_text())["url"].split("/")[-2]
    for job, publisher in (("build", "build-image"), ("manifest", "publish-multi-arch-manifest")):
        steps = jobs[job]["steps"]
        guard = next(i for i, s in enumerate(steps) if "manifest-absent" in s.get("run", ""))
        publish = next(i for i, s in enumerate(steps) if publisher in s.get("uses", ""))
        assert guard < publish, job
    inputs = steps[publish]["with"]
    prefix = inputs["registry-prefix"].replace("${{ github.repository_owner }}", owner)
    assert release.IMAGE == f"{prefix}/{inputs['image-name']}"
    assert jobs["github-release"]["needs"] == "manifest"


@pytest.mark.parametrize("argv", [[], ["validate"], ["publish", "1.0.0"]])
def test_usage(argv):
    assert release.main(argv) == 2
