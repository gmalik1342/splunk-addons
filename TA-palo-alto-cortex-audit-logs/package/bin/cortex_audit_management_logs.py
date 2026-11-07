"""Modular input: Cortex audit management logs (/public_api/v1/audits/management_logs)."""

import import_declare_test  # noqa: F401  (UCC-generated: puts ../lib on sys.path)

from cortex_audit.collector import MANAGEMENT_LOGS
from cortex_audit.modinput import CortexAuditInput, run


class CortexAuditManagementLogs(CortexAuditInput):
    ENDPOINT = MANAGEMENT_LOGS
    TITLE = "Cortex Audit Management Logs"
    DESCRIPTION = "Collects audit management logs from the Palo Alto Cortex public API."
    DEFAULT_DELAY_S = 60


if __name__ == "__main__":
    run(CortexAuditManagementLogs)
