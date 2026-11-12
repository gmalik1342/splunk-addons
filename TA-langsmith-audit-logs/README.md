# Audit Logs Add-on for LangSmith (TA-langsmith-audit-logs)

| | |
|---|---|
| App ID | `TA-langsmith-audit-logs` |
| Title | Audit Logs Add-on for LangSmith |
| Author | Gaurav Malik |
| Version | 1.0.0 |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x (Python 3.9 / 3.13) |

Collects [LangSmith audit logs](https://docs.langchain.com/langsmith/audit-logs) (Enterprise) from
[`GET /api/v1/audit-logs`](https://docs.langchain.com/langsmith/smith-api/audit-logs/get-audit-logs):
`X-API-Key` + `X-Organization-Id` headers, inclusive `start_time`/`end_time` (ISO 8601, both required),
`limit` ≤ 100, `cursor` paging, optional `operations[]` and `workspace_id`. Items are OCSF v1.7 API Activity
(class 6003). Retention up to 400 days.

| Region | Base URL |
|---|---|
| US | `https://api.smith.langchain.com` |
| EU | `https://eu.api.smith.langchain.com` |
| APAC | `https://apac.api.smith.langchain.com` |
| AWS US | `https://aws.api.smith.langchain.com` |
| Self-hosted | `https://<your host>` (Helm 0.12.33+, audit logs enabled) |

Sourcetype `langsmith:audit`; input type `langsmith_audit_logs`; REST root `TA_langsmith_audit_logs`.

## Layout

```
globalConfig.json                       UCC: account (region, self-hosted URL, org ID, API key), proxy, logging, input
package/
  bin/langsmith_audit/client.py         headers, regions, cursor paging, retries, HTTPS only
  bin/langsmith_audit/collector.py      ≤6 h closed windows, 10 min overlap, metadata.uid dedupe
  bin/langsmith_audit/modinput.py       splunklib Script + solnlib config/logging/KV Store checkpoint
  bin/langsmith_audit_logs.py           modular input entry point
  bin/langsmith_account_handler.py      validates the key on account save
  default/ props, eventtypes, tags      OCSF → CIM Authentication + Change (+account)
tests/test_langsmith_audit.py           fake LangSmith API: windows, inclusive edges, late events, cursors, retries
build.sh                                test → ucc-gen build → package → AppInspect (cloud)
```

## Build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh        # dist/TA-langsmith-audit-logs-1.0.0.tar.gz + dist/appinspect_report.json
```

## Before publishing: check against a real organization

The API reference doesn't say:
- the unit of OCSF `time`. OCSF uses epoch milliseconds, and the collector also accepts seconds and microseconds;
- how the next page is requested. The add-on passes the returned `cursor` back as the `cursor` query parameter;
- how repeated `operations` are encoded. The add-on repeats `operations=<op>`;
- rate limits. The add-on spaces requests 0.25 s apart and retries 429.

Confirm these with a real Enterprise org (one run with DEBUG logging) before uploading.
