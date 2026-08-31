**Unreleased**

> **Scope of this file.** It records what changed in each version and what that
> means for someone installing or calling this connector. The investigation
> record behind these changes — the theories that were tried and discarded, the
> lab-side verification, the process lessons — deliberately lives outside the
> shipped package, in the UC17 implementation plan and project memory. Earlier
> revisions of this file carried that narrative inline; it was removed on
> 2026-08-31 and remains in this repository's git history.

> **Version numbering restarts twice below.** The app identity was reset on
> 2026-08-25 and again on 2026-08-29, each time with a new `appid` and the
> version returned to 1.0.0. Read the entries below a reset as the provenance of
> what the package above it contains, not as a continuous series.

---

## 1.0.4 (2026-08-31) — `client_cert` and `client_ca` are plain string fields

A certificate and a CA bundle are **public material by definition** — the
private key is the secret. Both were declared `sensitive`, which hid them behind
password inputs for no security benefit and put them on the wrong side of a real
platform hazard: SOAR returns a `sensitive` field **encrypted** on read, so any
read-modify-write of the asset writes the ciphertext back as if it were the
value.

`client_cert` and `client_ca` are now plain strings, matching the classic twin,
which has declared them that way since its first version. Unchanged and still
`sensitive`: `client_key`, `client_secret`, `ddi_password`.

**[!] Upgrade note — re-enter these two fields after upgrading.** An asset
created against 1.0.3 or earlier holds `client_cert` and `client_ca` as
encrypted values. Changing the declared type does not decrypt what is already
stored, so after installing this version **open the asset, paste the
certificate and CA back in, and save** before running an action. Symptom if you
skip it: mTLS fails at the handshake, which on this gateway surfaces as an
authentication error rather than a TLS one. `client_key` is unaffected — it is
still `sensitive` and its stored value is still valid.

Export packages are unaffected: asset-template redaction keys off a PEM-blob
content check, not the field type, so both fields were already placeholdered
regardless.

## 1.0.3 (2026-08-31) — `limit` goes back on the wire; 1.0.14's rule was wrong

**Reverts the "never send `WHERE` and `limit` together" rule introduced at
1.0.14.** It was wrong. The real appliance returns **HTTP 200** for a filtered
call carrying `limit=1`, and bounds the result to exactly one row — verified on
`ip_block_subnet_list` and `ip_address_list`.

The rule had been inferred from a single observation: a filtered call "with
`limit=1`" appeared to terminate early while the same call without it waited for
a response. That difference was **a shell artefact, not backend behaviour**. An
unquoted URL splits at `&`, so the arm believed to carry `limit` never sent it —
the shell backgrounded curl at the `&` and returned to the prompt immediately,
which is what "terminates early" actually was. Both arms of the comparison sent
identical `WHERE`-only requests, so the observation contained no information
about `limit` at all. Quoting the URL sends both parameters and returns 200.

**What changes for callers:** `limit` is honoured server-side again on filtered
calls. The client-side truncation helper added at 1.0.14 is removed, and with it
the accepted limitation that a multi-match filter (`parent_subnet_name`,
`parent_site_name`) transferred every matching row and was bounded only after
transfer. That cost is gone; the bound is the appliance's job again.

The rule that does stand, unchanged since 1.0.2: **a list call must always carry
a bound.** With neither `WHERE` nor `limit` the backend attempts an unbounded
scan and times out. `limit` now always goes on the wire.

Six tests were inverted to pin the corrected behaviour and stop the rule being
reintroduced — the mock accepts both parameters either way and cannot catch this
on its own. Mirrored into the classic twin (1.0.2). 41 classic tests, 26 mock
tests, all passing.

**Still open:** the original HTTP 401 on `list subnets` at classic 1.0.6 was
real and reached the connector through `requests`, with no shell involved. Its
cause is now **unexplained** — `limit` is exonerated. Several other things
changed between that failure and the current working state (the `name` →
`subnet_name` filter column at 1.0.8, `Content-Type` → `Accept` at 1.0.12, the
credential `.strip()` at 1.0.10, and a target-side asset-config correction), and
which of them mattered has not been established. No new theory is offered here.

