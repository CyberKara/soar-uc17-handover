# efficientip_ddi — EfficientIP SOLIDserver via APIM

Splunk SOAR connector for analyst-driven IP lookup enrichment against an
EfficientIP SOLIDserver DDI (DNS/DHCP/IPAM) backend reached through an APIM
gateway rather than called directly. Consumed by the `efficientip_ddi_enrich`
playbook (UC17, `soar-playbooks`).

**Classic `BaseConnector` style.** This is the one recorded exemption from FR-01
(SDK for new connectors) in `docs/dev-rules.md`, and it is permanent. An SDK
twin of this app existed alongside it from 2026-08-26 so both styles could be
compared against the real airgapped appliance; on 2026-08-31 the user decided in
this app's favour and the SDK one was deleted. The deciding factor was
operational, not functional: SOAR 8.5's App Debugger — the connector's GUI
edit/view page — cannot dispatch actions for SDK-based apps at all, and on an
airgapped appliance that panel is often the operator's only way to exercise an
action by hand. This app took over the SDK app's name and role under a fresh
`appid`, with `app_version` reset to 1.0.0.

Unlike the deleted SDK app, this one does **raw pass-through** —
`action_result.add_data(record)` forwards every key SOLIDserver returns, rather
than mapping a curated subset.

______________________________________________________________________

## Auth model (3 layers, every request)

1. **mTLS** — `client_cert` + `client_key` (+ optional `client_ca`) presented to
   APIM at the TLS layer. Same PEM-normalize-to-tempfile pattern as
   `cyberark_ccp`: SOAR's config textareas mangle PEM whitespace, so raw config
   values are re-wrapped before use.
2. **`Authorization: Basic base64(client_id:client_secret)`** — the APIM-level
   app credential. No OAuth token exchange; the header is sent directly on every
   call, nothing to cache or refresh.
3. **`X-IPM-Username` / `X-IPM-Password`** — forwarded by APIM to SOLIDserver's
   own backend auth. Each value is base64-encoded **independently**
   (`base64(ddi_username)`, `base64(ddi_password)`) — not combined like the Basic
   Auth layer, not folded into it.

   **The header names matter.** Through v1.0.11 these were sent as
   `X-DDI-Username` / `X-DDI-Password`. On the target appliance (operator's own
   test, 2026-09-30) that naming alone makes every call answer **HTTP 401 with
   `"message": "The specified document is not valid JSON data"`**: the operator's
   working curl sent `x-ipm-username` / `x-ipm-password`, and renaming only those
   two headers in it to `X-DDI-*` reproduced the 401 exactly. v1.0.12 sends the
   `X-IPM-*` names. The asset fields keep their `ddi_*` names.

Earlier notes here said the `X-DDI-*` names were confirmed against the real APIM
(2026-08-25) and end-to-end on the real appliance (2026-08-29). The 2026-09-30
test above contradicts that for the target appliance, and this README cannot say
which is right for any other APIM: if a deployment ever needs different names,
they are the two constants `DDI_USERNAME_HEADER` / `DDI_PASSWORD_HEADER` in
`efficientip_ddi_consts.py`.

## Endpoint convention

Flat service names under `/rest/`, `WHERE=<field>='<value>'` filtering. The
APIM may publish them under its own path prefix
(`https://<apim>/<prefix>/rest/ip_address_list`): put everything before `/rest`
in the asset's `base_url`, and the connector appends `/rest/<service>`. That
works on the target appliance, where the operator's working curl goes through a
two-segment prefix.

Addresses are filterable **two ways**, as a sibling pair of columns:
`hostaddr` takes the dotted form and `ip_addr` takes zero-padded hex. This
connector uses **`hostaddr`** (no underscore), confirmed by the operator's own
working curl on the target appliance, 2026-09-30, so no encoding step is needed
on the way in. **`host_addr` (with an underscore) is not a column there**: it
answers with a SOLIDserver SQL error (`sql_error` 7). Through v1.0.11 the
connector used `host_addr`, and an earlier README called it confirmed on the
real appliance. The only test of it on record in the plan is the soar8 run
against the mock, which had been seeded with that name. The hex column still
matters for anything that has to *range*-compare addresses — see the note under
`list subnets` filters. The user has directly observed `/rest/ip_address_list`,
`/rest/ip_alias_list/ip_id/{ip_id}`, `/rest/dns_zone_list`, `/rest/ip_pool_list`
and `/rest/ip_block_subnet_list` on the real system.

