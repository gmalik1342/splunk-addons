"""Consistency checks on the package: versions, names, knowledge objects, dashboard."""

import configparser
import json
import os
import re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(__file__)
PKG = os.path.join(HERE, "..", "package")
DEFAULT = os.path.join(PKG, "default")

APP_ID = "TA-pinecone-audit-logs"
TITLE = "Audit Logs Add-on for Pinecone"


def conf(name):
    cp = configparser.RawConfigParser(strict=True, delimiters=("=",), comment_prefixes=("#",))
    cp.optionxform = str
    with open(os.path.join(DEFAULT, name)) as fh:
        cp.read_file(fh)
    return cp


def test_versions_match():
    app = conf("app.conf")
    manifest = json.load(open(os.path.join(PKG, "app.manifest")))
    version = manifest["info"]["id"]["version"]
    assert app["launcher"]["version"] == version
    assert app["id"]["version"] == version
    assert re.search(r"^Version: {}$".format(re.escape(version)),
                     open(os.path.join(PKG, "README.txt")).read(), re.M)
    assert re.search(r"^{}\s".format(re.escape(version)),
                     open(os.path.join(PKG, "README.txt")).read().split("Release notes")[-1], re.M)


def test_names_match():
    app = conf("app.conf")
    manifest = json.load(open(os.path.join(PKG, "app.manifest")))
    assert app["ui"]["label"] == manifest["info"]["title"] == TITLE
    assert app["package"]["id"] == app["id"]["name"] == manifest["info"]["id"]["name"] == APP_ID
    assert "splunk" not in TITLE.lower()
    assert manifest["platformRequirements"]["splunk"]["Enterprise"] == "*"
    assert manifest["info"]["author"][0]["name"] == "Gaurav Malik"


def test_tags_reference_eventtypes():
    eventtypes = conf("eventtypes.conf").sections()
    for stanza in conf("tags.conf").sections():
        assert stanza.startswith("eventtype=")
        assert stanza.split("=", 1)[1] in eventtypes
    for et in eventtypes:
        assert 'sourcetype="pinecone:audit"' in conf("eventtypes.conf")[et]["search"]


def test_dashboard_is_simplexml_11_and_uses_macro():
    path = os.path.join(DEFAULT, "data", "ui", "views", "pinecone_audit_overview.xml")
    root = ET.parse(path).getroot()
    assert root.get("version") == "1.1"
    queries = [q.text for q in root.iter("query")]
    assert queries and all(q.startswith("`pinecone_audit`") for q in queries)
    assert "pinecone_audit" in conf("macros.conf").sections()
    assert not any(el.get("script") for el in root.iter())  # no custom JS
    nav = ET.parse(os.path.join(DEFAULT, "data", "ui", "nav", "default.xml")).getroot()
    assert nav.find("view").get("name") == "pinecone_audit_overview"


def test_no_python_hidden_or_binary_files():
    for dirpath, dirnames, filenames in os.walk(PKG):
        for name in dirnames + filenames:
            assert not name.startswith("."), os.path.join(dirpath, name)
            assert not name.endswith((".py", ".pyc", ".so", ".dll", ".exe", ".dylib", ".pyd"))
    assert not os.path.exists(os.path.join(PKG, "local"))
    assert not os.path.exists(os.path.join(PKG, "metadata", "local.meta"))


def test_icons_present_and_sized():
    import struct
    for name, size in (("appIcon.png", 36), ("appIcon_2x.png", 72),
                       ("appIconAlt.png", 36), ("appIconAlt_2x.png", 72)):
        with open(os.path.join(PKG, "static", name), "rb") as fh:
            head = fh.read(24)
        assert head[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", head[16:24]) == (size, size)
