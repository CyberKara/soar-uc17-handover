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
3. **`X-DDI-Username` / `X-DDI-Password`** — forwarded by APIM to SOLIDserver's
   own backend auth. Each value is base64-encoded **independently**
   (`base64(ddi_username)`, `base64(ddi_password)`) — not combined like the Basic
   Auth layer, not folded into it.

Confirmed against the real APIM by curl (2026-08-25) and end-to-end on the real
appliance (2026-08-29).

## Endpoint convention

Flat service names under `/rest/`, `WHERE=<field>='<value>'` filtering, IPv4
addresses filtered as **hex**, not dotted-decimal — SOLIDserver's real classic
REST API convention. The user has directly observed `/rest/ip_address_list`,
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
| `get ip address` | investigate | `address` (req), `limit` (default 1) | `GET /rest/ip_address_list?WHERE=ip_addr='<hex>'` |
| `list subnets` | investigate | exactly one of `subnet_name` / `subnet_id` / `parent_subnet_name` / `site_name`; `limit` (default 1) | `GET /rest/ip_block_subnet_list` |
| `get ip pool` | investigate | `name` (req), `limit` (default 1) | `GET /rest/ip_pool_list?WHERE=pool_name='<name>'` |
| `list aliases` | investigate | `ip_id` (req, from `get ip address`), `limit` (default 1) | `GET /rest/ip_alias_list/ip_id/{ip_id}` |

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
| `start_hostaddr` / `end_hostaddr` | dotted IP (not exposed) |

The caller-facing parameter name is not always the `WHERE` column: `site_name`
filters as `parent_site_name`, and `subnet_name` filters on `subnet_name` while
the record comes back under `name`. That mapping lives in
`LIST_SUBNETS_FILTERS` in `efficientip_ddi_consts.py`.

## Asset configuration

| Field | Required | Type | Notes |
|---|---|---|---|
| `base_url` | Yes | string | APIM gateway base URL, e.g. `https://apim.internal.example` |
| `client_id` | Yes | string | APIM app client ID (Basic Auth username) |
| `client_secret` | Yes | password | APIM app client secret (Basic Auth password) |
| `ddi_username` | Yes | string | SOLIDserver backend username, sent via `X-DDI-Username` |
| `ddi_password` | Yes | password | SOLIDserver backend password, sent via `X-DDI-Password` |
| `client_cert` | Yes | string | PEM client certificate for mTLS |
| `client_key` | Yes | password | PEM private key matching `client_cert` |
| `client_ca` | No | string | PEM CA bundle to verify APIM's server cert; blank uses system CAs |
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
**Values in a `WHERE` clause must be single-quoted**; `_bounded_query()` always
quotes them.

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
unchanged, moments later. The connector holds no per-call state — headers are
recomputed from config on every call, there is no session, cookie or token, certs
are written and deleted per call — so identical inputs produce identical bytes.
That is what makes retrying meaningful here rather than re-asking a question the
server already answered.

- Applies to **every action, including `test connectivity`**.
- `401` only. `400` and `403` are deterministic and are never retried.
- Linear backoff between attempts, not immediate re-fire: rapid repeated auth
  failures are what trip gateway lockout and quota policies, and if the cause is
  an auth-cache TTL gap, the wait is the part that helps.
- **Never silent.** Every attempt is logged with its peer address, and a call
  that only succeeded on a later attempt reports `Succeeded on attempt N of M` in
  the action result. The intermittency is still an open investigation, so the
  retry must not bury the evidence for it.

Retry is a mitigation, not a diagnosis. It is designed so that running it
produces *better* evidence than not running it: if attempt 1 fails at one peer
address and attempt 2 succeeds at another, that single pair of log lines
identifies a load-balanced node with inconsistent trust.

### Reading the diagnostic log

Everything is written through `save_progress`, so it renders in both the App
Debugger panel and the container action result — the only channel that reaches an
operator with no shell. Secrets never print: auth headers, cookies and PEM
material are replaced by a length and a SHA-256 prefix.

| Line | Answers |
|---|---|
| `idle: Ns since last successful call` | Separates the three surviving 401 theories: an auth-cache expiry fails after a **gap**, a quota policy fails under a **burst** (the opposite), a bad load-balanced node correlates with neither. |
| `retry plan: up to N attempt(s) ...` | What this asset is configured to do. |
| `attempt N/M: HTTP s from peer <ip:port>` | **Which node served this call** — the decisive line when a 401 follows one address while 200s follow another. |
| `dns: <host> -> <addrs>` | Does the APIM name resolve to more than one node? |
| `sent:` / `sent headers` | The request as `requests` encoded it, read off the PreparedRequest — not our intent. |
| `response headers` | `WWW-Authenticate`, quota counters, gateway request-ids, cache markers. |
| `received body` | Logged on success **and** failure — an intermittent fault is only readable by diffing a good call against a bad one. |
| `parse: <branch>` | Which response branch was taken; an empty 204 and an empty JSON array both end as "no records". |

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

**Unit/regression suite** — 41 tests, pinning defects that previously passed
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
- `get ip pool` — range fields are `start_hostaddr`/`end_hostaddr`, not
  `pool_start_hostaddr`/`pool_end_hostaddr`.
- `list aliases` — the alias name field is `alias_name`, not `ip_alias`
  (`ip_alias` is real, but on `ip_address_list`, not `ip_alias_list`).

A fourth followed the same shape: on `ip_block_subnet_list`, `name` is only the
**SELECT** column and the **filterable** column is `subnet_name`. The usual "the
`WHERE` column matches the `SELECT` column" convention does not hold on this
service. This was undetectable locally in both directions — the mock matched on
`name`, and it also fell through to returning every record when a `WHERE` did not
match, so even a probe asking "did it return a row?" would have said yes for
either key. The mock now matches `subnet_name` only and deliberately does not
also accept `name`.

**Still open:**

- `ip_alias_list`'s `alias_name` and `get_ip_pool`'s identity field remain
  **analogy-based**, not independently confirmed against this org's real APIM —
  `raw_json` covers them meanwhile. A real-appliance retest is still owed.
- `list subnets`' `subnet_start_ip_addr`/`subnet_end_ip_addr` mapping is an
  analogy to the `subnet_*`-prefixed fields nested inside
  `ip_address_list`/`ip_pool_list`; the current public docs only cover a
  differently-named `ip_subnet_list`.
- **Range filters on `list subnets`** — designed, deliberately not built, behind
  three read-only appliance probes written out in the UC17 plan.
- Whether the APIM proxies `/rest/*` verbatim or under its own prefix (fold it
  into `base_url` if so).
- **IPv6 filtering** — hex-encoding is only vendor-confirmed for IPv4.
- A `list subnets` 401 seen on the real appliance (2026-08-29) is **unexplained**.
  Four causes have now been asserted for it and none survived; do not adopt a
  fifth without evidence. Since 2026-09-01 it is *mitigated* by the 401 retry
  above and instrumented by the idle-gap line — but mitigated is not explained,
  and the retry is deliberately noisy so the evidence keeps accumulating.
  Percent-encoding of the `WHERE` clause and the `limit` parameter are both
  ruled out, and the `403 = bad request` mapping rules out every remaining
  query-shaped explanation.
