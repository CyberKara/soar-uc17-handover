# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-09-01 15:40 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi-v1.0.3.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/*.tgz` (PBs) | efficientip_ddi_enrich, efficientip_ddi_action_test |
| `playbooks/source/` | Same CFs/playbooks, extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `docs/` | Implementation plan doc, for full design context |

## [!] Upgrading over an earlier install — read this first

These apply only if this app is already installed on the target from a
previous package. On a completely fresh target, skip to Install order.

- **Which of these applies depends on what is already installed — check the Apps list first.** Open Apps and search for `EfficientIP`. If you see **exactly one** app (named `efficientip_ddi` / `EfficientIP DDI`), you installed the 2026-08-31 package or later: this one is a **normal in-place upgrade**. Install it over the existing app — same internal identifier — and your existing asset keeps working with every credential intact. **Do not delete anything and do not re-enter any credential.** If instead you see **two** apps (an `efficientip_ddi` and an `EfficientIP DDI (Classic)`), you are still on a package older than 2026-08-31, and the note below applies to you instead.

- **Only if the Apps list showed TWO apps.** Up to 2026-08-31 this use case shipped two: `efficientip_ddi` (SDK-based) and `EfficientIP DDI (Classic)`. The SDK app has been withdrawn, because its actions cannot be run from the connector's edit/view page in the SOAR web interface — a limitation of the platform, not of the app. The classic app is now the only one, and it has taken the `efficientip_ddi` name under a new internal identifier, so SOAR installs it as a brand-new app rather than upgrading anything. After installing: delete BOTH old apps and their assets through the web interface (Apps > the app > Delete), then create a fresh asset for the new app from the template in this package. Re-enter every credential by hand; secret fields do not carry across in the template.

- **Two new asset fields, both optional.** `retry_count` (default 3) and `retry_backoff` (default 2 seconds) control how a request answered with HTTP 401 is retried. They have working defaults, so an in-place upgrade needs no action: leave them alone unless you want to tune them. Set `retry_count` to 1 to disable retrying entirely.

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
