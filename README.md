# Splunk Add-ons by Gaurav Malik

Source for my Splunk technology add-ons (TAs) published on Splunkbase. Each
add-on is a self-contained [Splunk UCC](https://splunk.github.io/addonfactory-ucc-generator/)
project with its own tests and `build.sh`.

| Add-on | Folder | Version | Collects | Sourcetype |
|---|---|---|---|---|
| Audit Logs Add-on for Palo Alto Networks Cortex | [`TA-palo-alto-cortex-audit-logs`](TA-palo-alto-cortex-audit-logs) | 1.0.1 | Cortex audit management logs and agent audit reports | `cortex:audit:management_logs`, `cortex:audit:agent_reports` |
| Specialist Stats Add-on for VeeOne | [`TA-veeone`](TA-veeone) | 1.1.1 | VeeOne specialist stats (daily snapshot) | `veeone:logs` |
| Workload Security Alerts Add-on for NetApp Cloud Insights | [`TA-netapp_cloud_insights_secure`](TA-netapp_cloud_insights_secure) | 1.1.1 | NetApp Cloud Insights Workload Security (Cloud Secure) alerts | `netapp:cloud_secure:alerts` |
| Defender Inventory Add-on for Palo Alto Networks Prisma Cloud | [`TA-prisma-defender`](TA-prisma-defender) | 1.1.1 | Prisma Cloud Compute Defender inventory, summary, registry scan progress | `prisma:defender` |
| Cloud Discovery Add-on for Palo Alto Networks Prisma Cloud | [`TA-prisma-cloud-discovery`](TA-prisma-cloud-discovery) | 1.1.1 | Prisma Cloud Compute cloud discovery entities and scan results | `prisma:cloud_discovery` |
| Activity Feed Add-on for Anthropic Claude | [`TA-claude-activity-feed`](TA-claude-activity-feed) | 1.0.1 | Anthropic Compliance API Activity Feed (Claude audit events) | `anthropic:claude:activity` |
| Audit Logs Add-on for Pinecone | [`TA-pinecone-audit-logs`](TA-pinecone-audit-logs) | 1.0.0 | Pinecone audit logs from S3 (parsing + CIM; collected by the Splunk Add-on for AWS) | `pinecone:audit` |
| Audit Logs Add-on for Cursor | [`TA-cursor-audit-logs`](TA-cursor-audit-logs) | 1.0.0 | Cursor audit logs from the Admin API (Enterprise) | `cursor:audit` |

## Documentation

Full documentation is in [`docs/`](docs/README.md) (also published on the
[wiki](https://github.com/gmalik1342/splunk-addons/wiki)): a page per add-on
(setup, data, searches, troubleshooting, release notes), plus guides for
[installing](docs/Installing-an-Add-on.md), [troubleshooting](docs/Troubleshooting.md),
[building](docs/Building-and-CI.md), [releasing](docs/Releasing-a-New-Version.md)
and [publishing on Splunkbase](docs/Publishing-on-Splunkbase.md).

## Building

Requires Linux x86_64 and Python 3.12+ (or Docker). From an add-on folder:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

`build.sh` runs the unit tests, `ucc-gen build` (vendoring pure-Python
dependencies only), packages the add-on, and runs Splunk AppInspect in Splunk
Cloud precert mode. Outputs land in `dist/`: the Splunkbase upload package
(`<App-ID>-<version>.tar.gz`) and `appinspect_report.json`.

GitHub Actions ([`.github/workflows/build.yml`](.github/workflows/build.yml))
builds every add-on on each push and fails if AppInspect reports any failure
or error; the packages and reports are attached to each run as artifacts.

## Conventions

* App ID, input type, sourcetype and REST root never change between versions.
* Version lives in `globalConfig.json`, `package/default/app.conf` (twice),
  `package/app.manifest` and the add-on's `__init__.py`; a unit test enforces
  that they match. Add release notes to `package/README.txt`.
* `python.required = 3.9, 3.13` (Cortex: `3.13`, since it uses splunk-sdk 3.x).
* Keep `platformRequirements.splunk.Enterprise` at `"*"` in `app.manifest`:
  Splunkbase's packaging toolkit only knows releases up to 8.0.
* Secrets are only ever stored in Splunk's encrypted credential store; TLS is
  always verified.

## License

Apache License 2.0, see [LICENSE](LICENSE). These are community add-ons, not
built, endorsed or supported by Splunk or the vendors whose APIs they use.
