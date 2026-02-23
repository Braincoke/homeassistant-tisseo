# Publishing Checklist (Integration)

Use this checklist before creating a public release.

## 1) Privacy and Secrets

- [ ] Confirm no API key is hardcoded in `custom_components/tisseo/*`.
- [ ] Confirm no personal paths, emails, or private identifiers in docs/examples.
- [ ] Confirm `.gitignore` excludes local files (`__pycache__`, `._*`, `.DS_Store`, logs).

Quick scans:

```bash
rg -n -S "api_key\\s*[:=]|Bearer\\s+|token\\s*[:=]|password\\s*[:=]" .
rg -n -S "/Users/|/Volumes/homeassistant/config|@gmail\\.com|@icloud\\.com" .
```

## 2) Functional Checks

- [ ] Restart Home Assistant and verify the integration loads without errors.
- [ ] Validate config flow, options flow, and stop setup.
- [ ] Validate global API usage sensors and planned departures service.
- [ ] Validate button/manual refresh and smart/static/time-window behavior.

## 3) Documentation

- [ ] README is up to date with current entities/services/options.
- [ ] API reference docs match implementation (`TISSEO_API_REFERENCE.md`).
- [ ] Planned-window behavior docs are current (`PLANNED_WINDOW_DEPARTURES.md`).

## 4) Release Metadata

- [ ] `manifest.json` version bumped.
- [ ] `manifest.json` documentation/issue URLs point to the final public repo.
- [ ] `hacs.json` is valid for your intended repository layout.

## 5) Git Tag and Release

- [ ] Create tag `vX.Y.Z`.
- [ ] Publish GitHub release notes with migration notes and known limitations.
