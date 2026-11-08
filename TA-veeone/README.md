# Specialist Stats Add-on for VeeOne (TA-veeone)

| | |
|---|---|
| App ID | `TA-veeone` |
| Title | Specialist Stats Add-on for VeeOne |
| Author | Gaurav Malik |
| Version | 1.1.1 |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x |

Collects specialist stats from the VeeOne open API
(`GET {base_url}/api/v2/specialist/stats`, `X-API-Key` header) as one JSON
event per specialist, sourcetype `veeone:logs`. Each run is a full snapshot;
all events in a run share the run timestamp. Default interval: daily.

1.1.0 replaces the Add-on Builder 1.0.0 build, whose input called an
undefined `fetch_events()` and stored a client ID / secret key in plain text.
The App ID, input type (`veeone_logs`), sourcetype and REST root (`TA_veeone`)
are unchanged.

## Layout

```
globalConfig.json          # UCC: UI, REST handlers, input stanza
package/
  app.manifest  README.txt  LICENSES/LICENSE.txt
  default/ app.conf props.conf
  metadata/default.meta    # write: admin, sc_admin
  static/  appIcon*.png
  lib/requirements.txt     # pure-Python deps vendored by ucc-gen (see comments)
  bin/
    veeone/                # Splunk-free client (unit tested) + modinput
    veeone_logs.py         # modular input entry point
    veeone_account_handler.py  # validates the API key on account save
tests/                     # pytest, no Splunk needed
build.sh                   # test -> ucc-gen build -> package -> AppInspect (cloud)
```

## Build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

Outputs `dist/TA-veeone-1.1.0.tar.gz` and `dist/appinspect_report.json`.

## Notes

* `python.required = 3.9, 3.13`: Splunk 10.2+ runs the add-on on 3.13, older
  versions use Python 3.9. `splunk-sdk` stays on 2.1.x because 3.x requires
  Python 3.13 (AppInspect warns that the SDK is older than 3.0; it is not a
  failure). Moving to splunk-sdk 3.x means dropping 3.9 and Splunk < 10.2.
* Keep `platformRequirements.splunk.Enterprise` in `app.manifest` at `"*"`:
  Splunkbase's packaging toolkit only knows releases up to 8.0, so narrower
  ranges fail upload validation. Set real compatibility on the listing.
* Release checklist: bump the version in `globalConfig.json`, `app.conf`
  (twice), `app.manifest`, `veeone/__init__.py` (a test enforces this), add
  release notes to `package/README.txt`, rebuild.
