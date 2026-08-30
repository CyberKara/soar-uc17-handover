"""efficientip_ddi — Splunk SOAR SDK connector for EfficientIP SOLIDserver via APIM.

Analyst-driven IP/DNS lookup enrichment against an EfficientIP SOLIDserver
DDI (DNS/DHCP/IPAM) backend that sits behind an API gateway (APIM), not
called directly. Three auth layers stack on every request:

  1. mTLS — client cert/key (+ optional CA) presented to APIM at the TLS
     layer, same PEM-normalize-to-tempfile pattern as the classic
     `cyberark_ccp` connector.
  2. `Authorization: Basic base64(client_id:client_secret)` — the APIM-level
     app credential. No OAuth token exchange — this header goes on every
     call directly, nothing to cache or refresh.
  3. `X-DDI-Username` / `X-DDI-Password` headers — forwarded by APIM to
     SOLIDserver's own backend auth. Each value is base64-encoded
     independently, not combined like the Basic-auth layer — vendor-confirmed
     real-APIM behavior, not a guess.

Built and tested against `soar8/migration/mock-backend/mock_efficientip_ddi.py`
(:8447, mirrored into `soar8/soar-connectors/test/`), which matches the same
per-value base64 encoding for the DDI header layer.

Endpoints follow SOLIDserver's classic REST API convention — flat service
names under `/rest/{service}`, filtered via a `WHERE=<field>='<value>'` query
param. `/rest/ip_address_list`, `/rest/ip_alias_list/ip_id/{ip_id}`,
`/rest/dns_zone_list`, `/rest/ip_pool_list`, and `/rest/ip_block_subnet_list`
are vendor-confirmed to exist on the real APIM. There is no record-level DNS
service — only zone-level `dns_zone_list` — so `get dns record` is not
implemented; a prior `dns_rr_list`-based attempt was this project's own
inference from public docs and was never seen on the real system. Rebuild
that action only once a real record-level endpoint is identified.
`test_connectivity` calls `/rest/ip_block_subnet_list` bare (no params) since
that's the one confirmed-real endpoint that needs no filter.

`ip_block_subnet_list`'s filterable columns are vendor-confirmed:
`subnet_name`, `subnet_id`, `parent_subnet_name`, `parent_site_name`,
`start_ip_addr`/`end_ip_addr` (hex) and `start_hostaddr`/`end_hostaddr` (dotted
IP). Note the filter column is **`subnet_name`** while the *returned* record
carries its name under **`name`** — the two genuinely differ on this service,
so the usual "WHERE column matches SELECT column" assumption is wrong here and
filtering on `name=` does not work.

`WHERE` is a real, **required** parameter on `ip_address_list` — not optional,
and not a guess — which is why filtering here uses query-string `WHERE=` and
not `ip_alias_list`'s path-parameter style (that's a "list children of a known
ip_id" sub-resource shortcut, not the general list-filtering convention).
`ip_pool_list`/`ip_block_subnet_list` take `WHERE` as *optional*, matching why
`test_connectivity` can call the latter without a `WHERE` clause (it still
sends `limit=1` — see the `limit` policy below). Output field names
(`subnet_name`, `site_name`, `mac_addr`, `ip_class_name`,
`ip_class_parameters`, `ip_id`, `name`) are the vendor's real field names
for `ip_address_list` — confirmed against SOLIDserver's own public REST
method reference (`solidserverrest` project docs, v9.0.1a), not just
inferred by SDK analogy. That cross-check caught 3 real bugs that had been
silently masked because the mock used the same wrong names:
`get ip address`'s hostname field is `name`, not `hostdev_name` (not a real
field at all); `get ip pool`'s address-range fields are `start_hostaddr`/
`end_hostaddr`, not `pool_start_hostaddr`/`pool_end_hostaddr`; `list
aliases`' own name field is `alias_name`, not `ip_alias` (`ip_alias` is a
real field, but on `ip_address_list`, not `ip_alias_list`). `description` is
extracted from the `ip_class_parameters` custom-attribute blob, not a
dedicated field. **`ip_block_subnet_list`'s and `ip_alias_list`'s own field
sets are still not independently confirmed against this org's real APIM**
— `ip_block_subnet_list` is this org's confirmed-real endpoint name but
doesn't match any method in the current public docs (which only document
`ip_subnet_list`, likely a newer/renamed API generation), so its field
names are inferred by analogy to the `subnet_*`-prefixed fields nested
inside `ip_address_list`/`ip_pool_list` rather than copied from
`ip_subnet_list`'s own (differently-prefixed) field set; `ip_alias_list`'s
non-`alias_name` fields are still analogy-based too. All three
lower-confidence actions carry a `raw_json` fallback field; check it if a
named field comes back empty.

**`limit` policy: every list call is bounded, and the bound is an action
parameter (`limit`, default 1).** On the real APIM an
unbounded call (no `WHERE`, no `limit`) times out server-side — the backend
does a full scan/dump. Adding `limit` alone (no `WHERE`) works fine, and a
`WHERE`-filtered single-record lookup also works. Relying on `WHERE` alone
to stay narrow isn't safe either: a filter style other than the exact-match
ones used here (e.g. a range filter instead of an exact `ip_addr=`/`name=`
match) could legitimately return hundreds of rows. So a `limit` always goes
on the wire — but it is the analyst's/playbook's to raise, not a hardcoded
1. `test_connectivity` keeps a fixed `limit=1` since it has no parameter
surface and only needs to prove reachability.

**Every record-returning action emits one output row per record**
(`list[...]` return → SOAR flattens to `action_result.data.*`), so raising
`limit` actually widens the result instead of being silently discarded. At
the default `limit=1` this is behaviorally identical to returning a single
row. Truncating to `records[0]` while advertising `data.*` was a real bug:
an IP with two DNS aliases reported one, with no indication more existed.

`ddi_user`/`ddi_pwd` appearing in the vendor's endpoint-parameter docs for
every service means DDI auth context is required, already satisfied by the
`X-DDI-Username`/`X-DDI-Password` headers — not literal query parameters
this connector needs to add. IPv6 filtering is unconfirmed (hex-encoding is
only vendor-confirmed for IPv4).
"""

