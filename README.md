# Splunk Add-ons by Gaurav Malik

Source for my Splunk technology add-ons (TAs) published on Splunkbase. Each
add-on is a self-contained [Splunk UCC](https://splunk.github.io/addonfactory-ucc-generator/)
project with its own tests and `build.sh`.

| Add-on | Folder | Version | Collects | Sourcetype |
|---|---|---|---|---|
| Palo Alto Cortex Audit Logs Add-on | [`TA-palo-alto-cortex-audit-logs`](TA-palo-alto-cortex-audit-logs) | 1.0.0 | Cortex audit management logs and agent audit reports | `cortex:audit:management_logs`, `cortex:audit:agent_reports` |
| VeeOne Add-on | [`TA-veeone`](TA-veeone) | 1.1.0 | VeeOne specialist stats (daily snapshot) | `veeone:logs` |
| NetApp_Cloud_Insights_Secure | [`TA-netapp_cloud_insights_secure`](TA-netapp_cloud_insights_secure) | 1.1.0 | NetApp Cloud Insights Workload Security (Cloud Secure) alerts | `netapp:cloud_secure:alerts` |
| Prisma Defender | [`TA-prisma-defender`](TA-prisma-defender) | 1.1.0 | Prisma Cloud Compute Defender inventory, summary, registry scan progress | `prisma:defender` |
| Prisma Cloud Discovery | [`TA-prisma-cloud-discovery`](TA-prisma-cloud-discovery) | 1.1.0 | Prisma Cloud Compute cloud discovery entities and scan results | `prisma:cloud_discovery` |
| Claude Activity Feed Add-on | [`TA-claude-activity-feed`](TA-claude-activity-feed) | 1.0.0 | Anthropic Compliance API Activity Feed (Claude audit events) | `anthropic:claude:activity` |

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
