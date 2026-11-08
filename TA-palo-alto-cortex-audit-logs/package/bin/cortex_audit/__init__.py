"""Shared code for the Audit Logs Add-on for Palo Alto Networks Cortex.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-palo-alto-cortex-audit-logs"
CONF_PREFIX = "ta_palo_alto_cortex_audit_logs"
ADDON_VERSION = "1.0.1"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