import base64
import ipaddress
import json
import os
import tempfile
from urllib.parse import parse_qsl

import requests
from soar_sdk.abstract import SOARClient
from soar_sdk.action_results import ActionOutput, OutputField
from soar_sdk.app import App
from soar_sdk.asset import AssetField, BaseAsset
from soar_sdk.compat import PythonVersion
from soar_sdk.exceptions import ActionFailure
from soar_sdk.logging import getLogger
from soar_sdk.params import Param, Params

logger = getLogger()

DEFAULT_LIMIT = 1

LIMIT_DESCRIPTION = (
    "Maximum number of records to return (default 1). Must be a positive whole "
    "number -- an unbounded call times out server-side on the real APIM, so a "
    "limit always goes on the wire."
)

PEM_BLOCK_TYPES = [
    ("-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"),
    ("-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"),  # gitleaks:allow -- PEM header marker, not a key
    ("-----BEGIN RSA PRIVATE KEY-----", "-----END RSA PRIVATE KEY-----"),
    ("-----BEGIN EC PRIVATE KEY-----", "-----END EC PRIVATE KEY-----"),
]


class Asset(BaseAsset):
    base_url: str = AssetField(
        description="Base URL of the APIM gateway fronting SOLIDserver, e.g. https://apim.internal.example",
        required=True,
    )
    client_id: str = AssetField(
        description="APIM app client ID (sent as the Basic Auth username).",
        required=True,
    )
    client_secret: str = AssetField(
        description="APIM app client secret (sent as the Basic Auth password).",
        required=True,
        sensitive=True,
    )
    ddi_username: str = AssetField(
        description="SOLIDserver backend username, forwarded through APIM via X-DDI-Username.",
        required=True,
    )
    ddi_password: str = AssetField(
        description="SOLIDserver backend password, forwarded through APIM via X-DDI-Password.",
        required=True,
        sensitive=True,
    )
    client_cert: str = AssetField(
        description="PEM client certificate presented to APIM for mTLS.",
        required=True,
        sensitive=True,
    )
    client_key: str = AssetField(
        description="PEM private key matching client_cert.",
        required=True,
        sensitive=True,
    )
    client_ca: str = AssetField(
        description="PEM CA bundle to verify APIM's server certificate (optional — leave blank to use system CAs).",
        required=False,
        default="",
        sensitive=True,
    )
    verify_ssl: bool = AssetField(
        description="Verify APIM's TLS server certificate.",
        default=True,
    )


