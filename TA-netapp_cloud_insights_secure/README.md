# Workload Security Alerts Add-on for NetApp Cloud Insights (TA-netapp_cloud_insights_secure)

| | |
|---|---|
| App ID | `TA-netapp_cloud_insights_secure` |
| Version | 1.1.1 |
| Author | Gaurav Malik |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x |

Collects Workload Security (Cloud Secure) alerts from NetApp Data
Infrastructure Insights: `GET {tenant}/rest/v1/cloudsecure/alerts`
(`limit`, `offset`, `timeRange=ONE_WEEK`, `sort=alertTimestamp`; header
`X-CloudInsights-ApiKey`). Sourcetype `netapp:cloud_secure:alerts`, CIM Alerts.

1.1.0 replaces the Add-on Builder 1.0.8 build (a REST/cloud-connect input that
re-ingested up to a week of alerts whenever a new alert arrived). App ID,
input type `cloud_secure_alerts`, sourcetype and REST root are unchanged.

## Collection

* Each run pages through the API's one-week window (`limit=1000`, `offset`).
* KV Store checkpoint (`ta_netapp_cloud_insights_secure_checkpoints`, key
  `cloud_secure_alerts__<input>`) holds `{id: [alertTimestamp, sha256-prefix]}`.
  An alert is emitted if its id is new or its content hash changed; entries
  older than 8 days are pruned. State is saved after the run (at-least-once).
* Paging stops on a short or empty page, when `count` (if it is a total) is
  reached, if the API ignores `offset` (a page adds no new ids), or after 100
  pages.

## Layout / build

Same as the other UCC add-ons: `globalConfig.json`, `package/`, `tests/`,
`build.sh` (tests -> ucc-gen build with pure-Python, Python-3.9-compatible
deps -> package -> AppInspect cloud precert).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

## Notes

* `python.required = 3.9, 3.13`; splunk-sdk stays on 2.1.x (3.x needs
  Python 3.13). AppInspect warns about this; it is not a failure.
* Keep `platformRequirements.splunk.Enterprise` at `"*"` in `app.manifest`
  (Splunkbase's packaging toolkit only knows releases up to 8.0).
* Release checklist: bump the version in `globalConfig.json`, `app.conf`
  (twice), `app.manifest`, `cloud_secure/__init__.py` (a test enforces this),
  add release notes to `package/README.txt`, rebuild.
* Not verified against a live tenant; `offset` paging and the meaning of
  `count` are handled defensively.
