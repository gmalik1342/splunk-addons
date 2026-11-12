"""Shared code for the Audit Logs Add-on for Cursor.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-cursor-audit-logs"
CONF_PREFIX = "ta_cursor_audit_logs"
ADDON_VERSION = "1.0.0"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
