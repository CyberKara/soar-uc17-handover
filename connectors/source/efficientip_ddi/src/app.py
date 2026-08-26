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

`WHERE` is a real, **required** parameter on `ip_address_list` — not optional,
and not a guess — which is why filtering here uses query-string `WHERE=` and
not `ip_alias_list`'s path-parameter style (that's a "list children of a known
ip_id" sub-resource shortcut, not the general list-filtering convention).
`ip_pool_list`/`ip_block_subnet_list` take `WHERE` as *optional*, matching why
`test_connectivity` can call the latter bare. Output field names
(`subnet_name`, `site_name`, `mac_addr`, `ip_class_name`,
`ip_class_parameters`, `ip_id`, `name`) are the vendor's real field names
for `ip_address_list` — confirmed against SOLIDserver's own public REST
method reference (`solidserverrest` project docs, v9.0.1a), not just
inferred by SDK analogy. That pass (2026-08-25) also caught 3 real bugs
that had been silently masked because the mock used the same wrong names:
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
    appid="71a7abcc-75fa-4a8d-ae9d-23fb352869e4",
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


def _ip_to_hex(address: str) -> str:
    """SOLIDserver's ip_addr filter field takes the address as hex, not dotted-decimal."""
    return ipaddress.ip_address(address).packed.hex()


def _parse_class_parameters(raw: str) -> dict[str, str]:
    """SOLIDserver packs custom attributes as a query-string-style blob, e.g. 'key1=val1&key2=val2&'."""
    if not raw:
        return {}
    return dict(parse_qsl(raw.rstrip("&"), keep_blank_values=True))


def _sql_escape(value: str) -> str:
    """Escape a value for SOLIDserver's SQL-ANSI-style WHERE clause."""
    return value.replace("'", "''")


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
    basic = base64.b64encode(f"{asset.client_id}:{asset.client_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {basic}",
        "X-DDI-Username": base64.b64encode(asset.ddi_username.encode()).decode(),
        "X-DDI-Password": base64.b64encode(asset.ddi_password.encode()).decode(),
    }


def _request(asset: Asset, method: str, path: str, params: dict | None = None) -> dict:
    """Centralized REST call — see dev-rules.md FR-05."""
    url = f"{asset.base_url.rstrip('/')}{path}"
    headers = _auth_headers(asset)
    headers["Content-Type"] = "application/json"

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
        data = {}
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
    # connectivity/auth check.
    _request(asset, "GET", "/rest/ip_block_subnet_list")
    logger.info("test connectivity OK (APIM /rest/ip_block_subnet_list reachable, mTLS + auth accepted)")


class GetIpAddressParams(Params):
    address: str = Param(description="IPv4/IPv6 address to look up in SOLIDserver's IPAM.", required=True, cef_types=["ip"])


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


@app.action(
    name="get ip address",
    description="Look up an IP address in SOLIDserver's IPAM (subnet, space, status, hostname, MAC, class) for enrichment.",
    action_type="investigate",
    read_only=True,
)
def get_ip_address(
    params: GetIpAddressParams,
    soar: SOARClient,
    asset: Asset,
) -> GetIpAddressOutput:
    hex_addr = _ip_to_hex(params.address)
    records = _ensure_list(
        _request(
            asset,
            "GET",
            "/rest/ip_address_list",
            params={"WHERE": f"ip_addr='{hex_addr}'"},
        ),
        "ip_address_list",
    )
    if not records:
        raise ActionFailure(f"No IP address record found in SOLIDserver for {params.address}")
    record = records[0]
    class_params = _parse_class_parameters(record.get("ip_class_parameters", ""))

    return GetIpAddressOutput(
        address=params.address,
        ip_id=record.get("ip_id", ""),
        subnet=record.get("subnet_name", ""),
        space=record.get("site_name", ""),
        status=record.get("multistatus", ""),
        hostname=record.get("name", ""),
        mac_address=record.get("mac_addr", ""),
        ddi_class=record.get("ip_class_name", ""),
        description=class_params.get("description", ""),
    )


# "get dns record" is not implemented — no record-level DNS service exists on
# the real APIM (only zone-level dns_zone_list); dns_rr_list was this
# project's own inference from public client docs, never actually observed.
# Rebuild only once a real record-level endpoint is identified.


class ListSubnetsParams(Params):
    name: str = Param(description="Subnet name to look up in SOLIDserver's IPAM (e.g. '10.20.30.0/24').", required=True)


