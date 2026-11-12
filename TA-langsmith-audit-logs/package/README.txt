Audit Logs Add-on for LangSmith
===============================
Author:  Gaurav Malik
Version: 1.0.0
License: Apache License 2.0 (see LICENSES/LICENSE.txt)

Collects LangSmith (LangChain) audit logs from the LangSmith API:
API keys, personal access tokens and service keys, roles, organization and
workspace members, SSO, SCIM, logins, billing, data retention settings,
datasets, tracing projects, agents, prompts, deployments, bulk exports,
MCP servers and more.

  Input                  Endpoint                           Sourcetype
  ---------------------  ---------------------------------  ----------------
  LangSmith Audit Logs   GET <region>/api/v1/audit-logs     langsmith:audit

Events arrive in OCSF v1.7 API Activity format (class 6003); the original
LangSmith record is kept under unmapped.original_audit_log. Event time is the
OCSF "time" field. Logins are mapped to the CIM Authentication data model;
create/update/delete operations to CIM Change (API key, role, member, SSO and
SCIM changes are also tagged account).

Requirements
------------
* LangSmith Enterprise plan (audit logs are an Enterprise feature) and an API
  key belonging to an Organization Admin or Organization Operator.
* The organization ID (UUID).
* Cloud regions: US, EU, APAC, AWS US. Self-hosted: Helm chart 0.12.33+ with
  audit logs enabled for the organization.
* Splunk Enterprise 9.0+ or Splunk Cloud Platform. Python 3.9 or 3.13
  (python.required = 3.9, 3.13). Uses the KV Store for checkpoints.

Install on search heads (field extractions, CIM mapping) and on the instance
that runs the input (heavy forwarder, or the Inputs Data Manager / search head
in Splunk Cloud).

Setup
-----
1. Configuration > Accounts > Add: region (or Self-hosted + URL), organization
   ID and API key (stored encrypted, tested when you save).
2. Optional: Configuration > Proxy, Configuration > Logging.
3. Inputs > Create New Input > LangSmith Audit Logs:
     Interval           Poll frequency, 60-86400 s (default 300)
     Index              Destination index
     Start Time (UTC)   First-run start, YYYY-MM-DDThh:mm:ssZ (default 24h back)
     Ingestion Delay    Seconds behind real time, 60-3600 (default 300)
     Operations         Optional comma-separated filter, e.g. login, create_api_key
     Workspace ID       Optional: one workspace's events only (UUID)

How collection works
--------------------
Each run collects closed time windows (at most six hours) from the checkpoint
up to "now - Ingestion Delay", 100 events per page with the API's cursor. The
last 10 minutes are re-read every run and de-duplicated on the event id
(metadata.uid), so events recorded late are not missed and none are ingested
twice. The checkpoint (KV Store collection ta_langsmith_audit_logs_checkpoints)
advances only after a window is fully written. HTTP 429 and 5xx responses are
retried, honouring Retry-After. Catch-up runs stop after about 55 minutes and
resume next run. LangSmith keeps audit events for up to 400 days.

Data and CIM
------------
Key raw fields: api.operation, status, time, actor.user.uid,
actor.user.credential_uid, src_endpoint.ip, http_request.http_method,
http_request.url.path, http_response.code, resources{}.uid,
unmapped.original_audit_log.{organization_id, workspace_id, ...}.
Normalised fields: user, user_id, credential_id, src, signature and command
(api.operation), action (login: success / failure; create/add/invite:
created; update: modified; delete/remove/revoke: deleted; get/list/read/query:
read), status, object, object_id, object_category, change_type, http_method,
uri_path, response_code, dest (organization ID), workspace_id, app,
vendor_product.
Eventtypes: langsmith_audit, langsmith_audit_authentication (tag
authentication), langsmith_audit_change (tag change),
langsmith_audit_account_change (tags change, account).

Example searches
----------------
  sourcetype=langsmith:audit | stats count BY api.operation status
  sourcetype=langsmith:audit api.operation=*api_key* | table _time user api.operation status src
  | datamodel Change search | search sourcetype=langsmith:audit

Troubleshooting
---------------
Logs: index=_internal source=*ta_langsmith_audit_logs*
  401  wrong API key
  403  not Enterprise, the key's user is not an Organization Admin/Operator,
       or the Organization ID doesn't match the key
  404  wrong region or self-hosted URL, or audit logs not enabled (self-hosted)
  422  invalid start time or operation filter
  429  rate limited; the add-on waits and retries
Re-collect: clone the input under a new name, or delete the record
langsmith_audit_logs__<input name> from the KV Store collection
ta_langsmith_audit_logs_checkpoints.

Support
-------
Community supported: https://github.com/gmalik1342/splunk-addons/issues
This is a community add-on. It is not built, endorsed or supported by
LangChain or Splunk. LangSmith and LangChain are trademarks of LangChain, Inc.

Release notes
-------------
1.0.0  Initial release: LangSmith audit logs (OCSF API Activity) for US, EU,
       APAC, AWS US and self-hosted deployments; windowed collection with
       overlap and event-id de-duplication; cursor paging; encrypted and
       validated API key; proxy support; CIM Authentication and Change
       mapping; Python 3.9 and 3.13; Splunk Cloud compatible.