app = App(
    name="efficientip_ddi",
    app_type="ddi",
    logo="logo.svg",
    logo_dark="logo_dark.svg",
    product_vendor="EfficientIP",
    product_name="SOLIDserver",
    publisher="Ted",
    # SOAR correlates an installed app by this GUID and carries GUI state across
    # versions of the same one, so changing it makes a target instance treat the
    # app as new rather than as an upgrade of what it remembers. Playbooks bind
    # to this value through their action nodes' connectorId -- change it and
    # every playbook referencing the app must be rebound to match.
    appid="b847c7d1-ee21-4af8-a92c-a91f5eb4b00d",
    python_version=PythonVersion.PY_3_13,
    min_phantom_version="7.0.0",
    fips_compliant=False,
    asset_cls=Asset,
)


def _normalize_pem(pem_string: str) -> str:
    """Re-wrap a PEM block at 64 chars/line — SOAR config textareas mangle whitespace (NFR-04)."""
    if not pem_string:
        return pem_string

    pem_string = pem_string.strip()
    normalized_blocks = []

    for header, footer in PEM_BLOCK_TYPES:
        parts = pem_string.split(header)
        for part in parts:
            if footer in part:
                body, _ = part.split(footer, 1)
                body = "".join(body.split())
                lines = [body[i : i + 64] for i in range(0, len(body), 64)]
                normalized_blocks.append(header + "\n" + "\n".join(lines) + "\n" + footer)

    if not normalized_blocks:
        return pem_string
    return "\n".join(normalized_blocks)


def _setup_cert_files(asset: Asset) -> tuple[str, str, str | None]:
    """Write normalized cert/key/ca PEMs to temp files. Caller must clean up."""
    cert_pem = _normalize_pem(asset.client_cert)
    key_pem = _normalize_pem(asset.client_key)
    ca_pem = _normalize_pem(asset.client_ca) if asset.client_ca else ""

    if not cert_pem or not key_pem:
        raise ActionFailure("client_cert and client_key are required for mTLS")

    written_paths: list[str] = []
    try:
        cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
        written_paths.append(cert_file.name)
        cert_file.write(cert_pem)
        cert_file.close()

        key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
        written_paths.append(key_file.name)
        key_file.write(key_pem)
        key_file.close()

        ca_path = None
        if ca_pem:
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
            written_paths.append(ca_file.name)
            ca_file.write(ca_pem)
            ca_file.close()
            ca_path = ca_file.name
    except Exception:
        _cleanup_temp_files(*written_paths)
        raise

    return cert_file.name, key_file.name, ca_path


def _cleanup_temp_files(*file_paths: str | None) -> None:
    for path in file_paths:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _validate_int(value: object, field_name: str) -> int:
    """Coerce a numeric param to a real int.

    SOAR hands numeric params through as float or str often enough that raw
    interpolation is unsafe: a float 1001.0 interpolated into a URL path
    yields /rest/ip_alias_list/ip_id/1001.0 and a false "no aliases". Same
    precedent as proofpoint_trap's _validate_integer().
    """
    try:
        # float() first, not int(): SOAR hands a numeric param through as
        # 1001.0 often enough that int("1001.0") -- which raises -- would
        # reject the very case this helper exists to absorb.
        as_float = float(str(value).strip())
    except (TypeError, ValueError) as e:
        raise ActionFailure(f"'{field_name}' must be a whole number, got: {value!r}") from e
    if as_float != int(as_float):
        raise ActionFailure(f"'{field_name}' must be a whole number, got: {value!r}")
    parsed = int(as_float)
    if parsed < 1:
        raise ActionFailure(f"'{field_name}' must be a positive whole number, got: {parsed}")
    return parsed


