# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-08-31 10:18 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi.tgz, efficientip_ddi_classic-v1.0.2.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/*.tgz` (PBs) | efficientip_ddi_enrich, efficientip_ddi_action_test, efficientip_ddi_classic_action_test |
| `playbooks/source/` | Same CFs/playbooks, extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `docs/` | Implementation plan doc, for full design context |

## [!] Upgrading over an earlier install — read this first

These apply only if this app is already installed on the target from a
previous package. On a completely fresh target, skip to Install order.

- **If you already have an asset for this app from an earlier package (v1.0.3 or older), you must re-enter `client_cert` and `client_ca` after installing.** Those two fields changed from a secret type to a plain text field in v1.0.4, because a certificate and a CA bundle are not secrets — only the private key is. SOAR does not convert what it already stored: the old encrypted value stays in place and is then used as if it were the certificate text. The app installs cleanly and the asset still looks filled in, but every action fails. The error names TLS or authentication, which is misleading — nothing is wrong with your credentials. Open the asset, paste the certificate and the CA bundle in again, save, and run Test Connectivity. `client_key` is unaffected.

## Install order

1. **Install the connector app(s)** — Apps > Install App, upload each file in `connectors/`.
   (`connectors/source/` is the same code extracted for reading — don't import from there,
   the GUI needs the `.tgz`.)
2. **Configure assets from the templates in `assets/`** — Apps > Configure New Asset for
   each. Fields marked in a template's `redacted_fields` list are placeholders
   (`<<SET ME...>>`) — **you must fill these in yourself**; they were never exported
   with usable values. Two different reasons appear in that list, and each placeholder
   says which one applies:

   - **Secrets** (passwords, API keys, certificates/keys) — take these from your own
     vault/CMDB. SOAR encrypts `password`-type fields at rest, so the export process
     cannot read them back in usable form even in principle.
   - **Identities and addresses** (usernames, client/app ids, endpoint URLs) — these
     are not secret, but they belonged to the source environment and are meaningless
     here. Enter the values *your* target system expects. **An identity must match the
     credential you enter beside it** — a real password paired with a leftover username
     from the source environment authenticates as nothing and returns HTTP 401.
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
