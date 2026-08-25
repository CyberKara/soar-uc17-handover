# efficientip_ddi — Connector-Only Export (2026-08-25, v1.0.7)

**Scope: connector only.** UC17 (EfficientIP DDI Enrichment) is still Phase 1/2 —
the design doc (`docs/usecases/uc17_efficientip_ddi_enrich_implementation_plan.md`)
was approved 2026-08-25 but the playbook side has not been built or deployed to
soar8 yet. This package does **not** contain a full UC handover (no playbooks, no
custom functions, no HANDOVER.md/HANDOVER_french.md) — only the connector app.

## What changed since the previous export (v1.0.3 → v1.0.7)

Real fixes and endpoint corrections against the actual APIM/SOLIDserver backend,
not just a version bump — see `connectors/source/efficientip_ddi/release_notes/unreleased.md`
for full detail per version. Highlights:

- **Action set changed.** `get dns record` was **removed** (1.0.5) — no
  record-level DNS endpoint was ever confirmed on the real APIM, only
  zone-level, and the original implementation was this project's own
  unconfirmed inference. Three new actions were added in its place, all
  built against user-confirmed real endpoints: **`list subnets`**, **`get ip
  pool`**, **`list aliases`** (chained off `get ip address`'s new `ip_id`
  output).
- Current action set: `test connectivity`, `get ip address`, `list subnets`,
  `get ip pool`, `list aliases`.
- `test connectivity` now calls a real confirmed no-filter endpoint
  (`ip_block_subnet_list`) instead of the original invented `/ddi/health` path.
- DDI backend auth header encoding fixed (1.0.3) — `X-DDI-Username`/
  `X-DDI-Password` are independently base64-encoded, confirmed via curl
  against the real APIM.
- SQL-injection-shaped bug fixed (1.0.7, code review): `_sql_escape()` was
  dropped when `get dns record` was removed, but the two newest actions'
  `WHERE` clauses needed it too — a name containing a single quote would
  have broken the filter.
- `get ip pool` and `list aliases`' field names are inferred by analogy to
  `get ip address`'s confirmed conventions, **not independently
  vendor-confirmed** — both carry a `raw_json` fallback field. Flag this to
  whoever validates this connector against the real appliance.

## Contents

| Path | What |
|------|------|
| `connectors/efficientip_ddi.tgz` | Installable connector package (SOAR SDK style, built fresh via `soarapps package build`, v1.0.7) — install via Apps > Install App in the target SOAR GUI |
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
a reachable service from soar8 itself** (unlike the other mocks, which run as a systemd
unit on the ansible controller, firewalled to soar8's source IP). Standing that up is
Ansible-side work, out of this project's scope.

## Next steps for a full UC17 handover

1. Build the playbook (`/kara-do-uc-create`, continuing from the approved design doc)
2. Deploy + validate against the mock backend on soar8
3. Add a `HANDOVER_REGISTRY` entry for `efficientip_ddi_enrich` in `tools/export_handover.py`
4. Re-run a full export — that pass will supersede this connector-only one
