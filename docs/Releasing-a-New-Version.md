# Releasing a new version

## 1. Change the code

Keep these stable across versions, or existing installs and searches break:

- **App ID** (`[package] id` / `[id] name` in `app.conf`)
- **Input type** (the modular input / script name)
- **Sourcetype(s)**
- **REST root** (`meta.restRoot` in `globalConfig.json`)

## 2. Bump the version in every place

| File | Where |
|---|---|
| `globalConfig.json` | `meta.version` |
| `package/default/app.conf` | `[launcher] version` **and** `[id] version` |
| `package/app.manifest` | `info.id.version` |
| `package/bin/<package>/__init__.py` | `ADDON_VERSION` |

A unit test (`test_versions_match`) fails the build if these don't match. Also increase `[install] build` in `app.conf`.

Use semantic versions: patch (`1.1.1`) for fixes, minor (`1.2.0`) for new features, major for breaking changes. Splunkbase rejects re-uploads of an existing version number.

## 3. Release notes

Add an entry at the top of the *Release notes* section in `package/README.txt` and on the add-on's wiki page.

## 4. Build and check

Push to `main` (or open a pull request). GitHub Actions builds and AppInspects all add-ons. Download the package from the run's **Artifacts**, or build locally with `./build.sh`. Expect **0 failures**; see [Building and CI](Building-and-CI.md) for the expected warnings.

## 5. Upload

Follow [Publishing on Splunkbase](Publishing-on-Splunkbase.md): upload the new package as a new release of the existing listing.
