# Cloud Discovery Add-on for Palo Alto Networks Prisma Cloud (TA-prisma-cloud-discovery)

| | |
|---|---|
| App ID | `TA-prisma-cloud-discovery` |
| Version | 1.1.1 |
| Author | Gaurav Malik |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x |

Snapshot input for the Prisma Cloud Compute Console API (`/api/<ver>/`):
`cloud/discovery/download` (CSV, one event per row, `record_type=discovery_entity`)
and `cloud/discovery` (paged 50 per page, `record_type=discovery_scan_result`),
both with `x-prisma-cloud-target-env: {"permission":"monitorCloud"}`.
Sourcetype `prisma:cloud_discovery`. HTTP basic auth (access key ID / secret
key); TLS always verified.

1.1.0 replaces the Add-on Builder 1.0.0 build, which disabled TLS
verification, passed the proxy settings incorrectly, took a pre-encoded token
plus two full URLs per input, and swallowed API errors with `print()`. App ID,
input type `prisma_cloud_discovery`, sourcetype and REST root are unchanged.

Shares its client code (`bin/prisma_compute/`) with the Prisma Defender add-on.

## Build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

## Notes

* `python.required = 3.9, 3.13`; splunk-sdk stays on 2.1.x (3.x needs
  Python 3.13). AppInspect warns about this; it is not a failure.
* Keep `platformRequirements.splunk.Enterprise` at `"*"` in `app.manifest`.
* Release checklist: bump the version in `globalConfig.json`, `app.conf`
  (twice), `app.manifest`, `prisma_compute/__init__.py` (a test enforces this),
  add release notes to `package/README.txt`, rebuild.
