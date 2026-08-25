# efficientip_ddi — Connector-Only Export (2026-08-25)

**Scope: connector only.** UC17 (EfficientIP DDI Enrichment) is still Phase 1/2 —
the design doc (`docs/usecases/uc17_efficientip_ddi_enrich_implementation_plan.md`)
was approved 2026-08-25 but the playbook side has not been built or deployed to
soar8 yet. This package does **not** contain a full UC handover (no playbooks, no
custom functions, no HANDOVER.md/HANDOVER_french.md) — only the connector app that
was built and installed on soar8 ahead of the playbook work.

## Contents

| Path | What |
|------|------|
| `connectors/efficientip_ddi.tgz` | Installable connector package (SOAR SDK style, built fresh via `soarapps package build`, v1.0.3) — install via Apps > Install App in the target SOAR GUI |
| `connectors/efficientip_ddi_README.md` | Connector's own README — full action contract (`test connectivity`, `get ip address`, `get dns record`) |
| `connectors/source/efficientip_ddi/` | Same package contents extracted flat, for human review only — the GUI import needs the `.tgz`, not these loose files |
| `assets/efficientip_ddi_mock.json` | Template for the connector's own asset config, pulled from soar8's `efficientip_ddi mock` asset. All `password`-type fields plus PEM blobs and the lab-internal `base_url` are redacted (`redacted_fields` lists exactly which) — re-enter real values from your own vault/CMDB. Non-secret fields (`client_id`, `ddi_username`, `verify_ssl`) came through as configured on the source env; review before reuse, this was a lab mock asset, not a production one. |

## What's deliberately not here

- **No playbook** — `efficientip_ddi_enrich` hasn't been written yet (Phase 2, not started)
- **No live credential values** — SOAR encrypts `password`-type asset fields at rest; this export can't read them back in usable form even in principle
- **No discovery-target or production asset data** — only this connector's own template asset was pulled, never any real target's config

## Backend note

The connector's only backend today is `soar8/migration/mock-backend/mock_efficientip_ddi.py`
(:8447) — reachable directly from the soar8 dev environment, but **not yet deployed as
a reachable service from soar8 itself** (unlike the other mocks, which run as a systemd
unit on the ansible controller, firewalled to soar8's source IP). Standing that up is
Ansible-side work, out of this project's scope, and is a prerequisite for testing this
connector's asset end-to-end in any environment other than this dev one.

## Next steps for a full UC17 handover

1. Build the playbook (`/kara-do-uc-create`, continuing from the approved design doc)
2. Deploy + validate against the mock backend on soar8
3. Add a `HANDOVER_REGISTRY` entry for `efficientip_ddi_enrich` in `tools/export_handover.py`
4. Re-run a full export — that pass will supersede this connector-only one