**`get dns record` does not exist and must not be rebuilt on a guess.** Only
zone-level `dns_zone_list` is confirmed; there is no confirmed record-level DNS
service. The `dns_rr_list` endpoint an early draft used was this project's own
inference from public client docs and was never observed on the real APIM.

### Bounding rule — every list call carries a bound

A list call carrying **neither** `WHERE` nor `limit` makes the backend attempt an
unbounded scan and time out server-side. So a bound always goes on the wire:
`_bounded_query()` always sends `limit`, and adds `WHERE` when filtering.

> **`WHERE` and `limit` together are fine.** A "never send both" rule was shipped
> once and is **disproven** — the real appliance returns HTTP 200 for a filtered
> call carrying `limit=1` and bounds it to exactly one row, on
> `ip_block_subnet_list` and `ip_address_list` alike. The observation behind that
> rule was a shell-quoting artefact: an unquoted curl URL splits at `&`, so the
> arm believed to carry `limit` never sent it and the shell merely backgrounded
> curl. Both arms were identical `WHERE`-only requests. Do not reintroduce it.

## Actions

| Action | Type | Parameters | Notes |
|---|---|---|---|
| `test connectivity` | test | — | `GET /rest/ip_block_subnet_list?limit=1` |
| `get ip address` | investigate | `address` (req), `limit` (default 1) | `GET /rest/ip_address_list?WHERE=hostaddr='<dotted ip>'` |
| `list subnets` | investigate | exactly one of `subnet_name` / `subnet_id` / `parent_subnet_name` / `site_name`; `limit` (default 1) | `GET /rest/ip_block_subnet_list` |

Two endpoints only, by user decision 2026-09-24: `ip_block_subnet_list` and
`ip_address_list`. `get ip pool` (`/rest/ip_pool_list`) and `list aliases`
(`/rest/ip_alias_list/ip_id/{ip_id}`) were removed in v1.0.11 — do not re-add
them without asking.

All record-returning actions emit **one row per record** and carry a `raw_json`
fallback field, because not every field name is independently vendor-confirmed
(see Provenance).

### `list subnets` filters

`subnet_name` is the subnet's **NAME — a label**, e.g. `CORP_LAN-USERS`, **not**
its CIDR (user-confirmed 2026-08-29). Underscores and hyphens; no dots or
slashes. Looking a subnet up **by address** needs the range columns, which are
not exposed as action parameters yet — see the UC17 plan's deferred range
filters.

Full set of filterable columns on `ip_block_subnet_list`:

| Column | Value form |
|---|---|
| `subnet_name` | the subnet's name/label |
| `subnet_id` | internal id |
| `parent_subnet_name` | parent subnet's name |
| `parent_site_name` | site/space name (exposed as the `site_name` parameter) |
| `start_ip_addr` / `end_ip_addr` | hex-encoded address (not exposed) |

> **If range filters are ever built, they must use the hex columns.** `WHERE` is
> SQL, so `<=`/`>=` on a dotted string compares lexicographically, not
> numerically: `"9.0.0.1" > "10.0.0.1"` is *true* as a string and wrong as an
> address. Zero-padded hex sorts identically to numeric order
> (`"09000001" < "0a000001"`), which is very likely why the hex columns exist at
> all. Equality is safe either way; containment is not.
| `start_hostaddr` / `end_hostaddr` | dotted IP (not exposed) |

The caller-facing parameter name is not always the `WHERE` column: `site_name`
filters as `parent_site_name`, and `subnet_name` filters on `subnet_name` while
the record comes back under `name`. That mapping lives in
`LIST_SUBNETS_FILTERS` in `efficientip_ddi_consts.py`.

## Asset configuration

