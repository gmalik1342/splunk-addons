# Audit Logs Add-on for Pinecone

| | |
|---|---|
| App ID | `TA-pinecone-audit-logs` |
| Version | 1.0.0 |
| Input | none: uses the Splunk Add-on for AWS (Generic S3) |
| Sourcetype | `pinecone:audit` |
| Splunk | Enterprise 9.0+ and Cloud (no Python) |
| CIM | Authentication, Change |
| Source | [`TA-pinecone-audit-logs`](../TA-pinecone-audit-logs) |

Parses [Pinecone audit logs](https://docs.pinecone.io/guides/production/configure-audit-logs): organization, project, index, backup, API key, Private Endpoint and login events. It also includes a **Pinecone Audit Overview** dashboard.

Pinecone has **no audit-log API**. It writes the logs as JSON files to your own S3 or GCS bucket every 30 minutes, and only after audit logging is enabled (Enterprise plan or HIPAA add-on; organization owners only). This add-on has no collector. The Splunk Add-on for AWS reads the bucket, and this add-on parses, timestamps and normalises the events.

**Supported in 1.0.0:** Amazon S3. Google Cloud Storage isn't supported yet, because the Google Cloud add-on's bucket input assigns its own sourcetypes and can't set `pinecone:audit`.

## Where to install

| Splunk instance | Required |
|---|---|
| Search heads | Yes (field extractions, CIM, dashboard) |
| Instance running the AWS S3 input (heavy forwarder / IDM) | Yes (event breaking and timestamps are applied where data is parsed) |
| Indexers | Only if data reaches them unparsed |

## Setup

1. **Pinecone** (organization owner): enable audit logs with Amazon S3 as the destination, giving the bucket (optionally `bucket/subdirectory`) and an IAM role ARN that lets Pinecone write to it.
2. **Splunk Add-on for AWS:** add an AWS account or IAM role that can read the bucket.
3. Create a **Generic S3** input:

| Setting | Value |
|---|---|
| S3 bucket | your Pinecone audit bucket |
| S3 key prefix | the subdirectory, if you set one |
| Source type | `pinecone:audit` (type it in) |
| Index | your audit index |
| Polling interval | `1800` (Pinecone writes every 30 minutes) |
| Blacklist | `.*audit-log-access-test.*` |

4. If the index isn't searched by default, edit the `pinecone_audit` macro so the dashboard finds the data.

## Data and CIM

One event per audit record, timestamped with `event.time`. Raw fields keep Pinecone's names (`event.action`, `event.resource_type`, `actor.principal_name`, …).

| Normalised field | From |
|---|---|
| `user` / `user_id` / `actor_type` | `actor.principal_name` / `actor.principal_id` / `actor.principal_type` |
| `action` | login → `success`/`failure`; create → `created`; update → `modified`; delete → `deleted` |
| `object` / `object_id` / `object_category` | `event.resource_name` / `event.resource_id` / `event.resource_type` |
| `status`, `result`, `reason` | `event.outcome.*` |
| `dest` | `organization_name` |
| `change_type` | `AAA` for users and API keys, `application` otherwise |

| Eventtype | Tags |
|---|---|
| `pinecone_audit_authentication` | `authentication` |
| `pinecone_audit_change` | `change` |
| `pinecone_audit_account_change` | `change`, `account` |

## Searches

```
sourcetype=pinecone:audit | stats count BY event.resource_type event.action
```
```
sourcetype=pinecone:audit event.resource_type=api-key
| table _time actor.principal_name event.action event.resource_name
```
```
| datamodel Change search | search sourcetype=pinecone:audit
```

## Troubleshooting

| Symptom | Check |
|---|---|
| No events | AWS add-on logs: `index=_internal source=*splunk_ta_aws* (ERROR OR WARN)`; the input's source type is exactly `pinecone:audit`; Pinecone writes every 30 minutes |
| Several records in one event, or wrong time | This add-on must be installed where the S3 input runs. Supported layouts: one object per line, JSON arrays (single-line or one object per line). Multi-line (pretty-printed) objects aren't supported |
| Dashboard empty but search finds data | Edit the `pinecone_audit` macro to include your index |

## Release notes

- **1.0.0**: Initial release. `pinecone:audit` sourcetype for Pinecone audit logs read from Amazon S3 by the Splunk Add-on for AWS; event breaking for NDJSON and JSON arrays; CIM Authentication and Change mapping; overview dashboard.

---
Pinecone is a trademark of Pinecone Systems, Inc. This add-on is not built, endorsed or supported by Pinecone.
