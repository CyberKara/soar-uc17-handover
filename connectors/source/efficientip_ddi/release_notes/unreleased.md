**Unreleased**

## 1.0.1 (2026-08-29 — comment cleanup; no behaviour change)

Stripped session/investigation narrative out of `.py` and `.json` source across
both connectors, their consts, both mock copies and both test suites: dates,
"confirmed live", "user-confirmed", "user decision", and references to how a
finding was arrived at. Code comments now read as timeless explanations of why
the current behaviour is what it is. The investigation record lives in the UC17
implementation plan, `next-steps.md` and project memory, where it belongs.

A connector's `README.md` is deliberately **not** included in this sweep — it is
reference material that ships to airgapped operators and legitimately carries
dated troubleshooting tables.

No functional change. Version bumped only so the installed artifact and the
shipped artifact stay the same thing rather than differing by their comments.

## 1.0.0 (2026-08-29, later still — fresh app identity for the airgapped install)

**Not a rollback. A deliberate identity reset**, at the user's request, ahead of
the next airgapped handover.

SOAR correlates an installed app by its `appid` and carries GUI state across
versions of the same one. Reusing the identity meant the airgapped instance kept
trying to reconcile the new package against its memory of the old install, with
visibly wrong results in the GUI. A fresh GUID makes it a genuinely new app
rather than an upgrade wearing stale state.

| | Was | Now |
|---|---|---|
| SDK `appid` | `71a7abcc-…` | `b847c7d1-…` |
| SDK version | 1.0.14 | **1.0.0** |
| Classic `appid` | `4e9c768b-…` | `daa10f0c-…` |
| Classic version | 1.0.11 | **1.0.0** |

**Names are unchanged** (`efficientip_ddi`, `EfficientIP DDI (Classic)`) — user
decision. The `appid` is the correlation key; the names stay readable.

**No code changed.** Every fix through 1.0.14 / classic 1.0.11 is present
byte-for-byte: the WHERE/limit mutual exclusion, credential stripping, the
`Accept` header, optional subnet filters, and the label-shaped fixtures. The
version number no longer maps to this file's history above — read the entries
above 1.0.0 as the provenance of what this package contains.

**Playbooks had to be rebound.** A playbook's action nodes carry `connectorId`
— the appid — so all three UC17 playbooks referenced the old GUIDs in 12 places
and would not have resolved their action blocks against the new apps. Updated
in `soar-playbooks` and redeployed.

**These install as NEW apps, side by side with the old ones.** They do not
replace them. On any environment carrying the previous identity, the old app
should be deleted by hand once the new one is verified — otherwise two entries
coexist. Same caveat as the previous identity reset.

## 1.0.14 (2026-08-29, later still — NEVER send WHERE and limit together)

**The real-appliance 401 is solved, and it was ours.** User-observed on the
appliance: a `WHERE`-filtered call carrying `limit` makes the backend **abort
the query** and return HTTP 401; the identical call **without** `limit` succeeds
(slower, because the filter is actually doing work).

Every observation this connector has ever collected fits one rule:

| `WHERE` | `limit` | Result |
|---|---|---|
| no | no | times out — unbounded full scan (v1.0.2) |
| no | yes | works — what `test_connectivity` does |
| yes | no | works — the user's `ip_address_list` call |
| yes | yes | **fails** — backend aborts, HTTP 401 |

A `WHERE` already bounds the query. `limit` is redundant beside one and
actively harmful.

**The cause was the fix from v1.0.2**, which added `limit=1` "defensively" to
`get_ip_address`, `list_subnets` and `get_ip_pool` — and said so at the time:
*"untested whether `WHERE` alone is sufficient to bound those queries on the
real backend, so this is cheap insurance."* It was not insurance; it was the
bug, and it broke exactly those three actions while leaving `test_connectivity`
(limit only) and `list_aliases` (path-param, neither) healthy. That asymmetry
was visible in the symptom for days and read as a service-specific gateway
problem instead.

`_bounded_query()` now sends one or the other, never both. A caller's `limit` is
still honoured on a filtered call — applied client-side via
`_apply_client_limit()`, since it cannot go on the wire.

**Six new tests pin this**, and they carry more weight than usual: the mock
accepts both parameters happily, so it can never reproduce this failure. These
tests are the only thing standing between the project and shipping it a second
time.

Mirrored into the classic twin (1.0.11). 41 classic tests passing (was 35).

### Theories that died getting here

