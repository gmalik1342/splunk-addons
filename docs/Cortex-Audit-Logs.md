# Audit Logs Add-on for Palo Alto Networks Cortex

| | |
|---|---|
| App ID | `TA-palo-alto-cortex-audit-logs` |
| Version | 1.0.1 |
| Inputs | `cortex_audit_management_logs`, `cortex_audit_agent_reports` |
| Sourcetypes | `cortex:audit:management_logs`, `cortex:audit:agent_reports` |
| Splunk | Enterprise 10.2+ and Cloud 10.2+ (Python 3.13) |
| CIM | Authentication |
| Source | [`TA-palo-alto-cortex-audit-logs`](../TA-palo-alto-cortex-audit-logs) |

Collects audit data from the Palo Alto Networks Cortex public API.

| Input | API endpoint | Event time |
|---|---|---|
| Cortex Audit Management Logs | `POST /public_api/v1/audits/management_logs` | `AUDIT_INSERT_TIME` |
| Cortex Audit Agent Reports | `POST /public_api/v1/audits/agents_reports` | `TIMESTAMP` |

> **Why Splunk 10.2+?** The add-on bundles the Splunk SDK for Python 3.x, which requires Python 3.13. Splunk ships Python 3.13 from 10.2.

## Prerequisites in Cortex

1. **Settings > Configurations > API Keys > + New Key.** The Advanced key type is recommended. Use a role that can view audit logs (Instance Administrator, or a custom role with Audit Logs view).
2. Note the **API Key**, **API Key ID** and **API URL** (*Copy API URL*).
3. The management logs API requires a Cortex license that includes it; otherwise it returns HTTP 402.

## Setup

1. **Configuration > Accounts > Add:** API URL, API Key ID, key type (Advanced or Standard) and API Key.
2. Optional: **Configuration > Proxy**, **Configuration > Logging**.
3. **Inputs > Create New Input**, choose the input type and set:

| Setting | Meaning | Default |
|---|---|---|
| Interval | Poll frequency, 60–86400 s | 300 |
| Index | Destination index | default |
| Start Time (UTC) | First-run start, `YYYY-MM-DDThh:mm:ssZ` | 24 hours back |
| Ingestion Delay | Seconds behind real time, so late records aren't missed | 60 (management logs), 300 (agent reports) |
| Categories | Agent reports only: `audit`, `monitoring`, `status` | all |

## How collection works

Each run collects closed time windows of at most one hour, from the last checkpoint up to *now − Ingestion Delay*, paging 100 records at a time. The KV Store checkpoint (`ta_palo_alto_cortex_audit_logs_checkpoints`) advances only after a window is fully written, so nothing is skipped. If a run stops mid-window, that window is collected again, which can produce a few duplicates. Catch-up runs stop after about 55 minutes and resume on the next run.

## Data and CIM

Management log events with `AUDIT_ENTITY=AUTH` are tagged for the CIM **Authentication** data model (eventtype `cortex_audit_authentication`). Field aliases: `user`, `user_name`, `src`, `dest`, `action`, `status`, `severity`, `signature`, `vendor_product`.

## Searches

```
sourcetype=cortex:audit:management_logs | stats count BY AUDIT_ENTITY AUDIT_ENTITY_SUBTYPE
```
```
| datamodel Authentication search | search sourcetype=cortex:audit:management_logs
```

## Troubleshooting

Logs: `index=_internal source=*ta_palo_alto_cortex_audit_logs*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong API URL, key, key ID or key type |
| HTTP 402 | The tenant's license doesn't include the API |
| HTTP 403 | The API key's role lacks audit log permission |

See also [Troubleshooting](Troubleshooting.md).

## Release notes

- **1.0.1** – Renamed to "Audit Logs Add-on for Palo Alto Networks Cortex" to follow the Splunkbase naming conventions. No functional changes.
- **1.0.0** – Initial release: management logs and agent reports inputs, Standard and Advanced API keys, proxy support, KV Store checkpointing, credential validation, CIM Authentication mapping.