def _ip_to_hex(address: str) -> str:
    """SOLIDserver's ip_addr filter field takes the address as hex, not dotted-decimal."""
    try:
        return ipaddress.ip_address(address).packed.hex()
    except ValueError as e:
        raise ActionFailure(
            f"'{address}' is not a valid IP address -- this action takes a single "
            f"IPv4 or IPv6 address, not a hostname, CIDR range, or URL"
        ) from e


def _parse_class_parameters(raw: str) -> dict[str, str]:
    """SOLIDserver packs custom attributes as a query-string-style blob, e.g. 'key1=val1&key2=val2&'."""
    if not raw:
        return {}
    return dict(parse_qsl(raw.rstrip("&"), keep_blank_values=True))


def _sql_escape(value: str) -> str:
    """Escape a value for SOLIDserver's SQL-ANSI-style WHERE clause."""
    return value.replace("'", "''")


def _bounded_query(limit: int, where: str | None = None) -> dict:
    """Build the query params. NEVER send `WHERE` and `limit` together.

    The backend's behaviour across the four combinations:

        WHERE   limit   result
        no      no      times out -- unbounded full scan
        no      yes     works     -- what test_connectivity does
        yes     no      works     -- slower, the filter is doing real work
        yes     yes     FAILS     -- backend aborts the query, returns HTTP 401

    A `WHERE` already bounds the query, so `limit` alongside one is redundant
    and actively harmful.

    The caller's `limit` is still honoured on a filtered call, just applied
    client-side by the caller truncating the result -- see _apply_client_limit.

    Two different reasons the drop is safe, worth keeping straight:

      - Exact-match filters on a unique value (ip_addr, subnet_name, subnet_id,
        pool_name) can only match one record, so `limit` was never doing
        anything and nothing is lost.
      - parent_subnet_name and parent_site_name deliberately match MANY records,
        so `limit` is NOT redundant there -- it is genuinely the caller's
        intent, which is why _apply_client_limit exists rather than the bound
        simply being discarded.

    ACCEPTED LIMITATION: on a broad filter (e.g. a site-wide parent_site_name)
    the appliance returns every match and we bound it only after transfer. This
    is exactly the risk v1.0.2 was reaching for when it added the limit, and
    there is no server-side remedy -- the one parameter that would bound it is
    the one the backend refuses alongside a WHERE. Fine for the exact-match
    lookups this connector is built around; watch it if a site-wide filter is
    ever pointed at a large IPAM.
    """
    return {"WHERE": where} if where else {"limit": limit}


def _apply_client_limit(records: list, limit: int, where: str | None) -> list:
    """Honour `limit` on a filtered call, where it cannot go on the wire.

    Only truncates when a WHERE was sent; an unfiltered call was already
    bounded server-side.
    """
    return records[:limit] if where else records


# Caller-facing filter parameter -> the WHERE column it actually filters on,
# for ip_block_subnet_list. Two entries are NOT identity mappings, which is the
# whole reason this is a table rather than an f-string: "subnet_name" filters
# but the record comes back under "name", and the caller-facing "site_name"
# (what the record returns) filters as "parent_site_name". Getting this wrong
# is invisible against a permissive backend.
#
# Also filterable but deliberately NOT exposed: start_ip_addr / end_ip_addr
# (hex) and start_hostaddr / end_hostaddr (dotted IP). Those are range columns,
# and a useful range filter needs comparison operators and/or AND-composition,
# neither of which is supported as far as anyone has established. See the probe
# list in the UC17 plan before building them.
LIST_SUBNETS_FILTERS = {
    "subnet_name": "subnet_name",
    "subnet_id": "subnet_id",
    "parent_subnet_name": "parent_subnet_name",
    "site_name": "parent_site_name",
}


