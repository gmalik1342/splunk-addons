"""Modular input: NetApp Cloud Insights Workload Security (Cloud Secure) alerts."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict
from urllib.parse import urlparse

from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

from . import ADDON_NAME, CONF_PREFIX
from .client import CloudSecureClient, build_proxies
from .collector import collect

INPUT_TYPE = "cloud_secure_alerts"
SOURCETYPE = "netapp:cloud_secure:alerts"
CHECKPOINT_COLLECTION = CONF_PREFIX + "_checkpoints"


def _context_from_uri(server_uri: str) -> Dict[str, Any]:
    parsed = urlparse(server_uri)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}


def _realm(conf_name: str) -> str:
    return "__REST_CREDENTIAL__#{}#configs/conf-{}".format(ADDON_NAME, conf_name)


class CloudSecureAlertsInput(smi.Script):
    def get_scheme(self) -> smi.Scheme:
        scheme = smi.Scheme("NetApp Cloud Secure Alerts")
        scheme.description = (
            "Collects Workload Security (Cloud Secure) alerts from NetApp Cloud Insights."
        )
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        scheme.add_argument(
            smi.Argument("name", title="Name", description="Input name", required_on_create=True)
        )
        scheme.add_argument(smi.Argument("account", title="Account", required_on_create=True))
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition) -> None:
        if not definition.parameters.get("account"):
            raise ValueError("Account is required.")

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter) -> None:
        meta = inputs.metadata
        session_key = meta["session_key"]
        context = _context_from_uri(meta["server_uri"])
        log.Logs.set_context()
        logger = log.Logs().get_logger("{}_{}".format(CONF_PREFIX, INPUT_TYPE))
        logger.setLevel(
            conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name=CONF_PREFIX + "_settings",
            )
        )
        for stanza, params in inputs.inputs.items():
            try:
                self._run_input(stanza, params, session_key, context, logger, ew)
            except Exception as exc:  # noqa: BLE001 - log every failure, keep other stanzas running
                log.log_exception(
                    logger, exc, "Collection Error",
                    msg_before="input={} failed: {}".format(stanza, exc),
                )

    def _run_input(self, stanza, params, session_key, context, logger, ew) -> None:
        account_name = params.get("account")
        if not account_name:
            raise ValueError("No account configured for this input.")
        index = params.get("index") or "default"
        input_name = stanza.split("://", 1)[-1]

        cfm = conf_manager.ConfManager(
            session_key, ADDON_NAME, realm=_realm(CONF_PREFIX + "_account"), **context
        )
        try:
            account = cfm.get_conf(CONF_PREFIX + "_account").get(account_name)
        except conf_manager.ConfStanzaNotExistException as exc:
            raise ValueError("Account '{}' does not exist.".format(account_name)) from exc

        settings = conf_manager.ConfManager(
            session_key, ADDON_NAME, realm=_realm(CONF_PREFIX + "_settings"), **context
        )
        try:
            proxy = settings.get_conf(CONF_PREFIX + "_settings").get("proxy")
        except (conf_manager.ConfManagerException, conf_manager.ConfStanzaNotExistException):
            proxy = None

        client = CloudSecureClient(
            base_url=account.get("tenant_url"),
            api_key=account.get("api_key"),
            proxies=build_proxies(proxy),
            logger=logger,
        )
        store = checkpointer.KVStoreCheckpointer(
            CHECKPOINT_COLLECTION, session_key, ADDON_NAME, **context
        )
        checkpoint_key = "{}__{}".format(INPUT_TYPE, input_name)

        def emit(alert: Dict[str, Any], event_time) -> None:
            ew.write_event(
                smi.Event(
                    data=json.dumps(alert, ensure_ascii=False, separators=(",", ":")),
                    time="{:.3f}".format(event_time) if event_time is not None else None,
                    index=index,
                    sourcetype=SOURCETYPE,
                    source=stanza,
                    stanza=stanza,
                )
            )

        logger.info("input=%s account=%s starting collection", stanza, account_name)
        state, stats = collect(client=client, state=store.get(checkpoint_key), emit=emit, logger=logger)
        # Saved only after the whole run succeeded: a failed run re-emits next time
        # (at-least-once) rather than losing alerts.
        store.update(checkpoint_key, state)
        log.events_ingested(
            logger, stanza, SOURCETYPE, stats.new + stats.updated, index, account=account_name
        )
        logger.info(
            "input=%s finished: pages=%d alerts_in_window=%d new=%d updated=%d tracked=%d stop=%s",
            stanza, stats.pages, stats.seen, stats.new, stats.updated,
            len(state["alerts"]), stats.stopped_reason,
        )


def run() -> None:
    try:
        sys.exit(CloudSecureAlertsInput().run(sys.argv))
    except Exception:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
