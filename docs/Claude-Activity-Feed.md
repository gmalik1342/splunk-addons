# Claude Activity Feed Add-on

| | |
|---|---|
| App ID | `TA-claude-activity-feed` |
| Version | 1.0.0 |
| Input | `claude_activity_feed` |
| Sourcetype | `anthropic:claude:activity` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | none (planned) |
| Source | [`TA-claude-activity-feed`](../TA-claude-activity-feed) |

A lightweight add-on that collects the [Anthropic Compliance API](https://platform.claude.com/docs/en/manage-claude/compliance-api) **Activity Feed** (`GET https://api.anthropic.com/v1/compliance/activities`): audit events such as sign-ins, admin and settings changes, API key lifecycle, member and invite management, and chat, file and project activity.

**Built for Claude Console organizations with a plain Admin API key.** A Claude Enterprise Compliance Access Key also works. It reads the Activity Feed only: no chat content, files, user directory or session transcripts.

## Prerequisites

- The **Compliance API must be enabled** for your organization. The feed only contains activity from the time it was enabled.
- An **Admin API key** from Claude Console (*Settings > Admin keys*, `sk-ant-admin01-...`) or a Compliance Access Key, with the `read:compliance_activities` scope.

## Setup

1. **Configuration > Accounts > Add:** paste the API key. It is stored encrypted and tested when you save.
2. Optional: **Configuration > Proxy**, **Configuration > Logging**.
3. **Inputs > Create New Input > Claude Activity Feed:**

| Setting | Meaning | Default |
|---|---|---|
| Interval | Poll frequency, 60–3600 s | 300 |
| Index | Destination index | default |
| Start Time (UTC) | First-run start, `YYYY-MM-DDThh:mm:ssZ` | 24 hours back |
| Ingestion Delay | Seconds behind real time, 60–3600 | 120 |
| Activity Types | Optional comma-separated filter, e.g. `sso_login_initiated, claude_organization_settings_updated` | all |

## How collection works

Follows Anthropic's [window-polling guidance](https://platform.claude.com/docs/en/manage-claude/compliance-integration-patterns):

- Queries **closed time windows** (at most one hour) ending at least the Ingestion Delay in the past. Activities take about a minute to become queryable, so the delay can't go below 60 s.
- Re-reads a **10-minute overlap** before each window to catch late-indexed activities, and **de-duplicates on activity `id`** (the API delivers at least once).
- Pages each window with cursors (`after_id`) until `has_more` is false.
- The KV Store checkpoint (`ta_claude_activity_feed_checkpoints`) moves forward only after a whole window is written. Catch-up runs stop after about 55 minutes and resume on the next run.
- Retries 429/5xx/529 with backoff, honouring `retry-after`. The organization limit is 600 requests per minute across all Compliance API clients.

## Data

One JSON event per activity, timestamped with `created_at`: `id`, `type`, `organization_id`, `organization_uuid`, `actor{...}` and type-specific fields. Search-time fields: `user`, `user_id`, `src`, `http_user_agent`, `signature` (= `type`), `actor_type`, `vendor_product`.

Actor types: `user_actor`, `api_actor`, `admin_api_key_actor`, `unauthenticated_user_actor`, `anthropic_actor`, `system_actor`, `scim_directory_sync_actor`.

## Searches

```
sourcetype=anthropic:claude:activity | stats count BY type
```
```
sourcetype=anthropic:claude:activity actor_type=admin_api_key_actor
| table _time type actor.admin_api_key_id src
```
```
sourcetype=anthropic:claude:activity type=compliance_api_accessed
```

## Troubleshooting

Logs: `index=_internal source=*ta_claude_activity_feed*`. Each run logs events written, duplicates skipped and the checkpoint position.

| Error | Cause |
|---|---|
| HTTP 401 | Wrong or revoked API key |
| HTTP 403 | Missing `read:compliance_activities` scope, or the Compliance API isn't enabled |
| HTTP 404 | The Compliance API isn't available for the organization |
| HTTP 400 | Bad Start Time format or Activity Types filter |
| HTTP 429 warnings | Organization rate limit reached; the add-on waits and retries |

## Release notes

- **1.0.0** – Initial release.

---
Claude and Anthropic are trademarks of Anthropic, PBC. This add-on is not built, endorsed or supported by Anthropic.
