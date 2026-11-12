Audit Logs Add-on for Cursor
============================
Author:  Gaurav Malik
Version: 1.0.0
License: Apache License 2.0 (see LICENSES/LICENSE.txt)

Collects Cursor audit logs from the Cursor Admin API: sign-ins and sign-outs,
members and roles, invites, Team / user / organization API keys, service
accounts, team settings, rules, MCP servers, integrations, directory groups,
SSO, Cloud Agents, Bugbot and more.

  Input               Endpoint                                   Sourcetype
  ------------------  -----------------------------------------  ------------
  Cursor Audit Logs   GET https://api.cursor.com/teams/audit-logs   cursor:audit
                      (Team API key), or
                      GET .../organizations/audit-logs
                      (Organization API key, auditlogs:read)

Event time is the event's "timestamp". Sign-ins/sign-outs are mapped to the
CIM Authentication data model; all other events to CIM Change (member, role,
API key and service account changes are also tagged account).

Requirements
------------
* Cursor Enterprise plan (audit logs are Enterprise-only) and an Admin API key:
  - Team API key: one team's events, or
  - Organization API key with the auditlogs:read (or admin:*) scope: all
    linked teams plus organization-level events (optionally one team).
* Splunk Enterprise 9.0+ or Splunk Cloud Platform. Python 3.9 or 3.13
  (python.required = 3.9, 3.13). Uses the KV Store for checkpoints.

Install on search heads (field extractions, CIM mapping) and on the instance
that runs the input (heavy forwarder, or the Inputs Data Manager / search head
in Splunk Cloud).

Setup
-----
1. Configuration > Accounts > Add: choose the key type, paste the API key
   (stored encrypted, tested when you save) and, for Organization keys, an
   optional numeric Team ID.
2. Optional: Configuration > Proxy, Configuration > Logging.
3. Inputs > Create New Input > Cursor Audit Logs:
     Interval           Poll frequency, 60-86400 s (default 300)
     Index              Destination index
     Start Time (UTC)   First-run start, YYYY-MM-DDThh:mm:ssZ (default 24h back)
     Ingestion Delay    Seconds behind real time, 60-3600 (default 300)
     Event Types        Optional comma-separated filter, e.g. login, add_user

How collection works
--------------------
Each run collects closed time windows (at most six hours) from the checkpoint
up to "now - Ingestion Delay", 500 events per page, oldest first. The last 10
minutes are re-read every run and de-duplicated on event_id, so events
recorded late are not missed and none are ingested twice. The checkpoint
(KV Store collection ta_cursor_audit_logs_checkpoints) advances only after a
window is fully written. Requests are spaced to stay within Cursor's limit of
20 requests per minute per team; HTTP 429 responses are retried, honouring
Retry-After. Catch-up runs stop after about 55 minutes and resume next run.

Cursor does not log failed sign-ins, prompts, responses or generated code.

Data and CIM
------------
Raw fields: event_id, timestamp, ip_address, user_email, event_type,
application_type, event_data{...}.
Normalised fields: user (user_email), src (ip_address), signature and command
(event_type), action (logins: success; add/create: created;
remove/delete/revoke: deleted; otherwise modified), object, object_category,
change_type, status, app, dest, vendor_product.
Eventtypes: cursor_audit, cursor_audit_authentication (tag authentication),
cursor_audit_change (tag change), cursor_audit_account_change (tags change,
account).

Example searches
----------------
  sourcetype=cursor:audit | stats count BY event_type
  sourcetype=cursor:audit event_type=*api_key* | table _time user event_type event_data.*
  | datamodel Authentication search | search sourcetype=cursor:audit

Troubleshooting
---------------
Logs: index=_internal source=*ta_cursor_audit_logs*
  401  wrong API key, or wrong key type (Team vs Organization)
  403  not an Enterprise team, or the Organization key lacks auditlogs:read
  404  wrong key type for the endpoint
  429  rate limit (20/min per team); the add-on waits and retries
Re-collect: clone the input under a new name, or delete the record
cursor_audit_logs__<input name> from the KV Store collection
ta_cursor_audit_logs_checkpoints.

Support
-------
Community supported: https://github.com/gmalik1342/splunk-addons/issues
This is a community add-on. It is not built, endorsed or supported by Anysphere
(Cursor) or Splunk. Cursor is a trademark of Anysphere, Inc.

Release notes
-------------
1.0.0  Initial release: Cursor audit logs via the Admin API (Team or
       Organization keys), windowed collection with overlap and event_id
       de-duplication, 20 requests/minute pacing, encrypted and validated
       API key, proxy support, CIM Authentication and Change mapping,
       Python 3.9 and 3.13, Splunk Cloud compatible.
