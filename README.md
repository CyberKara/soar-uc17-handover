# efficientip_ddi — Connector-Only Export (2026-08-25, v1.0.0, new appid)

**Scope: connector only.** UC17 (EfficientIP DDI Enrichment) is still Phase 1/2 —
the design doc (`docs/usecases/uc17_efficientip_ddi_enrich_implementation_plan.md`)
was approved 2026-08-25 but the playbook side has not been built or deployed to
soar8 yet. This package does **not** contain a full UC handover (no playbooks, no
custom functions, no HANDOVER.md/HANDOVER_french.md) — only the connector app.

## [!] If you already installed an earlier version of this package

**The v1.0.3 and v1.0.7 packages previously pushed to this mirror were broken.**
Both were missing `requests`/`urllib3`/`certifi`/`idna`/`charset-normalizer`/
`beautifulsoup4`/`soupsieve` from the bundled wheels — a `soarapps package build`
bug (see NFR-09 in `soar-connectors/docs/dev-rules.md`) that silently drops these
packages regardless of `pyproject.toml`/`uv.lock`. Installing either would fail
to import (`ModuleNotFoundError: requests`) and register **zero actions** — this
is the exact "action test connectivity not found" symptom, confirmed directly on
soar8 (`GET /rest/app/204` showed `actions: []` for the live v1.0.7 install).
**Delete any prior install of this connector before installing this version.**

## appid reset — this is a new app, not an upgrade

This version also carries a **new `appid`** (`71a7abcc-75fa-4a8d-ae9d-23fb352869e4`,
replacing `414f081c-261b-4eea-a04c-2edf9135c637`) and resets to `version 1.0.0`,
by deliberate decision rather than carrying the broken 1.0.x history/appid across
again. **SOAR will treat this as a brand-new app, not an in-place upgrade of the
old one.** If you installed a prior `414f081c...` build, delete it by hand first —
otherwise you'll end up with two `efficientip_ddi` entries.

Functionally this v1.0.0 is identical to what would have been "v1.0.8": same 5
actions (`test connectivity`, `get ip address`, `list subnets`, `get ip pool`,
`list aliases`), same wheel fix. It has **not** been rebuilt with
`soarapps package build` for this export — that tool is the one with the wheel
bug, so this exact `.tgz` (already hand-verified, see below) is shipped as-is
rather than regenerated.

## Verification performed before this export

Before packaging, this exact `.tgz` was checked with a from-scratch clean-room
install (`pip install --no-index --find-links wheels/shared splunk-soar-sdk
requests` in a fresh Python 3.13 venv, no ambient packages) — this exercises real
dependency resolution and would surface any missing wheel, unlike just importing
`app.py` in an environment that already has packages installed some other way.
Result: clean install, `import src.app` succeeds with zero errors. **Do the same
check yourself after any future rebuild of this connector** — don't trust
`soarapps package build`'s wheel set as-is (NFR-09).

## What changed since the previous export (v1.0.7 → v1.0.0 reset)

See `connectors/source/efficientip_ddi/release_notes/unreleased.md` for full
per-version detail. Highlights beyond the appid/version reset itself:

- **Action set** (unchanged from the last export): `test connectivity`,
  `get ip address`, `list subnets`, `get ip pool`, `list aliases`.
- `get ip pool` and `list aliases`' field names are inferred by analogy to
  `get ip address`'s confirmed conventions, **not independently
  vendor-confirmed** — both carry a `raw_json` fallback field.

## Contents

| Path | What |
|------|------|
| `connectors/efficientip_ddi.tgz` | Installable connector package (SOAR SDK style), v1.0.0, appid `71a7abcc-75fa-4a8d-ae9d-23fb352869e4` — install via Apps > Install App in the target SOAR GUI |
| `connectors/efficientip_ddi_README.md` | Connector's own README — full current action contract |
| `connectors/source/efficientip_ddi/` | Same package contents extracted flat, for human review only — the GUI import needs the `.tgz`, not these loose files |
| `assets/efficientip_ddi_mock.json` | Template for the connector's own asset config, pulled from soar8's `efficientip_ddi mock` asset. All `password`-type fields plus PEM blobs and the lab-internal `base_url` are redacted (`redacted_fields` lists exactly which) — re-enter real values from your own vault/CMDB. |

## What's deliberately not here

- **No playbook** — `efficientip_ddi_enrich` hasn't been written yet (Phase 2, not started)
- **No live credential values** — SOAR encrypts `password`-type asset fields at rest; this export can't read them back in usable form even in principle
- **No discovery-target or production asset data** — only this connector's own template asset was pulled, never any real target's config

## Backend note

The connector's only backend today is `soar8/migration/mock-backend/mock_efficientip_ddi.py`
(:8447) — reachable directly from the soar8 dev environment, but **not yet deployed as
a reachable service from soar8 itself**. Standing that up is Ansible-side work, out
of this project's scope.

## Next steps for a full UC17 handover

1. Build the playbook (`/kara-do-uc-create`, continuing from the approved design doc)
2. Deploy + validate against the mock backend on soar8
3. Add a `HANDOVER_REGISTRY` entry for `efficientip_ddi_enrich` in `tools/export_handover.py`
4. Re-run a full export — that pass will supersede this connector-only one