def _select_optional_filter(params: Params, filter_map: dict[str, str]) -> tuple[str, str]:
    """Pick at most one supplied filter, returning (where_column, value).

    Returns (None, None) when no filter is set: `limit` alone is a legal and
    intentional call. `ip_block_subnet_list` needs no filter params at all --
    test_connectivity has always relied on exactly that, and it is the one
    shape confirmed to work on the real APIM. It is also the shape to reach for
    when a `WHERE` clause is being rejected by the gateway rather than the
    backend (see the UC17 plan's WHERE-rejection section).

    At most one, never two: this service's WHERE clause has only ever been
    confirmed carrying a single column='value' condition. Whether it accepts
    AND at all is unverified against the real APIM, so composing two filters
    would be a coded guess of precisely the kind that shipped as
    WHERE=name='...' and passed locally for two versions.
    """
    supplied = []
    for name in filter_map:
        value = getattr(params, name, "") or ""
        if value.strip():
            supplied.append((name, value.strip()))
    if not supplied:
        return None, None
    if len(supplied) > 1:
        raise ActionFailure(
            "Set exactly ONE filter, got {}. This service is only confirmed to accept a "
            "single WHERE condition; combining filters is not supported.".format(
                ", ".join(name for name, _ in supplied)
            )
        )
    param_name, value = supplied[0]
    return filter_map[param_name], value


def _ensure_list(data, context: str) -> list:
    """_request() is assumed to return a bare JSON array for list services — not yet
    confirmed against the real APIM, which might wrap results in an envelope instead.
    Fail with a clear message here rather than a raw KeyError/TypeError on records[0]."""
    if not isinstance(data, list):
        raise ActionFailure(
            f"Unexpected response shape from {context} (expected a JSON array, "
            f"got {type(data).__name__}): {str(data)[:200]}"
        )
    return data


def _auth_headers(asset: Asset) -> dict[str, str]:
    # Every one of these four is hand-entered into a SOAR asset field, and all four
    # get base64-encoded, so surrounding whitespace survives into the credential
    # instead of being rejected at entry. A single pasted trailing newline yields a
    # wrong credential and an HTTP 401 indistinguishable from a genuinely wrong value.
    client_id = asset.client_id.strip()
    client_secret = asset.client_secret.strip()
    ddi_username = asset.ddi_username.strip()
    ddi_password = asset.ddi_password.strip()

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {basic}",
        "X-DDI-Username": base64.b64encode(ddi_username.encode()).decode(),
        "X-DDI-Password": base64.b64encode(ddi_password.encode()).decode(),
    }


def _request(asset: Asset, method: str, path: str, params: dict | None = None) -> dict:
    """Centralized REST call — see dev-rules.md FR-05."""
    url = f"{asset.base_url.rstrip('/')}{path}"
    headers = _auth_headers(asset)
    # No Content-Type header. It describes a request BODY, and every action
    # here is a bodiless GET -- declaring "application/json" on a request with
    # no body invites a strict server to parse the empty body as a JSON
    # document and reject it -- the appliance answers that with an HTTP 401 and
    # "The specified document is not valid JSON data". Add Content-Type back
    # per-request if a POST/PUT with a real body is ever needed.
    headers["Accept"] = "application/json"

    cert_path = key_path = ca_path = None
    try:
        cert_path, key_path, ca_path = _setup_cert_files(asset)
        verify = ca_path if (asset.verify_ssl and ca_path) else asset.verify_ssl

        response = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            cert=(cert_path, key_path),
            verify=verify,
            timeout=15,
        )
    except requests.exceptions.SSLError as e:
        raise ActionFailure(f"TLS/mTLS error connecting to APIM: {e}") from e
    except requests.exceptions.ConnectionError as e:
        raise ActionFailure(f"Could not reach APIM: {e}") from e
    except requests.exceptions.RequestException as e:
        raise ActionFailure(f"Error connecting to APIM: {e}") from e
    finally:
        _cleanup_temp_files(cert_path, key_path, ca_path)

    return _process_response(response)


