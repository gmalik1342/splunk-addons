# Workload Security Alerts Add-on for NetApp Cloud Insights

| | |
|---|---|
| App ID | `TA-netapp_cloud_insights_secure` |
| Version | 1.1.1 |
| Input | `cloud_secure_alerts` |
| Sourcetype | `netapp:cloud_secure:alerts` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | Alerts |
| Source | [`TA-netapp_cloud_insights_secure`](../TA-netapp_cloud_insights_secure) |

Collects Workload Security (formerly Cloud Secure) alerts from NetApp Data Infrastructure Insights (Cloud Insights): `GET {tenant}/rest/v1/cloudsecure/alerts`, token in the `X-CloudInsights-ApiKey` header. One event per alert, timestamped with `alertTimestamp`.

## How collection works

Each run pages through the API's one-week window (`limit=1000`, `offset`) and ingests an alert only if its `id` is **new or its content changed** since it was last ingested, e.g. its status moved from *New* to *Resolved* or an automated action ran. A KV Store checkpoint (`ta_netapp_cloud_insights_secure_checkpoints`) remembers what was sent; entries older than 8 days are pruned.

> The API only returns the last week of alerts. If the input is stopped for longer than that, older alerts are not collected.

## Setup

1. In Cloud Insights, create a Workload Security **API access token** (*Admin > API Access*; Administrator role required).
2. **Configuration > Accounts > Add:**
   - **Tenant URL:** e.g. `https://xyzcorp.c01.cloudinsights.netapp.com` (a full `.../rest/v1/cloudsecure/alerts` URL is also accepted)
   - **API Access Token:** stored encrypted, tested when you save
3. **Inputs > Create New Input > Cloud Secure Alerts:** account, interval (default 300 s) and index.

## Data and CIM

Mapped to the CIM **Alerts** data model (eventtype `netapp_cloud_secure_alert`, tag `alert`): `signature` (= `alertType`), `severity` (normalised; the original value is kept in `vendor_severity`), `user` (= `userName`), `description`, `type`, `app`, `vendor_product`.

## Searches

Current state of each alert:
```
sourcetype=netapp:cloud_secure:alerts
| stats latest(status) AS status latest(severity) AS severity
        latest(alertType) AS alertType latest(userName) AS user BY id
```
```
| datamodel Alerts search | search sourcetype=netapp:cloud_secure:alerts
```

## Troubleshooting

Logs: `index=_internal source=*ta_netapp_cloud_insights_secure*`

| Error | Cause |
|---|---|
| HTTP 401 | Wrong or revoked API access token |
| HTTP 403 | The token can't read Workload Security alerts |
| HTTP 404 | Wrong Tenant URL |

## Upgrading from 1.0.x

1.0.x stored the REST URL and API key on each input and re-ingested up to a week of alerts whenever a new one arrived. After upgrading, add an account (the old REST URL can be pasted as the Tenant URL), then delete the old input and create a new one. The first run ingests the last week of alerts once.

## Release notes

- **1.1.1** – Renamed to "Workload Security Alerts Add-on for NetApp Cloud Insights" to follow the Splunkbase naming conventions. No functional changes.
- **1.1.0** – Rebuilt on UCC. Each alert ingested once, and again only when it changes; paging through all alerts; account-based setup with encrypted, validated token; CIM Alerts mapping; retries with backoff; proxy support; Python 3.9 and 3.13; Splunk Cloud compatible.
- **1.0.8** – Add-on Builder release.
