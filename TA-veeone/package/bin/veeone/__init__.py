"""Shared code for the VeeOne Add-on.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-veeone"
CONF_PREFIX = "ta_veeone"
ADDON_VERSION = "1.1.0"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
