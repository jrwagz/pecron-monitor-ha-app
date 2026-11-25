#!/usr/bin/env python3
"""Checks and file edits for .github/workflows/release.yaml. Standard library only.

release.py validate VERSION         every precondition of a release
release.py manifest-absent VERSION  refuse once the release manifest is published
release.py notes VERSION            print the changelog section
release.py bump VERSION             set version (and image) in config.yaml
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = "pecron_monitor_ha_app/config.yaml"
CHANGELOG = "pecron_monitor_ha_app/CHANGELOG.md"
IMAGE = "ghcr.io/jrwagz/pecron-monitor-ha-app"

# SemVer 2.0.0 without build metadata: "+" is not allowed in an image tag.
_NUMBER = r"(?:0|[1-9]\d*)"
_IDENTIFIER = rf"(?:{_NUMBER}|\d*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
)
_VERSION_LINE = re.compile(r'^version:[ \t]*["\']?([^"\'\s#]+)["\']?[^\n]*$', re.MULTILINE)


class ReleaseError(Exception):
    pass


def parse(version: str) -> tuple:
    """Return a key that sorts in SemVer precedence order."""
    match = _SEMVER.fullmatch(version)
    if not match:
        raise ReleaseError(f"{version!r} is not a SemVer version such as 1.2.3 or 1.2.3-rc.1")
    pre = match[4]
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in (pre.split(".") if pre else ())
    )
    # A release sorts after its pre-releases.
    return int(match[1]), int(match[2]), int(match[3]), pre is None, identifiers


def config_version(config: str) -> str:
    match = _VERSION_LINE.search(config)
    if not match:
        raise ReleaseError(f"no version line in {CONFIG}")
    return match[1]


def notes(changelog: str, version: str) -> str:
    """Return the text under the version's "## [x.y.z]" heading."""
    heading = re.compile(rf"^## \[?{re.escape(version)}\]?(?:[ \t].*)?$", re.MULTILINE)
    match = heading.search(changelog)
    if not match:
        raise ReleaseError(f"{CHANGELOG} has no '## [{version}]' heading")
    rest = changelog[match.end() :]
    # The section ends at the next version or at the link definitions.
    end = re.search(r"^(?:## |\[[^\]]+\]:)", rest, re.MULTILINE)
    body = rest[: end.start() if end else None].strip()
    if not body:
        raise ReleaseError(f"the {version} section of {CHANGELOG} is empty")
    return body + "\n"


def check_order(version: str, current: str, tags: list[str]) -> None:
    new, old = parse(version), parse(current)
    if f"v{version}" in tags:
        raise ReleaseError(f"git tag v{version} already exists")
    released = any(tag.startswith("v") for tag in tags)
    if new < old or (new == old and released):
        needed = "greater than" if released else "at least"
        raise ReleaseError(f"{version} must be {needed} the version in {CONFIG} ({current})")


def check_manifest_absent(version: str, run: Callable = subprocess.run) -> None:
    """Fail unless the registry says the tag does not exist. Needs a registry login."""
    ref = f"{IMAGE}:{version}"
    result = run(["docker", "buildx", "imagetools", "inspect", ref], capture_output=True, text=True)
    if result.returncode == 0:
        raise ReleaseError(f"{ref} is already published; a published tag never changes")
    output = result.stderr + result.stdout
    missing = (f"{ref}: not found", "manifest unknown", "MANIFEST_UNKNOWN")
    if not any(text in output for text in missing):
        raise ReleaseError(f"could not check whether {ref} exists: {output.strip()}")


def bump(config: str, version: str) -> str:
    """Set the version and, if there is none yet, add the image key after it."""
    config_version(config)  # fail loudly if there is nothing to replace
    lines = f'version: "{version}"'
    if not re.search(r"^image:", config, re.MULTILINE):
        lines += f"\nimage: {IMAGE}"
    return _VERSION_LINE.sub(lambda _: lines, config, count=1)


def git_tags(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "tag", "--list"], capture_output=True, text=True, check=True
    )
    return result.stdout.split()


def main(argv: list[str], root: Path = ROOT, run: Callable = subprocess.run) -> int:
    commands = ("validate", "manifest-absent", "notes", "bump")
    if len(argv) != 2 or argv[0] not in commands:
        print(f"usage: release.py {'|'.join(commands)} VERSION", file=sys.stderr)
        return 2
    command, version = argv
    try:
        parse(version)
        if command == "validate":
            notes((root / CHANGELOG).read_text(encoding="utf-8"), version)
            current = config_version((root / CONFIG).read_text(encoding="utf-8"))
            check_order(version, current, git_tags(root))
            check_manifest_absent(version, run)
            print(f"{version} can be released")
        elif command == "manifest-absent":
            check_manifest_absent(version, run)
        elif command == "notes":
            print(notes((root / CHANGELOG).read_text(encoding="utf-8"), version), end="")
        else:
            path = root / CONFIG
            path.write_text(bump(path.read_text(encoding="utf-8"), version), encoding="utf-8")
    except (ReleaseError, OSError, subprocess.CalledProcessError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
