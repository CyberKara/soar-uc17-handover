# EfficientIP DDI Enrichment (UC17) — Implementation Plan

Current design. How it got here (every dated change, test and investigation): `uc17_history.md`,
not shipped in the handover. Open work: the Splunk project's `docs/next-steps.md` (not shipped).

## Scope

- Every IP address on a new artifact of a labelled container is looked up in EfficientIP
  SOLIDserver's IPAM, reached through the organisation's APIM gateway, and the result is written to
  the container as one note. Each address is looked up once per container.
- A diagnostic playbook lets an operator run the connector's actions through SOAR's real dispatch.
- Read-only: nothing is written to IPAM. Out of scope: DNS records (no record-level DNS service is
  confirmed on the APIM), IP pools and aliases (removed), lookups by address range (not built, see
  Known limitations).

## Architecture

| Playbook | Type | Label | Active | Role |
|---|---|---|---|---|
| `efficientip_ddi_enrich` | automation, `artifact_created` | `events` | **yes** | Looks up the IPs of new artifacts, writes the enrichment note |

**Connector `efficientip_ddi`** (classic `BaseConnector`; the permanent FR-01 exemption, because
the App Debugger cannot run SDK-app actions and it is the airgapped operator's only hands-on test).
Actions: `test connectivity`, `get ip address`, `list subnets`. Every call is a bodiless GET with
three auth layers:

1. mTLS to the APIM: `client_cert` + `client_key` (+ optional `client_ca`).
2. `Authorization: Basic base64(client_id:client_secret)`, the APIM app credential.
3. `X-IPM-Username` / `X-IPM-Password`, each value base64-encoded on its own, which the APIM
   forwards to SOLIDserver.

No CF, no custom list, no Timer asset. The playbooks ship pointed at the asset `efficientip_ddi mock`.

## Playbooks

### `efficientip_ddi_enrich`

start → `collect_ips` (code) → `get_ip_address` (action) → `finalize` (code) → end. No inputs, no
outputs.

- **`collect_ips`:** `phantom.collect_from_contains(contains=["ip", "ipv6"])`, so every value of an
  artifact field SOAR types as ip/ipv6 (the CEF registry plus each artifact's own `cef_types`), from
  the artifacts in the run's scope (the new ones on a triggered run). A field not typed ip is
  ignored even when it holds an address. Values are split on spaces, commas and semicolons; what
  does not parse as an address is dropped; IPv6 is compressed. It then reads the container's notes
  titled `EfficientIP DDI Enrichment*` over REST and drops every address whose row there reads
  `found…` or `not found`; a `failed` or `skipped` one is looked up again. Nothing left: the run
  stops with a debug line and writes no note. At most 50 addresses per run; the rest are
  `skipped (over 50 addresses, next run)`.
- **`get_ip_address`:** its Custom Code rebuilds the parameters as one set per address with
  `limit` 5 (an address can sit in several spaces): one app_run, one action result per address.
- **`finalize`** writes the note `EfficientIP DDI Enrichment` (markdown):
  - `**Lookup:** N address(es): x found, y not found, z failed[, k skipped]`;
  - a table, one row per IPAM record: IP, Hostname (`name`), Aliases (`ip_alias`), Subnet
    (`subnet_name`), Parent subnet (`parent_subnet_name`), Lookup;
  - `### Per-IP detail`, one block per record: the bold IP (with its space when it has several
    records), then space (`site_name`), space class (`site_class_name`), MAC (`mac_addr`), class
    (`ip_class_name`), description, IP (hex) (`ip_addr`), class parameters
    (`ip_class_parameters`), `-` when empty. Every field the appliance returns is in the note except
    `ip_id`.
  - Lookup values: `found`, `found (5+ records, more may exist)`, `not found` (the connector's
    message starts `No IP address record found`), `failed` (its block gives the message, first 300
    characters), `failed (not dispatched)` (no action result: SOAR refused the action; the reason
    is in the playbook run), `skipped (…)`. An IPv6 `not found` block says it is not proof of
    absence.
  - Above 19,000 characters the note splits into `EfficientIP DDI Enrichment (k/N)` parts, never
    inside a block, with the table header repeated (the appliance cuts a note at about 22,000).

## Data model and API facts

**Services** (flat names under `/rest/`; the asset's `base_url` holds everything before `/rest`,
including an APIM prefix):

| Action | Request |
|---|---|
| `test connectivity` | `GET /rest/ip_block_subnet_list?limit=1` |
| `get ip address` | `GET /rest/ip_address_list?limit=<n>&WHERE=hostaddr='<dotted ip>'` |
| `list subnets` | `GET /rest/ip_block_subnet_list?limit=<n>[&WHERE=<column>='<value>']` |

- Every list call carries `limit` (default 1); with neither `WHERE` nor `limit` the backend scans
  unbounded and times out. `WHERE` and `limit` together are fine.
- `WHERE` is SQL: a string value must be single-quoted (unquoted it returns 400,
  `[{"errno": "50028", "sql_error": "7"}]`); an integer needs no quotes (`ip_id=1697182`). The
  connector quotes every value, `subnet_id` included.
- `hostaddr` takes the dotted address, `ip_addr` the zero-padded hex; `host_addr` is not a column
  (`sql_error` 7).
- `list subnets` filters, at most one per call (none = a bare list bounded by `limit`):
  `subnet_name` → `subnet_name`, `subnet_id` → `subnet_id`, `parent_subnet_name` →
  `parent_subnet_name`, `site_name` → `parent_site_name`. The record comes back with its name
  under `name`. A subnet name is a label such as `CORP_LAN-USERS`, not a CIDR.

**Response codes:**

| Code | Meaning on this API | Connector |
|---|---|---|
| 200 | success | parses JSON |
| 204 | no matching record | `No IP address record found…` / `No subnet found…`, action failed |
| 400 | bad request from SOLIDserver (body has `errno`) | `errno` in the message |
| 401 | unauthorized, the only auth code | the message names the cause, see below |
| 403 | bad request from the APIM, **not** forbidden | the message says so |

No request is retried. **401:** `X-Backside-Transport` `OK OK` is SOLIDserver's own credential
verdict (check `ddi_username`/`ddi_password`). `FAIL FAIL` means the APIM's backend leg failed and
the gateway made up the 401: check the mTLS client certificate first, then give the APIM
administrator the `APIm-Debug-Trans-Id` the message quotes. No header: check
`client_id`/`client_secret` and the certificate.

**`get ip address` records** (the 11 fields the appliance returns): `ip_id`, `ip_addr`,
`subnet_name`, `site_name`, `name`, `mac_addr`, `ip_class_name`, `ip_class_parameters`,
`parent_subnet_name`, `site_class_name`, `ip_alias`. The connector passes each record through
as-is, one data item per record, and adds `address` (the address asked) and `description` (from
`ip_class_parameters`' `description=`). The APIM fixes this field set; the connector cannot ask for
more.

**`list subnets` records** (declared, not confirmed on the appliance): `subnet_id`, `name`,
`parent_subnet_name`, `site_name`, `tree_path`, `subnet_start_ip_addr`, `subnet_end_ip_addr`,
`subnet_size`, `subnet_class_name`, `subnet_class_parameters`, plus `description`.

## Setup Guide

1. **Connector:** Apps > Install App with the `efficientip_ddi` package. Over an existing install it
   upgrades in place and the asset keeps its credentials.
2. **Asset:** the playbook ships pointed at `efficientip_ddi mock`. Keep that name, or re-point its
   action block to your asset in the VPE and save.

   | Field | Value |
   |---|---|
   | `base_url` | APIM URL including any path prefix before `/rest` |
   | `client_id` / `client_secret` | APIM app credential (Basic auth) |
   | `ddi_username` / `ddi_password` | SOLIDserver account, sent as `X-IPM-*` |
   | `client_cert` / `client_key` | PEM client certificate and key for mTLS |
   | `client_ca` | optional PEM CA bundle; blank uses the `requests` CA bundle, not the OS store |
   | `verify_ssl` | default `true` |
   | `debug_logging` | off; on adds one progress line per call (URL without credentials, status, `X-Backside-Transport`, `APIm-Debug-Trans-Id`, body start) |

   Enter every credential by hand: password fields do not cross the air gap as usable values. Then
   use the asset's Test Connectivity button.
3. **Import** `efficientip_ddi_enrich`.
4. **`efficientip_ddi_enrich`:** set its label(s) to the label of the containers to enrich
   (`events` as shipped), leave **Run As** at the default (the automation user, which reads the
   container's notes over REST) and **activate** it. A re-import replaces the playbook, so redo this
   step after every re-import.

## Verification

- **Lab:** the mock `mock_efficientip_ddi.py` (port 8447, mTLS required) serves `10.20.30.40`
  (`host01.corp.local`, alias `fin-ws01.corp.local`) and `10.20.30.99`; `192.0.2.1` is not found.
  `tools/uc17_verify.sh` (`soar-playbooks`) checks the mock, one `get ip address` through SOAR, the
  enrich playbook on a fresh `events` container (expect one note: `.40` found, `192.0.2.1` not
  found, `deviceCustomString1` ignored).
- **Target:** the asset's Test Connectivity button, then on a test container with the enrich
  label: one artifact with a known address in `sourceAddress` and an
  unused one in `destinationAddress` (expect one note, `found` and `not found`), then a second
  artifact with the same two (expect no new note).
- **Diagnostics:** `uc17_airgapped_probe.sh` (read-only GETs, credentials from the environment)
  answers the API-shape questions only the appliance can.

## Known limitations

- **IPv6:** `hostaddr` is confirmed for IPv4 only, and whether SOLIDserver stores the compressed or
  the expanded form is unknown; an IPv6 `not found` is not proof of absence.
- **Not exercised on the mock:** a failed lookup row and the 5-record cap; note splitting is tested
  offline only. The demo's expired prompt is untested.
- **Untyped fields:** an address in a field SOAR does not type as ip/ipv6 is not looked up.
- **`list subnets` ranges are not built.** Looking a subnet up by address needs the range columns
  (`start_ip_addr`/`end_ip_addr` hex, `start_hostaddr`/`end_hostaddr` dotted), and three read-only
  appliance probes come first:
  1. `AND` in `WHERE`:
     `GET /rest/ip_block_subnet_list?WHERE=parent_site_name='<site>' AND parent_subnet_name='<parent>'&limit=5`
     (narrowed rows = composition works; 400/403 or an ignored condition = one filter stays the rule);
  2. comparison operators: `GET /rest/ip_block_subnet_list?WHERE=start_hostaddr>='10.20.0.0'&limit=5`;
  3. representation: probe 2 again on `start_ip_addr` with hex (`0a140000`).

  Ranges must compare the hex columns: dotted strings compare as text (`"9.0.0.1" > "10.0.0.1"`).
  Once answered: extend `LIST_SUBNETS_FILTERS`, relax `_select_optional_filter()` to the confirmed
  rule, and teach the mock's `WHERE` parser the new grammar.
- `list subnets`' `subnet_start_ip_addr`/`subnet_end_ip_addr` names are an analogy to the
  `subnet_*` fields of `ip_address_list`, not vendor-confirmed.
