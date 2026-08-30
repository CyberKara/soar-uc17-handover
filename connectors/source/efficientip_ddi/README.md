# efficientip_ddi — EfficientIP SOLIDserver via APIM (SOAR SDK)

Splunk SOAR SDK app for analyst-driven IP lookup enrichment against an
EfficientIP SOLIDserver DDI (DNS/DHCP/IPAM) backend that is reached through
an APIM gateway rather than called directly.

The DDI header auth encoding is confirmed against the real APIM (curl,
2026-08-25). Endpoint paths (2026-08-25 rewrite) follow SOLIDserver's real
classic REST API convention — flat service names under `/rest/`,
`WHERE=<field>='<value>'` filtering, IP addresses filtered as hex not
dotted-decimal — sourced from public EfficientIP client code (Ruby/Go
SDKs). **Structurally confirmed** against this org's real APIM: the user
has directly observed `/rest/ip_address_list`, `/rest/ip_alias_list/ip_id/
{ip_id}`, `/rest/dns_zone_list`, `/rest/ip_pool_list`, and
`/rest/ip_block_subnet_list` on the real system. **`get dns record` was
removed** (2026-08-25, later) — only zone-level `dns_zone_list` is
confirmed to exist; there's no confirmed record-level DNS service, and
`dns_rr_list` was this project's own inference from public docs, never
actually observed on the real APIM. Rebuild it only once a real
record-level endpoint is identified. **Resolved (2026-08-25, later):**
`WHERE` is confirmed real and **required** on `ip_address_list` — settling
the earlier open question in favor of query-string filtering over
`ip_alias_list`'s path-parameter style, which is a
"list-children-of-a-known-parent" shortcut, not the general list-filtering
convention. `ip_pool_list`/`ip_block_subnet_list` take `WHERE` as
*optional*. Three more actions added on this basis (`list subnets`,
`get ip pool`, `list aliases`) — see Actions below; the latter two carry a
`raw_json` fallback field since their own field sets aren't independently
vendor-confirmed the way `ip_address_list`'s are. Still open: whether the
APIM proxies `/rest/*` verbatim or under its own prefix (fold that into
`base_url` if so), and IPv6 filtering (hex-encoding is only
vendor-confirmed for IPv4). Playbook design that consumes this connector's
actions hasn't been done yet — this connector is a prerequisite step,
built first per user request.

**Confirmed live (2026-08-26): `limit` matters, not just `WHERE`.** The user
tested directly against the real APIM: `GET /rest/ip_address_list?limit=5`
(no `WHERE` at all) returns fine, but the same call with **neither** `WHERE`
nor `limit` times out server-side — the backend appears to be doing a full,
unbounded scan/dump without one. A single-record lookup via
`WHERE=ip_addr='<hex>'` (e.g. `WHERE=ip_addr='0a4f181f'`) also works, as
already used here. `test_connectivity` was calling `ip_block_subnet_list`
completely bare (no `WHERE`, no `limit`) — exactly the reported failure
shape — so it's fixed to send `limit=1`. `get_ip_address`/`list_subnets`/
`get_ip_pool`'s existing `WHERE=`-filtered calls now also send `limit=1`
defensively, since it's **not yet confirmed** whether `WHERE` alone is
sufficient to bound those queries on the real backend or whether `limit` is
required alongside it too — see the connector's own next-steps entry for
the specific airgapped tests that would settle this.

______________________________________________________________________

## Auth model (3 layers, every request)

1. **mTLS** — `client_cert` + `client_key` (+ optional `client_ca`)
   presented to APIM at the TLS layer. Same PEM-normalize-to-tempfile
   pattern as the classic `cyberark_ccp` connector — SOAR's config
   textareas mangle PEM whitespace, so raw config values are re-wrapped
   before use.
2. **`Authorization: Basic base64(client_id:client_secret)`** — the
   APIM-level app credential. No OAuth token exchange — this header is
   sent directly on every call, nothing to cache or refresh.
3. **`X-DDI-Username` / `X-DDI-Password`** — forwarded by APIM to
   SOLIDserver's own backend auth. Each value is base64-encoded
   independently (`base64(ddi_username)`, `base64(ddi_password)` — not
   combined like the Basic Auth layer, not folded into it).

## Actions

