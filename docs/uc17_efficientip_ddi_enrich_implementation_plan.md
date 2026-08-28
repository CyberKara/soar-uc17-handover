> **Note:** this copy has had 2 reference(s) to the source lab's own
> internal addresses replaced with `<lab-address-redacted>`. They named
> the lab that built this package, never a target system of yours.

# EfficientIP DDI Enrichment (UC17) — Implementation Plan

**Status:** [x] planned | [x] built | [x] E2E validated | [x] code review fixes | [x] VPE polish | [ ] released

> **Live ids move on every deploy — always resolve by name, never by an id
> written down here.** `./tools/uc17_verify.sh` does exactly that
> (`?_filter_name=`, highest version wins); so does
> `curl .../rest/playbook?_filter_name__icontains=efficientip`. Ids quoted in
> the dated sections below are historical records of what was live *that day*,
> not current state — see `[[project-soar85-gui-save-on-finish-output-clobber]]`.

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
`mock-efficientip-ddi.service` on the ansible controller (`<lab-address-redacted>`, mTLS
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

> **Repo-wide grep DONE 2026-08-27** (commit `dd6bba9`). Only offender was
> `tie_attack_detail.py`'s `build_enrichment_note`. But the audit turned up a
> second, worse problem in the fix *itself*: moving the call into `on_finish`
> is not sufficient, because `on_finish` was written with no
> `## Custom Code Start/End` markers. `userCode` is built only from text
> between those markers, so the call lived in `.py` alone — it deploys and runs,
> but the first VPE open-and-save regenerates `on_finish` empty and the playbook
> silently emits **no output at all**. That would have fired on this very
> document's outstanding "VPE GUI open-and-look pass". `check_usercode_sync.py`
> reported clean throughout because it skipped marker-less functions; it now
> reports `NOMARKERS` and exits non-zero. Fixed here and in three `tenable_ad`
> playbooks. See `docs/vpe-dev/constraints.md`.

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

No parent UC currently chains into this, per resolved question 3.

---

## Open items (from the 2026-08-27 code review)

### Resolved 2026-08-27 (connector v1.0.7 / classic v1.0.5 — built, NOT yet installed)

- [x] **`list aliases` / `list subnets` returned only `records[0]`.** All four
  record-returning actions on both connectors now emit one row per record
  (`list[ActionOutput]` on the SDK side, a per-record `add_data()` loop on the
  classic side, with `total_objects` reporting the true count instead of a
  hardcoded `1`).
- [x] **`limit` is now a real action parameter** (numeric, optional, default 1)
  on all four, replacing the hardcoded `limit=1` — this was the already-agreed
  design from 2026-08-26 and it is also what makes the multi-record fix
  reachable, since `limit=1` would otherwise guarantee the truncation stayed.
  A bound still always goes on the wire (unbounded calls time out on the real
  APIM); raising it is now the caller's to do. At the default, behavior is
  identical to v1.0.6, so nothing calling these actions today changes.
  `test connectivity` keeps a fixed `limit=1` — no parameter surface.
- [x] **`ip_id` type split.** `list aliases`' parameter is now a string on both
  connectors, matching `get ip address`' string output, so the chain the action
  descriptions instruct users to build is actually wireable in the VPE.
- [x] **Classic `param["ip_id"]` interpolated raw into the URL path.** Both
  connectors now run it through a `_validate_int()` (the `proofpoint_trap`
  `_validate_integer()` precedent), so a float `1001.0` can no longer become
  `/rest/ip_alias_list/ip_id/1001.0` and a false "no aliases". `1001.5` is
  rejected rather than truncated.
- [x] **`_ip_to_hex()` raised a bare `ValueError`** for a hostname/CIDR/typo.
  Both connectors now fail the action cleanly with a message saying what the
  parameter actually takes, and without calling the API at all.
- [x] **Mock `_WHERE_RE` never un-doubled `''`.** Fixed in both mock copies,
  which now also honor `limit`, seed a two-alias IP, and seed a pool name
  containing an apostrophe — the escaping path previously had no seed data that
  could exercise it.
- [x] **The escaping path had no regression coverage.** Added
  `efficientip_ddi_classic/tests/` (23 tests) and
  `soar-connectors/test/test_mock_efficientip_ddi.py` (16 tests). This paid for
  itself immediately: the float-`ip_id` test failed against the first draft of
  `_validate_int()`, which used `int(str(value))` and so rejected `1001.0` —
  exactly the case it was written to absorb.
- [x] **Playbook `finalize()` kept only `alias_result[0][0]`.** Now collects
  every alias. Output spec gains `alias_names` (comma-separated, all) and
  `alias_count`; `alias_name` still carries the first, so existing callers are
  unaffected. The summary note's line is relabelled "Aliases".
- [x] **`check_ip_found` gated on `ip_id != ""` only.** Now also requires
  `get_ip_address:action_result.status == "success"`, matching what the
  Architecture section always said. Fixed in both the `.py` and the decision
  node's JSON conditions (a native block's config does not live in `userCode`,
  so `check_usercode_sync.py --fix` would not have caught it).
