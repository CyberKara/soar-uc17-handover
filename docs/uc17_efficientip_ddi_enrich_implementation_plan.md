# EfficientIP DDI Enrichment (UC17) — Implementation Plan

**Status:** [x] planned | [x] built | [x] E2E validated | [ ] code review fixes | [ ] VPE polish | [ ] released

> Design drafted 2026-08-24, approved 2026-08-25 (open questions below resolved by
> user). **Built + deployed + live-verified 2026-08-25 (later still)** — see
> "Build + live-verify (2026-08-25)" below.

## Context

Analyst-driven IP/DNS lookup enrichment against EfficientIP SOLIDserver (DDI:
DNS/DHCP/IPAM), reached through an APIM gateway. The connector (`efficientip_ddi`,
SOAR SDK, app id 204 on soar8) was built and installed first, per explicit user
request — this doc covers the playbook side that calls it, the second half of the
same `/kara-do-uc-create` session.

**No real SOLIDserver/APIM instance exists.** The connector's only backend is
`soar8/migration/mock-backend/mock_efficientip_ddi.py` (:8447), now deployed as
`mock-efficientip-ddi.service` on the ansible controller (`<<SET ME — this was the LAB's own internal address, not a real target address>>`, mTLS
left enabled — matching the real APIM's requirement, unlike the other mocks'
`--no-mtls` convenience), same pattern as the existing mock services, firewalled
to soar8's source IP only (Ansible-side fix, 2026-08-25 — see ansible project's
`docs/next-steps.md`). The `efficientip_ddi mock` SOAR asset (id 19) passes
`test connectivity` and all 5 actions complete the full mTLS+auth+HTTP round trip
against app id 205 (v1.0.0, appid `71a7abcc-...` — reset from the original
`414f081c-...` after an unrelated `soarapps package build` wheel-bundling bug,
see NFR-09 in `soar-connectors/docs/dev-rules.md`, required reinstalling anyway).

Connector actions available (as of app v1.0.0/appid `71a7abcc-...`, app id 205):
`test connectivity`, `get ip address` (IPAM lookup by IP — `ip_id`, subnet, space,
status, hostname, MAC, class, description), `list subnets`, `get ip pool`, `list
aliases` (aliases of a known `ip_id`, chained off `get ip address`'s output).
**`get dns record` does not exist** — no confirmed record-level DNS service was
ever found on the real APIM (only zone-level `dns_zone_list`), so the action was
removed rather than shipped on a guess. See
`soar8/soar-connectors/connectors/efficientip_ddi/README.md` for the full contract.

## Architecture (revised 2026-08-25 — `get dns record` removal)

**One Data playbook, no orchestrator, no CFs.** Two chained lookup actions with no
branching complexity between them doesn't justify a parent/child split or a custom
function — matches `constraints.md`'s bias toward the simplest structure that fits.

The original design paired an `ip` input with `get ip address` and a `hostname`
input with `get dns record` — that second half no longer has an action to call.
**User decision (2026-08-25):** drop the `hostname` input entirely; replace the
DNS-ish angle with `list aliases`, chained off `get ip address`'s `ip_id` output —
alias hostnames (e.g. `host01-alt.corp.local`) cover similar ground to a DNS
lookup for this use case's purposes, without inventing an unconfirmed endpoint.

- **`efficientip_ddi_enrich`** (Data playbook, `playbooks/efficientip_ddi_enrich/`)
  - **Trigger**: none — not automation-triggered. Runs either analyst-initiated
    (manually launched against an existing container) or chained from another UC's
    playbook via `phantom.playbook()`, the same role `ip_enrich` plays for UC2/UC3
    today.
  - **Inputs** (`playbook_input`): `ip` (required string) — single input now.
  - **Flow**:
    1. `on_start` — native **decision** block: if `ip` is empty, route to
       `format_error` (native **format** block → terminal note); otherwise continue.
    2. Native **action** block: `get ip address` on the `efficientip_ddi` asset,
       input bound to `playbook_input:ip`.
    3. Native **decision** block: if `get ip address` succeeded and its `ip_id`
       output is non-empty, continue to alias lookup; otherwise skip straight to
       the format/note step with just the IP result (or the failure noted) —
       partial success stays a first-class outcome, not an error (see resolved
       question 1 below, still applies to this chain).
    4. Native **action** block: `list aliases` on the same asset, input bound to
       `get_ip_address:action_result.data.*.ip_id` (the prior action's own output,
       not `playbook_input`).
    5. Both paths converge on a native **format** block assembling a
       human-readable summary (subnet/space/status/hostname/MAC/class/description
       from `get ip address`, plus alias name(s) from `list aliases` if that step
       ran), then `phantom.add_note()` on the container so an analyst running this
       manually sees the result without digging into action-run history.
    6. `phantom.save_playbook_output_data()` exposes the raw action-result fields
       (not just the formatted note) so a **parent** playbook that chains this one
       can consume individual fields directly — same pattern as
       `playbook-patterns.md`'s documented `output_spec` usage.
  - **Activation**: none needed — Data playbooks aren't automation-triggered, so
    there's nothing to `POST /rest/playbook/{id} {"active": true}` here.

## Open questions — resolved 2026-08-25

1. **Partial success is fine.** If `get ip address` succeeds but the alias lookup
   404s (or vice versa were both still independent), that is not a playbook
   failure — note the partial result in the summary rather than erroring out.
2. **Keeps its UC number — stays UC17**, not reclassified as an unnumbered
   Integration.
3. **No UC chains into this right away.** Ships standalone, buildable/testable
   on its own; wiring into a parent UC (if any) is deferred to later.
4. **(New, resolved same day) `hostname`/`get dns record` dropped, replaced by
   `ip`→`get ip address`→`list aliases` chaining** — see Architecture above.

## Testing strategy

Same mock-first approach as every other UC: against the now-reachable
`efficientip_ddi mock` asset (id 19, `mock-efficientip-ddi.service` on the ansible
controller), run the playbook against a test container with `ip` matching the
mock's seed data (`10.20.30.40`, `ip_id` 1001, alias `host01-alt.corp.local`),
confirm the note and `save_playbook_output_data()` fields both come back correct
for the full chain, then confirm the not-found path (e.g. `10.20.30.99`, which has
no alias seed data) produces the intended partial-success behavior per question 1.

## Build + live-verify (2026-08-25, later still)

Built exactly per the Architecture above (single Data playbook, no CFs, native
action/decision/format blocks per `vpe-block-reference.md`) and registered in
`deploy.py`/`pull_soar.py`/`snapshot.py`'s hardcoded `USE_CASES` (see
`project-soar-deploy-manifest-hardcoded` memory). Deployed to soar8 as
`efficientip_ddi_enrich` id=672 v3, labeled `events` (no dedicated
`efficientip_ddi` label exists yet — labels can't be created via REST, only
the SOAR Admin GUI; using the pre-existing generic `events` label kept this
launchable without a new admin step, since the design never mandated a
specific label). Connector-side prerequisite: `efficientip_ddi` v1.0.0→v1.0.1
fixed 3 field-name bugs found by cross-referencing SOLIDserver's real public
REST docs (`get ip address`'s hostname is `name` not `hostdev_name`,
`get ip pool`'s range fields are `start_hostaddr`/`end_hostaddr` not
`pool_start_hostaddr`/`pool_end_hostaddr`, `list aliases`' name field is
`alias_name` not `ip_alias`) — see `soar-connectors` README/app.py and commit
`25ff063`. Mock restarted to pick up the matching fix.

