# CIM Add-on for Zscaler Deception

| | |
|---|---|
| App ID | `TA-zscaler-deception-cim` |
| Version | 1.0.0 |
| Author | Gaurav Malik |
| Sourcetypes | `zscaler:deception:events`, `zscaler:deception:audit` |
| CIM | Intrusion Detection, Alerts |
| Splunk | Enterprise 9.0+, Splunk Cloud Platform |
| Source | [`TA-zscaler-deception-cim`](../TA-zscaler-deception-cim) |

Community add-on that parses Zscaler Deception decoy events and audit logs, maps decoy events to the CIM Intrusion Detection and Alerts data models with MITRE ATT&CK technique IDs, and adds a **Zscaler Deception Overview** dashboard. It is not developed, endorsed or supported by Zscaler, Inc., and it does not change any setting of the official Zscaler add-on.

Zscaler Deception sends its own data (Deception Admin Portal > Orchestrate > SIEM Integrations), so this add-on has no collector and no Python.

## Setup (HTTP Event Collector, recommended)

1. Create one HEC token per log type, with source type `zscaler:deception:events` (Events) or `zscaler:deception:audit` (Audit Logs). Zscaler's guide suggests `_json`; use these instead so the CIM mapping applies.
2. In the Deception Admin Portal, add a Splunk SIEM integration with the HEC URL, the token and the log type.
3. If the index is not searched by default, edit the `zscaler_deception_events` and `zscaler_deception_audit` macros.

## Setup (syslog)

Send Deception syslog to a syslog server (Splunk Connect for Syslog, or rsyslog plus a forwarder) with source type `zscaler:deception:events` (or `:audit`). The syslog header in front of the JSON is removed at index time, so install the add-on where the data is first parsed.

## Data and CIM

- One JSON object per event, with flat dotted keys (`attacker.ip`); arrays become multi-value fields (`mitre_ids{}`).
- Attacker → `src`, `src_ip`, `src_host`, `src_port`, `src_user`, `user`. Decoy → `dest`, `dest_ip`, `dest_category`, `decoy_type`.
- `action=allowed` (decoys observe, they do not block), `signature`, `signature_id`, `category` (kill chain phase), `severity` (normalised to lower case), `ids_type` (host / network / application by event type), `mitre_technique_id`, `description`, `risk_score`.
- Eventtype `zscaler_deception_detection` (tags `ids`, `attack`, `alert`) excludes `whitelisted=true`; whitelisted events stay searchable under `zscaler_deception_whitelisted`.
- `zscaler:deception:audit` is parsing only in 1.0.0; CIM mapping for audit logs needs real samples.

## Release notes

- **1.0.0**: initial release.
