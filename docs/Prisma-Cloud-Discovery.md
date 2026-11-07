# Prisma Cloud Discovery

| | |
|---|---|
| App ID | `TA-prisma-cloud-discovery` |
| Version | 1.1.0 |
| Input | `prisma_cloud_discovery` |
| Sourcetype | `prisma:cloud_discovery` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | none |
| Source | [`TA-prisma-cloud-discovery`](../TA-prisma-cloud-discovery) |

Collects cloud discovery results from the Prisma Cloud Compute Console API, so you can see which cloud resources exist across your accounts and which are protected by Defenders. Each run is a **snapshot** (default daily):

| record_type | What | Endpoint |
|---|---|---|
| `discovery_entity` | One event per row of the cloud discovery CSV export (all cloud scan data) | `GET /api/<ver>/cloud/discovery/download` |
| `discovery_scan_result` | One event per cloud discovery scan result (account / region / service) | `GET /api/<ver>/cloud/discovery` (50 per page, all pages) |

Each collection can be turned off on the input.

## Setup

1. In Prisma Cloud, create an **access key** (access key ID + secret key) for a role with the permissions below. For a self-hosted Console, a Compute Console user also works.
2. **Configuration > Accounts > Add:**
   - **Console URL:** *Runtime Security (Compute) > Manage > System > Utilities > Path to Console*, e.g. `https://us-east1.cloud.twistlock.com/us-1-123456789` (SaaS) or `https://console.example.com:8083` (self-hosted)
   - **Access Key ID** and **Secret Key:** sent with HTTP basic auth over TLS, stored encrypted, tested when you save
   - **API Version:** e.g. `v34.02` (default) or `v1`
3. Optional: **Configuration > Proxy**, **Configuration > Logging**.
4. **Inputs > Create New Input > Prisma Cloud Discovery:** account, interval (default 86400 s), index, and which collections to run.

The role needs the **Monitor Cloud** (cloud discovery) read permission. Cloud discovery must be configured and have run in Prisma Cloud; the add-on only collects what the Console has already discovered.

## Searches

```
sourcetype=prisma:cloud_discovery record_type=discovery_entity
| eventstats max(_time) AS latest | where _time=latest
```
```
sourcetype=prisma:cloud_discovery record_type=discovery_scan_result
| eventstats max(_time) AS latest | where _time=latest
```

## Troubleshooting

Logs: `index=_internal source=*ta_prisma_cloud_discovery*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong or expired access key ID / secret key |
| HTTP 403 | The role lacks the Monitor Cloud permission |
| HTTP 404 | Wrong Console URL or API version |
| SSL errors | A self-hosted Console needs a certificate the Splunk instance trusts |

## Upgrading from 1.0.0

1.0.0 stored a pre-encoded token and two full endpoint URLs on each input. Add an account with the access key ID and secret key, then delete the old input and create a new one. Every event now has `record_type`; the field names from the API are unchanged.

## Release notes

- **1.1.0** – Rebuilt on UCC. TLS verification always on; account-based setup (Console URL + API version instead of two URLs); encrypted, validated credentials; fixed proxy handling; errors logged instead of silently ending collection; `record_type`; per-collection toggles; daily default; retries; Python 3.9 and 3.13; Splunk Cloud compatible.
- **1.0.0** – Initial release (Add-on Builder).
