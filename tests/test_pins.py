"""Pinned versions in the Dockerfile and requirements files are exact."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "pecron_monitor_ha_app"


def dockerfile_args() -> dict[str, str]:
    text = (APP / "Dockerfile").read_text()
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", text, re.MULTILINE))


def test_base_image_tag_is_release_suffixed():
    base = dockerfile_args()["BUILD_FROM"]
    # e.g. ghcr.io/home-assistant/base-python:3.14-alpine3.24-2026.11.0
    pattern = r"ghcr\.io/home-assistant/base-python:\d+\.\d+-alpine\d+\.\d+-\d{4}\.\d+\.\d+"
    assert re.fullmatch(pattern, base)


def test_library_pin():
    args = dockerfile_args()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", args["PECRON_MONITOR_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{40}", args["PECRON_MONITOR_SHA"])


def requirement_lines(path: Path) -> list[str]:
    lines = [ln.split("#")[0].strip() for ln in path.read_text().splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("-r ")]


def test_requirements_are_exact_pins():
    for path in (APP / "requirements.txt", ROOT / "requirements-dev.txt"):
        for line in requirement_lines(path):
            pin = re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*", line)
            assert pin, f"{path.name}: {line}"


def test_no_ble_dependencies():
    names = {ln.split("==")[0].lower() for ln in requirement_lines(APP / "requirements.txt")}
    assert names.isdisjoint({"pexpect", "bleak", "bluepy"})


def test_no_stray_app_manifests():
    # The Supervisor treats any config.yaml|yml|json at any depth as an app manifest.
    manifests = [
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("config.*")
        if p.suffix in {".yaml", ".yml", ".json"} and ".git" not in p.parts
    ]
    assert manifests == ["pecron_monitor_ha_app/config.yaml"]