def _process_response(response: requests.Response) -> dict:
    """Content-type-aware response handling, per FR-05 (JSON / empty / other)."""
    content_type = response.headers.get("Content-Type", "")

    if "json" in content_type:
        try:
            data = response.json()
        except ValueError as e:
            raise ActionFailure(f"Unable to parse JSON response: {e}") from e
    elif not response.content:
        # The real APIM returns HTTP 204 No Content (empty body, no
        # Content-Type) for a "not found"/empty result on a list endpoint --
        # not a 200 with an empty JSON array.
        # Every action in this connector expects a list from _ensure_list(),
        # so default to [] here, not {} -- a dict would fail that isinstance
        # check and surface a confusing "unexpected response shape" error
        # instead of the intended friendly "No X found" ActionFailure.
        data = []
    elif response.ok:
        raise ActionFailure(
            f"Unexpected non-JSON response (status {response.status_code}, "
            f"content-type {content_type or 'unknown'}): {response.text[:200]}"
        )
    else:
        data = {}

    if response.ok:
        return data

    detail = data.get("message") if isinstance(data, dict) and data else response.text
    raise ActionFailure(f"EfficientIP/APIM returned HTTP {response.status_code}: {detail}")


@app.test_connectivity()
def test_connectivity(soar: SOARClient, asset: Asset) -> None:
    # No dedicated health-check service exists in SOLIDserver's real API.
    # ip_block_subnet_list is the one endpoint confirmed to exist on the real
    # APIM that needs no filter/params at all, making it the safest possible
    # connectivity/auth check. limit=1 is required, not optional: a bare list
    # call with no WHERE *and* no limit times out server-side on the real APIM;
    # limit alone (no WHERE) is what works.
    _request(asset, "GET", "/rest/ip_block_subnet_list", params={"limit": 1})
    logger.info("test connectivity OK (APIM /rest/ip_block_subnet_list reachable, mTLS + auth accepted)")


class GetIpAddressParams(Params):
    address: str = Param(description="IPv4/IPv6 address to look up in SOLIDserver's IPAM.", required=True, cef_types=["ip"])
    limit: int = Param(description=LIMIT_DESCRIPTION, required=False, default=DEFAULT_LIMIT)


class GetIpAddressOutput(ActionOutput):
    address: str = OutputField(cef_types=["ip"])
    ip_id: str = OutputField()
    subnet: str = OutputField()
    space: str = OutputField()
    status: str = OutputField()
    hostname: str = OutputField(cef_types=["host name"])
    mac_address: str = OutputField(cef_types=["mac address"])
    ddi_class: str = OutputField()
    description: str = OutputField()
    raw_json: str = OutputField()


@app.action(
    name="get ip address",
    description="Look up an IP address in SOLIDserver's IPAM (subnet, space, status, hostname, MAC, class) for enrichment. Named fields are best-effort -- raw_json is the reliable source of truth, since these have been wrong under manual mapping more than once (e.g. hostname was hostdev_name until confirmed otherwise).",
    action_type="investigate",
    read_only=True,
)
def get_ip_address(
    params: GetIpAddressParams,
    soar: SOARClient,
    asset: Asset,
) -> list[GetIpAddressOutput]:
    hex_addr = _ip_to_hex(params.address)
    limit = _validate_int(params.limit, "limit")
    records = _ensure_list(
        _request(
            asset,
            "GET",
            "/rest/ip_address_list",
            params=_bounded_query(limit, f"ip_addr='{hex_addr}'"),
        ),
        "ip_address_list",
    )
    records = records[:limit]
    if not records:
        raise ActionFailure(f"No IP address record found in SOLIDserver for {params.address}")

    outputs = []
    for record in records:
        class_params = _parse_class_parameters(record.get("ip_class_parameters", ""))
        outputs.append(
            GetIpAddressOutput(
                address=params.address,
                ip_id=str(record.get("ip_id", "")),
                subnet=record.get("subnet_name", ""),
                space=record.get("site_name", ""),
                status=record.get("multistatus", ""),
                hostname=record.get("name", ""),
                mac_address=record.get("mac_addr", ""),
                ddi_class=record.get("ip_class_name", ""),
                description=class_params.get("description", ""),
                raw_json=json.dumps(record),
            )
        )
    return outputs


# "get dns record" is not implemented — no record-level DNS service exists on
# the real APIM (only zone-level dns_zone_list); dns_rr_list was this
# project's own inference from public client docs, never actually observed.
# Rebuild only once a real record-level endpoint is identified.


