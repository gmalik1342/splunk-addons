"""Emulates Splunk's parsing of the Zscaler Deception sourcetypes on sample files.

Index time (reproduced as Splunk does it):
  * LINE_BREAKER: the first capture group is the delimiter; it is removed.
  * SEDCMD s/regex/replacement/ applied to each event.
  * TRANSFORMS nullQueue drops events whose raw text matches the regex.
  * TIME_PREFIX regex, then TIME_FORMAT within MAX_TIMESTAMP_LOOKAHEAD chars.
Search time:
  * KV_MODE=json: flat keys keep their names, arrays become "<key>{}"
    multi-value fields, booleans become "true"/"false".
  * EVAL-<field>: evaluated independently against the extracted fields, with
    a small evaluator for the SPL functions this add-on uses.
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
EVENTS_ST = "zscaler:deception:events"
AUDIT_ST = "zscaler:deception:audit"


def read_conf(name):
    cp = configparser.RawConfigParser(strict=True, delimiters=("=",), comment_prefixes=("#",))
    cp.optionxform = str
    with open(os.path.join(DEFAULT, name)) as fh:
        cp.read_file(fh)
    return cp


PROPS_ALL = read_conf("props.conf")
PROPS = PROPS_ALL[EVENTS_ST]
TRANSFORMS = read_conf("transforms.conf")
EXPECTED = json.load(open(os.path.join(SAMPLES, "expected.json")))


# --------------------------------------------------------------- index time
def splunk_sed(expr, text):
    m = re.fullmatch(r"s/(.*)/(.*)/(g?)", expr)
    assert m, expr
    repl = re.sub(r"\\(\d)", r"\\g<\1>", m.group(2))
    return re.sub(m.group(1), repl, text, count=0 if m.group(3) else 1)


def parse(raw, props=PROPS):
    breaker = re.compile(props["LINE_BREAKER"])
    events, pos = [], 0
    for m in breaker.finditer(raw):
        events.append(raw[pos:m.start(1)])
        pos = m.end(1)
    events.append(raw[pos:])
    out = []
    for ev in events:
        if not ev.strip():
            continue
        dropped = False
        for key in (k for k in props if k.startswith("TRANSFORMS-")):
            for name in props[key].split(","):
                t = TRANSFORMS[name.strip()]
                if t["FORMAT"] == "nullQueue" and re.search(t["REGEX"], ev):
                    dropped = True
        for key in sorted(k for k in props if k.startswith("SEDCMD-")):
            ev = splunk_sed(props[key], ev)
        # Drop must hold whichever order Splunk applies SEDCMD and TRANSFORMS.
        for key in (k for k in props if k.startswith("TRANSFORMS-")):
            for name in props[key].split(","):
                t = TRANSFORMS[name.strip()]
                if t["FORMAT"] == "nullQueue" and re.search(t["REGEX"], ev):
                    assert dropped, "drop decision depends on SEDCMD order"
        if not dropped:
            out.append(ev)
    return out


def event_time(raw):
    m = re.search(PROPS["TIME_PREFIX"], raw)
    assert m, "TIME_PREFIX not found"
    window = raw[m.end():m.end() + int(PROPS["MAX_TIMESTAMP_LOOKAHEAD"])]
    return datetime.strptime(window[:19], PROPS["TIME_FORMAT"]).replace(tzinfo=timezone.utc)


# -------------------------------------------------------------- search time
def kv_json(raw):
    fields = {}
    for key, value in json.loads(raw).items():
        if isinstance(value, list):
            fields[key + "{}"] = [str(v) for v in value]
        elif isinstance(value, bool):
            fields[key] = "true" if value else "false"
        elif value is not None:
            fields[key] = str(value)
    return fields


TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<field>\'[^\']+\')|(?P<num>\d+(?:\.\d+)?)'
                   r'|(?P<op>==|!=|[(),.])|(?P<word>[A-Za-z_][A-Za-z0-9_]*))')


def tokenize(expr):
    pos, out = 0, []
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        assert m and m.end() > pos, "cannot parse EVAL at: " + expr[pos:]
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class Eval:
    """Recursive-descent evaluator for the SPL subset used in props.conf."""

    FUNCS = {"coalesce", "case", "lower", "null", "true", "if", "in"}

    def __init__(self, expr, fields):
        self.toks, self.i, self.f = tokenize(expr), 0, fields
        self.refs = []

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        assert value is None or tok[1] == value, (tok, value)
        self.i += 1
        return tok

    def run(self):
        v = self.or_()
        assert self.i == len(self.toks), self.toks[self.i:]
        return v

    def or_(self):
        v = self.and_()
        while self.peek() == ("word", "OR"):
            self.take()
            r = self.and_()
            v = bool(v) or bool(r)
        return v

    def and_(self):
        v = self.cmp()
        while self.peek() == ("word", "AND"):
            self.take()
            r = self.cmp()
            v = bool(v) and bool(r)
        return v

    def cmp(self):
        v = self.concat()
        if self.peek()[1] in ("==", "!="):
            op = self.take()[1]
            r = self.concat()
            if v is None or r is None:
                return None
            return (v == r) if op == "==" else (v != r)
        return v

    def concat(self):
        v = self.primary()
        while self.peek()[1] == ".":
            self.take()
            r = self.primary()
            v = None if v is None or r is None else str(v) + str(r)
        return v

    def args(self):
        self.take("(")
        out = []
        if self.peek()[1] != ")":
            out.append(self.or_())
            while self.peek()[1] == ",":
                self.take()
                out.append(self.or_())
        self.take(")")
        return out

    def primary(self):
        kind, val = self.take()
        if kind == "str":
            return json.loads(val)
        if kind == "num":
            return val
        if kind == "field":
            name = val[1:-1]
            self.refs.append(name)
            return self.f.get(name)
        if val == "(":
            v = self.or_()
            self.take(")")
            return v
        assert kind == "word" and val in self.FUNCS, val
        a = self.args()
        if val == "null":
            return None
        if val == "true":
            return True
        if val == "lower":
            return None if a[0] is None else str(a[0]).lower()
        if val == "coalesce":
            return next((x for x in a if x is not None), None)
        if val == "if":
            return a[1] if a[0] else a[2]
        if val == "in":
            return None if a[0] is None else a[0] in a[1:]
        if val == "case":
            for cond, res in zip(a[::2], a[1::2]):
                if cond:
                    return res
            return None
        raise AssertionError(val)


def search_time(raw, props=PROPS):
    fields = kv_json(raw)
    out = dict(fields)
    for key in (k for k in props if k.startswith("EVAL-")):
        out[key[5:]] = Eval(props[key], fields).run()  # EVALs read original values
    return {k: v for k, v in out.items() if v is not None}


# -------------------------------------------------------------------- tests
@pytest.mark.parametrize("sample", ["syslog_rfc5424.log", "syslog_rfc3164.log",
                                    "hec_raw.json", "hec_raw_crlf.json"])
def test_event_breaking_and_header_removal(sample):
    raw = open(os.path.join(SAMPLES, sample), newline="").read()
    events = parse(raw)
    assert [json.loads(e) for e in events] == EXPECTED
    for ev, exp in zip(events, EXPECTED):
        assert ev.startswith("{") and ev.endswith("}")
        assert event_time(ev) == datetime.strptime(
            exp["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def test_timestamp_found_before_header_removal():
    # Timestamp extraction happens before SEDCMD, on the raw syslog line.
    line = open(os.path.join(SAMPLES, "syslog_rfc5424.log")).readline()
    assert line.startswith("<26>1 2024-12-04T22:29:58.000Z")
    assert event_time(line).isoformat() == "2024-12-04T22:29:58+00:00"


def test_keepalive_dropped():
    raw = "<30>1 2024-12-05T08:30:00.000Z siem-connector Zscaler Deception 982 - - connector keep-alive\n"
    assert parse(raw) == []
    assert parse(raw, PROPS_ALL[AUDIT_ST]) == []


def test_real_recon_event_cim():
    f = search_time(parse(open(os.path.join(SAMPLES, "syslog_rfc5424.log")).read())[0])
    assert f["src"] == f["src_ip"] == "198.51.100.3"
    assert f["src_host"] == "198.51.100.4"
    assert f["src_port"] == "64537"
    assert f["dest"] == "abcd.com" and f["dest_ip"] == "198.51.100.4"
    assert f["dest_category"] == "External" and f["decoy_type"] == "recon"
    assert f["action"] == "allowed"
    assert f["severity"] == "medium"
    assert f["category"] == "Reconnaissance"
    assert f["ids_type"] == "network"
    assert f["signature"] == "Zscaler Deception recon activity"
    assert f["signature_id"] == f["deception_type"] == "recon"
    assert f["mitre_technique_id"] == ["T1594", "T1595", "T1133", "T1595.002"]
    assert f["threat_parse_id"] == ["recon_abuseipdb_low", "recon_activity"]
    assert f["http_method"] == "GET" and f["uri_path"] == "/remote/login" and f["status"] == "200"
    assert f["risk_score"] == "25" and f["attacker_score"] == "60"
    assert f["event_id"] == EXPECTED[0]["id"]
    assert f["vendor_product"] == "Zscaler Deception"
    assert f["description"] == "Zscaler Deception recon activity from 198.51.100.3 on decoy abcd.com"
    assert f["whitelisted"] == "false"
    assert "user" not in f and "src_user" not in f


def test_network_and_host_events():
    events = [search_time(e) for e in parse(open(os.path.join(SAMPLES, "hec_raw.json")).read())]
    ssh, endpoint = events[1], events[2]
    assert ssh["severity"] == "high"            # upper case is normalised
    assert ssh["ids_type"] == "network"
    assert "src_host" not in ssh                # name equals IP: not repeated
    assert endpoint["severity"] == "critical"
    assert endpoint["ids_type"] == "host"
    assert endpoint["user"] == endpoint["src_user"] == "CORP\\jdoe"
    assert endpoint["dest"] == "lure-credentials" and "dest_ip" not in endpoint
    assert endpoint["is_itdr"] == "true"
    assert "http_method" not in endpoint


@pytest.mark.parametrize("raw_sev,cim", [("LOW", "low"), ("Info", "informational"),
                                         ("informational", "informational"), ("bogus", "unknown")])
def test_severity_values(raw_sev, cim):
    assert search_time(json.dumps({"type": "web", "severity": raw_sev}))["severity"] == cim


@pytest.mark.parametrize("etype,ids_type", [("windows", "host"), ("ransomware", "host"), ("itdr", "host"),
                                            ("credtheft", "host"), ("aws", "application"),
                                            ("azure", "application"), ("QOS", "network"),
                                            ("mongodb", "network"), ("SSH", "network")])
def test_ids_type(etype, ids_type):
    assert search_time(json.dumps({"type": etype}))["ids_type"] == ids_type


def test_evals_are_independent():
    # Splunk evaluates EVALs independently; none may depend on another's output.
    names = {k[5:] for k in PROPS if k.startswith("EVAL-")}
    for key in (k for k in PROPS if k.startswith("EVAL-")):
        ev = Eval(PROPS[key], {})
        ev.run()
        for ref in ev.refs:
            assert ref not in names - {key[5:]}, (key, ref)


def test_whitelisted_kept_but_not_tagged():
    eventtypes = read_conf("eventtypes.conf")
    tags = read_conf("tags.conf")
    assert "NOT whitelisted=true" in eventtypes["zscaler_deception_detection"]["search"]
    assert set(tags["eventtype=zscaler_deception_detection"]) == {"ids", "attack", "alert"}
    assert "eventtype=zscaler_deception_whitelisted" not in tags.sections()
    assert len(parse(open(os.path.join(SAMPLES, "hec_raw.json")).read())) == 4


def test_settings():
    for st in (EVENTS_ST, AUDIT_ST):
        p = PROPS_ALL[st]
        assert p["KV_MODE"] == "json" and p["SHOULD_LINEMERGE"] == "false"
        assert p["EVAL-vendor_product"] == '"Zscaler Deception"'
    assert PROPS["TZ"] == "UTC"
    # Never touch the official add-on's or Splunk's built-in sourcetypes.
    for st in PROPS_ALL.sections():
        assert st.startswith("zscaler:deception:"), st
