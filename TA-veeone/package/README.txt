VeeOne Add-on
=============

Collects specialist stats from the VeeOne open API
(GET /api/v2/specialist/stats) into Splunk.

  Input                     Sourcetype     Event time
  ------------------------  -------------  ---------------------------
  VeeOne Specialist Stats   veeone:logs    snapshot time (one per run)

Each run fetches the full specialist list and writes one JSON event per
specialist. All events from one run share the same timestamp, so each run
is a snapshot. The default interval is once a day (86400 s).

Compatibility
-------------
Splunk Enterprise 9.0+ and Splunk Cloud Platform. Python 3.9 or 3.13
(python.required = 3.9, 3.13; Splunk 10.2+ uses 3.13).
Install on search heads (search-time JSON field extraction) and on the
instance that runs the input (heavy forwarder, or the Inputs Data Manager /
search head in Splunk Cloud).

Setup
-----
1. Get an API key from VeeOne.
2. In the add-on, go to Configuration > Accounts > Add:
   - API Base URL: the VeeOne API host, e.g. https://openapi.veeone.io
     (https://openapi-uat.veeone.io for the UAT environment)
   - API Key: sent as the X-API-Key header; stored encrypted.
   The key is tested against the API when you save.
3. Optional: Configuration > Proxy, Configuration > Logging.
4. Inputs > Create New Input > VeeOne Specialist Stats: choose the account,
   interval and index.

Searches
--------
Latest snapshot:
  index=<your_index> sourcetype=veeone:logs
  | eventstats max(_time) AS latest_snapshot
  | where _time=latest_snapshot

Troubleshooting
---------------
  index=_internal source=*ta_veeone*

Upgrading from 1.0.0
--------------------
1.0.0 inputs used Client ID / Secret Key fields that the API never used,
and stored them unencrypted. After upgrading, delete the old input, add an
account with your API key, and create a new input.

Release notes
-------------
1.1.0  Rebuilt on the Splunk UCC framework. Working collection from
       /api/v2/specialist/stats with X-API-Key auth; API key stored
       encrypted and validated on save; configurable API base URL;
       snapshot-per-run with a daily default interval; retries with
       backoff; proxy support; Python 3.9 and 3.13 support; Splunk Cloud
       compatible.
1.0.0  Initial release.
