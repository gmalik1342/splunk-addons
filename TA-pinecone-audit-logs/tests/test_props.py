"""Emulates Splunk's index-time parsing of pinecone:audit on sample files.

Splunk semantics reproduced here:
  * LINE_BREAKER: the first capture group is the delimiter; it is removed and
    a new event starts after it.
  * SEDCMD s/regex/replacement/ applied to each event.
  * TRANSFORMS nullQueue drops events whose raw text matches the regex.
  * TIME_PREFIX regex, then TIME_FORMAT within MAX_TIMESTAMP_LOOKAHEAD chars.
"""

import configparser
import json
import os
import re
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(__file__)
DEFAULT = os.path.join(HERE, "..", "package", "default")
SAMPLES = os.path.join(HERE, "samples")


def read_conf(name):
    cp = configparser.RawConfigParser(strict=True, delimiters=("=",), comment_prefixes=("#",))
    cp.optionxform = str  # keep key case
    with open(os.path.join(DEFAULT, name)) as fh:
        cp.read_file(fh)
    return cp


PROPS = read_conf("props.conf")["pinecone:audit"]
TRANSFORMS = read_conf("transforms.conf")


def splunk_sed(expr, text):
    m = re.fullmatch(r"s/(.*)/(.*)/(g?)", expr)
    assert m, expr
    return re.sub(m.group(1), m.group(2), text, count=0 if m.group(3) else 1)


def parse(raw):
    breaker = re.compile(PROPS["LINE_BREAKER"])
    events, pos = [], 0
    for m in breaker.finditer(raw):
        events.append(raw[pos:m.start(1)])
        pos = m.end(1)
    events.append(raw[pos:])
    out = []
    for ev in events:
        for key in sorted(k for k in PROPS if k.startswith("SEDCMD-")):
            ev = splunk_sed(PROPS[key], ev)
        dropped = False
        for name in PROPS["TRANSFORMS-pinecone_drop_non_events"].split(","):
            t = TRANSFORMS[name.strip()]
            if t["FORMAT"] == "nullQueue" and re.search(t["REGEX"], ev):
                dropped = True
        if ev.strip() and not dropped:
            out.append(ev)
    return out


def event_time(ev):
    m = re.search(PROPS["TIME_PREFIX"], ev)
    assert m, "TIME_PREFIX not found"
    window = ev[m.end():m.end() + int(PROPS["MAX_TIMESTAMP_LOOKAHEAD"])]
    py_fmt = PROPS["TIME_FORMAT"].replace("%3N", "%f")
    text = window[:24]  # 2024-10-21T20:51:53.697Z
    return datetime.strptime(text, py_fmt).replace(tzinfo=timezone.utc)


EXPECTED = json.load(open(os.path.join(SAMPLES, "expected.json")))


@pytest.mark.parametrize("sample", [
    "ndjson.json", "ndjson_crlf.json", "ndjson_sorted_keys.json", "array_compact.json",
    "array_spaced.json", "array_lines.json", "array_sorted_keys.json",
])
def test_event_breaking(sample):
    raw = open(os.path.join(SAMPLES, sample), newline="").read()
    events = parse(raw)
    assert [json.loads(e) for e in events] == EXPECTED
    for ev, exp in zip(events, EXPECTED):
        assert event_time(ev) == datetime.strptime(
            exp["event"]["time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def test_nested_parameters_do_not_split():
    raw = open(os.path.join(SAMPLES, "array_compact.json")).read()
    assert '},{"id":"x2"' in raw  # the trap is present
    assert len(parse(raw)) == len(EXPECTED)


def test_access_test_file_dropped():
    raw = open(os.path.join(SAMPLES, "audit-log-access-test")).read()
    assert parse(raw) == []


def test_time_prefix_hits_event_time_not_parameters():
    ev = parse(open(os.path.join(SAMPLES, "ndjson.json")).read())[0]
    assert event_time(ev).isoformat().startswith("2024-10-21T20:51:53.697")


def test_search_time_settings():
    assert PROPS["KV_MODE"] == "json"
    assert PROPS["SHOULD_LINEMERGE"] == "false"
    assert PROPS["TZ"] == "UTC"
    evals = {k for k in PROPS if k.startswith("EVAL-")}
    for field in ("action", "user", "dest", "app", "status", "object", "object_category",
                  "change_type", "vendor_product", "signature"):
        assert "EVAL-" + field in evals
