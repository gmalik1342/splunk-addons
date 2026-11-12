# Audit Logs Add-on for Pinecone (TA-pinecone-audit-logs)

| | |
|---|---|
| App ID | `TA-pinecone-audit-logs` |
| Title | Audit Logs Add-on for Pinecone |
| Author | Gaurav Malik |
| Version | 1.0.0 |
| License | Apache-2.0 |
| Type | Knowledge-only add-on: props/transforms, CIM eventtypes/tags, dashboard. No Python. |

Pinecone has **no audit-log API**. It writes audit logs as JSON files to the
customer's S3 or GCS bucket every 30 minutes (Enterprise plan or HIPAA add-on).
So this add-on doesn't collect anything itself. The Splunk Add-on for AWS reads
the bucket with a **Generic S3 input**, using the custom source type
`pinecone:audit`, and this add-on parses, timestamps and normalises the events.

GCS isn't supported in 1.0.0, because the Google Cloud add-on's bucket input
assigns its own sourcetypes (`google:gcp:buckets:*`) and can't set a custom one.

## Layout

```
package/
  app.manifest, README.txt, LICENSES/
  default/
    app.conf
    props.conf        event breaking, timestamp, CIM field EVALs
    transforms.conf   drops non-JSON lines (e.g. Pinecone's access-test file)
    eventtypes.conf, tags.conf   CIM Authentication, Change (+account)
    macros.conf       `pinecone_audit` base search for the dashboard
    data/ui/          nav + Simple XML 1.1 dashboard (no JS)
  metadata/default.meta
  static/             original icons (no vendor logo)
tests/
  samples/            NDJSON, CRLF, JSON array (compact / spaced / one per line),
                      sorted-key variants, access-test file
  test_props.py       emulates LINE_BREAKER, SEDCMD, nullQueue and timestamping
  test_package.py     versions, names, tags→eventtypes, dashboard, no hidden/binary files
build.sh              tests → package → AppInspect (if installed)
```

## Build

```bash
pip install -r requirements-dev.txt
./build.sh            # dist/TA-pinecone-audit-logs-1.0.0.tar.gz (+ appinspect_report.json)
```

## Before publishing: verify with a real file

Pinecone doesn't document the exact layout of a batch file. The event
breaking handles one object per line and JSON arrays (single-line or one
object per line), with either key order. It does **not** handle
pretty-printed, multi-line objects. Before the first Splunkbase upload, drop
a real Pinecone audit file into `tests/samples/` with an expected-events JSON
file, add it to the test list, and run `./build.sh`. Also confirm the
`event.time` format (`2024-10-21T20:51:53.697Z` per the docs).

## Event schema (Pinecone security overview)

`id`, `organization_id`, `organization_name`, `client.userAgent`,
`actor.{principal_id, principal_name, principal_type (user|api_key|service_account), display_name}`,
`event.{time, action (create|update|delete|login), resource_type (organization|user|project|index|backup|api-key|private-endpoints),
resource_id, resource_name, outcome.{result, reason, error_code}, parameters}`.
