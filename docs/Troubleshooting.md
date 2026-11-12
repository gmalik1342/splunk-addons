# Troubleshooting

## 1. Read the add-on's logs

Every add-on writes its own log file to `_internal`:

| Add-on | Search |
|---|---|
| Cortex Audit Logs | `index=_internal source=*ta_palo_alto_cortex_audit_logs*` |
| VeeOne | `index=_internal source=*ta_veeone*` |
| NetApp Cloud Insights Secure | `index=_internal source=*ta_netapp_cloud_insights_secure*` |
| Prisma Defender | `index=_internal source=*ta_prisma_defender*` |
| Prisma Cloud Discovery | `index=_internal source=*ta_prisma_cloud_discovery*` |
| Claude Activity Feed | `index=_internal source=*ta_claude_activity_feed*` |
| Pinecone Audit Logs | No log of its own (no collector); check the AWS add-on: `index=_internal source=*splunk_ta_aws* (ERROR OR WARN)` |
| Cursor Audit Logs | `index=_internal source=*ta_cursor_audit_logs*` |
| LangSmith Audit Logs | `index=_internal source=*ta_langsmith_audit_logs*` |

For more detail, set **Configuration > Logging > Log level** to `DEBUG`, wait for the next run, then set it back. Each run logs a summary line (events written, pages, checkpoint position or failures).

Account validation errors are logged under `*_account_validation*` in the same source.

## 2. Common errors

| Symptom | Usual cause | Fix |
|---|---|---|
| Saving the account fails with **HTTP 401** | Wrong key/secret, expired or revoked key | Re-create the key and paste it again |
| **HTTP 403** | The key's role lacks permission for that endpoint | Grant the permission listed on the add-on's page |
| **HTTP 404** | Wrong base / tenant / console URL, or API version | Check the URL format on the add-on's page |
| **HTTP 429** warnings | Vendor rate limit | Nothing; the add-on waits (honouring `Retry-After`) and retries. Raise the interval if it's constant |
| **SSL: CERTIFICATE_VERIFY_FAILED** | TLS is always verified; the server's certificate isn't trusted | Use a publicly trusted certificate, or add the CA to the trust store used by Splunk's Python |
| **Connection timed out / refused** | Firewall, DNS or proxy | Test from the Splunk host; configure **Configuration > Proxy** |
| Saving works but **no events** | Input disabled, wrong index, or nothing new yet | Check the input is enabled and search the input's index; snapshot inputs run on their interval (daily for VeeOne and Cloud Discovery) |

## 3. Re-collecting data

**Incremental inputs** (Cortex, NetApp, Claude, Cursor, LangSmith) keep a checkpoint in a KV Store collection named `<app>_checkpoints`. To start over, either:

- **Clone the input** under a new name (simplest; the new name has no checkpoint), or
- **Delete the checkpoint record** for the input from the KV Store collection, e.g. with the REST API:
  ```
  curl -k -u admin https://localhost:8089/servicesNS/nobody/<App ID>/storage/collections/data/<collection>/<key> -X DELETE
  ```
  The key is `<input type>__<input name>`.

**Snapshot inputs** (VeeOne, Prisma Defender, Prisma Cloud Discovery) don't keep a checkpoint; every run collects everything.

## 4. Still stuck?

Open an issue in the [repository](https://github.com/gmalik1342/splunk-addons/issues) with the add-on name and version, the Splunk version, and the relevant log lines (remove any keys or hostnames you don't want to share).