## 1.0.2 (2026-08-31) — release notes trimmed to a changelog

These release notes ship inside the installed package, so they land on every
target this connector is carried to. They had accumulated the full
investigation record — discarded theories, source-environment specifics and
process commentary — which is not operator material. Rewritten as a changelog:
what changed per version, what it means for someone installing or calling this
connector, and which changes are breaking. The investigation record lives in the
UC17 implementation plan and project memory.

No source, manifest, or behaviour change. Version bumped only so the installed
and shipped artifacts remain the same thing.

## 1.0.1 (2026-08-29) — comment cleanup, no behaviour change

Investigation narrative removed from `.py`/`.json` source, consts, mock copies
and test suites; comments now explain why current behaviour is what it is,
without recording how it was arrived at. `README.md` is deliberately exempt — it
is operator reference material and legitimately carries dated troubleshooting
tables.

No functional change. Version bumped only so the installed and shipped artifacts
are the same thing rather than differing by their comments.

## 1.0.0 (2026-08-29) — fresh app identity

A deliberate identity reset, not a rollback.

| | Was | Now |
|---|---|---|
| SDK `appid` | `71a7abcc-…` | `b847c7d1-…` |
| Classic `appid` | `4e9c768b-…` | `daa10f0c-…` |
| Version | 1.0.14 / classic 1.0.11 | **1.0.0** |

SOAR correlates an installed app by its `appid` and carries GUI state across
versions of the same one, so reusing the identity meant a target instance kept
reconciling each new package against its memory of the old install. A fresh GUID
makes it a genuinely new app instead of an upgrade wearing stale state.

**Operator impact:**

- These install as **new apps beside the old ones** — they do not replace them.
  Delete the previous app by hand once the new one is verified, or two entries
  coexist.
- **Playbooks must be rebound.** A playbook's action nodes carry `connectorId`
  (the appid), so any playbook referencing the old GUIDs will not resolve its
  action blocks. The three UC17 playbooks were updated and redeployed.
- App **names are unchanged** (`efficientip_ddi`, `EfficientIP DDI (Classic)`).
- **No code changed.** Every fix through 1.0.14 / classic 1.0.11 is present
  byte-for-byte.

---

## 1.0.14 (2026-08-29) — `WHERE` and `limit` are mutually exclusive

**Operationally the most important rule in this connector.** This backend
aborts the query and returns **HTTP 401** if a call carries both a `WHERE`
clause and a `limit`:

| `WHERE` | `limit` | Result |
|---|---|---|
| no | no | times out — unbounded full scan |
| no | yes | works |
| yes | no | works |
| yes | yes | **fails — backend aborts, HTTP 401** |

A `WHERE` already bounds the query, so `limit` beside one is redundant and
actively harmful. `_bounded_query()` now sends one or the other, never both. A
caller's `limit` is still honoured on a filtered call, applied client-side by
`_apply_client_limit()` since it cannot go on the wire.

**Accepted limitation:** on an exact-match filter (`ip_addr`, `subnet_name`,
`subnet_id`, `pool_name`) only one record can match, so dropping `limit` costs
nothing. On a multi-match filter (`parent_subnet_name`, `parent_site_name`) the
appliance returns **every** match and the bound is client-side only. There is no
server-side remedy available.

Mirrored into the classic twin (1.0.11). Pinned by six tests, which carry
unusual weight: the mock accepts both parameters, so it cannot reproduce this
failure.

## 1.0.13 (2026-08-29) — subnet names are labels, not CIDRs

Real subnet names on this appliance are labels (`BLABL_BLABL-LABLLA` — letters,
underscores, hyphens), not CIDR strings. Both parameter descriptions now say so,
and the fixtures were reseeded to match (`CORP_LAN-USERS` / `CORP_LAN-PRINTERS`
under `CORP_CORE-NET`), with addresses in the `*_ip_addr` range fields.

**Consequence for callers:** *"which subnet contains this IP?"* cannot be
answered through `subnet_name`. It needs `start_hostaddr`/`end_hostaddr` — the
range filters, which are not yet exposed (see 1.0.10).

## 1.0.12 (2026-08-29) — `Accept` instead of `Content-Type` on bodiless GETs

