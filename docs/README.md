# Splunk Add-ons

Documentation for Gaurav Malik's Splunk technology add-ons (TAs). Source code, build scripts and CI live in the [main repository](https://github.com/gmalik1342/splunk-addons).

## Add-ons

| Add-on | Version | What it collects | Sourcetype(s) | Splunk |
|---|---|---|---|---|
| [Audit Logs Add-on for Palo Alto Networks Cortex](Cortex-Audit-Logs.md) | 1.0.1 | Cortex audit management logs and agent audit reports | `cortex:audit:management_logs`, `cortex:audit:agent_reports` | 10.2+ |
| [Specialist Stats Add-on for VeeOne](VeeOne.md) | 1.1.1 | VeeOne specialist stats (daily snapshot) | `veeone:logs` | 9.0+ |
| [Workload Security Alerts Add-on for NetApp Cloud Insights](NetApp-Cloud-Insights-Secure.md) | 1.1.1 | Workload Security (Cloud Secure) alerts | `netapp:cloud_secure:alerts` | 9.0+ |
| [Defender Inventory Add-on for Palo Alto Networks Prisma Cloud](Prisma-Defender.md) | 1.1.1 | Prisma Cloud Compute Defender inventory, summary, registry scan progress | `prisma:defender` | 9.0+ |
| [Cloud Discovery Add-on for Palo Alto Networks Prisma Cloud](Prisma-Cloud-Discovery.md) | 1.1.1 | Prisma Cloud Compute cloud discovery entities and scan results | `prisma:cloud_discovery` | 9.0+ |
| [Activity Feed Add-on for Anthropic Claude](Claude-Activity-Feed.md) | 1.0.1 | Anthropic Compliance API Activity Feed (Claude audit events) | `anthropic:claude:activity` | 9.0+ |
| [Audit Logs Add-on for Pinecone](Pinecone-Audit-Logs.md) | 1.0.0 | Pinecone audit logs from S3 (parsing + CIM; collected by the Splunk Add-on for AWS) | `pinecone:audit` | 9.0+ |
| [Audit Logs Add-on for Cursor](Cursor-Audit-Logs.md) | 1.0.0 | Cursor audit logs from the Admin API (Enterprise) | `cursor:audit` | 9.0+ |

All add-ons support Splunk Cloud Platform.

The Pinecone add-on is knowledge-only: Pinecone delivers audit logs to an S3 bucket, so collection is done by the Splunk Add-on for AWS and the add-on provides parsing, CIM mapping and a dashboard.

## Guides

- [Installing an add-on](Installing-an-Add-on.md): where to install and the common setup steps
- [Troubleshooting](Troubleshooting.md): logs, common HTTP errors, re-collecting data
- [Building and CI](Building-and-CI.md): build locally, what GitHub Actions does
- [Releasing a new version](Releasing-a-New-Version.md): version bump checklist
- [Publishing on Splunkbase](Publishing-on-Splunkbase.md): upload checklist and form answers

## Common design

Every add-on with a collector is built on the [Splunk UCC framework](https://splunk.github.io/addonfactory-ucc-generator/) and follows the same rules:

- **Accounts, not per-input secrets.** Credentials are entered once under *Configuration > Accounts*, stored encrypted in Splunk's credential store, and tested against the API when you save.
- **TLS is always verified.** HTTP and SOCKS5 proxies are supported under *Configuration > Proxy*.
- **Retries with backoff** for rate limits (HTTP 429) and server errors, honouring `Retry-After`.
- **No duplicates by design.** Incremental inputs keep a KV Store checkpoint; snapshot inputs stamp every event in a run with the same time.
- **Pure-Python dependencies only**, so the packages pass Splunk Cloud vetting.
- **Stable names.** App ID, input type, sourcetype and REST root never change between versions.

---
These are community add-ons, not built, endorsed or supported by Splunk or by the vendors whose APIs they use.
