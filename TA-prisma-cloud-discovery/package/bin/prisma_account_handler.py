"""Custom REST handler for the Account tab: verifies the Console URL and credentials before saving.

Referenced from globalConfig.json (restHandlerModule / restHandlerClass);
the UCC-generated TA_prisma_cloud_discovery_rh_account.py imports it.
"""

import import_declare_test  # noqa: F401

import logging

from solnlib import conf_manager, log
from splunk import admin
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

from prisma_compute import ADDON_NAME, CONF_PREFIX
from prisma_compute.client import PrismaApiError, PrismaClient, build_proxies

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


class PrismaAccountHandler(AdminExternalHandler):
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

    def _existing_secret(self):
        conf = _cfm(self.getSessionKey(), "account").get_conf(CONF_PREFIX + "_account")
        return conf.get(self.callerArgs.id).get("secret_key")

    def _proxy(self):
        try:
            conf = _cfm(self.getSessionKey(), "settings").get_conf(CONF_PREFIX + "_settings")
            return conf.get("proxy")
        except Exception:  # noqa: BLE001 - proxy settings are optional
            return None

    def _validate(self):
        logger = _logger()
        secret = self._first("secret_key")
        if not secret or secret == MASK:
            secret = self._existing_secret()
        try:
            client = PrismaClient(
                console_url=self._first("console_url"),
                access_key_id=self._first("access_key_id"),
                secret_key=secret,
                api_version=self._first("api_version"),
                proxies=build_proxies(self._proxy()),
                timeout=60,
                max_retries=1,
                logger=logger,
            )
            client.discovery_results_page(limit=1, offset=0)
        except (ValueError, PrismaApiError) as exc:
            logger.warning("Account validation failed for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException("Validation failed: {}".format(exc)) from None
        except Exception as exc:  # noqa: BLE001 - network errors etc.
            logger.warning("Account validation error for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException(
                "Could not reach the Prisma Cloud Compute Console: {}".format(type(exc).__name__)
            ) from None
