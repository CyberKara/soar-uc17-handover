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
| `list subnets` | investigate | `name` | `subnet_id`, `subnet_name`, `parent_subnet`, `space`, `start_address`, `end_address`, `size`, `ddi_class`, `description` (via `GET /rest/ip_block_subnet_list?WHERE=subnet_name='<name>'`) |
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

**2026-08-25 status:** installed live on soar8 (app id 204, `app_version`
1.0.5). First real airgapped `test_connectivity` run against the actual
APIM failed with "not found" — root cause: the original `/ddi/health` path
doesn't exist on the real backend, it was never more than a placeholder
for the mock. Endpoints rewritten to SOLIDserver's real REST convention;
the user then supplied several endpoint paths they've directly observed on
the real APIM, confirming `/rest/ip_address_list` and
`/rest/ip_block_subnet_list` structurally and ruling out a confirmed
record-level DNS service (only `dns_zone_list` seen — `get dns record`
removed as a result). `test_connectivity` now targets
`ip_block_subnet_list` bare, the safest of the confirmed-real endpoints.
**Still not fully verified:** whether `get_ip_address`'s `WHERE=` filter
actually works on the real APIM (vs. the path-parameter style seen on
`ip_alias_list`), and whether `/rest/*` is proxied verbatim or under a
prefix. Re-test against the real airgapped system.