Recorded because the sequence is the lesson, not the answer:

1. **DDI credentials not base64-encoded** — disproven from source; the 1.0.3 fix
   was present.
2. **`Content-Type: application/json` on a bodiless GET** — exonerated with no
   new test: the connector sets it on *every* request including the passing
   `test_connectivity`, so both arms of the experiment already existed.
3. **The percent-encoded `=` operator (`%3D`)** — killed by one user data point
   (`ip_address_list?WHERE=ip_addr%3D%27...%27` returns 200). A fix had been
   written; it was **reverted before shipping** rather than change a wire format
   that demonstrably works.
4. **Per-service APIM policy on `ip_block_subnet_list`** — plausible, and wrong.
   It was never about the service.

Four theories, three of them mine, all killed by a single cheap observation the
user already had. **Ask for the observation before building the fix.**

## 1.0.13 (2026-08-29, later still — subnet names are LABELS, not CIDRs)

**A wrong data model that had been baked into the fixtures since the mock was
written, found by the user in one line: "subnet_name can't be ip".**

Real subnet names on the appliance look like `BLABL_BLABL-LABLLA` — underscores
and hyphens, no dots, no slashes. The mock seeded `name: "10.20.30.0/24"`, both
manifests gave `'10.20.30.0/24'` as the parameter example, and both diagnostic
playbooks filtered on it. Every reader — human or model — came away believing
subnet names are CIDR-shaped.

Two real costs, neither of them cosmetic:

- **It manufactured a phantom bug.** The only reason a `/` ever appeared in a
  `WHERE` value was that fake CIDR name. Real names contain nothing that
  percent-encodes, so the `%2F`-blocked-by-the-gateway theory was chasing an
  artefact of our own test data. Hours went into it.
- **It hid the real requirement.** If names are labels, then *"which subnet
  contains this IP?"* — the question anyone actually asks of IPAM — cannot be
  answered through `subnet_name` at all. It needs `start_hostaddr`/`end_hostaddr`,
  the **deferred range filters**. Those were ranked nice-to-have; they are in
  fact the point, and name filtering is the marginal feature.

Fixed: both parameter descriptions now say NAME-not-CIDR and point at the range
columns for address lookup; both mock copies reseeded to `CORP_LAN-USERS` /
`CORP_LAN-PRINTERS` under parent `CORP_CORE-NET`, with the addresses left where
they belong (the `*_ip_addr` range fields); both diagnostic playbooks and both
test suites follow. The seed carries a comment explaining why, so it does not
drift back.

Same failure class as the `WHERE=name='...'` bug: **the mock agreed with the
code, so both were wrong together and nothing local could tell.** A fixture that
invents domain data is not neutral — it teaches, and it taught wrong. Test data
should come from the real system or be visibly synthetic, never plausible-and
-invented.

61 tests still green (35 classic connector, 26 mock), `check_usercode_sync.py`
clean across all 21 playbooks.

## 1.0.12 (2026-08-29, later still — drop Content-Type from bodiless GETs)

Every action here is a **GET with no body**, yet `_request()` set
`Content-Type: application/json` on all of them, unconditionally, since the
connector's first version. `Content-Type` describes a request body. Declaring
one that does not exist invites a strict server to read an empty body as a JSON
document and reject it. Replaced with `Accept: application/json`, which is what
was actually meant — we care what comes back, not what we did not send.

**Why now.** Testing classic 1.0.6 against the real appliance, `list subnets`
returned **HTTP 401** with the appliance's own error body carrying
`"message": "The specified document is not valid JSON data"`. That string is in
none of our code — it is the appliance saying it tried to parse a document and
failed. The only JSON document this connector ever claimed to send is the
phantom one this header announced.

**Explicitly unconfirmed as the cause.** The theory has a hole: `test
connectivity` sends the identical header and passes, which this does not
explain. A one-line curl probe settles it — the known-good call, plus only
`-H "Content-Type: application/json"`. The header is wrong on its own terms
regardless of how that comes out, which is why the fix ships now rather than
waiting.

Also re-pinned by test, because it was the first hypothesis raised and deserves
a permanent answer: **`X-DDI-Username`/`X-DDI-Password` are base64-encoded**
(the 1.0.3 fix), verified by decoding them back in
`test_ddi_headers_are_base64_encoded`. They were never sent in plain text in
1.0.6.

Mirrored into the classic twin (1.0.9). 35 classic tests passing (was 32).

## 1.0.11 (2026-08-29, later — `list subnets` filters are fully optional)

