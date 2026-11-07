"""Shared code for the Claude Activity Feed Add-on.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-claude-activity-feed"
CONF_PREFIX = "ta_claude_activity_feed"
ADDON_VERSION = "1.0.0"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