- [x] **`docs/dev-rules.md` inventory row was stale** (app id 204,
  `get dns record`, "no playbook built yet"). Rewritten, and
  `efficientip_ddi_classic` added to the table for the first time.
- [x] **FR-01 exemption for the classic twin was unrecorded.** Now written into
  FR-01 itself as the one standing exemption, with its scope ("not a maintained
  implementation, do not extend") and an explicit removal condition.

### Found while doing the above — corrects a standing project belief

- [x] **The "NFR-09 `soarapps package build` wheel-drop bug" is not a bug.**
  The 7 omitted packages (`requests`, `urllib3`, `certifi`, `idna`,
  `charset_normalizer`, `beautifulsoup4`, `soupsieve`) are entries in the SDK's
  own `DEPENDENCIES_TO_SKIP`, documented in its source as *"provided by the
  Python runner"* and sourced from Splunk's SOAR FAQ. It therefore happens on
  **every** build by design — which is why three sessions of hand-re-adding the
  wheels each silently reverted on the next rebuild. Corrected in dev-rules
  NFR-09, and automated: new `soar-connectors/tools/build_sdk_app.py` runs the
  SDK's own build with the skip-list emptied and then verifies the result,
  failing non-zero if any platform-provided wheel is missing. The v1.0.7
  package it produces has a wheel set identical to the last known-good build
  (65 packages).
- [ ] **Still unresolved:** the real appliance threw `ModuleNotFoundError:
  requests` on a build that lacked those wheels, which contradicts the SDK's
  skip-list premise. We keep bundling them until that is settled **against the
  real appliance** — `build_sdk_app.py --stock` builds the SDK-stock variant for
  exactly that A/B test.

### Shipped 2026-08-27 (later still)

The user uninstalled all three EfficientIP apps in the GUI — the stale 204 **and**
both live ones — then approved a clean-slate reinstall.

- [x] **App 204 uninstalled by the user**, closing the item REST could never do.
  Left disabled; the reinstall did not touch it.
- [x] **Connectors installed in place** via `tools/install_app.sh`:
  `efficientip_ddi` v1.0.7 → app id 205, `efficientip_ddi_classic` v1.0.5 → app
  id 206. Both `disabled: false`, 5 registered actions each (checked on
  `/rest/app_action?_filter_app=`, the endpoint that actually reports them).
- [x] **Assets re-bound.** Uninstalling orphaned assets 19 and 22 (`app: None`
  on the detail endpoint, not just the list view) and **reinstalling did not
  re-bind them** — worth knowing, since that was the obvious assumption. Their
  `configuration` survived fully intact, so no credentials had to be re-entered.
  Fixed with `POST /rest/asset/<id> {"app_id": <app>}`, a shape first tested on
  a throwaway asset because the REST-quirks memory warns that a `POST` without
  `configuration` resets every field. It does not, for this shape: all 9 keys
  and their byte-lengths were unchanged, on the scratch asset and then on both
  real ones. Scratch asset deleted afterwards.
- [x] **Playbook deployed.** `efficientip_ddi_enrich` id=**678** v6,
  `passed_validation: true`, `active: false` (correct for a data playbook).
  Verified the *live* copy carries this session's changes rather than trusting
  the deploy: grepped the post-deploy assembled snapshot for `alias_names`,
  `alias_count`, the multi-alias `collect2` loop, the two-condition
  `check_ip_found` and the "Aliases" label, and read `output_spec` back over
  REST (12 fields, both new ones present). **This closes the GUI-save
  `on_finish` hazard on the live copy**, which was the "do this first" item.

### Still open

- [x] **Live functional test of the multi-record fix — DONE.** Was blocked on a
  mock restart: `mock-efficientip-ddi.service` was active on the ansible
  controller and reachable from soar8 (asset 19 → `https://<lab-address-redacted>:8447`),
  but the running process predated the seed change and still returned **1**
  alias for `ip_id` 1001. The unit was restarted (approved) and the chain
  re-run: `list aliases` at `limit` > 1 returns **2 rows** through SOAR and
  `efficientip_ddi_enrich` reports `alias_count: 2` with both names. See the
  "GUI-test readiness" section below.
### GUI-test readiness (2026-08-27, prepared)

Everything needed for a GUI pass is deployed and pre-verified over REST, so a
GUI run should be a confirmation rather than a debugging session.

- Live ids *at the time of this section* (2026-08-27): `efficientip_ddi_enrich`
  684 v8, `efficientip_ddi_action_test` 685 v5,
  `efficientip_ddi_classic_action_test` 686 v4 — all `passed_validation: true`.
  **Superseded by later deploys; verified 2026-08-28 as 711 v18 / 712 v11 /
  713 v10.** Resolve by name rather than trusting either set. Apps: 205 v1.0.8
  (SDK), 206 v1.0.6 (classic), 5 actions each, assets 19/22 bound with
  `verify_ssl: false` — those have held.
- **Verified end to end after the mock restart:** `list aliases` returns 2 rows
  through SOAR, the enrich playbook reports `alias_count: 2` with both names,
  8/8 actions PASS on both connectors. `./tools/uc17_verify.sh` runs the lot.
- **Both action-test playbooks updated for the new connector contract.** Their
  `list aliases` node still declared `ip_id` as `data_type: "numeric"`, which is
  exactly what stops the VPE binding `get ip address`'s now-string `ip_id`
  output to it — fixed to `string` in both. They also never passed `limit`, so
  at the default of 1 they could not tell a working multi-record result from
  the old truncation bug; both now pass `limit: "10"` and their note reports the
  alias **count** and every name, with a line saying what a count of 1 would
  mean.
- Pre-run over REST: all 8 actions across both connectors PASS, and
  `efficientip_ddi_enrich` completes emitting `alias_names`/`alias_count`.
- [x] **The wildcard-datapath GUI-save hazard — resolved by conversion, not by
  policing saves.** All three playbooks have an action node whose `ip_id` binds
  to a wildcard datapath (`...:action_result.data.*.ip_id`), which is the shape
  `[[project-soar-gui-regen-action-param-corruption]]` warns a VPE save can
  comma-join into one malformed parameter. This section originally carried that
  as "a GUI save here is a **mandatory redeploy**". **Superseded:** all three
  were converted to VPE-canonical form and now pass `check_vpe_shape.py`, and
  the user confirmed live that a save on a fully canonical playbook produces
  **no new version at all** — SOAR computes an identical payload and stores
  nothing. The detector is still worth running (`tools/uc17_verify.sh hazards`
  lists the bindings) but the blanket redeploy rule no longer applies to these
  three. Redeploy if a save *does* produce a new version:
  `./tools/deploy.sh --use-case efficientip_ddi_enrich`.
- [x] **VPE GUI open-and-look pass DONE 2026-08-28 — zero warnings.** Performed
  by the user on the live copy (711 v18); everything rendered clean. This was
  the last gate owed under `[[feedback-playbook-build-process-gate]]`, and it
  also confirms the VPE-canonical conversion held end to end.
- [x] Mock service restarted; live seed confirmed at 2 aliases, and
  `list subnets` now passes *genuinely* rather than by fallthrough.
- [x] **The enrich playbook itself was stale too — caught only by running it.**
  After the restart the raw action returned 2 rows while the playbook still
  reported `alias_count: 1`: its `list aliases` node passed no `limit` (so the
  connector default of 1 truncated) and still declared `ip_id` as `numeric`.
  The same two defects were in all three playbooks; the enrich one was missed
  on the first pass because only the two test playbooks were being reviewed.
  Now sends `limit: "50"` — bounded but generous, since its own
  `alias_names`/`alias_count` outputs are meaningless at 1 and an unbounded call
  times out on the real APIM.
- [x] **Mock hardened so this class of bug fails loudly.** An unrecognised
  `WHERE` column used to return every record — which is why `WHERE=name=` passed
  locally for two versions — and is now a 400 naming the valid columns. The mock
  also encodes the vendor-confirmed filter-to-record-key mapping including the
  two WHERE≠SELECT cases (`subnet_name`→`name`, `parent_site_name`→`site_name`).
  Deliberately stricter than the real API, whose behavior for an unknown column
  is unknown: the permissive option demonstrably hides real bugs.
- [x] ~~`WHERE`-filter-key hypothesis for `ip_block_subnet_list`~~ —
  **RESOLVED 2026-08-27 by asking the user, and it was a real bug.** `name` is
  not a filterable column at all, only the SELECT column the record returns
  under; the filterable column is `subnet_name`. Fixed in both connectors
  (1.0.8 / 1.0.6) and both mocks, with regression tests from both sides. The
  mock could never have caught it: it matched on `name`, *and* it falls through
  to returning every record on an unmatched `WHERE`, so even a probe asking
  "did it return a row?" would have answered yes for either key.
- [ ] Real airgapped retest of everything else — neither connector has been run
  against the real SOLIDserver/APIM since the field-name fixes. Confirmed from
  the user meanwhile: the response is a bare JSON array (what `_ensure_list()`
  assumes), and `limit=1` returns exactly one record. Still unconfirmed:
  `ip_alias_list`'s own field names — `alias_name` remains analogy-based, and
  the user had no `ip_id` with aliases to check against, so this cannot be
  settled from their side yet. `raw_json` covers it meanwhile.
- [ ] The two action-test playbooks are 271 lines differing by ~5 (the `ASSET`
  constant and 4 note titles); `ASSET` as a `playbook_input` would collapse
  them. **Deliberately not done** — it trades a diagnostic playbook's
  zero-argument launch for a typed input on every manual run, and touching
  their block structure risks a GUI regression on playbooks whose only job is
  diagnosing one. Worth revisiting only if a third connector variant appears.
- [ ] Open design item, **now unblocked**: purpose-built `WHERE` filter
  parameters rather than a raw passthrough param. It was blocked on the user
  naming concrete filter needs; the 2026-08-27 answer supplied them. Confirmed
  filterable columns on `ip_block_subnet_list`: `subnet_name`, `subnet_id`,
  `parent_subnet_name`, `parent_site_name`, `start_ip_addr`/`end_ip_addr`
  (hex), `start_hostaddr`/`end_hostaddr` (dotted IP). "List subnets under a
  parent" maps to `parent_subnet_name`, "by site" to `parent_site_name`, and
  the address pairs give a real range lookup — the exact case that motivated
  making `limit` caller-controlled, since a range filter can legitimately
  return many rows. Not started; needs a design pass on which of these become
  named parameters.

### Verification performed this session (soar8 + mock only)

- 23 classic-connector unit tests, 16 mock-server tests — all passing.
- 13 live end-to-end checks driving **both** connectors' real request path
  against a running mock over real mTLS: multi-alias retrieval at `limit=10`,
  bounding at `limit=1`, the apostrophe-name escaping round trip, `204 No
  Content` → empty list, float-`ip_id` absorption, hostname rejection, and the
  classic twin's raw pass-through keeping real SOLIDserver key names.
- `check_usercode_sync.py` clean across all 3 UC17 playbooks.
- SDK manifest regenerated and inspected: `ip_id` string, `limit` numeric
  default 1 on all four data actions, `data.*` output shape unchanged.