**User decision, reversing the "exactly one filter required" rule shipped hours
earlier in 1.0.10.** `limit` is now the only thing that need be set: with no
filter, `list subnets` issues a bare bounded call — `GET
/rest/ip_block_subnet_list?limit=N`, no `WHERE` on the wire at all.

That is not a new shape. It is exactly what `test_connectivity` has always
done, it is the one call confirmed to work against the real APIM, and
`ip_block_subnet_list` is documented as needing no filter params. The earlier
refusal was defending against a playbook losing its filter binding and
enriching a random subnet; the user weighed that against being forced to supply
a filter and chose the simpler contract.

It also matters right now for a live reason: a **401 on `list subnets` against
the real appliance while `test connectivity` passes** was reported this session.
The two calls go to the same URL with byte-identical auth headers — the only
difference is the `WHERE` parameter — so the gateway is reacting to the clause
itself, not to any credential. An unfiltered call is the workaround as well as
the diagnostic. See the UC17 plan's WHERE-rejection section.

**Two filters is still refused**, unchanged: that is about `AND` being
unconfirmed on the real APIM, an unrelated question to whether zero filters is
legal.

The classic twin's selector was also reworked to return an explicit
`(ok, column, value)` rather than making the caller infer "no filter" from
"error" by inspecting `action_result`'s status — with zero filters now a
success, those two cases had to stop sharing a return shape.

Mirrored into the classic twin (1.0.8). 32 classic tests still passing; the
former no-filter refusal test now asserts the opposite — no `WHERE` on the
wire, `limit` still on it, two rows returned.

## 1.0.10 (2026-08-29 — purpose-built subnet filters; strip hand-entered credentials)

### Purpose-built `WHERE` filters on `list subnets`

Closes the design item deferred at 1.0.8. `list subnets` took one required
`name` param and could only ever answer "tell me about this exact subnet". It
now exposes the confirmed-filterable columns as named parameters:

| Parameter | WHERE column | Answers |
|---|---|---|
| `subnet_name` | `subnet_name` | this exact subnet (the old `name`) |
| `subnet_id` | `subnet_id` | this subnet by id |
| `parent_subnet_name` | `parent_subnet_name` | the subnets under a parent |
| `site_name` | `parent_site_name` | the subnets in a space/site |

Two of those mappings are deliberately not identities, so the mapping lives in
a `LIST_SUBNETS_FILTERS` table rather than an f-string — the same mismatch
class that shipped as `WHERE=name='...'` and passed locally for two versions.

**Exactly one filter, enforced before the call.** Zero filters and two filters
both fail without touching the APIM. Two is refused because AND-composition has
never been confirmed on the real APIM — silently dropping a condition would be
the same coded guess this connector keeps getting caught by. Zero is refused
because an unfiltered lookup returns arbitrary rows: a playbook that lost its
filter binding would enrich against a random subnet and look like it worked.
(`test_connectivity` still makes its bare bounded call; that path is unchanged.)

**Ranges deliberately not built.** `start_ip_addr`/`end_ip_addr` (hex) and
`start_hostaddr`/`end_hostaddr` (dotted IP) are confirmed filterable, but a
useful range needs comparison operators and/or AND, neither of which anyone has
confirmed. The UC17 plan carries the three curl probes that would settle it.

**Breaking parameter change:** `name` → `subnet_name`. Both diagnostic
playbooks updated (`.py` and `.json`, `requiredParameters` now `[]`, sync check
clean). `get ip pool`'s own `name` param is untouched. Nothing else binds this
action — the enrich playbook never called it.

Mirrored into the classic twin (1.0.7), manifest included. The mock gained a
second subnet under the same parent and site, without which a parent/site
filter would return one row and prove nothing — the same trap the single-alias
seed set. Coverage: 32 classic-connector tests (was 24), 26 mock tests (was 22).

### Strip whitespace from every hand-entered credential

**Latent bug, one of the two candidate causes of the real appliance's HTTP 401
on 2026-08-28.** `_auth_headers()` base64-encoded `client_id`, `client_secret`,
`ddi_username` and `ddi_password` exactly as stored. The three PEM fields get
whitespace-normalised by `_normalize_pem()`; these four never did.

On an airgapped box every one of these is typed or pasted into a SOAR asset
field by hand, and base64 preserves whatever surrounds the value — so a single
trailing newline yields a credential that is wrong by one byte and a 401 that
is indistinguishable from a genuinely wrong password. All four are now
`.strip()`ed at the point of use.