class ListSubnetsParams(Params):
    # Four optional filters, AT MOST one used per call. None of them is
    # required: `limit` alone lists subnets, the same bare bounded shape
    # test_connectivity uses. See _select_optional_filter().
    subnet_name: str = Param(description="Filter by subnet NAME -- the human label the subnet carries in IPAM (e.g. 'Corporate-LAN'), not its CIDR. To find a subnet by address you need the range columns, which this action does not yet expose.", required=False, default="")
    subnet_id: str = Param(description="Filter by SOLIDserver subnet id.", required=False, default="")
    parent_subnet_name: str = Param(description="Filter by parent subnet name — lists the subnets underneath it.", required=False, default="")
    site_name: str = Param(description="Filter by space/site name — lists the subnets belonging to it. Filters on the API's 'parent_site_name' column.", required=False, default="")
    limit: int = Param(description=LIMIT_DESCRIPTION, required=False, default=DEFAULT_LIMIT)


class ListSubnetsOutput(ActionOutput):
    subnet_id: str = OutputField()
    subnet_name: str = OutputField()
    parent_subnet: str = OutputField()
    space: str = OutputField()
    tree_path: str = OutputField()
    start_address: str = OutputField(cef_types=["ip"])
    end_address: str = OutputField(cef_types=["ip"])
    size: str = OutputField()
    ddi_class: str = OutputField()
    description: str = OutputField()
    raw_json: str = OutputField()


@app.action(
    name="list subnets",
    description="Look up subnets in SOLIDserver's IPAM (parent, space, address range, size, class) for enrichment. Only 'limit' need be set: with no filter this lists subnets bare, the same shape test connectivity uses. Optionally set AT MOST ONE filter: subnet_name, subnet_id, parent_subnet_name (lists the subnets under a parent) or site_name (lists the subnets in a space). Raise 'limit' above the default of 1 to see more than one row, which the parent/site filters and the unfiltered call usually need. Output field names follow ip_address_list's confirmed subnet_* conventions but ip_block_subnet_list's own field set is not independently vendor-confirmed — check raw_json if a named field comes back empty.",
    action_type="investigate",
    read_only=True,
)
def list_subnets(
    params: ListSubnetsParams,
    soar: SOARClient,
    asset: Asset,
) -> list[ListSubnetsOutput]:
    limit = _validate_int(params.limit, "limit")
    # Resolved before the call, so an ambiguous filter fails without ever
    # touching the APIM. LIST_SUBNETS_FILTERS carries the param -> WHERE column
    # mapping, including the two that deliberately differ.
    column, value = _select_optional_filter(params, LIST_SUBNETS_FILTERS)
    where = f"{column}='{_sql_escape(value)}'" if column else None
    records = _ensure_list(
        _request(asset, "GET", "/rest/ip_block_subnet_list",
                 params=_bounded_query(limit, where)),
        "ip_block_subnet_list",
    )
    records = _apply_client_limit(records, limit, where)
    if not records:
        where = f" for {column}='{value}'" if column else ""
        raise ActionFailure(f"No subnet found in SOLIDserver{where}")

    outputs = []
    for record in records:
        class_params = _parse_class_parameters(record.get("subnet_class_parameters", ""))
        outputs.append(
            ListSubnetsOutput(
                subnet_id=str(record.get("subnet_id", "")),
                # "name" is the subnet's own identity field on
                # ip_block_subnet_list -- not "subnet_name", which is the
                # guess borrowed from ip_subnet_list's public docs.
                subnet_name=record.get("name", ""),
                parent_subnet=record.get("parent_subnet_name", ""),
                space=record.get("site_name", ""),
                tree_path=record.get("tree_path", ""),
                start_address=record.get("subnet_start_ip_addr", ""),
                end_address=record.get("subnet_end_ip_addr", ""),
                size=str(record.get("subnet_size", "")),
                ddi_class=record.get("subnet_class_name", ""),
                description=class_params.get("description", ""),
                raw_json=json.dumps(record),
            )
        )
    return outputs