| Field | Required | Type | Notes |
|---|---|---|---|
| `base_url` | Yes | string | APIM gateway base URL **including any APIM path prefix before `/rest`**, e.g. `https://apim.internal.example/some/prefix` |
| `client_id` | Yes | string | APIM app client ID (Basic Auth username) |
| `client_secret` | Yes | password | APIM app client secret (Basic Auth password) |
| `ddi_username` | Yes | string | SOLIDserver backend username, sent via `X-IPM-Username` |
| `ddi_password` | Yes | password | SOLIDserver backend password, sent via `X-IPM-Password` |
| `client_cert` | Yes | string | PEM client certificate for mTLS |
| `client_key` | Yes | password | PEM private key matching `client_cert` |
| `client_ca` | No | string | PEM CA bundle to verify APIM's server cert. Blank uses the `requests` library's own CA bundle, or the file named by `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` when one of those is set. It does not read the OS trust store. |
| `verify_ssl` | No (default `true`) | boolean | |
| `retry_count` | No (default `3`) | numeric | Total attempts for a request answered with HTTP 401. `1` disables retrying. Clamped to 1–10. |
| `retry_backoff` | No (default `2`) | numeric | Base seconds between 401 retries; the wait grows linearly (1x, 2x, 3x). Clamped to 0–30. |

`client_cert` and `client_ca` are deliberately `string`, not `password`: a client
certificate and a CA certificate are public by definition (NFR-04). Beyond
correctness, every password-typed field is a hazard for the REST
read-modify-write pattern this project uses on assets — a GET value written back
corrupts it.

> **Across an air gap, re-enter every credential by hand.** Password-type field
> values do not survive a handover export as usable values. This was the whole
> cause of the 2026-08-28 `Test Connectivity` 401 on the real appliance — the
> code was fine, the asset config was not. See
> `project-soar-efficientip-airgapped-first-run`.

## Response codes

This API returns four codes, and **one does not carry its usual HTTP meaning**:

| Code | Meaning here | Connector behaviour |
|---|---|---|
| `200` | Success | Body parsed as JSON |
| `204` | No content — zero matching records | Treated as an empty result set, not an error. Whether "no records" is an action failure is each action's own call. |
| `400` | **Bad request**, from the SOLIDserver backend — body carries `errno`/`sql_error` | Never retried; `errno` surfaced in the error message |
| `401` | Unauthorized — the **only** auth-layer code | **Retried** (see below) |
| `403` | **Bad request**, from the APIM gateway — *not* "forbidden" | Never retried; the error message says so explicitly |

Bad requests arrive as **either 400 or 403**, most likely because two different
layers can reject one: the gateway answers `403`, the SOLIDserver backend behind
it answers `400`, which is why only the `400` body carries an `errno`. Confirmed
live on the real appliance 2026-09-01: an unquoted `WHERE` value
(`ip_addr=<hex>`) returns `400` with `[{"errno": "50028", "sql_error": "7"}]`,
while the correctly quoted form (`ip_addr='<hex>'`) returns `204` for no match.
**String values in a `WHERE` clause must be single-quoted**; `_bounded_query()`
always quotes them. The clause is SQL and types values the way SQL does, so an
**integer** column needs no quotes — `WHERE=ip_id=1697182` was confirmed working
live on 2026-09-01. Every column currently exposed is string-typed, so quoting is
right in every present case.

**Percent-encoding the `=` is irrelevant.** The same integer query was confirmed
working both as `WHERE=ip_id%3D1697182` and as `WHERE=ip_id=1697182`. Combined
with the unquoted-string `400`, this isolates quoting as the only variable that
ever mattered here — an earlier reading that suspected the encoding is retired.

> **Do not infer the filterable columns from the response body.** This API has
> already been shown to differ: on `ip_block_subnet_list` records come back under
> `name` while the filterable column is `subnet_name`. A column missing from a
> response is not evidence that you cannot filter on it.
>
> Note also what a `204` tells you. It means the clause **parsed** and matched
> nothing — a bad column or bad syntax returns `400`/`403` instead. So a `204`
> confirms a column is real; it says nothing about whether your *value* was right.

