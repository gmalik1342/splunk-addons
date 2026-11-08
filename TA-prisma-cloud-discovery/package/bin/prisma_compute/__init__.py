"""Shared code for the Prisma Cloud Discovery add-on.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-prisma-cloud-discovery"
CONF_PREFIX = "ta_prisma_cloud_discovery"
ADDON_VERSION = "1.1.1"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
