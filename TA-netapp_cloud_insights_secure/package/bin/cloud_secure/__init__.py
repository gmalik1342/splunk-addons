"""Shared code for the NetApp Cloud Insights Workload Security (Cloud Secure) add-on.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-netapp_cloud_insights_secure"
CONF_PREFIX = "ta_netapp_cloud_insights_secure"
ADDON_VERSION = "1.1.0"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
