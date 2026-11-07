# Publishing on Splunkbase

## Upload checklist

1. Build the package (GitHub Actions artifact or `./build.sh`); AppInspect must show **0 failures**.
2. On Splunkbase: **existing listing > Manage > New release**, or **Submit an app** for a new one.
3. Upload `<App ID>-<version>.tar.gz`. Splunkbase runs its own packaging validation and security check.
4. Fill in the release form (below), then submit. Selecting **Splunk Cloud** compatibility triggers Cloud vetting.

## Lessons learned

| Problem | Fix |
|---|---|
| *"Splunk Packaging Toolkit error: manifest.platformRequirements.splunk: Version requirement includes no supported version of Splunk Enterprise"* | The toolkit only knows Enterprise releases up to 8.0. Keep `"Enterprise": "*"` in `app.manifest` and set real compatibility with the checkboxes on the form |
| *"Summary must be at least 80 characters"* | Write a summary of 80+ characters |
| Re-upload rejected | Bump the version; the same version can't be uploaded twice |
| Old listing retired for Python / Cloud issues | Rebuild with UCC, set `python.required`, remove compiled binaries and `local.meta`, verify TLS (see each add-on's 1.1.0 notes) |

## Release form answers

| Field | Answer |
|---|---|
| End-user license | Apache License Version 2.0 |
| Export control: *"This package contains encrypted code"* | **Unchecked.** The add-ons use the platform's TLS and Splunk's credential store, and bundle no cryptography libraries. Re-check this if a crypto library is ever bundled |
| Platform version compatibility | 9.0–10.7 (all), **except Cortex Audit Logs: 10.2+ only** (Python 3.13) |
| Release notes | From the add-on's wiki page |

## Per-add-on listing answers

| Add-on | Categories | CIM versions |
|---|---|---|
| Cortex Audit Logs | Security, Fraud & Compliance; Endpoint | 4.x, 5.x, 6.x, 8.x (Authentication) |
| VeeOne | Business Analytics; Information | none |
| NetApp Cloud Insights Secure | Security, Fraud & Compliance; IT Operations | 4.x, 5.x, 6.x, 8.x (Alerts) |
| Prisma Defender | Security, Fraud & Compliance; Endpoint | none |
| Prisma Cloud Discovery | Security, Fraud & Compliance; Endpoint | none |
| Claude Activity Feed | Artificial Intelligence; Security, Fraud & Compliance | none |

## Listing text

Each listing needs a summary (80+ characters), short description, details, installation and troubleshooting. Base them on the add-on's wiki page: overview → details, *Setup* → installation, *Troubleshooting* → troubleshooting. State that it's a community add-on, not affiliated with the vendor, and don't use vendor logos.

## Media

Splunkbase gallery images: 1600×900 PNG works well. Use illustrative graphics (overview, how it works, sample event) or real screenshots from a test instance; never mock up a Splunk UI that isn't real, and don't use vendor logos.

## Naming

- "X Add-on for Splunk" is the accepted pattern; don't start a name with "Splunk" or use a full product name like "Splunk Enterprise".
- Don't change the App ID of an existing listing; a new App ID means a new listing, and existing installs won't upgrade.
