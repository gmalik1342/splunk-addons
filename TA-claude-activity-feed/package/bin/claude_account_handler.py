"""Custom REST handler for the Account tab: verifies the API key before saving.

Referenced from globalConfig.json (restHandlerModule / restHandlerClass);
the UCC-generated TA_claude_activity_feed_rh_account.py imports it.
"""

import import_declare_test  # noqa: F401

import logging

from solnlib import conf_manager, log
from splunk import admin
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

from claude_activity import ADDON_NAME, CONF_PREFIX
from claude_activity.client import ActivityFeedClient, AnthropicApiError, build_proxies

MASK = "********"


def _logger() -> logging.Logger:
    log.Logs.set_context()
    return log.Logs().get_logger(CONF_PREFIX + "_account_validation")


def _cfm(session_key, conf_suffix):
    return conf_manager.ConfManager(
        session_key,
        ADDON_NAME,
        realm="__REST_CREDENTIAL__#{}#configs/conf-{}_{}".format(ADDON_NAME, CONF_PREFIX, conf_suffix),
    )


class ClaudeAccountHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleCreate(self, confInfo):
        self._validate()
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleEdit(self, confInfo):
        self._validate()
        AdminExternalHandler.handleEdit(self, confInfo)

    def _first(self, key):
        value = self.payload.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        return value

    def _existing_api_key(self):
        conf = _cfm(self.getSessionKey(), "account").get_conf(CONF_PREFIX + "_account")
        return conf.get(self.callerArgs.id).get("api_key")

    def _proxy(self):
        try:
            conf = _cfm(self.getSessionKey(), "settings").get_conf(CONF_PREFIX + "_settings")
            return conf.get("proxy")
        except Exception:  # noqa: BLE001 - proxy settings are optional
            return None

    def _validate(self):
        logger = _logger()
        api_key = self._first("api_key")
        if not api_key or api_key == MASK:
            api_key = self._existing_api_key()
        try:
            client = ActivityFeedClient(
                api_key=api_key,
                proxies=build_proxies(self._proxy()),
                timeout=60,
                max_retries=1,
                logger=logger,
            )
            client.test_connection()
        except (ValueError, AnthropicApiError) as exc:
            logger.warning("Account validation failed for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException("Validation failed: {}".format(exc)) from None
        except Exception as exc:  # noqa: BLE001 - network errors etc.
            logger.warning("Account validation error for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException(
                "Could not reach the Anthropic API: {}".format(type(exc).__name__)
            ) from None