Every action here is a GET with no body, yet `_request()` set
`Content-Type: application/json` on all of them. `Content-Type` describes a
request body; declaring one that does not exist invites a strict server to read
an empty body as a JSON document and reject it. Replaced with
`Accept: application/json`.

Also pinned by test: `X-DDI-Username`/`X-DDI-Password` are base64-encoded (the
1.0.3 fix), verified by decoding them back.

Mirrored into the classic twin (1.0.9).

## 1.0.11 (2026-08-29) — `list subnets` filters are fully optional

`limit` is now the only parameter that need be set. With no filter, `list
subnets` issues a bare bounded call (`GET /rest/ip_block_subnet_list?limit=N`,
no `WHERE` on the wire) — the same shape `test connectivity` has always used.

**Two filters is still refused**, unchanged: `AND` composition is unconfirmed on
the real APIM, and silently dropping a condition would be a coded guess.

The classic twin's filter selector now returns an explicit `(ok, column, value)`
rather than making the caller infer "no filter" from an error status, since zero
filters is now a success. Mirrored into the classic twin (1.0.8).

## 1.0.10 (2026-08-29) — purpose-built subnet filters; credentials stripped

### Named `WHERE` filters on `list subnets`

`list subnets` previously took one required `name` parameter and could only
answer "tell me about this exact subnet". It now exposes the confirmed-filterable
columns:

| Parameter | `WHERE` column | Answers |
|---|---|---|
| `subnet_name` | `subnet_name` | this exact subnet (the old `name`) |
| `subnet_id` | `subnet_id` | this subnet by id |
| `parent_subnet_name` | `parent_subnet_name` | the subnets under a parent |
| `site_name` | `parent_site_name` | the subnets in a space/site |

Two of those mappings are not identities, so the mapping lives in a
`LIST_SUBNETS_FILTERS` table rather than an f-string.

**[!] Breaking parameter change: `name` → `subnet_name`.** Any caller binding
the old parameter must be updated. `get ip pool`'s own `name` parameter is
untouched.

**Ranges deliberately not built.** `start_ip_addr`/`end_ip_addr` (hex) and
`start_hostaddr`/`end_hostaddr` (dotted) are confirmed filterable, but a useful
range needs comparison operators and/or `AND`, neither of which is confirmed on
this APIM.

### Whitespace stripped from hand-entered credentials

`_auth_headers()` base64-encoded `client_id`, `client_secret`, `ddi_username`
and `ddi_password` exactly as stored, while the three PEM fields were
whitespace-normalised. On an airgapped box every one of these is typed or pasted
into an asset field by hand, and base64 preserves whatever surrounds the value —
so one trailing newline yields a credential wrong by a byte, and a 401
indistinguishable from a genuinely wrong password. All four are now stripped at
the point of use, with regression coverage from both directions (stripping must
not flatten two genuinely different values into a match).

Mirrored into the classic twin (1.0.7).

## 1.0.9 (2026-08-28) — packaging only

Version bump with no source, manifest, or behaviour change, to carry the
bundled build past the install gate (SOAR refuses an install whose `app_version`
is less than or equal to the live one). Build a dependency-stock variant with
`tools/build_sdk_app.py --stock` if that comparison is ever needed; it writes
`<name>-stock.tgz` and cannot overwrite the shipping artifact.

## 1.0.8 (2026-08-27) — real filter column for `ip_block_subnet_list`

`list subnets` filtered with `WHERE=name='<subnet>'`. On this APIM `name` is
**not a filterable column** — it is the SELECT column the record comes back
under. The filterable one is `subnet_name`. The WHERE column and the SELECT
column genuinely differ on this service.

Vendor-confirmed filterable columns: `subnet_name`, `subnet_id`,
`parent_subnet_name`, `parent_site_name`, `start_ip_addr`/`end_ip_addr` (hex),
`start_hostaddr`/`end_hostaddr` (dotted IP).

The record's *output* mapping is unchanged — `subnet_name` output still reads
`record["name"]`, which remains correct. Mirrored into the classic twin (1.0.6).

