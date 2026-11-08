# Activity Feed Add-on for Anthropic Claude (TA-claude-activity-feed)

| | |
|---|---|
| App ID | `TA-claude-activity-feed` |
| Version | 1.0.1 |
| Author | Gaurav Malik |
| License | Apache-2.0 |
| Framework | Splunk UCC (`ucc-gen`), splunktaucclib, solnlib, splunk-sdk 2.1.x |

Activity Feed-only collector for the Anthropic Compliance API
(`GET /v1/compliance/activities`, headers `x-api-key`,
`anthropic-version: 2026-10-21`), aimed at Claude Console organizations with a
plain Admin API key. Sourcetype `anthropic:claude:activity`.

## Collection design

Per Anthropic's "Design your compliance integration" guidance:

* Closed windows `[created_at.gte, created_at.lt)` of at most 1 hour, ending
  `delay` (default 120 s, minimum 60 s) before now; the documented indexing lag
  is ~1 minute.
* Each window re-reads a 10-minute overlap; activities are de-duplicated on
  `id` (delivery is at-least-once). State in KV Store
  (`ta_claude_activity_feed_checkpoints`, key `claude_activity_feed__<input>`):
  `{"high_water", "recent": {id: created_at}}`, pruned to the overlap.
* Pages are newest first; follow `last_id` as `after_id` while `has_more`.
* The checkpoint is saved after every completed window; runs stop after
  ~55 minutes.
* 429/5xx/529 retried with backoff honouring `retry-after`; 600 req/min org
  limit.

## Build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./build.sh
```

## Notes

* `python.required = 3.9, 3.13`; splunk-sdk stays on 2.1.x (3.x needs Python
  3.13). AppInspect warns about this; it is not a failure.
* Keep `platformRequirements.splunk.Enterprise` at `"*"` in `app.manifest`.
* `ANTHROPIC_VERSION` is pinned in `claude_activity/client.py`; update it when
  Anthropic releases a new API version you have tested.
* Icons are original artwork (no Anthropic marks).
* Release checklist: bump the version in `globalConfig.json`, `app.conf`
  (twice), `app.manifest`, `claude_activity/__init__.py` (a test enforces
  this), add release notes to `package/README.txt`, rebuild.
