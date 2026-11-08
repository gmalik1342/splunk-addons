Cloud Discovery Add-on for Palo Alto Networks Prisma Cloud
==========================================================

Collects cloud discovery results from the Prisma Cloud Compute (Twistlock)
Console API, so you can see which cloud resources exist across your
accounts and which are protected by Defenders.

  record_type             What                                       API endpoint
  ----------------------  -----------------------------------------  -------------------------------------
  discovery_entity        one event per row of the cloud discovery   GET /api/<ver>/cloud/discovery/download
                          CSV download (all cloud scan data)
  discovery_scan_result   one event per cloud discovery scan result  GET /api/<ver>/cloud/discovery
                          (account / region / service)

All events use sourcetype prisma:cloud_discovery. Each run is a snapshot;
events from one run share the run timestamp. The default interval is once
a day.

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
1. In Prisma Cloud, create an access key for a role with the Monitor Cloud
   (cloud discovery) read permission, or use a Compute Console user for
   self-hosted.
2. Configuration > Accounts > Add:
   - Console URL: Runtime Security (Compute) > Manage > System > Utilities >
     Path to Console, e.g. https://us-east1.cloud.twistlock.com/us-1-123456789
   - Access Key ID and Secret Key (stored encrypted)
   - API Version: e.g. v34.02 (default) or v1
   The credentials are tested against the Console when you save.
3. Optional: Configuration > Proxy, Configuration > Logging.
4. Inputs > Create New Input > Prisma Cloud Discovery: account, interval,
   index, and which of the two collections to run.

Searches
--------
Latest discovered entities:
  sourcetype=prisma:cloud_discovery record_type=discovery_entity
  | eventstats max(_time) AS latest | where _time=latest

Latest scan results:
  sourcetype=prisma:cloud_discovery record_type=discovery_scan_result
  | eventstats max(_time) AS latest | where _time=latest

Troubleshooting
---------------
  index=_internal source=*ta_prisma_cloud_discovery*

Upgrading from 1.0.0
--------------------
1.0.0 stored a base64 auth token and two full endpoint URLs on each input.
After upgrading, add an account with the access key ID and secret key, then
delete the old input and create a new one. Every event now has a
record_type field; the field names from the API are unchanged.

Release notes
-------------
1.1.1  Renamed to "Cloud Discovery Add-on for Palo Alto Networks Prisma Cloud"
       to follow the Splunkbase naming conventions. No functional changes.
1.1.0  Rebuilt on the Splunk UCC framework. TLS verification always on;
       credentials (access key ID + secret key) stored encrypted and
       validated on save; account-based setup (Console URL and API version
       instead of two full URLs); fixed proxy handling; errors are logged
       instead of silently ending collection; record_type field; each
       collection can be turned on or off; daily default interval; retries
       with backoff; Python 3.9 and 3.13 support; Splunk Cloud compatible.
1.0.0  Initial release.