`403` is the one to watch. Read as standard HTTP it looks like a permissions
problem and sends an operator hunting credentials and entitlements — the wrong
half of the stack. On this API it means the *request* was wrong: a bad filter
column, bad `WHERE` syntax, an invalid parameter. The connector's error text
names that explicitly rather than printing a bare `HTTP 403`, and treats `400`
identically.

Because both `400` and `403` cover malformed requests, a `401` **cannot** be the
gateway's way of rejecting a bad query. That is worth remembering when reading
the open 401 below: query-shaped explanations for it are ruled out by this table
alone.

### Retry on 401

The real appliance has been observed returning `401` for a request that succeeds,
unchanged, moments later. The cause is the APIM's backend leg failing: a captured
transient 401 carries `X-Backside-Transport: FAIL FAIL`, and the gateway synthesised
the 401 itself (2026-09-02). The connector holds no per-call state — headers are
recomputed from config on every call, there is no session, cookie or token, certs
are written and deleted per call — so identical inputs produce identical bytes.
That is what makes retrying meaningful here rather than re-asking a question the
server already answered.

- Applies to **every action, including `test connectivity`**.
- `401` only. `400` and `403` are deterministic and are never retried.
- **Not** a 401 whose `X-Backside-Transport` is all `OK` (`OK OK`): the gateway
  reached SOLIDserver, so that 401 is the backend's own credential verdict.
  Repeating it only risks a lockout (since v1.0.14). A `FAIL` value, or no header
  at all, is retried. Only one transient 401 has been captured, so the no-header
  case stays retryable until the appliance shows what it means.
- The final 401 message says which case it was: `OK` → check
  `ddi_username`/`ddi_password`; `FAIL` → escalate to the APIM administrator, with
  the call's `APIm-Debug-Trans-Id` in the message; no header → check
  `client_id`/`client_secret` and the client certificate.
- Linear backoff between attempts, not immediate re-fire: rapid repeated auth
  failures are what trip gateway lockout and quota policies.
- **Never silent.** A call that only succeeded on a later attempt reports
  `Succeeded on attempt N of M` in the action result, so the gateway fault stays
  visible to the operator who has to escalate it.

### Debug logging

`debug_logging` (off by default) adds one `save_progress` line per HTTP call, which
shows in both the App Debugger panel and the container action result (the only
channels an operator without a shell has):

```
GET https://<apim>/<prefix>/rest/ip_address_list?limit=1&WHERE=hostaddr%3D%2710.1.2.3%27 -> HTTP 401  X-Backside-Transport=FAIL FAIL  APIm-Debug-Trans-Id=<id>  body: {"message": "..."}
```

The URL carries only `limit`/`WHERE`; the credentials travel in headers and are
never printed. The body is cut at 500 characters. Until v1.0.14 this toggle drove a
much larger trace (DNS peers, socket peer address, a replayable curl line, ambient
proxy/netrc settings, PEM fingerprints, idle-gap timing); all of it was built to
hunt the 401 and was removed in v1.0.15 once both causes were known.

## Building and installing

```bash
tools/build.sh efficientip_ddi          # -> dist/efficientip_ddi-v<version>.tgz
tools/install_app.sh dist/efficientip_ddi-v<version>.tgz
```

Build on the **connected** host; never compile on the airgapped target. This app
bundles no wheels (`pip_dependencies = {"wheel": []}` — `requests`/`urllib3` come
from the SOAR runtime), so packaging is a clean tar honouring
`exclude_files.txt`.

SOAR refuses to install a connector whose `app_version` is **≤** the live
deployed version — check `GET /rest/app` and bump above *that*, not just above
the repo.

## Testing

**Unit/regression suite** — 59 tests, pinning defects that previously passed
silently:

```bash
pytest connectors/efficientip_ddi/tests
```

`tests/conftest.py` stubs the `phantom.*` modules (they only exist inside
`/opt/phantom`) before importing the connector, the same approach as
`cyberark_ccp/tests/conftest.py`.

**Mock backend** — `soar8/migration/mock-backend/mock_efficientip_ddi.py`, port
**8447**. Unlike the other mocks it requires mTLS **by default**, mirroring the
real APIM (there is no `--no-mtls` convenience in `mock_start.sh`'s `ddi`
target):