This does **not** confirm the 401's cause; the other candidate (the export
package shipping the lab's `client_id`/`ddi_username` as real values while only
the secrets were placeholdered) is fixed on the `soar-playbooks`
`export_handover.py` side and remains the leading explanation. Discriminating
between them still needs the full APIM error body.

Mirrored into the classic twin (1.0.7). Regression coverage pinned from both
directions in `efficientip_ddi_classic/tests/`: whitespace around any of the
four must not change the encoded headers
(`test_auth_headers_strip_pasted_whitespace`), and stripping must not flatten a
genuinely different value into a matching one
(`test_auth_headers_still_distinguish_genuinely_different_values`). The first
fails against the pre-fix connector, verified.

## 1.0.9 (2026-08-28 — no code change; ships the bundled build to soar8)

**Version bump only. No source, manifest, or action behaviour changes from
1.0.8.**

Its whole purpose is to get past the install gate. SOAR refuses an install whose
`app_version` is less than or equal to the live one, and soar8's app 205 was
already at 1.0.8 — so the bundled package could not replace the **stock** one
installed there without a new number.

Why replace it: app 205 was running the SDK-stock build (62 wheels, zero
platform-provided), while the artifact carried across the air gap is the bundled
one (70 wheels, all 7 platform-provided packages included). Everything
live-verified on soar8 was therefore exercising a different package from the one
that ships. This makes "tested" and "shipped" the same artifact.

This ends the stock/bundled A/B **on soar8 only**. That costs nothing: soar8 was
always known to provide those packages, and the open question — the real
airgapped appliance throwing `ModuleNotFoundError: requests` on a package that
lacked them — can only be settled on the appliance itself. Build a stock variant
with `tools/build_sdk_app.py --stock` if that comparison is ever needed again;
it now writes `<name>-stock.tgz` and cannot overwrite the shipping artifact.

## 1.0.8 (2026-08-27, later — real filter column for ip_block_subnet_list)

**Real bug, found by asking the user rather than by testing.** `list subnets`
filtered with `WHERE=name='<subnet>'`. On the real APIM `name` is **not a
filterable column at all** — it is the SELECT column the record comes back
under. The filterable one is `subnet_name`. The two genuinely differ on this
service, so the "WHERE column matches the SELECT column" assumption that
shipped as an explicit, commented hypothesis at 1.0.5 is **disproven**.

Vendor-confirmed filterable columns on `ip_block_subnet_list`: `subnet_name`,
`subnet_id`, `parent_subnet_name`, `parent_site_name`, `start_ip_addr` /
`end_ip_addr` (hex) and `start_hostaddr` / `end_hostaddr` (dotted IP). The last
four are the obvious inputs if the deferred "purpose-built WHERE filter
parameters" design is ever picked up.

Note this was invisible against the mock in **both** directions: the mock
matched on `name`, so the wrong key passed locally, and it also fell through to
returning every record when a `WHERE` did not match — which would have made a
naive "does it return a row?" probe answer "yes" for either key. The mock now
matches on `subnet_name` only, deliberately not accepting `name` as well, and
the regression is pinned from both sides
(`test_list_subnets_filters_on_subnet_name_not_name`,
`test_mock_rejects_the_non_filterable_name_column`).

Mirrored into the classic twin (1.0.6). The record's *output* mapping is
unchanged — `subnet_name` output still reads `record["name"]`, which remains
correct.

**Still unconfirmed:** `ip_alias_list`'s own field names (`alias_name` is still
analogy-based) — the user had no ip_id with aliases to check against.

## 1.0.7 (2026-08-27 — multi-record results, `limit` as a real parameter, input validation)

Fixes from the 2026-08-27 code review of UC17.

- **Every record-returning action emitted only `records[0]`** while
  advertising a `data.*` list datapath. An IP with two DNS aliases reported
  one, with no indication more existed. Found independently from both the
  connector and the playbook side. All four actions now return
  `list[ActionOutput]`, which the SDK flattens into one result with N data
  items. The mock had seeded exactly one alias, which is why this passed
  locally for as long as it did — it now seeds two.
- **`limit` is now a real action parameter (numeric, optional, default 1)**
  on all four record-returning actions, replacing the hardcoded `limit=1`.
  The bound still always goes on the wire — an unbounded call times out
  server-side on the real APIM — but raising it is now the caller's to do,
  and actually widens the result instead of being silently discarded. At the
  default this is behaviorally identical to 1.0.6, so nothing that calls
  these actions today changes. `test_connectivity` keeps a fixed `limit=1`;
  it has no parameter surface and only needs to prove reachability.