| Action | Type | Params | Output |
|---|---|---|---|
| `test connectivity` | test | — | pass/fail (`GET /rest/ip_block_subnet_list`, bare) |
| `get ip address` | investigate | `address` | `address`, `ip_id`, `subnet`, `space`, `status`, `hostname`, `mac_address`, `ddi_class`, `description` (via `GET /rest/ip_address_list?WHERE=ip_addr='<hex>'`) |
| `list subnets` | investigate | `name` | `subnet_id`, `subnet_name`, `parent_subnet`, `space`, `start_address`, `end_address`, `size`, `ddi_class`, `description`, `raw_json` (via `GET /rest/ip_block_subnet_list?WHERE=subnet_name='<name>'` — field names inferred, not vendor-confirmed) |
| `get ip pool` | investigate | `name` | `pool_id`, `pool_name`, `subnet`, `space`, `start_address`, `end_address`, `ddi_class`, `description`, `raw_json` (via `GET /rest/ip_pool_list?WHERE=pool_name='<name>'` — field names inferred, not vendor-confirmed) |
| `list aliases` | investigate | `ip_id` (int, from `get ip address`) | `ip_id`, `alias_name`, `raw_json` (via `GET /rest/ip_alias_list/ip_id/{ip_id}` — field names inferred, not vendor-confirmed) |

## Asset configuration

| Field | Required | Notes |
|---|---|---|
| `base_url` | Yes | APIM gateway base URL, e.g. `https://apim.internal.example` |
| `client_id` | Yes | APIM app client ID (Basic Auth username) |
| `client_secret` | Yes | APIM app client secret (Basic Auth password) |
| `ddi_username` | Yes | SOLIDserver backend username, sent via `X-DDI-Username` |
| `ddi_password` | Yes | SOLIDserver backend password, sent via `X-DDI-Password` |
| `client_cert` | Yes | PEM client certificate for mTLS |
| `client_key` | Yes | PEM private key matching `client_cert` |
| `client_ca` | No | PEM CA bundle to verify APIM's server cert; blank uses system CAs |
| `verify_ssl` | No, default `true` | |

## Local testing (before this is installed on soar8)

