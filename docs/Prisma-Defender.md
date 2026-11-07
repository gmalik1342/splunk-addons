# Prisma Defender

| | |
|---|---|
| App ID | `TA-prisma-defender` |
| Version | 1.1.0 |
| Input | `prisma_defender` |
| Sourcetype | `prisma:defender` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | none |
| Source | [`TA-prisma-defender`](../TA-prisma-defender) |

Collects Defender data from the Prisma Cloud Compute (Twistlock) Console API, SaaS or self-hosted. Each run is a **snapshot** (default hourly); every event carries a `record_type`:

| record_type | What | Endpoint |
|---|---|---|
| `defender` | One event per Defender, **connected and disconnected**: host, cluster, type, version, cloud, system info, enabled features, errors, certificate expiration | `GET /api/<ver>/defenders` (50 per page, all pages) |
| `defenders_summary` | Defender counts per category (connected / deployed / licensed) | `GET /api/<ver>/defenders/summary` |
| `registry_scan_progress` | One event per registry scan | `GET /api/<ver>/registry/progress` |
| `registry_scan_statistics` | Totals across registry scans | (computed) |

The three collections run independently and can each be turned off on the input; a permission error on one doesn't stop the others.

## Setup

1. In Prisma Cloud, create an **access key** (access key ID + secret key) for a role with the permissions below. For a self-hosted Console, a Compute Console user also works.
2. **Configuration > Accounts > Add:**
   - **Console URL:** *Runtime Security (Compute) > Manage > System > Utilities > Path to Console*, e.g. `https://us-east1.cloud.twistlock.com/us-1-123456789` (SaaS) or `https://console.example.com:8083` (self-hosted)
   - **Access Key ID** and **Secret Key:** sent with HTTP basic auth over TLS, stored encrypted, tested when you save
   - **API Version:** e.g. `v34.02` (default) or `v1`
3. Optional: **Configuration > Proxy**, **Configuration > Logging**.
4. **Inputs > Create New Input > Prisma Defender:** account, interval (default 3600 s), index, and which collections to run.

The role needs read access to **Defenders** and **registry scan results**.

## Searches

Latest Defender inventory:
```
sourcetype=prisma:defender record_type=defender
| eventstats max(_time) AS latest | where _time=latest
| table hostname cluster type version connected features_enabled errors
```
Disconnected Defenders:
```
sourcetype=prisma:defender record_type=defender connected=false
```

## Troubleshooting

Logs: `index=_internal source=*ta_prisma_defender*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong or expired access key ID / secret key |
| HTTP 403 | The role can't read that endpoint; the other collections still run |
| HTTP 404 | Wrong Console URL (SaaS URLs include the tenant path) or API version |
| SSL errors | TLS is always verified; a self-hosted Console needs a certificate the Splunk instance trusts |

## Upgrading from 1.0.0

1.0.0 stored a pre-encoded token on each input. Add an account with the access key ID and secret key, then delete the old input and create a new one. Visible changes: disconnected Defenders and all pages are now collected (1.0.0 returned at most 50 connected Defenders), registry progress covers every registry, and every event has `record_type`. Field names are otherwise unchanged.

## Release notes

- **1.1.0** – Rebuilt on UCC. TLS verification always on; encrypted, validated credentials; fixed proxy handling; all Defenders (connected and disconnected, all pages); all registry scans; `record_type`; per-collection toggles; hourly default; retries; Python 3.9 and 3.13; Splunk Cloud compatible.
- **1.0.0** – Initial release (Add-on Builder).
