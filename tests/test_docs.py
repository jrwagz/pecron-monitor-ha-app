import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
APP = ROOT / "pecron_monitor_ha_app"
DOCUMENTATION_NETS = [
    ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]


def schema_paths(node, prefix=""):
    if isinstance(node, list):  # list of objects, e.g. devices
        node = node[0]
    if not isinstance(node, dict):
        return
    for key, child in node.items():
        yield prefix + key
        yield from schema_paths(child, f"{prefix}{key}.")


def test_every_schema_key_path_is_documented():
    schema = yaml.safe_load((APP / "config.yaml").read_text())["schema"]
    docs = (APP / "DOCS.md").read_text()
    paths = list(schema_paths(schema))
    assert "devices.lan_ip" in paths
    assert [p for p in paths if f"`{p}`" not in docs] == []


def test_docs_only_use_documentation_ip_addresses():
    for path in (ROOT / "README.md", APP / "README.md", APP / "DOCS.md"):
        for found in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)", path.read_text()):
            address = ipaddress.ip_address(found)
            assert any(address in net for net in DOCUMENTATION_NETS), f"{path.name}: {found}"
