# Audit Logs Add-on for LangSmith

| | |
|---|---|
| App ID | `TA-langsmith-audit-logs` |
| Version | 1.0.0 |
| Input | `langsmith_audit_logs` |
| Sourcetype | `langsmith:audit` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | Authentication, Change |
| Source | [`TA-langsmith-audit-logs`](../TA-langsmith-audit-logs) |

Collects [LangSmith audit logs](https://docs.langchain.com/langsmith/audit-logs) (LangChain) from `GET /api/v1/audit-logs`: API keys and tokens, roles, organization and workspace members, SSO, SCIM, logins, billing, retention settings, datasets, tracing projects, agents, prompts, deployments, bulk exports, MCP servers and more. Events are in **OCSF v1.7 API Activity** format (class 6003), one JSON event per record, timestamped with OCSF `time`; the original LangSmith record is under `unmapped.original_audit_log`.

Audit logs need a **LangSmith Enterprise** plan and an API key belonging to an **Organization Admin or Organization Operator**. LangSmith keeps them for up to 400 days.

| Region | API URL |
|---|---|
| US | `https://api.smith.langchain.com` |
| EU | `https://eu.api.smith.langchain.com` |
| APAC | `https://apac.api.smith.langchain.com` |
| AWS US | `https://aws.api.smith.langchain.com` |
| Self-hosted | your instance URL (Helm chart 0.12.33+, audit logs enabled for the organization) |

## Setup

1. **Configuration > Accounts > Add:** region (or *Self-hosted* and its URL), organization ID (UUID) and API key (stored encrypted, tested when you save).
2. Optional: **Configuration > Proxy**, **Configuration > Logging**.
3. **Inputs > Create New Input > LangSmith Audit Logs:**

| Setting | Meaning | Default |
|---|---|---|
| Interval | Poll frequency, 60–86400 s | 300 |
| Index | Destination index | default |
| Start Time (UTC) | First-run start, `YYYY-MM-DDThh:mm:ssZ` | 24 hours back |
| Ingestion Delay | Seconds behind real time, 60–3600 | 300 |
| Operations | Optional comma-separated filter, e.g. `login, create_api_key` | all |
| Workspace ID | Optional: one workspace only (UUID) | whole organization |

## How collection works

- Collects closed windows of at most six hours, from the checkpoint up to *now − Ingestion Delay*, 100 events per page using the API's cursor (LangSmith's SIEM guidance is to pull the previous hour on a schedule).
- Re-reads the last 10 minutes each run and de-duplicates on the event id (`metadata.uid`). The API's time range is inclusive at both ends, so this also prevents edge duplicates.
- The KV Store checkpoint (`ta_langsmith_audit_logs_checkpoints`) advances only after a whole window is written. Catch-up runs stop after about 55 minutes and resume on the next run.
- HTTP 429 and 5xx are retried, honouring `Retry-After`.

## Data and CIM

| Normalised field | From |
|---|---|
| `user`, `user_id`, `credential_id` | `actor.user.uid`, `actor.user.credential_uid` |
| `src` | `src_endpoint.ip` |
| `signature`, `command` | `api.operation` |
| `action` | login: `success`/`failure`; create/add/invite: `created`; update: `modified`; delete/remove/revoke: `deleted`; get/list/read/query: `read` |
| `status` | OCSF `status` (`success`/`failure`) |
| `object`, `object_id`, `object_category`, `change_type` | `resources{}.uid` and the operation name |
| `dest`, `workspace_id` | organization and workspace from `unmapped.original_audit_log` |

| Eventtype | Tags |
|---|---|
| `langsmith_audit_authentication` | `authentication` |
| `langsmith_audit_change` | `change` |
| `langsmith_audit_account_change` | `change`, `account` |

## Searches

```
sourcetype=langsmith:audit | stats count BY api.operation status
```
```
sourcetype=langsmith:audit api.operation=*api_key* | table _time user api.operation status src
```
```
| datamodel Change search | search sourcetype=langsmith:audit
```

## Troubleshooting

Logs: `index=_internal source=*ta_langsmith_audit_logs*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong API key |
| HTTP 403 | Not Enterprise, the key's user isn't an Organization Admin/Operator, or the Organization ID doesn't match the key |
| HTTP 404 | Wrong region or self-hosted URL, or audit logs not enabled (self-hosted) |
| HTTP 422 | Invalid start time or operation filter |
| HTTP 429 warnings | Rate limited; the add-on waits and retries |

## Release notes

- **1.0.0**: Initial release. LangSmith audit logs (OCSF API Activity) for US, EU, APAC, AWS US and self-hosted; windowed collection with overlap and event-id de-duplication; cursor paging; encrypted, validated API key; proxy support; CIM Authentication and Change mapping; Python 3.9 and 3.13; Splunk Cloud compatible.

---
LangSmith and LangChain are trademarks of LangChain, Inc. This add-on is not built, endorsed or supported by LangChain.
