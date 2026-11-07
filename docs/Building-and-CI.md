# Building and CI

Each add-on folder in the [repository](https://github.com/gmalik1342/splunk-addons) is a self-contained [Splunk UCC](https://splunk.github.io/addonfactory-ucc-generator/) project:

```text
TA-<name>/
  globalConfig.json        UCC: UI, REST handlers, inputs (generates confs and UI)
  package/
    app.manifest           Splunkbase metadata
    README.txt             end-user docs + release notes (shipped in the package)
    default/               app.conf, props.conf, (eventtypes.conf, tags.conf)
    metadata/default.meta  write: admin, sc_admin
    static/                app icons
    lib/requirements.txt   runtime dependencies, vendored into lib/ at build time
    bin/                   modular input, account handler, and a Splunk-free package
  tests/                   pytest unit tests (no Splunk needed)
  build.sh                 test -> build -> package -> AppInspect
```

## Build locally

Linux x86_64 with Python 3.12+ (or Docker):

```bash
cd TA-<name>
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

From macOS/Windows:

```bash
docker run --rm -v "$PWD":/src -w /src python:3.13 \
  bash -c "pip install -r requirements-dev.txt && ./build.sh"
```

`build.sh`:

1. runs the unit tests;
2. runs `ucc-gen build`, installing dependencies with `--no-deps --only-binary=:all: --platform any --implementation py`, so **only pure-Python wheels** end up in `lib/` (no `.so`/`.pyd` files to fail Cloud vetting). It stops with an error if any compiled file appears;
3. packages to `dist/<App ID>-<version>.tar.gz`;
4. runs `splunk-appinspect inspect --mode precert --included-tags cloud` and writes `dist/appinspect_report.json`.

Every transitive dependency is listed explicitly in `package/lib/requirements.txt`. solnlib's `grpcio`/`protobuf`/`opentelemetry` dependencies are deliberately left out: they are only used by `solnlib.observability`, which nothing imports, and they ship compiled binaries.

## GitHub Actions

[`.github/workflows/build.yml`](../.github/workflows/build.yml) runs on every push to `main`, on pull requests and on demand (*Actions > Build and AppInspect > Run workflow*). It builds all six add-ons in parallel and **fails if AppInspect reports any failure or error**.

The upload packages and AppInspect reports are attached to each run: open the run under **Actions** and download them from **Artifacts**.

## Expected AppInspect warnings

Packages pass with **0 failures**. These warnings remain and are expected:

| Warning | Why it stays |
|---|---|
| `check_for_splunk_js`, `check_for_splunk_js_header_and_footer_view` | In UCC's generated UI JavaScript |
| `check_for_custom_mako_templates` | UCC's `base.html` (static; no Mako code), required by the UCC pages |
| `check_python_sdk_version` | splunk-sdk 2.1.x kept for Python 3.9 support (3.x needs Python 3.13) |
| `check_for_possible_threading` | `subprocess`/`threading` inside solnlib and splunklib |
| `check_hostnames_and_ips` | Example IPs in third-party docs (PySocks metadata) |
| `check_for_python_script_existence`, `check_for_modular_inputs`, `check_ucc_dependencies` | Informational ("No action required") |
