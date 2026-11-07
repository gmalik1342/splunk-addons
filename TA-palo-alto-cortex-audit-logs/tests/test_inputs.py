"""Checks on the modular input scripts using light stubs for Splunk-only modules."""

import json
import os
import sys
import types

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture()
def agent_module(monkeypatch):
    smi = types.SimpleNamespace(
        Argument=lambda *a, **k: (a, k), Script=object, Scheme=object,
    )
    splunklib = types.ModuleType("splunklib")
    splunklib.modularinput = smi
    stubs = {
        "import_declare_test": types.ModuleType("import_declare_test"),
        "splunklib": splunklib,
        "splunklib.modularinput": smi,
        "solnlib": types.SimpleNamespace(conf_manager=None, log=None),
        "solnlib.modular_input": types.SimpleNamespace(checkpointer=None),
    }
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "cortex_audit.modinput", raising=False)
    monkeypatch.delitem(sys.modules, "cortex_audit_agent_reports", raising=False)
    import cortex_audit_agent_reports
    return cortex_audit_agent_reports


def test_parse_categories(agent_module):
    assert agent_module.parse_categories("") == []
    assert agent_module.parse_categories("Status, audit,audit") == ["audit", "status"]
    with pytest.raises(ValueError):
        agent_module.parse_categories("audit,bogus")


def test_category_filter(agent_module):
    inp = agent_module.CortexAuditAgentReports.__new__(agent_module.CortexAuditAgentReports)
    assert inp.extra_filters({"categories": ""}) is None
    assert inp.extra_filters({"categories": "monitoring"}) == [
        {"field": "category", "operator": "in", "value": ["monitoring"]}
    ]


def test_global_config_matches_code():
    with open(os.path.join(ROOT, "globalConfig.json")) as fh:
        cfg = json.load(fh)
    from cortex_audit import ADDON_NAME, ADDON_VERSION, CONF_PREFIX
    from cortex_audit.collector import AGENT_REPORTS, MANAGEMENT_LOGS

    assert cfg["meta"]["name"] == ADDON_NAME
    assert cfg["meta"]["restRoot"].lower() == CONF_PREFIX
    assert cfg["meta"]["version"] == ADDON_VERSION
    services = {s["name"]: s for s in cfg["pages"]["inputs"]["services"]}
    assert set(services) == {MANAGEMENT_LOGS.input_type, AGENT_REPORTS.input_type}
    for svc in services.values():
        fields = {e["field"]: e for e in svc["entity"]}
        assert {"name", "account", "interval", "index", "start_time", "delay"} <= set(fields)
        assert fields["interval"]["required"] is True
    account = cfg["pages"]["configuration"]["tabs"][0]
    assert any(e["field"] == "api_key" and e.get("encrypted") for e in account["entity"])
    for script in services:
        assert os.path.isfile(os.path.join(ROOT, "package", "bin", script + ".py"))
    assert os.path.isfile(os.path.join(ROOT, "package", "bin", account["restHandlerModule"] + ".py"))


def test_versions_consistent():
    with open(os.path.join(ROOT, "package", "app.manifest")) as fh:
        manifest = json.load(fh)
    with open(os.path.join(ROOT, "package", "default", "app.conf")) as fh:
        app_conf = fh.read()
    from cortex_audit import ADDON_NAME, ADDON_VERSION

    assert manifest["info"]["id"]["name"] == ADDON_NAME
    assert manifest["info"]["id"]["version"] == ADDON_VERSION
    assert "version = {}".format(ADDON_VERSION) in app_conf
    assert manifest["info"]["author"][0]["name"] == "Gaurav Malik"