- **`list aliases`' `ip_id` parameter is now a string, not numeric.**
  `get ip address` emits `ip_id` as a string output, so the chain the action
  descriptions instruct users to build could not actually be wired in the
  VPE editor — it worked only via pydantic coercion when called from code.
  A new `_validate_int()` still enforces a whole number before it reaches
  the URL path, which also closes the float case: a numeric param arriving
  as `1001.0` produced `/rest/ip_alias_list/ip_id/1001.0` and a false "no
  aliases". Same precedent as `proofpoint_trap`'s `_validate_integer()`.
- **`_ip_to_hex()` raised a bare `ValueError`** for a non-IP `address`
  (hostname, CIDR, typo), so the SDK's generic handler dumped a raw
  traceback as the failure message. Now raises `ActionFailure` with a
  message that says what the parameter actually takes.
- Mirrored into the classic twin connector (1.0.5), whose manifest also had
  **stale declared outputs**: it still advertised the pre-`2315a4d` curated
  names (`data.*.subnet`, `.hostname`, `.status`) after the connector
  switched to raw pass-through, so every one of those datapaths was dead in
  the VPE. Rewritten to the real keys SOLIDserver returns. The twin also
  hardcoded `total_objects = 1`; it now reports the true count.
- **Regression coverage added, which is what caught the last two bugs.** The
  mock's `_WHERE_RE` never un-doubled `''`, so `_sql_escape()`'s output could
  never match seed data — and no seed record contained a quote, so the whole
  escaping path was untestable rather than merely untested. The mock now
  un-doubles, honors `limit`, and seeds both a two-alias IP and a pool name
  containing an apostrophe. New suites:
  `efficientip_ddi_classic/tests/` (23 tests) and
  `soar-connectors/test/test_mock_efficientip_ddi.py` (16 tests), plus a
  live end-to-end run of both connectors against the mock over real mTLS
  (13 checks). The float-`ip_id` test immediately failed against the first
  draft of `_validate_int()`, which used `int(str(value))` and so rejected
  `1001.0` — precisely the case it was written to absorb.

**Still not retested against the real airgapped SOLIDserver/APIM.** Nothing
here has touched the real appliance; the `WHERE`-filter-key hypothesis for
`ip_block_subnet_list` remains unconfirmed.

## 1.0.5 (2026-08-26, later still — real field names + raw pass-through everywhere)

User shared a real `ip_block_subnet_list` response record: `site_name` and
`parent_subnet_name` were correct, but the subnet's own name field is
`name`, not `subnet_name` as inferred by analogy to the differently-named
`ip_subnet_list` method in the public docs. Fixed the read side
(`list_subnets`'s `subnet_name` output now reads `record["name"]`) and,
as a hypothesis pending real confirmation, the `WHERE` filter key too
(`WHERE=name=` instead of `WHERE=subnet_name=` -- assumes the filter
column matches the SELECT column, unconfirmed). Added a new `tree_path`
output field, also present in the real record. Added `raw_json` to
`get_ip_address` (previously the only action without it, now every
action has it). Classic twin connector (`efficientip_ddi_classic`)
rebuilt around full raw pass-through instead of manual field mapping --
`action_result.add_data(record)` forwards every real key SOLIDserver
returns under `action_result.data.*.<key>`, eliminating the whole class
of field-name-guessing bugs found today (subnet_name/name,
start_hostaddr/pool_start_hostaddr, ip_alias/alias_name, hostdev_name/
name). `description` (parsed from the `*_class_parameters` blob) is
still added as a convenience key on top of the raw record.

## 1.0.4 (2026-08-26, later still — real 204 No Content on empty results)

User confirmed live: a "not found" result on the real APIM (e.g. an
unknown `ip_id` for `list_aliases`) returns HTTP 204 No Content (empty
body, no `Content-Type`), not a 200 with an empty JSON array.
`_process_response()`'s empty-content branch was defaulting to `{}` (a
dict) -- every action here expects a list from `_ensure_list()`, so a real
204 was tripping the generic "unexpected response shape" ActionFailure
instead of the intended friendly "No X found" message. Fixed: empty
content now defaults to `[]`. Mirrored into the classic twin connector.
Mock server (both copies) updated to actually return 204 (via a new
`send_no_content()` helper) instead of `200 []` for every not-found case,
so this exact scenario now has real regression coverage instead of
accidentally passing through a different code path.

