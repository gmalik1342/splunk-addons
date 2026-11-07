# Palo Alto Cortex Audit Logs Add-on

| | |
|---|---|
| App ID | `TA-palo-alto-cortex-audit-logs` |
| Title | Palo Alto Cortex Audit Logs Add-on |
| Author | Gaurav Malik |
| Version | 1.0.0 |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk |

Splunk input add-on for the Cortex public API audit endpoints. None of the
existing Cortex listings on Splunkbase cover them: Palo Alto Cortex XDR (SOAR),
the Endpoint Retriever (asset inventory), CCX Cortex XDR (CEF) and the XSOAR
Analytics App.

| Input (modular input type) | Endpoint | Sourcetype | Event time |
|---|---|---|---|
| `cortex_audit_management_logs` | `POST /public_api/v1/audits/management_logs` | `cortex:audit:management_logs` | `AUDIT_INSERT_TIME` |
| `cortex_audit_agent_reports` | `POST /public_api/v1/audits/agents_reports` | `cortex:audit:agent_reports` | `TIMESTAMP` |

Each input has a user-defined **Interval** (60–86400 s), **Index**, **Account**,
optional **Start Time (UTC)** and **Ingestion Delay**. Agent reports also have
an optional **Categories** filter (audit / monitoring / status).

## Repository layout

```
globalConfig.json                 # UCC: UI, REST handlers, input stanzas, monitoring dashboard
package/
  app.manifest                    # schema 2.0.0, author, license, deployments
  README.txt                      # end-user docs + release notes (shipped)
  LICENSES/LICENSE.txt
  default/ app.conf props.conf eventtypes.conf tags.conf
  metadata/default.meta           # write: admin, sc_admin
  static/  appIcon*.png           # original artwork (no vendor logos)
  lib/requirements.txt            # vendored into lib/ by ucc-gen
  bin/
    cortex_audit/                 # Splunk-free core, unit tested
      client.py                   # auth (standard/advanced), retries, proxy, HTTPS-only
      collector.py                # closed-window collection + checkpoints
      modinput.py                 # splunklib Script base, solnlib config/logging/KV checkpoint
    cortex_audit_management_logs.py
    cortex_audit_agent_reports.py
    cortex_audit_account_handler.py   # validates credentials on account save
tests/                            # pytest, no Splunk needed
build.sh                          # test -> ucc-gen build -> package -> AppInspect (cloud)
```

UCC generates `restmap.conf`, `web.conf`, `server.conf`, `inputs.conf`,
`README/*.spec`, the UI views, `import_declare_test.py` and the REST handler
scripts from `globalConfig.json`. Do not hand-edit those in `output/`.

## Collection design

* Both endpoints accept `timestamp` `gte`/`lte` filters (epoch ms) and return
  at most 100 rows per request. Management logs **cannot** be sorted by
  timestamp (documented sort fields: type, sub-type, result).
* So each run collects **closed windows** `[start, end]` of at most 1 hour,
  from `checkpoint + 1 ms` up to `now − Ingestion Delay`, paging by offset
  (`search_from`/`search_to`). Because the window is in the past, offsets are
  stable whatever order the API returns.
* The KV Store checkpoint (`ta_palo_alto_cortex_audit_logs_checkpoints`,
  key `<input_type>__<input_name>`) moves forward only after a window is fully
  written. Delivery is at-least-once: a crash mid-window re-collects that
  window. Windows never overlap (`lte end`, next `gte end+1`), so normal runs
  produce no duplicates.
* Catch-up runs stop after ~55 min and resume next interval.
* Retries: 429/5xx and connection errors, exponential backoff with jitter,
  honours `Retry-After`. 400/401/402/403 fail fast with a clear message.
  Secrets are never logged.
* Advanced keys: SHA-256(api_key + 64-char nonce + ms timestamp), fresh per
  request.

## Build

Build on **Linux x86_64** so pip never vendors macOS/Windows binaries (the
Prisma reference package shipped a `darwin` `.so`).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

Or from macOS/Windows via Docker:

```bash
docker run --rm -v "$PWD":/src -w /src python:3.9 \
  bash -c "pip install -r requirements-dev.txt && ./build.sh"
```

Outputs: `dist/TA-palo-alto-cortex-audit-logs-1.0.0.tar.gz` and
`dist/appinspect_report.json`.

Unit tests only: `python3 -m pytest -q tests`

## Splunk Cloud vetting checklist

- [ ] `./build.sh` passes; `appinspect_report.json` has 0 failures and 0 errors
      for `--mode precert --included-tags cloud` (review any warnings).
- [ ] `build.sh` reported no compiled binaries. If a dependency pulls them in,
      pin a version that doesn't, or document them for manual review.
- [ ] Version identical in `globalConfig.json`, `app.conf`, `app.manifest`,
      `cortex_audit/__init__.py` (tests enforce this).
- [ ] Install on a test Splunk 10.2+ instance (Python 3.13 is required): create an account (validation
      should succeed), create both inputs, confirm events,
      `index=_internal source=*ta_palo_alto_cortex_audit_logs*` is clean, and
      the Monitoring dashboard shows ingestion.
- [ ] Verify CIM: `| datamodel Authentication search | search sourcetype=cortex:audit:management_logs`.
- [ ] Upload to Splunkbase → **New App** → select *Splunk Cloud* compatibility
      to trigger Cloud vetting. Provide the README text, screenshots, and a
      support contact.
- [ ] For each release: bump the version in the four places, add release notes
      to `package/README.txt`, rebuild.

* Keep `platformRequirements.splunk.Enterprise` in `app.manifest` at `"*"`.
  Splunkbase's Packaging Toolkit only knows Enterprise releases up to 8.0, so
  any range excluding 8.0 (e.g. `>=9.0`, `>=10.2`) fails package validation.
  The real floor (10.2+, for Python 3.13) is enforced by `python.required`
  and set via the Splunkbase listing's compatibility checkboxes.

## Before first upload

* Confirm the App ID / title are free on Splunkbase (search "Cortex Audit").
* Decide on a public support email or URL for the listing and, optionally,
  add `email`/`company` to the author block in `app.manifest`.
* Test against a real tenant. The response schema here follows the published
  docs, and real samples may show fields worth adding to `props.conf`
  (e.g. a CIM Change mapping for non-AUTH management events).