```bash
cd soar8/migration/mock-backend && ./mock_start.sh ddi
```

**The mock follows the appliance (since v1.0.14).** It reads the `X-IPM-*`
header names and filters `ip_address_list` on `hostaddr`, and it does NOT also
accept `X-DDI-*` / `host_addr`: a connector that regressed to the old names fails
against it the way it failed on the appliance. The unit suite pins the same two
names.

Point the asset at `https://<mock-host>:8447` — **never** `127.0.0.1`/`localhost`,
the mock runs cross-host on the ansible controller — with
`client_cert`/`client_key` at `./certs/client.pem` / `./certs/client-key.pem`,
and the credential fields at the mock's documented test values (see
`mock_efficientip_ddi.py`'s own docstring).

**End-to-end** — `soar-playbooks`' `tools/uc17_verify.sh` runs the whole chain:
mock seed, a SOAR action dispatch, the enrichment playbook, and the action-test
playbook.

**On the real appliance** — `tools/uc17_airgapped_probe.sh` answers the questions
only the real SOLIDserver/APIM can settle. Read-only: every call is a GET against
a `*_list` service.

______________________________________________________________________

## Provenance and open questions

Output-field mappings were cross-referenced against SOLIDserver's own public REST
method reference (the `solidserverrest` project docs, v9.0.1a) rather than
inferred, which caught three bugs the mock had been masking (it was seeded with
the same wrong names, so everything passed locally):

- `get ip address` — hostname field is `name`, not `hostdev_name`
  (`hostdev_name` is not a real `ip_address_list` field at all).
- `get ip pool` (removed in v1.0.11) — range fields are `start_hostaddr`/`end_hostaddr`, not
  `pool_start_hostaddr`/`pool_end_hostaddr`.
- `list aliases` (removed in v1.0.11) — the alias name field is `alias_name`, not `ip_alias`
  (`ip_alias` is real, but on `ip_address_list`, not `ip_alias_list`).

A fourth followed the same shape: on `ip_block_subnet_list`, `name` is only the
**SELECT** column and the **filterable** column is `subnet_name`. The usual "the
`WHERE` column matches the `SELECT` column" convention does not hold on this
service. This was undetectable locally in both directions — the mock matched on
`name`, and it also fell through to returning every record when a `WHERE` did not
match, so even a probe asking "did it return a row?" would have said yes for
either key. The mock now matches `subnet_name` only and deliberately does not
also accept `name`.