## 1.0.3 (2026-08-26, later — limit=1 forced on every list call, including list_aliases)

User pointed out the 1.0.2 fix was incomplete as a general policy: relying
on `WHERE` alone to stay narrow isn't safe if a *different* filter style
were ever used (e.g. a range filter instead of an exact match could return
hundreds of rows), and `list_aliases` still had zero params at all — the
same bare-unbounded shape `test_connectivity` had before 1.0.2. Fixed:
`limit=1` now sent unconditionally on every one of the 5 actions' list
calls, not just the ones that lacked `WHERE`. Consolidated the rationale
into one docstring note instead of repeating it per call site. Mirrored
into the classic twin connector.

## 1.0.2 (2026-08-26 — real APIM timeout on unbounded list calls)

User reported live behavior against the real airgapped APIM: `GET
/rest/ip_address_list` with neither `WHERE` nor `limit` times out
server-side; adding `limit=N` (even with no `WHERE`) works fine, and a
single-record `WHERE=ip_addr='<hex>'` lookup also works (both confirmed
live, e.g. `?limit=5` and `?WHERE=ip_addr='0a4f181f'`). `test_connectivity`
was calling `ip_block_subnet_list` completely bare (no params at all) --
exactly the failure pattern reported -- so it's genuinely at risk of timing
out on the real APIM despite always passing against the mock (which has no
real backend to time out). Fixed: `test_connectivity` now sends
`limit=1`. Also added `limit=1` defensively to `get_ip_address`,
`list_subnets`, and `get_ip_pool`'s existing `WHERE=`-filtered calls --
untested whether `WHERE` alone is sufficient to bound those queries on the
real backend, so this is cheap insurance (we only ever want the one
matching record anyway) pending confirmation. `list_aliases` unchanged
(path-parameter style, not a `WHERE`/`limit` list call). Mirrored into the
classic twin connector (`efficientip_ddi_classic`) for the same reason.
Mock server unaffected -- it already ignores unrecognized query params.

## 1.0.1 (2026-08-25, later still — field-name fixes against real vendor docs)

Cross-referenced every action's field mapping against SOLIDserver's own
public REST method reference (`solidserverrest` project docs, v9.0.1a —
not just SDK-inferred field names) and found 3 real bugs that the mock had
been silently masking (mock was seeded with the same wrong names, so
everything "passed" against it):