**Real bug found and fixed during first live run:** `phantom.save_playbook_output_data()`
raises `RuntimeError: ... only allowed within the "on_finish"` when called from
a regular `@phantom.playbook_block()` function — confirmed via a real traceback
in `decided.log`. The Architecture's step 6 (and `tie_attack_detail.py`'s
`build_enrichment_note`, which this design partly modeled) call it from a
non-`on_finish` block; that pattern is apparently untested against a real
SOAR 8.5 GUI/live run (consistent with `tie_attack_detail` never having had
"a real GUI open-and-look pass", per existing memory). Fixed by switching to
the documented `save_run_data` → `on_finish` → `save_playbook_output_data`
pattern (`playbook-patterns.md`'s "save_run_data + on_finish output" section)
in both `finalize` and `note_error`. **This may be a broader latent bug** —
any other playbook in this repo calling `save_playbook_output_data()` outside
`on_finish` would hit the same RuntimeError on a real run; worth a repo-wide
grep, not chased here (out of UC17's scope).

**Live-verified against soar8 + mock (container 1835, playbook id 672),
4 real `/rest/playbook_run` calls:**
- `ip=10.20.30.40` (has alias): full chain, all 9 output fields populated
  correctly, note written, overall run `status: success`.
- `ip=10.20.30.99` (no hostname/mac/alias in seed but ip_id found): partial
  fields correctly empty, `alias_name` empty since no alias seed exists for
  `ip_id=1002`, note written, overall run `status: success` (get_ip_address
  itself succeeded).
- `ip=10.20.30.200` (not in mock at all): `check_ip_found` correctly routed
  around `list_aliases`, saved output correctly shows `status: partial`, note
  written — but the **overall `playbook_run.status` shows `failed`**, because
  `get_ip_address` itself raised `ActionFailure` (connector's "not found"
  convention) and SOAR's run-level status aggregates from constituent action
  statuses regardless of downstream graceful handling. This is a platform
  behavior, not a playbook bug — `on_finish` still runs and the saved output
  data is correct either way — but it means an analyst/parent playbook reading
  only the coarse run status (not `save_playbook_output_data`'s own `status`
  field) would see a not-found lookup as "failed" rather than "partial". Not
  fixed (would require the connector to stop raising on not-found, a
  connector-design decision out of this playbook's scope) — flagged here for
  awareness.
- Empty `ip`: `check_input` correctly routed to the error path, note written,
  saved output `status: error`, overall run `status: success` (no action ever
  ran, nothing to fail).

Not yet done: VPE GUI open-and-look pass (no known blocker, just not
performed from this session); no parent UC currently chains into this per
resolved question 3.