**`ip_address_list` on the target appliance returns 11 fields** (user, from a real
`get ip address` result, 2026-10-01): `ip_id`, `ip_addr`, `subnet_name`,
`site_name`, `name`, `mac_addr`, `ip_class_name`, `ip_class_parameters`,
`parent_subnet_name`, `site_class_name`, `ip_alias`. The SOLIDserverRest method
reference ([`docs/ip_address_list.md`](https://github.com/gregocgt/SOLIDserverRest/blob/master/docs/ip_address_list.md),
a community fork, version unstated, and without `hostaddr`, which the appliance
filters on) lists about 70 output fields, all 11 among them; `multistatus` is
documented but not returned. The method takes no field selection (`where`,
`orderby`, `offset`, `limit` only), so the subset is most likely fixed by the APIM
in front of SOLIDserver -- inferred, not measured. Fields such as `pool_name`,
`last_seen`, `dhcplease_end_time`, `hostdev_name` or `iplport_name` would have to be
exposed there; no connector change can request them.

**Still open:**

- `list subnets`' `subnet_start_ip_addr`/`subnet_end_ip_addr` mapping is an
  analogy to the `subnet_*`-prefixed fields nested inside
  `ip_address_list`/`ip_pool_list`; the current public docs only cover a
  differently-named `ip_subnet_list`.
- **Range filters on `list subnets`** — designed, deliberately not built, behind
  three read-only appliance probes written out in the UC17 plan.
- ~~Whether the APIM proxies `/rest/*` verbatim or under its own prefix.~~
  Answered 2026-09-30 for the target appliance: under a prefix, which goes in
  `base_url`.
- **IPv6 filtering** — `hostaddr` is confirmed for IPv4 only. The connector
  normalises IPv6 to its compressed form (`2001:0db8::0001` → `2001:db8::1`);
  whether the appliance stores that form or the expanded one is unverified.
- ~~A `list subnets` 401 seen on the real appliance (2026-08-29) is unexplained.~~
  **Explained 2026-09-02:** the transient 401 is the APIM's backend leg failing
  (`X-Backside-Transport: FAIL FAIL`), client-independent (bare curl failed 2 of 3).
  Escalate to the APIM administrator with the `APIm-Debug-Trans-Id`; the retry is
  the only mitigation on this side.
- **What every other 401 carries** — only one transient 401 has been captured. Not
  yet seen on the appliance: whether every transient 401 is `FAIL FAIL`, and what a
  genuinely wrong credential returns (`OK OK` from the backend, or no header from
  the gateway). v1.0.14 stops retrying only the `OK` case.

## v1.0.16 (2026-10-01) — `get ip address` outputs match the appliance

Manifest only; no code change (the action already forwards every key it receives).
The output datapaths now list what a real `get ip address` returned on the target
appliance (user, 2026-10-01): `ip_id`, `ip_addr`, `subnet_name`, `site_name`,
`name`, `mac_addr`, `ip_class_name`, `ip_class_parameters`, `parent_subnet_name`,
`site_class_name`, `ip_alias`, plus the connector's own `address` and
`description`. Added `parent_subnet_name`, `site_class_name` and `ip_alias`, so the
VPE offers them; removed `multistatus`, which the appliance does not return.

## v1.0.15 (2026-10-01) — simplified (user request)

The 401 hunt left the connector at ~1,200 lines, about half of it instrumentation
and narrative for theories that were later disproven. Both 401 causes are now known
(the APIM's backend leg, `X-Backside-Transport: FAIL FAIL`; and the `X-IPM-*` header
names), so the connector is cut to ~580 lines with the same actions, parameters,
outputs, auth, retry and error messages:

- **Removed:** DNS peer listing, socket peer address, replayable curl line, ambient
  env/netrc probe, PEM fingerprints, idle-gap timer and its saved state, streamed
  reads (needed only to read the peer address), per-attempt exchange dump,
  `add_debug_data()` (SOAR drops it, 8.5 and 8.6), and the **`user_agent` asset
  field** (a test knob for a disproven theory; an existing asset's stored value is
  simply ignored).
- **`debug_logging` now means one line per call** (see "Debug logging").
- **Kept:** 401 retry with backoff (not retried under `X-Backside-Transport: OK OK`),
  the 401 case in the message with the `APIm-Debug-Trans-Id`, `trust_env=False`,
  the platform CA-bundle fallback, credential stripping, PEM normalisation.
- `diagnostics/uc17_client_bisect.py` no longer ships in the handover (still in
  `tools/`); `uc17_airgapped_probe.sh` stays for the range-filter probes.

## v1.0.14 (2026-10-01) — v1.0.12's appliance fixes brought home; IPv6; 401 split; review fixes

v1.0.12 (below) was made directly in the handover mirror on 2026-09-30 and never
reached this source repo, so the lab kept building from v1.0.11. Two builds made
here on 2026-10-01 were numbered 1.0.12 and 1.0.13 without its fixes: installed on
soar8 only, never shipped. v1.0.14 carries v1.0.12 plus:

- **IPv6 reaches the connector.** `get ip address`'s `address` declared
  `contains: ["ip"]`, and SOAR validates a parameter against its contains types
  before dispatch: an IPv6 address was refused with `Parameter 'address' failed
  validation` and never reached the connector (soar8 playbook run 3469). Now
  `["ip", "ipv6"]`, the form 79 parameters in `reference_connectors/` use, and so
  are the two `address` output datapaths. Whether SOLIDserver answers an IPv6
  lookup on `ip_address_list` is unverified, and an IPv6 not-found says so.
- A 401 under `X-Backside-Transport: OK OK` is no longer retried, and every final
  401 says which case it was (see "Retry on 401").
- The debug-only work (DNS lookup of the APIM name, PEM fingerprints, environment
  probe, curl replay, peer address) runs only with `debug_logging` on. The DNS
  lookup used to run on every call, because the message was formatted before
  `_dbg()` checked the flag.
- Docstrings and comments that still called the 401 an open investigation are
  corrected.
- The unit suite and the lab mock now use `X-IPM-*` and `hostaddr` (see Testing).

## v1.0.12 (2026-09-30) — backend-auth header names, `hostaddr`

Found on the target appliance, from the operator's own working curl, which
differs from the connector in three ways. Two were the fault; one was cleared.

| Difference | Verdict | Evidence |
|---|---|---|
| Backend-auth headers `x-ipm-username` / `x-ipm-password` vs the connector's `X-DDI-Username` / `X-DDI-Password` | **The cause of the constant 401.** Fixed. | The operator renamed only those two headers in the working curl to `X-DDI-*` and got HTTP 401 `"The specified document is not valid JSON data"`, the exact message the connector showed. |
| `WHERE=hostaddr=…` vs the connector's `host_addr` | **Also wrong.** Fixed. | `host_addr` returns a SOLIDserver SQL error (`sql_error` 7) on that appliance. |
| URL prefix `/<seg>/<seg>/rest/…` | Not a fault. | The asset's `base_url` already carried the prefix. Now documented. |

Also cleared by the same curl: `Accept: application/json` and
`Cache-Control: no-cache` are sent by it too, so neither is a difference.

What changed:

- `X-DDI-Username` / `X-DDI-Password` → `X-IPM-Username` / `X-IPM-Password`,
  defined once as `DDI_USERNAME_HEADER` / `DDI_PASSWORD_HEADER` in the consts
  module, and used by the request builder, the debug-log redaction, and the
  curl emitter. **The redaction list moved with them**: without that, the debug
  log would have printed the two credentials in clear.
- `get ip address` filters on `hostaddr`.
- The two diagnostics scripts send the `X-IPM-*` names. Before this, their curl
  rows would have failed the same way the connector did and would not have
  reproduced a working request.
- Comment and README corrections: the `Content-Type` comment in
  `_make_rest_call` blamed a header that is not sent and was already exonerated;
  the `client_ca` row claimed "system CAs".

Unchanged: every action, parameter, output field and asset field. `efficientip_ddi_enrich`
and `efficientip_ddi_action_test` need no re-import, and an in-place upgrade keeps the asset.

Not verified against the real appliance: this was checked against a local mTLS
stand-in built to behave as the operator's tests showed (401 without the `X-IPM-*`
headers, SQL error on `host_addr`). It shows the code sends what the working curl
sends; the appliance's own answer is the operator's Test Connectivity.

