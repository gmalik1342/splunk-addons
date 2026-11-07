#!/usr/bin/env bash
# Build, package and AppInspect (Splunk Cloud precert) the add-on.
# Run on Linux x86_64 (or in Docker, see README.md) so that no macOS/Windows
# binaries end up in lib/.
set -euo pipefail
cd "$(dirname "$0")"

APP="TA-palo-alto-cortex-audit-logs"
VERSION="$(python3 -c "import json;print(json.load(open('globalConfig.json'))['meta']['version'])")"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ERROR: build on Linux (or use the Docker command in README.md)." >&2
  exit 1
fi

echo ">> Unit tests"
python3 -m pytest -q tests

echo ">> ucc-gen build ${APP} ${VERSION}"
rm -rf output dist
# Vendor pure-Python wheels only, resolved for the add-on's Python
# (python.required = 3.13), with no transitive resolution: every runtime
# dependency is listed explicitly in package/lib/requirements.txt. This keeps
# compiled binaries (grpcio, protobuf, mypyc builds of charset-normalizer) and
# solnlib's unused opentelemetry stack out of lib/.
PIP_FLAGS="--no-deps --only-binary=:all: --platform any --implementation py --python-version 3.13"
ucc-gen build --ta-version "${VERSION}" --pip-custom-flag "${PIP_FLAGS}"

echo ">> Removing build junk"
find "output/${APP}" \( -name '__pycache__' -o -name '*.pyc' -o -name '.DS_Store' -o -name '._*' \) -prune -exec rm -rf {} +

echo ">> Checking for compiled binaries (not allowed in lib/)"
BINARIES="$(find "output/${APP}" -type f \( -name '*.so' -o -name '*.dylib' -o -name '*.pyd' -o -name '*.dll' -o -name '*.exe' \) || true)"
if [[ -n "${BINARIES}" ]]; then
  echo "ERROR: compiled files found; fix package/lib/requirements.txt:" >&2
  echo "${BINARIES}" >&2
  exit 1
fi

echo ">> Packaging"
mkdir -p dist
COPYFILE_DISABLE=1 ucc-gen package --path "output/${APP}" -o dist
PKG="$(ls dist/${APP}*.tar.gz | head -1)"

echo ">> AppInspect (Splunk Cloud precert)"
splunk-appinspect inspect "${PKG}" \
  --mode precert \
  --included-tags cloud \
  --output-file dist/appinspect_report.json \
  --data-format json

echo ">> Done: ${PKG}"
echo "   Report: dist/appinspect_report.json"
