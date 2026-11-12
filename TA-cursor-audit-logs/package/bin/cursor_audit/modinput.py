"""Modular input: Cursor audit logs (Admin API)."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

from . import ADDON_NAME, CONF_PREFIX
from .client import AuditLogClient, build_proxies
from .collector import DEFAULT_LAG_S, MIN_LAG_S, collect, parse_event_types, parse_start_time

INPUT_TYPE = "cursor_audit_logs"
SOURCETYPE = "cursor:audit"
CHECKPOINT_COLLECTION = CONF_PREFIX + "_checkpoints"
MAX_RUNTIME_S = 3300


def _context_from_uri(server_uri: str) -> Dict[str, Any]:
    parsed = urlparse(server_uri)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}


def _realm(conf_name: str) -> str:
    return "__REST_CREDENTIAL__#{}#configs/conf-{}".format(ADDON_NAME, conf_name)


def _lag(value: Optional[str]) -> int:
    if value in (None, ""):
        return DEFAULT_LAG_S
    lag = int(value)
    if not MIN_LAG_S <= lag <= 3600:
        raise ValueError("Ingestion Delay must be between {} and 3600 seconds.".format(MIN_LAG_S))
    return lag


class CursorAuditLogsInput(smi.Script):
    def get_scheme(self) -> smi.Scheme:
        scheme = smi.Scheme("Cursor Audit Logs")
        scheme.description = "Collects Cursor audit logs from the Cursor Admin API."
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        scheme.add_argument(
            smi.Argument("name", title="Name", description="Input name", required_on_create=True)
        )
        scheme.add_argument(smi.Argument("account", title="Account", required_on_create=True))
        scheme.add_argument(smi.Argument("start_time", title="Start Time (UTC)", required_on_create=False))
        scheme.add_argument(smi.Argument("delay", title="Ingestion Delay", required_on_create=False))
        scheme.add_argument(smi.Argument("event_types", title="Event Types", required_on_create=False))
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition) -> None:
        params = definition.parameters
        if not params.get("account"):
            raise ValueError("Account is required.")
        parse_start_time(params.get("start_time"))
        parse_event_types(params.get("event_types"))
        _lag(params.get("delay"))

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

        client = AuditLogClient(
            api_key=account.get("api_key"),
            key_type=account.get("key_type") or "team",
            team_id=account.get("team_id"),
            proxies=build_proxies(proxy),
            logger=logger,
        )
        store = checkpointer.KVStoreCheckpointer(
            CHECKPOINT_COLLECTION, session_key, ADDON_NAME, **context
        )
        checkpoint_key = "{}__{}".format(INPUT_TYPE, input_name)

        def emit(event: Dict[str, Any], event_time: Optional[float]) -> None:
            ew.write_event(
                smi.Event(
                    data=json.dumps(event, ensure_ascii=False, separators=(",", ":")),
                    time="{:.3f}".format(event_time) if event_time is not None else None,
                    index=index,
                    sourcetype=SOURCETYPE,
                    source=stanza,
                    stanza=stanza,
                )
            )

        logger.info("input=%s account=%s starting collection", stanza, account_name)
        stats = collect(
            client=client,
            state=store.get(checkpoint_key),
            emit=emit,
            save_state=lambda state: store.update(checkpoint_key, state),
            start_time=parse_start_time(params.get("start_time")),
            lag_s=_lag(params.get("delay")),
            event_types=parse_event_types(params.get("event_types")),
            max_runtime_s=MAX_RUNTIME_S,
            logger=logger,
        )
        log.events_ingested(logger, stanza, SOURCETYPE, stats.events, index, account=account_name)
        logger.info(
            "input=%s finished: events=%d duplicates_skipped=%d windows=%d pages=%d high_water=%s stopped_early=%s",
            stanza, stats.events, stats.duplicates, stats.windows, stats.pages,
            stats.high_water, stats.stopped_early,
        )


def run() -> None:
    try:
        sys.exit(CursorAuditLogsInput().run(sys.argv))
    except Exception:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
