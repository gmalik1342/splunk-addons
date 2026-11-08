"""Shared code for the Defender Inventory Add-on for Palo Alto Networks Prisma Cloud.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-prisma-defender"
CONF_PREFIX = "ta_prisma_defender"
ADDON_VERSION = "1.1.1"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
