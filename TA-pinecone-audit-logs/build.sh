#!/usr/bin/env bash
# Test, package and AppInspect (Splunk Cloud precert) the add-on.
# Knowledge-only add-on: no Python, no UCC, no vendored libraries.
set -euo pipefail
cd "$(dirname "$0")"

APP="TA-pinecone-audit-logs"
VERSION="$(python3 -c "import json;print(json.load(open('package/app.manifest'))['info']['id']['version'])")"

echo ">> Unit tests"
python3 -m pytest -q tests

echo ">> Assembling output/${APP}"
rm -rf output dist
mkdir -p "output/${APP}" dist
cp -R package/. "output/${APP}/"
find "output/${APP}" \( -name '__pycache__' -o -name '*.pyc' -o -name '.DS_Store' -o -name '._*' \) -prune -exec rm -rf {} +

echo ">> Checking for hidden, compiled or local files"
BAD="$(find "output/${APP}" \( -name '.*' -o -name '*.so' -o -name '*.dylib' -o -name '*.pyd' -o -name '*.dll' -o -name '*.exe' -o -path '*/local' -o -name 'local.meta' \) -print)"
if [[ -n "${BAD}" ]]; then
  echo "ERROR: not allowed in the package:" >&2
  echo "${BAD}" >&2
  exit 1
fi
find "output/${APP}" -type d -exec chmod 755 {} +
find "output/${APP}" -type f -exec chmod 644 {} +

echo ">> Packaging"
PKG="dist/${APP}-${VERSION}.tar.gz"
COPYFILE_DISABLE=1 tar --owner=0 --group=0 --numeric-owner -czf "${PKG}" -C output "${APP}" 2>/dev/null \
  || COPYFILE_DISABLE=1 tar -czf "${PKG}" -C output "${APP}"   # BSD tar (macOS)

if command -v splunk-appinspect >/dev/null 2>&1; then
  echo ">> AppInspect (Splunk Cloud precert)"
  splunk-appinspect inspect "${PKG}" \
    --mode precert \
    --included-tags cloud \
    --output-file dist/appinspect_report.json \
    --data-format json
else
  echo "WARNING: splunk-appinspect not installed; skipped (pip install -r requirements-dev.txt)" >&2
fi

echo ">> Done: ${PKG}"