- `get ip address`: hostname field is `name`, not `hostdev_name`
  (`hostdev_name` isn't a real `ip_address_list` field at all).
- `get ip pool`: address-range fields are `start_hostaddr`/`end_hostaddr`,
  not `pool_start_hostaddr`/`pool_end_hostaddr` (also not real fields).
- `list aliases`: the alias name field is `alias_name`, not `ip_alias`
  (`ip_alias` is real, but it's an `ip_address_list` field, not an
  `ip_alias_list` one).

Also added a `raw_json` fallback to `list subnets` (previously the only
record-returning action without one) since `ip_block_subnet_list`'s own
field set still isn't independently confirmed against this org's real
APIM — the public docs only cover a differently-named `ip_subnet_list`.
Mock server (both copies) updated to match the corrected field names, not
just to keep passing — see its own docstring for the same 3 fixes.
Real airgapped retest still owed; nothing here has touched the actual APIM.

## 1.0.0 (2026-08-25, later still — clean reset, new appid)

User decision: rather than carry the 1.0.x history/appid across to the
airgapped instance a third time, reset to a fresh `appid`
(`71a7abcc-75fa-4a8d-ae9d-23fb352869e4`, replaces
`414f081c-261b-4eea-a04c-2edf9135c637`) and `version 1.0.0`. This is a
**new app to SOAR, not an in-place upgrade** — the old `414f081c...` app
(soar8 id 204, and whatever is live on the airgapped instance) will NOT be
replaced automatically and should be deleted by hand on both sides to avoid
two `efficientip_ddi` entries coexisting. Functionally identical to 1.0.8:
same NFR-09 wheel-drop fix (requests/urllib3/certifi/idna/charset-normalizer/
beautifulsoup4/soupsieve hand-patched back into wheels/shared/), same 5
actions. Re-verify from scratch under the new appid before shipping (see
next-steps.md).

## 1.0.8 (2026-08-25, later still — real root cause of the airgapped "action not found")

- The NFR-09 `soarapps package build` wheel-drop bug (first found and hand-fixed
  at 1.0.1, believed fixed) had silently **regressed on every rebuild since**
  (1.0.4 through 1.0.7) — nobody re-ran the clean-room wheel check after those
  rebuilds, so `requests`/`urllib3`/`certifi`/`idna`/`charset-normalizer`/
  `beautifulsoup4`/`soupsieve` were missing from every `.tgz` shipped since
  1.0.3, including the one actually carried across the air gap twice. Confirmed
  directly on soar8 itself, not just inferred: `GET /rest/app/204` showed
  `actions: []` for the live v1.0.7 install — the app failed to import
  (`ModuleNotFoundError: requests`) so SOAR never registered any actions,
  which is exactly the "action test connectivity not found" symptom reported
  from the real airgapped appliance.
- Hand-patched wheels back in (same 7 packages as 1.0.1) and re-verified via a
  from-scratch clean-room venv (`uv pip install --no-index`, only the
  manifest-declared wheels, then a real `import src.app`) — confirmed clean.
- Reinstalled on soar8 (app id 204): `GET /rest/app/204` now shows all 5
  actions registered (`test connectivity`, `get ip address`, `list subnets`,
  `get ip pool`, `list aliases`). Live-verified on soar8, not yet
  re-deployed to the real airgapped instance — that still needs a fresh
  carry-across with this version.
- Root process gap, not yet fixed: nothing enforces the clean-room wheel
  check on every rebuild, only the humans remembering to. Needs a scripted
  gate (see next-steps) before this bites a third time.

## 1.0.7 (2026-08-25, code-review fixes)

- Fixed unescaped user input in `list subnets`/`get ip pool`'s `WHERE`
  clauses (`_sql_escape()` was dropped when `get dns record` was removed,
  but the two new actions needed it too — a name containing a single quote
  would have broken the filter).
- Added `_ensure_list()` guard on all four record-returning actions
  (`get_ip_address`, `list_subnets`, `get_ip_pool`, `list_aliases`) — they
  all assumed `_request()` returns a bare JSON array; if the real APIM
  wraps results in an envelope instead (unconfirmed either way), this now
  fails with a clear `ActionFailure` message instead of a raw
  `KeyError`/`TypeError` traceback.

## 1.0.6 (2026-08-25, later still)

- Resolved the open filter-mechanism question from 1.0.5: the user confirmed
  `WHERE` is real and **required** on `ip_address_list`, settling it in
  favor of query-string filtering over `ip_alias_list`'s path-parameter
  style (which is a "list children of a known parent" shortcut, not the
  general convention).
- Added `ip_id` to `get ip address`'s output (from `ip_address_list`'s own
  `ip_id` field) so it can be chained into the new `list aliases` action.
- Added `list subnets` (`GET /rest/ip_block_subnet_list?WHERE=subnet_name=`)
  — field names follow `ip_address_list`'s confirmed `subnet_*` conventions.
- Added `get ip pool` (`GET /rest/ip_pool_list?WHERE=pool_name=`) — field
  names inferred by analogy, not independently vendor-confirmed; carries a
  `raw_json` fallback field.
