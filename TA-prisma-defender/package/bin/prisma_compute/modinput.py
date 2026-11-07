"""Modular input: Prisma Cloud Compute Defender inventory, summary and registry scan progress.

Each run is a snapshot: all events from one run share the run's timestamp.
The three collections run independently, so a permission error on one
(for example registry scan results) does not stop the others.
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
from .client import PrismaClient, build_proxies, is_true
from .records import defender_record, defenders_summary_record, registry_records

INPUT_TYPE = "prisma_defender"
SOURCETYPE = "prisma:defender"


def _context_from_uri(server_uri: str) -> Dict[str, Any]:
    parsed = urlparse(server_uri)
    return {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}


def _realm(conf_name: str) -> str:
    return "__REST_CREDENTIAL__#{}#configs/conf-{}".format(ADDON_NAME, conf_name)


class PrismaDefenderInput(smi.Script):
    def get_scheme(self) -> smi.Scheme:
        scheme = smi.Scheme("Prisma Defender")
        scheme.description = (
            "Collects Defender inventory, Defender summary and registry scan progress "
            "from the Prisma Cloud Compute Console."
        )
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        scheme.add_argument(
            smi.Argument("name", title="Name", description="Input name", required_on_create=True)
        )
        scheme.add_argument(smi.Argument("account", title="Account", required_on_create=True))
        for name, title in (
            ("collect_defenders", "Defender inventory"),
            ("collect_summary", "Defender summary"),
            ("collect_registry", "Registry scan progress"),
        ):
            scheme.add_argument(smi.Argument(name, title=title, required_on_create=False))
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

        client = PrismaClient(
            console_url=account.get("console_url"),
            access_key_id=account.get("access_key_id"),
            secret_key=account.get("secret_key"),
            api_version=account.get("api_version"),
            proxies=build_proxies(proxy),
            logger=logger,
        )
        snapshot_time = "{:.3f}".format(time.time())
        counts = {}

        def emit(record: Dict[str, Any]) -> None:
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
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1

        def enabled(name: str) -> bool:
            value = params.get(name)
            return True if value in (None, "") else is_true(value)

        logger.info("input=%s account=%s starting snapshot", stanza, account_name)
        failures = []

        if enabled("collect_summary"):
            try:
                record = defenders_summary_record(client.defenders_summary())
                if record:
                    emit(record)
            except Exception as exc:  # noqa: BLE001
                failures.append("defenders_summary")
                log.log_exception(logger, exc, "Collection Error",
                                  msg_before="input={} defenders/summary failed: {}".format(stanza, exc))

        if enabled("collect_registry"):
            try:
                for record in registry_records(client.registry_progress()):
                    emit(record)
            except Exception as exc:  # noqa: BLE001
                failures.append("registry_progress")
                log.log_exception(logger, exc, "Collection Error",
                                  msg_before="input={} registry/progress failed: {}".format(stanza, exc))

        if enabled("collect_defenders"):
            try:
                for defender in client.iter_defenders():
                    emit(defender_record(defender))
            except Exception as exc:  # noqa: BLE001
                failures.append("defenders")
                log.log_exception(logger, exc, "Collection Error",
                                  msg_before="input={} defenders failed: {}".format(stanza, exc))

        log.events_ingested(logger, stanza, SOURCETYPE, sum(counts.values()), index, account=account_name)
        logger.info("input=%s finished: %s failures=%s", stanza,
                    " ".join("{}={}".format(k, v) for k, v in sorted(counts.items())) or "no events",
                    ",".join(failures) or "none")


def run() -> None:
    try:
        sys.exit(PrismaDefenderInput().run(sys.argv))
    except Exception:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