class GetIpPoolParams(Params):
    name: str = Param(description="Pool name to look up in SOLIDserver's IPAM.", required=True)
    limit: int = Param(description=LIMIT_DESCRIPTION, required=False, default=DEFAULT_LIMIT)


class GetIpPoolOutput(ActionOutput):
    pool_id: str = OutputField()
    pool_name: str = OutputField()
    subnet: str = OutputField()
    space: str = OutputField()
    start_address: str = OutputField(cef_types=["ip"])
    end_address: str = OutputField(cef_types=["ip"])
    ddi_class: str = OutputField()
    description: str = OutputField()
    raw_json: str = OutputField()


@app.action(
    name="get ip pool",
    description="Look up an IP pool in SOLIDserver's IPAM by name for enrichment. Field names are inferred by analogy to ip_address_list's confirmed conventions, NOT independently vendor-confirmed — check raw_json if a named field comes back empty.",
    action_type="investigate",
    read_only=True,
)
def get_ip_pool(
    params: GetIpPoolParams,
    soar: SOARClient,
    asset: Asset,
) -> list[GetIpPoolOutput]:
    limit = _validate_int(params.limit, "limit")
    records = _ensure_list(
        _request(
            asset,
            "GET",
            "/rest/ip_pool_list",
            params=_bounded_query(limit, f"pool_name='{_sql_escape(params.name)}'"),
        ),
        "ip_pool_list",
    )
    records = records[:limit]
    if not records:
        raise ActionFailure(f"No IP pool found in SOLIDserver for {params.name}")

    outputs = []
    for record in records:
        class_params = _parse_class_parameters(record.get("pool_class_parameters", ""))
        outputs.append(
            GetIpPoolOutput(
                pool_id=str(record.get("pool_id", "")),
                pool_name=record.get("pool_name", params.name),
                subnet=record.get("subnet_name", ""),
                space=record.get("site_name", ""),
                start_address=record.get("start_hostaddr", ""),
                end_address=record.get("end_hostaddr", ""),
                ddi_class=record.get("pool_class_name", ""),
                description=class_params.get("description", ""),
                raw_json=json.dumps(record),
            )
        )
    return outputs


class ListAliasesParams(Params):
    # str, not int: "get ip address" emits ip_id as a string output field, and a
    # str param is what makes that chain actually wireable in the VPE editor
    # (the editor will not bind a string datapath to a numeric parameter).
    # _validate_int() below still enforces it is a whole number before it is
    # interpolated into the URL path.
    ip_id: str = Param(description="Internal SOLIDserver ip_id of the address to list aliases for (from 'get ip address' output).", required=True)
    limit: int = Param(description=LIMIT_DESCRIPTION, required=False, default=DEFAULT_LIMIT)


class ListAliasesOutput(ActionOutput):
    ip_id: str = OutputField()
    alias_name: str = OutputField(cef_types=["host name"])
    raw_json: str = OutputField()


@app.action(
    name="list aliases",
    description="List DNS aliases for a known SOLIDserver ip_id (chain off 'get ip address' output). Returns one row per alias -- raise 'limit' above the default of 1 to see them all. Field names are inferred, NOT independently vendor-confirmed — check raw_json if alias_name comes back empty.",
    action_type="investigate",
    read_only=True,
)
def list_aliases(
    params: ListAliasesParams,
    soar: SOARClient,
    asset: Asset,
) -> list[ListAliasesOutput]:
    ip_id = _validate_int(params.ip_id, "ip_id")
    limit = _validate_int(params.limit, "limit")
    records = _ensure_list(
        _request(asset, "GET", f"/rest/ip_alias_list/ip_id/{ip_id}", params={"limit": limit}),
        "ip_alias_list",
    )
    if not records:
        raise ActionFailure(f"No aliases found in SOLIDserver for ip_id {ip_id}")

    return [
        ListAliasesOutput(
            ip_id=str(ip_id),
            alias_name=record.get("alias_name", ""),
            raw_json=json.dumps(record),
        )
        for record in records
    ]


if __name__ == "__main__":
    app.cli()
