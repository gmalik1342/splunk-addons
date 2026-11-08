Defender Inventory Add-on for Palo Alto Networks Prisma Cloud
=============================================================

Collects from the Prisma Cloud Compute (Twistlock) Console API:

  record_type                What                                         API endpoint
  -------------------------  -------------------------------------------  -----------------------------
  defender                   one event per Defender (connected and        GET /api/<ver>/defenders
                             disconnected): host, cluster, version,
                             cloud, system info, enabled features, errors
  defenders_summary          Defender counts per category                 GET /api/<ver>/defenders/summary
                             (connected / deployed / licensed)
  registry_scan_progress     one event per registry scan                  GET /api/<ver>/registry/progress
  registry_scan_statistics   totals across registry scans

All events use sourcetype prisma:defender. Each run is a snapshot; events
from one run share the run timestamp. The default interval is hourly.

Compatibility
-------------
Splunk Enterprise 9.0+ and Splunk Cloud Platform. Python 3.9 or 3.13
(python.required = 3.9, 3.13; Splunk 10.2+ uses 3.13). Prisma Cloud Compute
SaaS and self-hosted Consoles. Install on search heads (JSON field
extraction) and on the instance that runs the input (heavy forwarder, or the
Inputs Data Manager / search head in Splunk Cloud).

TLS certificates are always verified. A self-hosted Console must present a
certificate trusted by the Splunk instance running the input.

Setup
-----
1. In Prisma Cloud, create an access key for a role that can read Defenders
   and registry scan results (or use a Compute Console user for self-hosted).
2. Configuration > Accounts > Add:
   - Console URL: Runtime Security (Compute) > Manage > System > Utilities >
     Path to Console, e.g. https://us-east1.cloud.twistlock.com/us-1-123456789
   - Access Key ID and Secret Key (stored encrypted)
   - API Version: e.g. v34.02 (default) or v1
   The credentials are tested against the Console when you save.
3. Optional: Configuration > Proxy, Configuration > Logging.
4. Inputs > Create New Input > Prisma Defender: account, interval, index, and
   which of the three collections to run.

Searches
--------
Latest Defender inventory:
  sourcetype=prisma:defender record_type=defender
  | eventstats max(_time) AS latest | where _time=latest
  | table hostname cluster type version connected features_enabled errors

Disconnected Defenders:
  sourcetype=prisma:defender record_type=defender connected=false

Troubleshooting
---------------
  index=_internal source=*ta_prisma_defender*

Upgrading from 1.0.0
--------------------
1.0.0 stored a base64 auth token, console URL and API version on each input.
After upgrading, add an account with the access key ID and secret key, then
delete the old input and create a new one. Changes visible in the data:
- Defender events now include disconnected Defenders and all pages (1.0.0
  only returned connected Defenders and at most one page).
- Registry scan progress is one event per registry plus a statistics event,
  instead of one event covering only the first two registries.
- Every event has a record_type field.

Release notes
-------------
1.1.1  Renamed to "Defender Inventory Add-on for Palo Alto Networks Prisma
       Cloud" to follow the Splunkbase naming conventions. No functional
       changes.
1.1.0  Rebuilt on the Splunk UCC framework. TLS verification always on;
       credentials (access key ID + secret key) stored encrypted and
       validated on save; account-based setup; fixed proxy handling; all
       Defenders collected (connected and disconnected, 50 per page, all
       pages); all registry scans collected; record_type field; each
       collection can be turned on or off; retries with backoff; Python 3.9
       and 3.13 support; Splunk Cloud compatible.
1.0.0  Initial release.
