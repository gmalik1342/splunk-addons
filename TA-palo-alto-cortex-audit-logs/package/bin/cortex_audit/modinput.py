"""Splunk modular input base shared by both Cortex audit inputs."""

from __future__ import annotations

import json
import logging
import sys
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

from . import ADDON_NAME, CONF_PREFIX
from .client import CortexAuditClient, build_proxies
from .collector import AuditEndpoint, collect, parse_start_time

CHECKPOINT_COLLECTION = CONF_PREFIX + "_checkpoints"
MAX_RUNTIME_S = 3300  # bound catch-up runs so config changes are picked up


def _context_from_uri(server_uri: str) -> Dict[str, Any]:
    parsed = urlparse(server_uri)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}


def _realm(conf_name: str) -> str:
    return "__REST_CREDENTIAL__#{}#configs/conf-{}".format(ADDON_NAME, conf_name)


class CortexAuditInput(smi.Script):
    """Subclasses set ENDPOINT, TITLE and DESCRIPTION."""

    ENDPOINT: AuditEndpoint
    TITLE = ""
    DESCRIPTION = ""
    DEFAULT_DELAY_S = 60

    # -- scheme -----------------------------------------------------------
    def extra_arguments(self) -> List[smi.Argument]:
        return []

    def get_scheme(self) -> smi.Scheme:
        scheme = smi.Scheme(self.TITLE)
        scheme.description = self.DESCRIPTION
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        scheme.add_argument(
            smi.Argument("name", title="Name", description="Input name", required_on_create=True)
        )
        scheme.add_argument(
            smi.Argument("account", title="Account", required_on_create=True)
        )
        scheme.add_argument(
            smi.Argument("start_time", title="Start Time (UTC)", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("delay", title="Ingestion Delay", required_on_create=False)
        )
        for arg in self.extra_arguments():
            scheme.add_argument(arg)
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition) -> None:
        params = definition.parameters
        parse_start_time(params.get("start_time"))
        delay = params.get("delay")
        if delay not in (None, "") and not (0 <= int(delay) <= 3600):
            raise ValueError("Ingestion Delay must be between 0 and 3600 seconds.")

    # -- per-input hooks ---------------------------------------------------
    def extra_filters(self, params: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        return None

    # -- run ----------------------------------------------------------------
    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter) -> None:
        meta = inputs.metadata
        session_key = meta["session_key"]
        context = _context_from_uri(meta["server_uri"])
        log.Logs.set_context()
        logger = log.Logs().get_logger("{}_{}".format(CONF_PREFIX, self.ENDPOINT.input_type))
        logger.setLevel(
            conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name=CONF_PREFIX + "_settings",
            )
        )
        for stanza, params in inputs.inputs.items():
            input_name = stanza.split("://", 1)[-1]
            try:
                self._run_input(stanza, input_name, params, session_key, context, logger, ew)
            except Exception as exc:  # noqa: BLE001 - log every failure, keep other stanzas running
                log.log_exception(
                    logger,
                    exc,
                    "Collection Error",
                    msg_before="input={} failed: {}".format(stanza, exc),
                )

    def _run_input(
        self,
        stanza: str,
        input_name: str,
        params: Dict[str, Any],
        session_key: str,
        context: Dict[str, Any],
        logger: logging.Logger,
        ew: smi.EventWriter,
    ) -> None:
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

        client = CortexAuditClient(
            api_url=account.get("api_url"),
            api_key_id=account.get("api_key_id"),
            api_key=account.get("api_key"),
            auth_type=account.get("auth_type") or "advanced",
            proxies=build_proxies(proxy),
            logger=logger,
        )
        store = checkpointer.KVStoreCheckpointer(
            CHECKPOINT_COLLECTION, session_key, ADDON_NAME, **context
        )
        checkpoint_key = "{}__{}".format(self.ENDPOINT.input_type, input_name)
        delay = params.get("delay")
        delay_s = int(delay) if delay not in (None, "") else self.DEFAULT_DELAY_S
        sourcetype = self.ENDPOINT.sourcetype
        source = "{}://{}".format(self.ENDPOINT.input_type, input_name)

        def emit(record: Dict[str, Any], event_time: Optional[float]) -> None:
            ew.write_event(
                smi.Event(
                    data=json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                    time="{:.3f}".format(event_time) if event_time is not None else None,
                    index=index,
                    sourcetype=sourcetype,
                    source=source,
                    stanza=stanza,
                )
            )

        logger.info("input=%s account=%s starting collection", stanza, account_name)
        stats = collect(
            client=client,
            endpoint=self.ENDPOINT,
            checkpoints=store,
            checkpoint_key=checkpoint_key,
            emit=emit,
            start_time_ms=parse_start_time(params.get("start_time")),
            delay_ms=delay_s * 1000,
            extra_filters=self.extra_filters(params),
            max_runtime_s=MAX_RUNTIME_S,
            logger=logger,
        )
        log.events_ingested(
            logger,
            stanza,
            sourcetype,
            stats.events,
            index,
            account=account_name,
        )
        logger.info(
            "input=%s finished: events=%d windows=%d last_end_ms=%s stopped_early=%s",
            stanza, stats.events, stats.windows, stats.end_ms, stats.stopped_early,
        )


def run(script_cls: type) -> None:
    try:
        sys.exit(script_cls().run(sys.argv))
    except Exception:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
