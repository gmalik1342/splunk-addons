"""Shared code for the Activity Feed Add-on for Anthropic Claude.

Kept free of Splunk imports so it can be unit tested outside Splunk.
"""

ADDON_NAME = "TA-claude-activity-feed"
CONF_PREFIX = "ta_claude_activity_feed"
ADDON_VERSION = "1.0.1"
USER_AGENT = "{}/{}".format(ADDON_NAME, ADDON_VERSION)
