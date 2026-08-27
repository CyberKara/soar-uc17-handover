# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-08-27 16:14 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi.tgz, efficientip_ddi_classic-v1.0.6.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/*.tgz` (PBs) | efficientip_ddi_enrich, efficientip_ddi_action_test, efficientip_ddi_classic_action_test |
| `playbooks/source/` | Same CFs/playbooks, extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `docs/` | Implementation plan doc, for full design context |

## Install order

1. **Install the connector app(s)** — Apps > Install App, upload each file in `connectors/`.
   (`connectors/source/` is the same code extracted for reading — don't import from there,
   the GUI needs the `.tgz`.)
2. **Configure assets from the templates in `assets/`** — Apps > Configure New Asset for
   each. Fields marked in a template's `redacted_fields` list are placeholders
   (`<<SET ME...>>`) — **you must fill these in yourself** from your own vault/CMDB; they
   were never exported with real values (SOAR encrypts `password`-type fields at rest and
   the export process cannot read them back in usable form even in principle).
3. **Import the playbooks** from `playbooks/*.tgz`, via Apps/Playbooks > Import in the
   target SOAR GUI. (`playbooks/source/` is the same code extracted for reading — don't
   import from there, the GUI needs the `.tgz`.)
4. **Activate automation playbooks** and set their **Run As** user per the implementation
   plan doc's Setup Guide (see `docs/`).

## Verification

After importing everything and activating automation playbooks, trigger one run manually
(e.g. the timer asset's manual poll, or per the implementation plan doc's trigger section)
and confirm: a container is created and the expected child playbook(s) run to completion.
Check `spawn.log`/`decided.log`/`actiond.log` on the target SOAR host if anything doesn't
fire as expected.

## What was deliberately NOT exported

- Real credential values for any `password`-type config field (see step 2 above).
- Anything not explicitly listed in Contents above.
