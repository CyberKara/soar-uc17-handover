# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-08-28 16:01 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

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
4. **Nothing to activate.** Every playbook in this package is an input (`data`)
   playbook — there is no automation trigger to enable and no **Run As** user to set.
   You run these by hand from a container: open the container, then Playbooks > Run
   Playbook and pick the one you want. See the implementation plan doc in `docs/`.

## Verification

After importing everything, open (or create) a container carrying the artifact this use
case reads, then run the playbook against it by hand: Playbooks > Run Playbook. See the
implementation plan doc in `docs/` for the artifact fields each playbook expects,
and confirm the run completes and its action results / added artifacts look right in the
container. Check `playbook.log`/`actiond.log` on the target SOAR host if a run fails or
an action errors.

## What was deliberately NOT exported

- Real credential values for any `password`-type config field (see step 2 above).
- Anything not explicitly listed in Contents above.