- Added `list aliases` (`GET /rest/ip_alias_list/ip_id/{ip_id}`,
  path-parameter style, chained off `get ip address`'s new `ip_id` output)
  — field names inferred, not independently vendor-confirmed; carries a
  `raw_json` fallback field.
- Mock server (both copies) updated with subnet/pool/alias seed data and
  the three new endpoints.

## 1.0.5 (2026-08-25, later)

- Removed `get dns record` — no record-level DNS service was ever confirmed
  on the real APIM, only zone-level (`dns_zone_list`, user-observed).
  `dns_rr_list` was this project's own inference from public client docs
  and was never actually seen on the real system. Rebuild only once a real
  record-level endpoint is identified.
- `test_connectivity` now calls `GET /rest/ip_block_subnet_list` bare
  instead of `ip_address_list?limit=1` — the user directly confirmed
  `ip_block_subnet_list`, `ip_address_list`, `ip_alias_list/ip_id/{ip_id}`,
  `dns_zone_list`, and `ip_pool_list` exist on the real APIM;
  `ip_block_subnet_list` needs no filter params at all, making it the
  safest possible connectivity check among the confirmed-real endpoints.
- Flagged (not yet fixed, needs a real curl test to resolve): whether
  `get_ip_address`'s `WHERE=ip_addr='<hex>'` query-string filter is
  actually how the real APIM filters `ip_address_list`, since the one
  filtered endpoint the user has observed (`ip_alias_list/ip_id/{ip_id}`)
  uses a path-parameter style instead. That endpoint lists aliases of a
  known parent ID though, which may be a different convention from
  top-level list filtering — genuinely unresolved either way.

## 1.0.4 (2026-08-25)

- Fixed all three action endpoints: the original `/ddi/health`,
  `/ddi/ip_address`, `/ddi/dns_record` paths were pure invention and don't
  exist on the real backend — the first real airgapped `test_connectivity`
  run against the actual APIM failed with "not found" as a direct result.
  Rewritten to match SOLIDserver's real classic REST API convention (flat
  service names under `/rest/`, `WHERE=<field>='<value>'` filtering):
  `test_connectivity` now does a cheap `GET /rest/ip_address_list?limit=1`
  (no dedicated health service exists in the vendor API), `get ip address`
  calls `GET /rest/ip_address_list?WHERE=ip_addr='<hex>'` (address must be
  hex-encoded, not dotted-decimal), `get dns record` calls
  `GET /rest/dns_rr_list?WHERE=rr_name='<fqdn>'`. Output field mapping
  updated to the vendor's real field names (`subnet_name`, `site_name`,
  `multistatus`, `hostdev_name`, `mac_addr`, `ip_class_name`, `rr_name`,
  `rr_type`, `rr_value1`, `rr_ttl`, `zone_name`); `description` is now
  parsed out of the `ip_class_parameters` custom-attribute blob instead of
  assuming a plain field. Sourced from public EfficientIP client code
  (Ruby/Go SDKs), not a confirmed contract with this org's actual APIM —
  still needs real airgapped re-verification, including whether the APIM
  proxies `/rest/*` verbatim or under its own prefix, and IPv6 filtering
  (hex-encoding only vendor-confirmed for IPv4). Mock server
  (`mock_efficientip_ddi.py`, both copies) updated to the same convention.

## 1.0.3 (2026-08-25)

- Fixed the DDI backend auth layer: `X-DDI-Username`/`X-DDI-Password` are now
  base64-encoded independently (`base64(ddi_username)`, `base64(ddi_password)`
  — not combined, not folded into the Basic Auth layer), confirmed against
  the real APIM via curl. Previously sent as plain text, which would have
  failed against the real backend. Mock server (`mock_efficientip_ddi.py`,
  both copies) updated to match and round-trip verified via curl.

## 1.0.2 (2026-08-24)

- Replaced the hand-rolled `urllib`/`ssl.SSLContext` HTTP layer in `_request()`
  with `requests` (`cert=`/`verify=` handle mTLS natively — no manual
  `SSLContext` needed). This was a pure simplification, not a new dependency:
  `requests` (+ `urllib3`/`idna`/`certifi`/`charset-normalizer`) was already
  forced into the bundle by `splunk-soar-sdk` itself (see 1.0.1), so using it
  in our own code costs nothing extra.
- Added `_process_response()` with real content-type detection (JSON / empty /
  unexpected), closing the FR-05 gap the old raw `json.loads()` had — a
  non-JSON 2xx response from APIM no longer crashes with an unhandled
  `JSONDecodeError`.
- Removed now-unused `ssl`, `json`, `urllib.error`, `urllib.request` imports
  and the `_ssl_ctx()` helper.
- Verified the same way as 1.0.1: clean-room venv, manifest-declared wheels
  only, `app.py --help` runs end-to-end.

## 1.0.1 (2026-08-24)

- Fixed bundled dependency set: removed the unused Outlook `.msg`/OLE/RTF-parsing
  chain (`extract-msg`, `oletools`, `msoffcrypto-tool`, `pcodedmp`, `rtfde`,
  `olefile`, `compressed-rtf`, `ebcdic`) pulled in transitively by
  `splunk-soar-sdk` but never exercised by this connector's own actions.
- Added `idna`, `requests`, `urllib3`, `certifi`, `charset-normalizer` — genuinely
  required by `soar_sdk.app_cli_runner`'s `requests` import at load time, but
  missing from the original bundle despite being correctly resolved in
  `uv.lock`. Without these, the app fails to import in an isolated
  (air-gapped-equivalent) environment.
- Verified via a clean-room venv: installed only the wheels the manifest
  declares, then imported `app.py` and ran its CLI entry point end-to-end.