A mock backend exists at
`soar8/migration/mock-backend/mock_efficientip_ddi.py` (mirrored into
`soar8/soar-connectors/test/mock_efficientip_ddi.py`), port **8447**.
Unlike the other mocks, it requires mTLS **by default** (mirrors the real
APIM's requirement — there is no `--no-mtls` convenience in
`mock_start.sh`'s `ddi` target). Start it:

```bash
cd soar8/migration/mock-backend
./mock_start.sh ddi
```

Point the asset at `https://<mock-host>:8447`, `client_cert`/`client_key`
at `./certs/client.pem` / `./certs/client-key.pem` (same shared CA as the
other mocks — see that directory's README for the mTLS/cert-SAN gotchas
around `127.0.0.1` vs the real reachable address), and `client_id`/
`client_secret`/`ddi_username`/`ddi_password` at the mock's documented test
values (see `mock_efficientip_ddi.py`'s own docstring).

Verified locally 2026-08-24 via direct `curl --cert/--key` against the live
mock: mTLS-required handshake rejection, missing-Basic-Auth 401, full
3-layer auth success, and a 404 not-found path (pre-rewrite, against the
original invented `/ddi/*` paths — mock updated 2026-08-25 to the current
`/rest/ip_address_list` / `/rest/dns_rr_list` convention, not yet
re-verified end-to-end since).

**2026-08-25 status (superseded, kept for history):** installed live on
soar8 (app id 204, `app_version` 1.0.5). First real airgapped
`test_connectivity` run against the actual APIM failed with "not found" —
root cause at the time looked like the original `/ddi/health` path not
existing on the real backend (it was never more than a placeholder for the
mock). Endpoints rewritten to SOLIDserver's real REST convention; the user
then supplied several endpoint paths they've directly observed on the real
APIM, confirming `/rest/ip_address_list` and `/rest/ip_block_subnet_list`
structurally and ruling out a confirmed record-level DNS service (only
`dns_zone_list` seen — `get dns record` removed as a result).
`test_connectivity` now targets `ip_block_subnet_list` bare, the safest of
the confirmed-real endpoints.

**2026-08-25 status (current):** the endpoint-path work above was real but
wasn't the actual "not found" cause — `soarapps package build` was
silently dropping `requests`+deps and `beautifulsoup4`+`soupsieve` from
every rebuild since v1.0.3 (NFR-09 in `docs/dev-rules.md`), so the app
never imported on an offline box and SOAR never ran it. Fixed by
hand-patching wheels back in; per an explicit user decision, shipped as a
**clean reset**: new `appid` **`71a7abcc-75fa-4a8d-ae9d-23fb352869e4`**
(replaces `414f081c-...`) at **v1.0.0**, live on soar8 as **app id 205**
(204 is deprecated, pending deletion). Mock-reachability-from-soar8 (the
separate Ansible-side gap noted above) is now fixed. All 5 actions
confirmed reaching the mock and completing a real mTLS+auth+HTTP
round-trip via `POST /rest/action_run` against app 205 / asset
`efficientip_ddi mock` (id 19) — `test connectivity` and `get ip address`
verified against real matching seed data (genuine positive match);
`list subnets`/`get ip pool`/`list aliases` verified via a correctly-shaped
app-level "not found" for lookup values absent from the mock's seed data,
not yet a confirmed positive match. **Still open:** real airgapped retest
of this exact package — nothing here has touched the real APIM directly
since the endpoint-path reconciliation above, and `list_subnets`/
`get_ip_pool`/`list_aliases`'s field names remain inferred, not
independently vendor-confirmed (see their `raw_json` fallback).

**2026-08-25 status (v1.0.1, field-name fixes against real vendor docs):**
cross-referenced every action's output-field mapping against SOLIDserver's
own public REST method reference (`solidserverrest` project docs on
GitLab, v9.0.1a) instead of relying only on SDK-inferred field names, and
found 3 real bugs the mock had been silently masking (it was seeded with
the same wrong names, so everything "passed" locally):

- `get ip address`: hostname field is `name`, not `hostdev_name`
  (`hostdev_name` isn't a real `ip_address_list` field at all).
- `get ip pool`: address-range fields are `start_hostaddr`/`end_hostaddr`,
  not `pool_start_hostaddr`/`pool_end_hostaddr` (also not real fields).
- `list aliases`: the alias name field is `alias_name`, not `ip_alias`
  (`ip_alias` is a real field, but on `ip_address_list`, not
  `ip_alias_list`).

### 2026-08-27 — `ip_block_subnet_list`'s filter column is `subnet_name`, not `name`

Vendor-confirmed. `list subnets` had been sending `WHERE=name='<subnet>'`,
which does not filter: on this service `name` is only the **SELECT** column
(what the record comes back under), and the **filterable** column is
`subnet_name`. The two genuinely differ here, so the usual "the WHERE column
matches the SELECT column" convention does not hold — that assumption shipped
at 1.0.5 as an explicit, commented hypothesis and is now disproven. Fixed in
1.0.8 (classic twin 1.0.6).

Full set of filterable columns on this service:

| Column | Value form |
|---|---|
| `subnet_name` | the subnet's NAME -- a label, e.g. `CORP_LAN-USERS`, **not** its CIDR (user-confirmed 2026-08-29). Underscores and hyphens, no dots or slashes. To look a subnet up **by address** you need the range columns below, not this one. |
| `subnet_id` | internal id |
| `parent_subnet_name` | parent subnet's name |
| `parent_site_name` | site/space name |
| `start_ip_addr` / `end_ip_addr` | hex-encoded address |
| `start_hostaddr` / `end_hostaddr` | dotted IP |

> **Never send `WHERE` and `limit` in the same request.** Confirmed against the
> real appliance (2026-08-29): a filtered call carrying `limit` makes the
> backend abort the query and return HTTP 401, while the same call without
> `limit` succeeds. A `WHERE` already bounds the query. An *unfiltered* call
> still needs `limit` — with neither, the backend does an unbounded scan and
> times out. The connector enforces this in `_bounded_query()` and applies a
> caller's `limit` client-side on filtered calls.

Note this was undetectable locally in **both** directions: the mock matched on
`name`, so the wrong key passed, and it also falls through to returning every
record when a `WHERE` does not match — so even a probe asking "did it return a
row?" would have answered yes for either key. The mock now matches
`subnet_name` only and deliberately does not also accept `name`.

Also confirmed the same day: the response is a bare JSON array (which is what
`_ensure_list()` assumes), and `limit=1` returns exactly one record.

`ip_block_subnet_list` and `ip_alias_list` are still not independently
confirmed against this org's real APIM — the current public docs only
cover a differently-named `ip_subnet_list`, so `list subnets`'s
`start_address`/`end_address` mapping (`subnet_start_ip_addr`/
`subnet_end_ip_addr`) is still an analogy to the `subnet_*`-prefixed
fields nested inside `ip_address_list`/`ip_pool_list`, not a copy of
`ip_subnet_list`'s own (differently-prefixed) field names — it now also
carries a `raw_json` fallback for the same reason `get_ip_pool`/
`list_aliases` already did. Mock server (both copies) updated to match.
Connector `app_version` 1.0.0→1.0.1. **Still needs a real airgapped
retest** — nothing here has touched the real APIM.
