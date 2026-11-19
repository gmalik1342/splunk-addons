CIM Add-on for Zscaler Deception
================================
Author:  Gaurav Malik
Version: 1.0.0
License: Apache License 2.0 (see LICENSES/LICENSE.txt)

Community add-on that parses Zscaler Deception decoy events and audit logs
in Splunk, maps decoy events to the CIM Intrusion Detection and Alerts data
models with MITRE ATT&CK technique IDs, and adds a "Zscaler Deception
Overview" dashboard.

  Sourcetype                  CIM
  --------------------------  ------------------------------------------------
  zscaler:deception:events    Intrusion Detection (tags ids, attack) and
                              Alerts (tag alert); whitelisted events excluded
  zscaler:deception:audit     Parsing only in 1.0.0 (JSON fields, no CIM)

This add-on is not developed, endorsed or supported by Zscaler, Inc. It does
not replace or change the official Zscaler add-on, and it can be installed
alongside it.

How the data gets in
--------------------
Zscaler Deception sends its data to Splunk itself; this add-on contains no
collector and no Python. In the Deception Admin Portal, Orchestrate > SIEM
Integrations offers Splunk (HTTP Event Collector) and syslog. Each event is
one JSON object with flat, dotted key names such as "attacker.ip".

Requirements
------------
* Splunk Enterprise 9.0+ or Splunk Cloud Platform.
* Zscaler Deception with access to the Deception Admin Portal.

Where to install
----------------
  Search heads                         Yes (field extractions, CIM, dashboard)
  HEC receivers / heavy forwarders     Yes (syslog header removal, line
  that first parse the data            breaking and timestamps happen there)
  Indexers                             Yes, if data reaches them unparsed
Splunk Cloud: install from the app browser; it is applied to the right tiers.

Setup: HTTP Event Collector (recommended)
-----------------------------------------
1. In Splunk, create one HEC token per log type:
     Events      Source type  zscaler:deception:events
     Audit Logs  Source type  zscaler:deception:audit
   (Zscaler's guide suggests _json; use these source types instead so the
   CIM mapping applies.) Choose your security index.
2. In the Deception Admin Portal: Orchestrate > SIEM Integrations > add
   Splunk. Enter the HEC URL (port 8088 on Splunk Enterprise, or your Splunk
   Cloud HEC endpoint), the token, and the log type. Pick the connector that
   can reach Splunk.
3. If the index is not searched by default, edit the zscaler_deception_events
   and zscaler_deception_audit macros (Settings > Advanced search > Search
   macros) so the dashboard finds the data.

Setup: syslog
-------------
Send Deception syslog to a syslog server (for example Splunk Connect for
Syslog, or rsyslog writing files read by a forwarder) and give it the source
type zscaler:deception:events (or :audit). The syslog header in front of the
JSON is removed at index time, so install this add-on where the data is first
parsed.

Data and CIM
------------
Raw fields keep Zscaler's names (attacker.ip, decoy.name, kill_chain_phase,
mitre_ids{}, ...). Normalised fields on zscaler:deception:events:
  src, src_ip, src_host, src_port, src_user, user      (attacker)
  dest, dest_ip, dest_category, decoy_type             (decoy)
  action (always "allowed": decoys observe, they do not block)
  signature, signature_id, category (kill chain phase), severity
  (critical / high / medium / low / informational), ids_type
  (host, network or application by event type), risk_score,
  attacker_score, mitre_technique_id, threat_parse_id, description,
  event_id, deception_type, http_method, uri_path, status (recon events),
  vendor, product, vendor_product, app.
Eventtypes: zscaler_deception_events, zscaler_deception_detection (tags ids,
attack, alert; excludes whitelisted=true), zscaler_deception_whitelisted,
zscaler_deception_audit.

Example searches
----------------
  sourcetype=zscaler:deception:events | stats count BY deception_type severity
  sourcetype=zscaler:deception:events | stats count BY mitre_technique_id
  | tstats count FROM datamodel=Intrusion_Detection
    WHERE IDS_Attacks.vendor_product="Zscaler Deception" BY IDS_Attacks.src

Troubleshooting
---------------
No events:
  * HEC: index=_internal sourcetype=splunkd component=HttpInputDataHandler
  * Check the integration status in the Deception Admin Portal.
Events still start with "<26>1 ..." or fields are missing:
  * The add-on is not installed where the data is first parsed, or the source
    type is not exactly zscaler:deception:events.
Wrong event time:
  * HEC event endpoint data keeps the time sent by Zscaler (or the arrival
    time). Syslog and HEC raw data use the "timestamp" field (UTC).

Support
-------
Community supported: https://github.com/gmalik1342/splunk-addons/issues
Zscaler and Zscaler Deception are trademarks of Zscaler, Inc. This add-on is
not affiliated with, developed, endorsed or supported by Zscaler, Inc. or
Splunk LLC.

Release notes
-------------
1.0.0  Initial release: zscaler:deception:events and zscaler:deception:audit
       source types for HEC and syslog; syslog header removal; CIM Intrusion
       Detection and Alerts mapping with MITRE ATT&CK technique IDs;
       whitelisted events excluded from the CIM; overview dashboard.
