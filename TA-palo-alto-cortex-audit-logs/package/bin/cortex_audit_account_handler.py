"""Custom REST handler for the Account tab: verifies credentials before saving.

Referenced from globalConfig.json (restHandlerModule / restHandlerClass);
the UCC-generated TA_palo_alto_cortex_audit_logs_rh_account.py imports it.
"""

import import_declare_test  # noqa: F401

import logging

from solnlib import conf_manager, log
from splunk import admin
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler

from cortex_audit import ADDON_NAME, CONF_PREFIX
from cortex_audit.client import CortexApiError, CortexAuditClient, build_proxies
from cortex_audit.collector import AGENT_REPORTS, MANAGEMENT_LOGS

MASK = "********"


def _logger() -> logging.Logger:
    log.Logs.set_context()
    return log.Logs().get_logger(CONF_PREFIX + "_account_validation")


class CortexAccountHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleCreate(self, confInfo):
        self._validate()
        AdminExternalHandler.handleCreate(self, confInfo)

    def handleEdit(self, confInfo):
        self._validate()
        AdminExternalHandler.handleEdit(self, confInfo)

    # ---------------------------------------------------------------------
    def _first(self, key):
        value = self.payload.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        return value

    def _existing_api_key(self):
        cfm = conf_manager.ConfManager(
            self.getSessionKey(),
            ADDON_NAME,
            realm="__REST_CREDENTIAL__#{}#configs/conf-{}_account".format(ADDON_NAME, CONF_PREFIX),
        )
        return cfm.get_conf(CONF_PREFIX + "_account").get(self.callerArgs.id).get("api_key")

    def _proxy(self):
        try:
            cfm = conf_manager.ConfManager(
                self.getSessionKey(),
                ADDON_NAME,
                realm="__REST_CREDENTIAL__#{}#configs/conf-{}_settings".format(ADDON_NAME, CONF_PREFIX),
            )
            return cfm.get_conf(CONF_PREFIX + "_settings").get("proxy")
        except Exception:  # noqa: BLE001 - proxy settings are optional
            return None

    def _validate(self):
        logger = _logger()
        api_key = self._first("api_key")
        if not api_key or api_key == MASK:
            api_key = self._existing_api_key()
        try:
            client = CortexAuditClient(
                api_url=self._first("api_url"),
                api_key_id=self._first("api_key_id"),
                api_key=api_key,
                auth_type=self._first("auth_type") or "advanced",
                proxies=build_proxies(self._proxy()),
                timeout=30,
                max_retries=1,
                logger=logger,
            )
            try:
                client.test_connection(MANAGEMENT_LOGS.path)
            except CortexApiError as exc:
                # 402/403 can be endpoint-specific (license or RBAC); accept the
                # account if the key works for the other audit endpoint.
                if exc.status not in (402, 403):
                    raise
                client.test_connection(AGENT_REPORTS.path)
        except (ValueError, CortexApiError) as exc:
            logger.warning("Account validation failed for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException("Validation failed: {}".format(exc)) from None
        except Exception as exc:  # noqa: BLE001 - network errors etc.
            logger.warning("Account validation error for %s: %s", self.callerArgs.id, exc)
            raise admin.ArgValidationException(
                "Could not reach the Cortex API: {}".format(type(exc).__name__)
            ) from None
