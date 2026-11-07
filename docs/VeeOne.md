# VeeOne Add-on

| | |
|---|---|
| App ID | `TA-veeone` |
| Version | 1.1.0 |
| Input | `veeone_logs` |
| Sourcetype | `veeone:logs` |
| Splunk | Enterprise 9.0+ and Cloud (Python 3.9 or 3.13) |
| CIM | none |
| Source | [`TA-veeone`](../TA-veeone) |

Collects specialist stats from the VeeOne open API (`GET {base URL}/api/v2/specialist/stats`, key in the `X-API-Key` header). Each run is a **full snapshot**: one JSON event per specialist record (e.g. `specialistId`, `licenceNumber`, `isActive`, `practiceGroup`), all sharing the run's timestamp.

## Setup

1. Get an API key from VeeOne.
2. **Configuration > Accounts > Add:**
   - **API Base URL:** the API host only, e.g. `https://openapi.veeone.io` (`https://openapi-uat.veeone.io` for UAT)
   - **API Key:** stored encrypted, tested when you save
3. Optional: **Configuration > Proxy**, **Configuration > Logging**.
4. **Inputs > Create New Input > VeeOne Specialist Stats:** account, interval (default 86400 s, once a day; range 300–604800) and index.

## Searches

Latest snapshot:
```
index=<your_index> sourcetype=veeone:logs
| eventstats max(_time) AS latest_snapshot
| where _time=latest_snapshot
```

## Troubleshooting

Logs: `index=_internal source=*ta_veeone*`

| Error | Cause |
|---|---|
| HTTP 401 / 403 | Wrong or expired API key, or the key can't read specialist stats |
| HTTP 404 | Wrong API Base URL; enter the host only, without a path |
| "Response is not valid JSON" | The base URL points to a web page, not the API |

With the daily default, the next snapshot may be up to 24 hours away; lower the interval temporarily to test.

## Upgrading from 1.0.0

1.0.0 had Client ID / Secret Key fields that the API never used, stored unencrypted, and its collection code was incomplete. After upgrading, delete the old input, add an account with your API key, and create a new input.

## Release notes

- **1.1.0** – Rebuilt on UCC. Working collection with `X-API-Key` auth; API key stored encrypted and validated on save; configurable API base URL; snapshot per run with a daily default; retries with backoff; proxy support; Python 3.9 and 3.13; Splunk Cloud compatible.
- **1.0.0** – Initial release (Add-on Builder).
