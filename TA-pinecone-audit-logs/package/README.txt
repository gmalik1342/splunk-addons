Audit Logs Add-on for Pinecone
==============================
Author:  Gaurav Malik
Version: 1.0.0
License: Apache License 2.0 (see LICENSES/LICENSE.txt)

Parses Pinecone audit logs in Splunk: organization, project, index, backup,
API key, Private Endpoint and login events, with CIM Authentication and Change
mappings and a "Pinecone Audit Overview" dashboard.

  Sourcetype       Event time     CIM
  ---------------  -------------  ------------------------------------------
  pinecone:audit   event.time     Authentication (logins), Change (create /
                                  update / delete; members and API keys are
                                  also tagged account)

How the data gets in
--------------------
Pinecone does not offer an API for audit logs. It writes them as JSON files to
your own Amazon S3 (or Google Cloud Storage) bucket every 30 minutes. This
add-on contains no collector: the Splunk Add-on for AWS reads the bucket, and
this add-on parses, timestamps and normalises the events.

Supported in 1.0.0: Amazon S3. Google Cloud Storage is not supported yet,
because the Google Cloud add-on's bucket input cannot set a custom sourcetype.

Requirements
------------
* Splunk Enterprise 9.0+ or Splunk Cloud Platform. No Python code.
* A Pinecone Enterprise plan (or the HIPAA add-on); only organization owners
  can configure audit logs.
* Splunk Add-on for AWS (Splunkbase app 1876) to read the bucket.

Where to install
----------------
  Search heads                          Yes (field extractions, CIM, dashboard)
  Instance running the AWS S3 input     Yes (event breaking and timestamps
  (heavy forwarder / IDM)               are applied where the data is parsed)
  Indexers                              Yes, if data reaches them unparsed
Splunk Cloud: install from the app browser; it is applied to the right tiers.

Setup
-----
1. In the Pinecone console (organization owner), open the organization's
   audit log settings (see Pinecone's "Configure audit logs" guide). Choose Amazon S3,
   enter the bucket (optionally bucket/subdirectory) and an IAM role ARN that
   lets Pinecone write to it. Pinecone writes a test file named
   "audit-log-access-test".
2. In the Splunk Add-on for AWS: add an AWS account or IAM role that can read
   the bucket.
3. Create a Generic S3 input:
     S3 bucket          your Pinecone audit bucket
     S3 key prefix      the subdirectory, if you set one
     Source type        pinecone:audit      (type it in; it is not in the list)
     Index              your security / audit index
     Polling interval   1800 (Pinecone writes every 30 minutes)
     Blacklist          .*audit-log-access-test.*
4. If the index is not searched by default, edit the pinecone_audit macro
   (Settings > Advanced search > Search macros) so the dashboard finds the data.

Only logs written after audit logging was enabled in Pinecone exist.

Data and CIM
------------
One event per audit record. Raw fields keep Pinecone's names (event.action,
event.resource_type, actor.principal_name, ...). Normalised fields:
  user, user_id, actor_type, dest (organization), app, object, object_id,
  object_category, command, action, status, result, reason, signature,
  change_type, http_user_agent, vendor_product.
  action: logins -> success / failure; create -> created; update -> modified;
          delete -> deleted.
Eventtypes: pinecone_audit, pinecone_audit_authentication (tag authentication),
pinecone_audit_change (tag change), pinecone_audit_account_change (tags change,
account).

Example searches
----------------
  sourcetype=pinecone:audit | stats count BY event.resource_type event.action
  sourcetype=pinecone:audit event.resource_type=api-key
  | table _time actor.principal_name event.action event.resource_name
  | datamodel Change search | search sourcetype=pinecone:audit

Troubleshooting
---------------
No events:
  * Check the S3 input in the AWS add-on:
    index=_internal source=*splunk_ta_aws* (ERROR OR WARN)
  * Pinecone writes every 30 minutes, and the S3 input polls on its interval.
  * Confirm the input's source type is exactly pinecone:audit.
Events are not split correctly, or the time is wrong:
  * This add-on supports one JSON object per line, and JSON arrays on one line
    or with one object per line. Multi-line (pretty-printed) objects are not
    supported. Check that this add-on is installed where the S3 input runs.

Support
-------
Community supported: https://github.com/gmalik1342/splunk-addons/issues
This is a community add-on. It is not built, endorsed or supported by Pinecone
Systems or Splunk. Pinecone is a trademark of Pinecone Systems, Inc.

Release notes
-------------
1.0.0  Initial release: pinecone:audit sourcetype for Pinecone audit logs read
       from Amazon S3 by the Splunk Add-on for AWS; event breaking for NDJSON
       and JSON arrays; CIM Authentication and Change mapping; overview
       dashboard.