class ListSubnetsOutput(ActionOutput):
    subnet_id: str = OutputField()
    subnet_name: str = OutputField()
    parent_subnet: str = OutputField()
    space: str = OutputField()
    start_address: str = OutputField(cef_types=["ip"])
    end_address: str = OutputField(cef_types=["ip"])
    size: str = OutputField()
    ddi_class: str = OutputField()
    description: str = OutputField()
    raw_json: str = OutputField()


@app.action(
    name="list subnets",
    description="Look up a subnet in SOLIDserver's IPAM by name (parent, space, address range, size, class) for enrichment. Output field names follow ip_address_list's confirmed subnet_* conventions but ip_block_subnet_list's own field set is not independently vendor-confirmed — check raw_json if a named field comes back empty.",
    action_type="investigate",
    read_only=True,
)
def list_subnets(
    params: ListSubnetsParams,
    soar: SOARClient,
    asset: Asset,
) -> ListSubnetsOutput:
    records = _ensure_list(
        _request(
            asset,
            "GET",
            "/rest/ip_block_subnet_list",
            params={"WHERE": f"subnet_name='{_sql_escape(params.name)}'"},
        ),
        "ip_block_subnet_list",
    )
    if not records:
        raise ActionFailure(f"No subnet found in SOLIDserver for {params.name}")
    record = records[0]
    class_params = _parse_class_parameters(record.get("subnet_class_parameters", ""))

    return ListSubnetsOutput(
        subnet_id=record.get("subnet_id", ""),
        subnet_name=record.get("subnet_name", params.name),
        parent_subnet=record.get("parent_subnet_name", ""),
        space=record.get("site_name", ""),
        start_address=record.get("subnet_start_ip_addr", ""),
        end_address=record.get("subnet_end_ip_addr", ""),
        size=str(record.get("subnet_size", "")),
        ddi_class=record.get("subnet_class_name", ""),
        description=class_params.get("description", ""),
        raw_json=json.dumps(record),
    )


class GetIpPoolParams(Params):
    name: str = Param(description="Pool name to look up in SOLIDserver's IPAM.", required=True)


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
) -> GetIpPoolOutput:
    records = _ensure_list(
        _request(
            asset,
            "GET",
            "/rest/ip_pool_list",
            params={"WHERE": f"pool_name='{_sql_escape(params.name)}'"},
        ),
        "ip_pool_list",
    )
    if not records:
        raise ActionFailure(f"No IP pool found in SOLIDserver for {params.name}")
    record = records[0]
    class_params = _parse_class_parameters(record.get("pool_class_parameters", ""))

    return GetIpPoolOutput(
        pool_id=record.get("pool_id", ""),
        pool_name=record.get("pool_name", params.name),
        subnet=record.get("subnet_name", ""),
        space=record.get("site_name", ""),
        start_address=record.get("start_hostaddr", ""),
        end_address=record.get("end_hostaddr", ""),
        ddi_class=record.get("pool_class_name", ""),
        description=class_params.get("description", ""),
        raw_json=json.dumps(record),
    )


class ListAliasesParams(Params):
    ip_id: int = Param(description="Internal SOLIDserver ip_id of the address to list aliases for (from 'get ip address' output).", required=True)


class ListAliasesOutput(ActionOutput):
    ip_id: str = OutputField()
    alias_name: str = OutputField(cef_types=["host name"])
    raw_json: str = OutputField()


@app.action(
    name="list aliases",
    description="List DNS aliases for a known SOLIDserver ip_id (chain off 'get ip address' output). Field names are inferred, NOT independently vendor-confirmed — check raw_json if alias_name comes back empty.",
    action_type="investigate",
    read_only=True,
)
def list_aliases(
    params: ListAliasesParams,
    soar: SOARClient,
    asset: Asset,
) -> ListAliasesOutput:
    records = _ensure_list(
        _request(asset, "GET", f"/rest/ip_alias_list/ip_id/{params.ip_id}"),
        "ip_alias_list",
    )
    if not records:
        raise ActionFailure(f"No aliases found in SOLIDserver for ip_id {params.ip_id}")

    return ListAliasesOutput(
        ip_id=str(params.ip_id),
        alias_name=records[0].get("alias_name", ""),
        raw_json=json.dumps(records),
    )


if __name__ == "__main__":
    app.cli()