**Still unconfirmed:** `ip_alias_list`'s own field names — `alias_name` remains
analogy-based.

## 1.0.7 (2026-08-27) — multi-record results, `limit` as a real parameter, input validation

- **Every record-returning action emitted only `records[0]`** while advertising
  a `data.*` list datapath, so an IP with two DNS aliases reported one with no
  indication more existed. All four actions now return `list[ActionOutput]`.
- **`limit` is a real action parameter** (numeric, optional, default 1) on all
  four record-returning actions, replacing the hardcoded `limit=1`. At the
  default this is behaviourally identical to 1.0.6. `test connectivity` keeps a
  fixed `limit=1`.
- **`list aliases`' `ip_id` is a string, not numeric.** `get ip address` emits
  `ip_id` as a string, so the documented chain could not be wired in the VPE
  editor. `_validate_int()` still enforces a whole number before it reaches the
  URL path, which also closes the float case (`1001.0` previously produced a
  false "no aliases").
- **`_ip_to_hex()` raised a bare `ValueError`** for a non-IP `address`, dumping
  a raw traceback as the failure message. Now raises `ActionFailure` with a
  message saying what the parameter takes.
- Mirrored into the classic twin (1.0.5), whose manifest also had **stale
  declared outputs** — it still advertised curated names after the connector
  switched to raw pass-through, so those datapaths were dead in the VPE. It also
  hardcoded `total_objects = 1`; it now reports the true count.

## 1.0.5 (2026-08-26) — real field names, raw pass-through everywhere

The subnet's own name field is `name`, not `subnet_name` as inferred by analogy
to the differently-named `ip_subnet_list` method in the public docs. Fixed the
read side and added a `tree_path` output. `raw_json` added to `get ip address`,
so every action now has it.

The classic twin was rebuilt around full raw pass-through instead of manual
field mapping: `add_data(record)` forwards every key the appliance returns under
`data.*.<key>`, eliminating a whole class of field-name-guessing bugs.
`description` (parsed from the `*_class_parameters` blob) is still added as a
convenience key on top of the raw record.

## 1.0.4 (2026-08-26) — HTTP 204 on empty results

A "not found" result on this APIM returns **HTTP 204 No Content** (empty body,
no `Content-Type`), not a 200 with an empty array. `_process_response()`'s
empty-content branch defaulted to `{}`, so a real 204 tripped the generic
"unexpected response shape" failure instead of the intended "No X found"
message. Empty content now defaults to `[]`. Mirrored into the classic twin.

## 1.0.3 (2026-08-26) — bound every list call

`limit=1` sent unconditionally on all five actions' list calls rather than only
those lacking a `WHERE`. **Superseded by 1.0.14**, which established that
`WHERE` and `limit` must never both be sent; a `WHERE` is itself a bound.

Also in this version: `X-DDI-Username`/`X-DDI-Password` are base64-encoded
independently (`base64(ddi_username)`, `base64(ddi_password)`) — not combined,
not folded into the Basic auth layer. Previously sent as plain text, which would
have failed against the real backend.

## 1.0.2 (2026-08-26) — unbounded list calls time out

A list call with neither `WHERE` nor `limit` makes the backend attempt a full
unbounded scan and time out server-side. A bound therefore always goes on the
wire. (The specific remedy used here — adding `limit=1` beside an existing
`WHERE` — was itself the cause of the 401 fixed in 1.0.14.)

## 1.0.1 (2026-08-25) — field-name fixes against vendor docs

Field names corrected against the real vendor documentation. Note the API
convention here is derived from vendor SDKs rather than a confirmed contract
with this APIM: whether it proxies `/rest/*` verbatim or under its own prefix,
and IPv6 filtering (hex-encoding is vendor-confirmed for IPv4 only), still need
real verification.

## 1.0.0 (2026-08-25) — clean reset, new appid

First identity reset. See the 2026-08-29 reset above for what an appid change
means operationally.

---

*Entries below predate the 2026-08-25 identity reset and cover the original
package's SDK-bundling history.*

## 1.0.8 (2026-08-25) — root cause of the airgapped "action not found"

