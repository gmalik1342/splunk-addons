"""Shared code for the Specialist Stats Add-on for VeeOne.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-veeone"
CONF_PREFIX = "ta_veeone"
ADDON_VERSION = "1.1.1"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
