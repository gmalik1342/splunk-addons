# Prisma Defender (TA-prisma-defender)

| | |
|---|---|
| App ID | `TA-prisma-defender` |
| Version | 1.1.0 |
| Author | Gaurav Malik |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x |

Snapshot input for the Prisma Cloud Compute Console API (`/api/<ver>/`):
`defenders` (paged, 50 per page, all pages, connected + disconnected),
`defenders/summary`, `registry/progress?onDemand=false`. Sourcetype
`prisma:defender`; events carry `record_type`. HTTP basic auth (access key ID /
secret key); TLS always verified.

1.1.0 replaces the Add-on Builder 1.0.0 build, which disabled TLS
verification, broke Defender collection when no proxy was set, requested 100
per page from an API capped at 50 (so it stopped after 50 Defenders), and
hard-coded two registry names. App ID, input type `prisma_defender`,
sourcetype and REST root are unchanged; event field names are kept.

Package `bin/prisma_compute/` (not `prisma_defender/`, which would clash with
the `prisma_defender.py` input script).

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