The SDK build silently drops seven packages it considers runtime-provided
(`requests`, `urllib3`, `certifi`, `idna`, `charset-normalizer`,
`beautifulsoup4`, `soupsieve`). Hand-fixed at 1.0.1, this regressed on every
rebuild from 1.0.4 through 1.0.7, so those packages were missing from every
package shipped since 1.0.3. The app then failed to import
(`ModuleNotFoundError: requests`), SOAR registered **no actions**, and the
symptom on the target was "action test connectivity not found" — an app that
appears installed but has an empty action list.

Wheels restored and re-verified from a clean-room venv (manifest-declared wheels
only, then a real import). **Always bundle for airgapped delivery** — a
dependency-stock build is not a shipping configuration.

## 1.0.7 (2026-08-25) — code-review fixes

- Fixed unescaped input in `list subnets`/`get ip pool`'s `WHERE` clauses
  (`_sql_escape()` had been dropped when `get dns record` was removed, but the
  two new actions needed it — a value containing a single quote broke the
  filter).
- Added an `_ensure_list()` guard on all four record-returning actions, which
  all assumed a bare JSON array. If the APIM ever wraps results in an envelope,
  this now fails with a clear message instead of a raw `KeyError`/`TypeError`.

## 1.0.6 (2026-08-25) — `list subnets`, `get ip pool`, `list aliases` added

`WHERE` is real and required on `ip_address_list`, settling query-string
filtering as the general convention (`ip_alias_list`'s path-parameter style is a
"list children of a known parent" shortcut, not the norm). `get ip address` now
emits `ip_id` so it can be chained into `list aliases`.

Three actions added: `list subnets` (`ip_block_subnet_list`), `get ip pool`
(`ip_pool_list`) and `list aliases` (`ip_alias_list/ip_id/{ip_id}`). The latter
two have field names inferred by analogy rather than vendor-confirmed, and both
carry a `raw_json` fallback.

## 1.0.5 (2026-08-25) — `get dns record` removed

No record-level DNS service was ever confirmed on this APIM, only zone-level.
`dns_rr_list` was an inference from public client docs and was never observed on
the real system; rebuild the action only once a real endpoint is identified.

`test connectivity` now calls `GET /rest/ip_block_subnet_list` bare rather than
`ip_address_list?limit=1` — that service needs no filter parameters, making it
the safest connectivity check among the confirmed-real endpoints.

## 1.0.4 (2026-08-25) — real endpoints

The original `/ddi/health`, `/ddi/ip_address` and `/ddi/dns_record` paths did
not exist on the real backend; the first airgapped `test connectivity` run
failed with "not found" as a direct result. Rewritten to SOLIDserver's classic
REST convention — flat service names under `/rest/`, `WHERE=<field>='<value>'`
filtering — with `get ip address` calling
`GET /rest/ip_address_list?WHERE=ip_addr='<hex>'` (**the address must be
hex-encoded, not dotted-decimal**). Output field names updated to the vendor's
real ones, and `description` is parsed out of the `ip_class_parameters`
custom-attribute blob rather than assumed to be a plain field.

## 1.0.3 (2026-08-25) — DDI backend auth layer

`X-DDI-Username`/`X-DDI-Password` base64-encoded independently rather than sent
as plain text.

## 1.0.2 (2026-08-24) — `requests` replaces the hand-rolled HTTP layer

Replaced the hand-rolled `urllib`/`ssl.SSLContext` layer in `_request()` with
`requests` (`cert=`/`verify=` handle mTLS natively). A pure simplification, not
a new dependency — `requests` and its chain were already forced into the bundle
by `splunk-soar-sdk` itself. Added `_process_response()` with real content-type
detection, so a non-JSON 2xx response no longer crashes with an unhandled
`JSONDecodeError`.

## 1.0.1 (2026-08-24) — bundled dependency set

Removed the unused Outlook `.msg`/OLE/RTF-parsing chain pulled in transitively
by `splunk-soar-sdk` but never exercised by this connector. Added `idna`,
`requests`, `urllib3`, `certifi`, `charset-normalizer` — genuinely required by
`soar_sdk.app_cli_runner` at load time but missing from the original bundle;
without them the app fails to import in an air-gapped-equivalent environment.
