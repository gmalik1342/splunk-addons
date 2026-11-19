# Test samples

- The first event (type `recon`) is a real Zscaler Deception syslog event
  supplied by a user (addresses are documentation ranges).
- The `ssh`, `endpoint` and whitelisted events are **synthetic**, built from
  the field names in Google SecOps' Zscaler Deception parser documentation.
  Replace them with real events when available.
- `expected.json` is the JSON each file must parse to, in order.
