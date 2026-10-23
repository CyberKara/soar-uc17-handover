# efficientip_ddi — EfficientIP SOLIDserver via APIM

Splunk SOAR connector for IP address and subnet lookups in an EfficientIP SOLIDserver DDI
(DNS/DHCP/IPAM) backend, reached through an APIM gateway rather than called directly. Used by the
`efficientip_ddi_enrich` and `efficientip_ddi_action_test` playbooks (UC17, `soar-playbooks`).

**Classic `BaseConnector` style**, the permanent FR-01 exemption in `docs/dev-rules.md`: SOAR's App
Debugger (the asset's view page) cannot run SDK-app actions, and on the airgapped appliance it is
the operator's only hands-on way to run one.

The actions do **raw pass-through**: `action_result.add_data(record)` forwards every key SOLIDserver
returns, one data item per record.

______________________________________________________________________

## Auth model (3 layers, every request)

1. **mTLS** — `client_cert` + `client_key` (+ optional `client_ca`) presented to the APIM. SOAR's
   config textareas mangle PEM whitespace, so the values are re-wrapped into temp files per call
   (as `cyberark_ccp` does).
2. **`Authorization: Basic base64(client_id:client_secret)`** — the APIM app credential, sent on
   every call; no token exchange.
3. **`X-IPM-Username` / `X-IPM-Password`** — forwarded by the APIM to SOLIDserver, each value
   base64-encoded on its own. The names matter: sent as `X-DDI-*`, every call on the target
   appliance answers HTTP 401 `"The specified document is not valid JSON data"`. If another APIM
   expects other names, they are `DDI_USERNAME_HEADER` / `DDI_PASSWORD_HEADER` in
   `efficientip_ddi_consts.py`. The asset fields keep their `ddi_*` names.

## Endpoints and filtering

Flat service names under `/rest/`, filtered with `WHERE=<column>='<value>'`. The APIM may publish
them under a path prefix: put everything before `/rest` in `base_url`, and the connector appends
`/rest/<service>`.

- **Every list call carries a bound.** With neither `WHERE` nor `limit` the backend scans unbounded
  and times out. `_bounded_query()` always sends `limit` and adds `WHERE` when filtering;
  `WHERE` and `limit` together are fine.
- **`WHERE` is SQL.** A string value must be single-quoted (unquoted, `ip_addr=<hex>` returns 400
  `[{"errno": "50028", "sql_error": "7"}]`); an integer needs no quotes (`ip_id=1697182`). The
  handlers quote every value, `subnet_id` included. Percent-encoding the `=` makes no difference.
- **Addresses** filter two ways: `hostaddr` (dotted, used here) or `ip_addr` (zero-padded hex).
  `host_addr` is not a column (`sql_error` 7).
- A `204` means the clause parsed and matched nothing; a bad column or syntax returns 400/403. A
  column missing from a response says nothing about whether it filters (`ip_block_subnet_list`
  filters on `subnet_name` but returns `name`).
- Two services only: `ip_address_list` and `ip_block_subnet_list`. There is no DNS record action:
  no record-level DNS service is confirmed on the APIM.

## Actions

| Action | Type | Parameters | Request |
|---|---|---|---|
| `test connectivity` | test | — | `GET /rest/ip_block_subnet_list?limit=1` |
| `get ip address` | investigate | `address` (required, IPv4/IPv6), `limit` (default 1) | `GET /rest/ip_address_list?WHERE=hostaddr='<dotted ip>'` |
| `list subnets` | investigate | at most one of `subnet_name` / `subnet_id` / `parent_subnet_name` / `site_name`; `limit` (default 1) | `GET /rest/ip_block_subnet_list` |

Not found (HTTP 204) fails the action with `No IP address record found in SOLIDserver for <ip>`
(plus a caveat for IPv6) or `No subnet found in SOLIDserver[ for <column>='<value>']`. Each record
gets `description` (from `description=` in its class parameters); `get ip address` records also get
`address`, the address asked.

**`list subnets` filters.** `subnet_name` is the subnet's **name, a label** such as
`CORP_LAN-USERS`, not its CIDR. No filter lists subnets unfiltered, bounded by `limit`; two or more
are refused, because `AND` in `WHERE` is unconfirmed. Parameter → column (`LIST_SUBNETS_FILTERS`):
`subnet_name` → `subnet_name`, `subnet_id` → `subnet_id`, `parent_subnet_name` →
`parent_subnet_name`, `site_name` → `parent_site_name`. Also filterable but not exposed:
`start_ip_addr`/`end_ip_addr` (hex) and `start_hostaddr`/`end_hostaddr` (dotted). A range filter
must compare the hex columns: dotted strings compare as text (`"9.0.0.1" > "10.0.0.1"`). It waits
on three appliance probes listed in the UC17 plan's Known limitations.

## Asset configuration

| Field | Required | Type | Notes |
|---|---|---|---|
| `base_url` | Yes | string | APIM base URL **including any path prefix before `/rest`** |
| `client_id` | Yes | string | APIM app client ID (Basic auth username) |
| `client_secret` | Yes | password | APIM app client secret (Basic auth password) |
| `ddi_username` | Yes | string | SOLIDserver username, sent as `X-IPM-Username` |
| `ddi_password` | Yes | password | SOLIDserver password, sent as `X-IPM-Password` |
| `client_cert` | Yes | string | PEM client certificate for mTLS |
| `client_key` | Yes | password | PEM private key matching `client_cert` |
| `client_ca` | No | string | PEM CA bundle for the APIM's server certificate. Blank uses `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` when set, else the `requests` CA bundle — never the OS trust store |
| `verify_ssl` | No (`true`) | boolean | |
| `debug_logging` | No (`false`) | boolean | See Debug logging |

`client_cert` and `client_ca` are `string`, not `password`: certificates are public (NFR-04), and
a password field read back over REST and written again corrupts it.

> **Across an air gap, re-enter every credential by hand.** Password-type values do not survive a
> handover export as usable values; a pasted trailing newline is stripped.

## Response codes

| Code | Meaning on this API | Connector |
|---|---|---|
| `200` | success | body parsed as JSON |
| `204` | no matching record | empty result; the action fails as not found |
| `400` | **bad request** from SOLIDserver (`errno`/`sql_error` in the body) | `errno` in the message |
| `401` | unauthorized, the **only** auth code | the message names the cause, see below |
| `403` | **bad request** from the APIM, *not* forbidden | the message says so |

Read as standard HTTP, a 403 sends an operator hunting credentials; on this API it means the request
was wrong (filter column, `WHERE` syntax, `limit`). No request is retried: each is sent once.

### 401

The 401 message reads the gateway's `X-Backside-Transport` header:

- all `OK`: the gateway reached SOLIDserver, which rejected the request → check
  `ddi_username`/`ddi_password`.
- `FAIL`: the APIM's backend leg failed and the gateway answered 401 itself → check the mTLS client
  certificate (`client_cert`/`client_key`) first, then give the APIM administrator the
  `APIm-Debug-Trans-Id` the message quotes. A `FAIL FAIL` 401 on about one call in three stopped
  once the appliance used a new client certificate.
- no header → check `client_id`/`client_secret` and the client certificate.

### Debug logging

`debug_logging` adds one `save_progress` line per HTTP call, shown in the App Debugger and the
container's action result:

```
GET https://<apim>/<prefix>/rest/ip_address_list?limit=1&WHERE=hostaddr%3D%2710.1.2.3%27 -> HTTP 401  X-Backside-Transport=FAIL FAIL  APIm-Debug-Trans-Id=<id>  body: {"message": "..."}
```

The URL carries only `limit`/`WHERE`; credentials travel in headers and are never printed. The body
is cut at 500 characters.

## Building and installing

```bash
tools/build.sh efficientip_ddi          # -> dist/efficientip_ddi-v<version>.tgz
tools/install_app.sh dist/efficientip_ddi-v<version>.tgz
```

Build on the **connected** host, never on the airgapped target. The app bundles no wheels
(`requests`/`urllib3` come from the SOAR runtime), so packaging is a clean tar honouring
`exclude_files.txt`. SOAR refuses an `app_version` at or below the live one: bump above
`GET /rest/app`, not just above the repo.

## Testing

- **Unit suite** (53 tests; `tests/conftest.py` stubs the `phantom.*` modules):
  `uvx --with requests pytest connectors/efficientip_ddi/tests`.
- **Mock** — `test/mock_efficientip_ddi.py`, port **8447**, mTLS required like the real APIM. It
  reads the `X-IPM-*` names and filters `ip_address_list` on `hostaddr` only, so a connector that
  regressed to `X-DDI-*` / `host_addr` fails against it. Point the asset at
  `https://<mock-host>:8447` (never `localhost`: it runs on the ansible controller) with the mock's
  certificates and the test credentials in its docstring.
- **End-to-end** — `soar-playbooks`' `tools/uc17_verify.sh`: mock seed, one SOAR action dispatch,
  the enrich playbook on a fresh container, the action-test playbook.
- **On the appliance** — `tools/uc17_airgapped_probe.sh` (read-only GETs) answers what only the
  real SOLIDserver/APIM can.

## Field provenance

- **`get ip address`**: the target appliance returns 11 fields (from a real result): `ip_id`,
  `ip_addr`, `subnet_name`, `site_name`, `name` (the hostname; `hostdev_name` is not an
  `ip_address_list` field), `mac_addr`, `ip_class_name`, `ip_class_parameters`,
  `parent_subnet_name`, `site_class_name`, `ip_alias`. The SOLIDserverRest method reference
  ([`docs/ip_address_list.md`](https://github.com/gregocgt/SOLIDserverRest/blob/master/docs/ip_address_list.md),
  a community fork) lists about 70 fields, these among them. The method takes no field selection,
  so the APIM most likely fixes the subset (inferred): fields such as `pool_name` or `last_seen`
  would have to be exposed there.
- **`list subnets`**: `name` is the select column, `subnet_name` the filter column.
  `subnet_start_ip_addr`/`subnet_end_ip_addr` follow the `subnet_*` fields of `ip_address_list` by
  analogy; the public docs only cover a differently named `ip_subnet_list`.

## Open questions

- **IPv6:** `hostaddr` is confirmed for IPv4 only. The connector compresses IPv6
  (`2001:0db8::0001` → `2001:db8::1`); whether the appliance stores that form is unverified.
- **Other 401s:** still unseen: what a wrong credential returns (`OK OK` from the backend, or no
  header from the gateway).
- **Range filters on `list subnets`:** see above.
