"""Modular input: snapshot of VeeOne specialist stats.

Each run fetches the full specialist list and writes one event per record.
All events from a run share the run's timestamp, so a single snapshot can be
selected with ``latest(_time)`` and changes over time can be compared.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any, Dict
from urllib.parse import urlparse

from solnlib import conf_manager, log
from splunklib import modularinput as smi

from . import ADDON_NAME, CONF_PREFIX
from .client import VeeOneClient, build_proxies

INPUT_TYPE = "veeone_logs"
SOURCETYPE = "veeone:logs"


def _context_from_uri(server_uri: str) -> Dict[str, Any]:
    parsed = urlparse(server_uri)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}


def _realm(conf_name: str) -> str:
    return "__REST_CREDENTIAL__#{}#configs/conf-{}".format(ADDON_NAME, conf_name)


class VeeOneSpecialistInput(smi.Script):
    def get_scheme(self) -> smi.Scheme:
        scheme = smi.Scheme("VeeOne Specialist Stats")
        scheme.description = "Collects a snapshot of specialist stats from the VeeOne API."
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

        client = VeeOneClient(
            base_url=account.get("api_url"),
            api_key=account.get("api_key"),
            proxies=build_proxies(proxy),
            logger=logger,
        )

        logger.info("input=%s account=%s starting snapshot", stanza, account_name)
        snapshot_time = "{:.3f}".format(time.time())
        records = client.fetch_specialist_stats()
        for record in records:
            ew.write_event(
                smi.Event(
                    data=json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                    time=snapshot_time,
                    index=index,
                    sourcetype=SOURCETYPE,
                    source=stanza,
                    stanza=stanza,
                )
            )
        log.events_ingested(logger, stanza, SOURCETYPE, len(records), index, account=account_name)
        logger.info("input=%s finished: records=%d", stanza, len(records))


def run() -> None:
    try:
        sys.exit(VeeOneSpecialistInput().run(sys.argv))
    except Exception:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
