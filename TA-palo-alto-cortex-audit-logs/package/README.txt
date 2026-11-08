Audit Logs Add-on for Palo Alto Networks Cortex
===============================================
Author:  Gaurav Malik
Version: 1.0.0
License: Apache License 2.0 (see LICENSES/LICENSE.txt)

Collects audit data from the Palo Alto Networks Cortex public API:

  Input                           API endpoint                                 Sourcetype
  ------------------------------  -------------------------------------------  ------------------------------
  Cortex Audit Management Logs    POST /public_api/v1/audits/management_logs   cortex:audit:management_logs
  Cortex Audit Agent Reports      POST /public_api/v1/audits/agents_reports    cortex:audit:agent_reports

Compatibility
-------------
Splunk Enterprise 10.2+ and Splunk Cloud Platform 10.2+. Runs on Python 3.13
(python.required = 3.13); the bundled Splunk SDK for Python 3.x requires it.
Install on search heads (search-time field extractions) and on the instance
that runs the inputs (heavy forwarder, or the Inputs Data Manager / search
head in Splunk Cloud).

Prerequisites in Cortex
-----------------------
1. Settings > Configurations > API Keys > + New Key.
   Advanced key type is recommended. Grant a role with permission to view
   audit logs (an Instance Administrator or a custom role with Audit Logs view).
2. Note the API Key, the API Key ID and the API URL ("Copy API URL").
3. The management log API requires a Cortex license that includes it (HTTP 402
   is returned otherwise).

Setup
-----
1. Configuration > Accounts > Add: enter the API URL, API Key ID, key type and
   API Key. The add-on tests the credentials before saving. The key is stored
   encrypted in Splunk's credential store.
2. (Optional) Configuration > Proxy, Configuration > Logging.
3. Inputs > Create New Input > choose an input type and set:
     Interval           Poll frequency in seconds (60 - 86400). Default 300.
     Index              Destination index.
     Start Time (UTC)   First-run start point, YYYY-MM-DDThh:mm:ssZ.
                        Default: 24 hours before the first run.
     Ingestion Delay    Seconds to stay behind real time so late records are
                        not missed. Default 60 (management logs), 300 (agent
                        reports).
     Categories         Agent reports only: audit, monitoring, status. Empty = all.

How collection works
--------------------
Each run collects closed time windows (at most one hour each) from the last
checkpoint up to "now - Ingestion Delay", paging 100 records at a time. The
checkpoint (KV Store collection ta_palo_alto_cortex_audit_logs_checkpoints) is
advanced after each window is written, so data is never skipped. If a run is
interrupted mid-window, that window is collected again on the next run, which
can produce a small number of duplicates.

To re-collect from scratch, delete the input's checkpoint record from the KV
Store collection, or clone the input under a new name.

Data and CIM
------------
Event time is taken from AUDIT_INSERT_TIME (management logs) and TIMESTAMP
(agent reports). Management log events with AUDIT_ENTITY=AUTH are tagged for
the CIM Authentication data model. Common aliases: user, user_name, src, dest,
action, status, severity, signature, vendor_product.

Troubleshooting
---------------
index=_internal source=*ta_palo_alto_cortex_audit_logs*
  401  wrong API URL, key, key ID or key type
  402  tenant license does not include the API
  403  API key role lacks audit log permission

Support
-------
Community supported. Use the contact link on the Splunkbase listing.

Release notes
-------------
1.0.1  Renamed to "Audit Logs Add-on for Palo Alto Networks Cortex" to follow
       the Splunkbase naming conventions. No functional changes.
1.0.0  Initial release: management logs and agent reports inputs, standard and
       advanced API keys, proxy support, KV Store checkpointing, credential
       validation, CIM Authentication mapping.
