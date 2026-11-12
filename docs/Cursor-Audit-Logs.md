# Audit Logs Add-on for Cursor

| | |
|---|---|
| App ID | `TA-cursor-audit-logs` |
| Version | 1.0.0 |
| Input | `cursor_audit_logs` |
| Sourcetype | `cursor:audit` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | Authentication, Change |
| Source | [`TA-cursor-audit-logs`](../TA-cursor-audit-logs) |

Collects [Cursor audit logs](https://cursor.com/docs/enterprise/compliance-and-monitoring) from the [Cursor Admin API](https://cursor.com/docs/account/teams/admin-api): sign-ins and sign-outs, members and roles, invites, API keys and service accounts, team settings, rules, MCP servers, integrations, directory groups, SSO, Cloud Agents, Bugbot and more. Each record is one JSON event, timestamped with `timestamp`.

| Key type | Endpoint |
|---|---|
| Team API key | `GET https://api.cursor.com/teams/audit-logs` (one team) |
| Organization API key (`auditlogs:read` or `admin:*`) | `GET https://api.cursor.com/organizations/audit-logs` (all linked teams plus org events; optionally one team) |

Audit logs need a **Cursor Enterprise** plan. Cursor doesn't log failed sign-ins, prompts, responses or generated code.

## Setup

1. Create an Admin API key in Cursor (Team key, or Organization key with `auditlogs:read`).
2. **Configuration > Accounts > Add:** key type, API key (stored encrypted, tested when you save), and for Organization keys an optional numeric Team ID.
3. Optional: **Configuration > Proxy**, **Configuration > Logging**.
4. **Inputs > Create New Input > Cursor Audit Logs:**

| Setting | Meaning | Default |
|---|---|---|
| Interval | Poll frequency, 60–86400 s | 300 |
| Index | Destination index | default |
| Start Time (UTC) | First-run start, `YYYY-MM-DDThh:mm:ssZ` | 24 hours back |
| Ingestion Delay | Seconds behind real time, 60–3600 | 300 |
| Event Types | Optional comma-separated filter, e.g. `login, add_user` | all |

## How collection works

- Collects closed windows of at most six hours, from the checkpoint up to *now − Ingestion Delay*, 500 events per page, oldest first (Cursor's docs say to page through consecutive windows; each request may span up to 30 days).
- Re-reads the last 10 minutes each run and de-duplicates on `event_id`, so late events aren't missed and nothing is ingested twice.
- The KV Store checkpoint (`ta_cursor_audit_logs_checkpoints`) advances only after a whole window is written. Catch-up runs stop after about 55 minutes and resume on the next run.
- Requests are spaced 3.2 s apart to stay within Cursor's 20 requests per minute per team; HTTP 429 is retried, honouring `Retry-After`.

## Data and CIM

Raw fields: `event_id`, `timestamp`, `ip_address`, `user_email`, `event_type`, `application_type`, `event_data{...}`.

| Normalised field | From |
|---|---|
| `user` / `src` | `user_email` / `ip_address` |
| `signature`, `command` | `event_type` |
| `action` | sign-ins: `success`; `add_`/`create_`: `created`; `remove_`/`delete_`/`revoke_`: `deleted`; otherwise `modified` |
| `object`, `object_category`, `change_type` | from `event_data` and the event type |

| Eventtype | Tags |
|---|---|
| `cursor_audit_authentication` | `authentication` |
| `cursor_audit_change` | `change` |
| `cursor_audit_account_change` | `change`, `account` |

## Searches

```
sourcetype=cursor:audit | stats count BY event_type
```
```
sourcetype=cursor:audit event_type=*api_key* | table _time user event_type event_data.*
```
```
| datamodel Authentication search | search sourcetype=cursor:audit
```

## Troubleshooting

Logs: `index=_internal source=*ta_cursor_audit_logs*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong API key, or wrong key type (Team vs Organization) |
| HTTP 403 | Not an Enterprise team, or the Organization key lacks `auditlogs:read` |
| HTTP 404 | Wrong key type for the endpoint |
| HTTP 429 warnings | Rate limit (20/min per team); the add-on waits and retries |

Cursor can also stream audit events to Splunk HEC on request. If you use that, set the HEC token's sourcetype to `cursor:audit` so these field mappings apply, and don't also run this input for the same team.

## Release notes

- **1.0.0**: Initial release. Cursor audit logs via the Admin API (Team or Organization keys); windowed collection with overlap and `event_id` de-duplication; 20 requests/minute pacing; encrypted, validated API key; proxy support; CIM Authentication and Change mapping; Python 3.9 and 3.13; Splunk Cloud compatible.

---
Cursor is a trademark of Anysphere, Inc. This add-on is not built, endorsed or supported by Anysphere.
