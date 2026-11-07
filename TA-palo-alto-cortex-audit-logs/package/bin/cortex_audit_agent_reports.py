"""Modular input: Cortex audit agent reports (/public_api/v1/audits/agents_reports)."""

import import_declare_test  # noqa: F401  (UCC-generated: puts ../lib on sys.path)

from splunklib import modularinput as smi

from cortex_audit.collector import AGENT_REPORTS
from cortex_audit.modinput import CortexAuditInput, run

VALID_CATEGORIES = ("audit", "monitoring", "status")


def parse_categories(value):
    """Parse the comma-separated category selection into a validated list."""
    if not value:
        return []
    items = [c.strip().lower() for c in str(value).split(",") if c.strip()]
    invalid = [c for c in items if c not in VALID_CATEGORIES]
    if invalid:
        raise ValueError("Unsupported categories: {}".format(", ".join(invalid)))
    return sorted(set(items))


class CortexAuditAgentReports(CortexAuditInput):
    ENDPOINT = AGENT_REPORTS
    TITLE = "Cortex Audit Agent Reports"
    DESCRIPTION = "Collects agent audit reports from the Palo Alto Cortex public API."
    DEFAULT_DELAY_S = 300

    def extra_arguments(self):
        return [smi.Argument("categories", title="Categories", required_on_create=False)]

    def validate_input(self, definition):
        super().validate_input(definition)
        parse_categories(definition.parameters.get("categories"))

    def extra_filters(self, params):
        categories = parse_categories(params.get("categories"))
        if not categories:
            return None
        return [{"field": "category", "operator": "in", "value": categories}]


if __name__ == "__main__":
    run(CortexAuditAgentReports)