## v1.0.11 (2026-09-24) — scope cut to two endpoints

User decision: the connector keeps only `ip_block_subnet_list` (`list subnets`,
plus `test connectivity`) and `ip_address_list` (`get ip address`). `get ip pool`
and `list aliases` were removed from the manifest, the handlers, the constants
and the tests; the transport tests that used `list aliases` as their carrier
(retry, 400/403/204, limit, headers) now run on `list subnets`. This also
retires the owed real-appliance retest of `alias_name` and the pool identity
field. `efficientip_ddi_enrich` no longer chains into an alias lookup.

## v1.0.10 (2026-09-09) — user_agent default blanked; reconciliation after the 8.6 rebuild

`soar8` was wiped and rebuilt to SOAR 8.6.0.530 on 2026-09-05, which reset the
live install to whatever the fresh deploy carried and left v1.0.9's decided
`user_agent` fix (see "Still open" history above — the client bisect on
2026-09-02 cleared User-Agent as a 401 suspect, making the curl-string default
plain leftover test scaffolding, not a fix in progress) shipped in the repo but
never installed. Closed both gaps in the same pass: `user_agent`'s manifest default changed from `"curl/8.4.0"` to `""` (blank keeps the HTTP library's own default; no code-side reference to the old string existed to update). Rebuilt as v1.0.10, installed live on the rebuilt soar8 (app id 196, same appid `33986f6c-…`), and re-verified via `efficientip_ddi_action_test`: 5/5 actions PASS.

