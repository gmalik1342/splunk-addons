# Audit Logs Add-on for Cursor (TA-cursor-audit-logs)

| | |
|---|---|
| App ID | `TA-cursor-audit-logs` |
| Title | Audit Logs Add-on for Cursor |
| Author | Gaurav Malik |
| Version | 1.0.0 |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x (Python 3.9 / 3.13) |

Collects [Cursor audit logs](https://cursor.com/docs/enterprise/compliance-and-monitoring) from the
[Cursor Admin API](https://cursor.com/docs/account/teams/admin-api) (Enterprise plan).

| Key type | Endpoint | Notes |
|---|---|---|
| Team API key | `GET https://api.cursor.com/teams/audit-logs` | one team |
| Organization API key (`auditlogs:read` or `admin:*`) | `GET https://api.cursor.com/organizations/audit-logs` | all linked teams + org events; optional `teamId` |

Basic auth (key as username). `startTime`/`endTime` (epoch ms here), at most 30 days per request,
`page` (1-indexed) / `pageSize` (≤ 500), oldest first, `eventTypes` filter. Rate limit: 20 requests/minute/team.

Sourcetype `cursor:audit`; input type `cursor_audit_logs`; REST root `TA_cursor_audit_logs`.

## Layout

```
globalConfig.json                     UCC: account (key type, API key, team ID), proxy, logging, input
package/
  bin/cursor_audit/client.py          basic auth, team/org endpoints, 3.2 s pacing, retries, HTTPS only
  bin/cursor_audit/collector.py       ≤6 h closed windows, 10 min overlap, event_id dedupe, page paging
  bin/cursor_audit/modinput.py        splunklib Script + solnlib config/logging/KV Store checkpoint
  bin/cursor_audit_logs.py            modular input entry point
  bin/cursor_account_handler.py       validates the key on account save
  default/ props, eventtypes, tags    CIM Authentication + Change (+account)
tests/test_cursor_audit.py            fake Cursor API: windows, inclusive edges, late events, paging, retries
build.sh                              test → ucc-gen build → package → AppInspect (cloud)
```

## Build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh        # dist/TA-cursor-audit-logs-1.0.0.tar.gz + dist/appinspect_report.json
```

## Before publishing

Test against a real Enterprise team. The docs show `login`, `add_user` and `team_settings` by name;
the CIM `action` / `object_category` rules match on event-type words (`add_`, `remove_`, `api_key`, `user`, …),
so check them against real `event_type` values and adjust `props.conf` if needed.

Cursor can also stream audit events to Splunk HEC on request (contact Cursor). If a customer uses that,
they should set the HEC token's sourcetype to `cursor:audit` so these field mappings apply, and not run this input as well.
