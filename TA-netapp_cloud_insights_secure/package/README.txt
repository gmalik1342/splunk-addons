NetApp_Cloud_Insights_Secure
============================

Collects Workload Security (formerly Cloud Secure) alerts from NetApp Data
Infrastructure Insights (Cloud Insights) via its REST API
(GET /rest/v1/cloudsecure/alerts).

  Input                Sourcetype                   Event time
  -------------------  ---------------------------  --------------
  Cloud Secure Alerts  netapp:cloud_secure:alerts   alertTimestamp

Each run pages through the alerts of the last week and ingests an alert only
if it is new or has changed since it was last ingested (for example its
status moved from New to Resolved, or an automated action ran). Use
`latest(status) BY id` for an alert's current state. Alerts are mapped to the
CIM Alerts data model (eventtype netapp_cloud_secure_alert, tag alert).

The API only returns the last week of alerts: if the input is stopped for
longer than a week, alerts older than that are not collected.

Compatibility
-------------
Splunk Enterprise 9.0+ and Splunk Cloud Platform. Python 3.9 or 3.13
(python.required = 3.9, 3.13; Splunk 10.2+ uses 3.13). Uses the KV Store for
checkpoints. Install on search heads (field extractions, CIM mapping) and on
the instance that runs the input (heavy forwarder, or the Inputs Data
Manager / search head in Splunk Cloud).

Setup
-----
1. In Cloud Insights, create a Workload Security API access token
   (Admin > API Access; Administrator role required).
2. In the add-on, go to Configuration > Accounts > Add:
   - Tenant URL: e.g. https://xyzcorp.c01.cloudinsights.netapp.com
   - API Access Token: sent as the X-CloudInsights-ApiKey header; stored
     encrypted. The token is tested against the API when you save.
3. Optional: Configuration > Proxy, Configuration > Logging.
4. Inputs > Create New Input > Cloud Secure Alerts: choose the account,
   interval (default 300 s) and index.

Searches
--------
Current state of each alert:
  sourcetype=netapp:cloud_secure:alerts
  | stats latest(status) AS status latest(severity) AS severity
          latest(alertType) AS alertType latest(userName) AS user BY id

CIM:
  | datamodel Alerts search | search sourcetype=netapp:cloud_secure:alerts

Troubleshooting
---------------
  index=_internal source=*ta_netapp_cloud_insights_secure*

Upgrading from 1.0.x
--------------------
1.0.x stored the REST URL and API key on each input. After upgrading, add an
account (the old REST URL can be pasted as the Tenant URL), then delete the
old input and create a new one. The first run ingests the last week of
alerts.

Release notes
-------------
1.1.0  Rebuilt on the Splunk UCC framework. Each alert is ingested once and
       again only when it changes (1.0.x re-ingested up to a week of alerts
       whenever a new one arrived); paging through all alerts; account-based
       setup with the token stored encrypted and validated on save; CIM
       Alerts mapping; retries with backoff; proxy support; Python 3.9 and
       3.13 support; Splunk Cloud compatible.
1.0.8  Add-on Builder release.
