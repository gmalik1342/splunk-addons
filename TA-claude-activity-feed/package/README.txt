Claude Activity Feed Add-on
===========================

A lightweight add-on that collects the Anthropic Compliance API Activity Feed
(GET https://api.anthropic.com/v1/compliance/activities) into Splunk: audit
events for your Claude organization, such as sign-ins, admin and settings
changes, API key lifecycle, member and invite management, and chat, file and
project activity.

Built for Claude Console (Claude Developer Platform) organizations that use a
plain Admin API key. It also works with a Claude Enterprise Compliance Access
Key, but only reads the Activity Feed: no chats, files, users or session
transcripts.

  Input                  Sourcetype                  Event time
  ---------------------  --------------------------  ----------
  Claude Activity Feed   anthropic:claude:activity   created_at

Each event is one Activity record (JSON): id, created_at, type,
organization_id, organization_uuid, actor{...} and type-specific fields.
Search-time aliases: user, user_id, src, http_user_agent, signature (= type),
actor_type, vendor_product.

How collection works
--------------------
Follows Anthropic's window-polling guidance. Each run queries closed time
windows that end at least the Ingestion Delay (default 120 s) in the past,
re-reads a 10-minute overlap to catch late-indexed activities, de-duplicates
on activity id, and pages with cursors. The checkpoint (KV Store) only moves
forward after a whole window is written. Catch-up runs process one-hour
windows and stop after about 55 minutes, resuming on the next run.

Compatibility
-------------
Splunk Enterprise 9.0+ and Splunk Cloud Platform. Python 3.9 or 3.13
(python.required = 3.9, 3.13; Splunk 10.2+ uses 3.13). Uses the KV Store for
checkpoints. Install on search heads (field extractions) and on the instance
that runs the input (heavy forwarder, or the Inputs Data Manager / search head
in Splunk Cloud).

Prerequisites
-------------
- The Compliance API must be enabled for your organization. The feed only
  contains activity from the time it was enabled.
- An Admin API key from Claude Console (Settings > Admin keys,
  sk-ant-admin01-...), or a Compliance Access Key, with the
  read:compliance_activities scope.

Setup
-----
1. Configuration > Accounts > Add: paste the API key. It is stored encrypted
   and tested against the API when you save.
2. Optional: Configuration > Proxy, Configuration > Logging.
3. Inputs > Create New Input > Claude Activity Feed: account, interval
   (default 300 s), index, and optionally:
   - Start Time (UTC): first-run start, default 24 hours back.
   - Ingestion Delay: seconds behind real time (default 120, minimum 60).
   - Activity Types: comma-separated filter, e.g.
     sso_login_initiated, claude_organization_settings_updated

Searches
--------
Activity by type:
  sourcetype=anthropic:claude:activity | stats count BY type

Admin API key actions:
  sourcetype=anthropic:claude:activity actor_type=admin_api_key_actor
  | table _time type actor.admin_api_key_id src

Who accessed compliance data:
  sourcetype=anthropic:claude:activity type=compliance_api_accessed

Troubleshooting
---------------
  index=_internal source=*ta_claude_activity_feed*

Release notes
-------------
1.0.0  Initial release.

This is a community add-on. It is not built, endorsed or supported by
Anthropic or Splunk. Claude and Anthropic are trademarks of Anthropic, PBC.
