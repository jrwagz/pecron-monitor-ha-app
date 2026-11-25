"""The app manifest's options, schema and translations agree."""

from pathlib import Path

import yaml

APP = Path(__file__).resolve().parent.parent / "pecron_monitor_ha_app"
MANIFEST = yaml.safe_load((APP / "config.yaml").read_text())
TRANSLATIONS = yaml.safe_load((APP / "translations" / "en.yaml").read_text())["configuration"]

EXCLUDED = {
    "alerts",
    "rules",
    "rule_state",
    "rule_state_path",
    "auto_discover",
    "tsl_cache",
    "energy_state_path",
}


def schema_paths(node, prefix=()):
    """Yield the key path of every schema entry; lists of mappings are descended."""
    if isinstance(node, list):
        node = node[0]
    for key, value in node.items():
        path = (*prefix, key)
        yield path
        if isinstance(value, (dict, list)):
            yield from schema_paths(value, path)


def translation_for(path):
    entry = TRANSLATIONS[path[0]]
    for key in path[1:]:
        entry = entry["fields"][key]
    return entry


def test_every_schema_key_has_name_and_description():
    for path in schema_paths(MANIFEST["schema"]):
        entry = translation_for(path)
        assert entry.get("name"), path
        assert entry.get("description"), path


def test_translations_have_no_unknown_keys():
    def walk(node, schema, prefix=()):
        if isinstance(schema, list):
            schema = schema[0]
        for key, entry in node.items():
            assert key in schema, (*prefix, key)
            if "fields" in entry:
                walk(entry["fields"], schema[key], (*prefix, key))

    walk(TRANSLATIONS, MANIFEST["schema"])


def test_every_option_exists_in_schema():
    def walk(options, schema, prefix=()):
        for key, value in options.items():
            assert key in schema, (*prefix, key)
            if isinstance(value, dict):
                walk(value, schema[key], (*prefix, key))

    walk(MANIFEST["options"], MANIFEST["schema"])


def test_excluded_library_keys_are_absent():
    keys = {path[-1] for path in schema_paths(MANIFEST["schema"])}
    assert keys.isdisjoint(EXCLUDED)
    # homeassistant.enabled is always on; the only "enabled" key is restore's.
    assert "homeassistant" not in MANIFEST["schema"]
    assert "enabled" not in MANIFEST["schema"]["mqtt"]


def test_secrets_use_password_type():
    schema = MANIFEST["schema"]
    assert schema["account"]["password"] == "password?"
    assert schema["devices"][0]["auth_key"] == "password?"
    assert schema["mqtt"]["password"] == "password?"
