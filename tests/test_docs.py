"""The user documentation holds no real network addresses."""

import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP = ROOT / "pecron_monitor_ha_app"
DOCUMENTATION_NETS = [
    ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]


def test_docs_only_use_documentation_ip_addresses():
    for path in (ROOT / "README.md", APP / "README.md", APP / "DOCS.md"):
        for found in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)", path.read_text()):
            address = ipaddress.ip_address(found)
            assert any(address in net for net in DOCUMENTATION_NETS), f"{path.name}: {found}"
