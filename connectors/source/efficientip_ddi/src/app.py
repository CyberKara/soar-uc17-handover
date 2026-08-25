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
     independently (not combined like the Basic-auth layer) — confirmed
     against the real APIM via curl (2026-08-25).

Built and tested against `soar8/migration/mock-backend/mock_efficientip_ddi.py`
(:8447, mirrored into `soar8/soar-connectors/test/`), updated to match the
real APIM's confirmed per-value base64 encoding for the DDI header layer.
The `/ddi/ip_address`/`/ddi/dns_record` endpoint paths/response shapes are
still this project's own invention, not vendor-confirmed — reconcile
against the real SOLIDserver REST API before pointing this at production.
"""

import base64
import os
import tempfile

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
    appid="414f081c-261b-4eea-a04c-2edf9135c637",
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
    _request(asset, "GET", "/ddi/health")
    logger.info("test connectivity OK (APIM /ddi/health reachable, mTLS + auth accepted)")


class GetIpAddressParams(Params):
    address: str = Param(description="IPv4/IPv6 address to look up in SOLIDserver's IPAM.", required=True, cef_types=["ip"])


class GetIpAddressOutput(ActionOutput):
    address: str = OutputField(cef_types=["ip"])
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
    data = _request(asset, "GET", "/ddi/ip_address", params={"address": params.address})

    return GetIpAddressOutput(
        address=data["address"],
        subnet=data.get("subnet", ""),
        space=data.get("space", ""),
        status=data.get("status", ""),
        hostname=data.get("hostname", ""),
        mac_address=data.get("mac_address", ""),
        ddi_class=data.get("class", ""),
        description=data.get("description", ""),
    )


class GetDnsRecordParams(Params):
    name: str = Param(description="Hostname/FQDN to look up.", required=True, cef_types=["host name", "domain"])


class GetDnsRecordOutput(ActionOutput):
    name: str = OutputField(cef_types=["host name", "domain"])
    record_type: str = OutputField()
    value: str = OutputField()
    zone: str = OutputField(cef_types=["domain"])
    ttl: int = OutputField()


@app.action(
    name="get dns record",
    description="Look up a DNS record (A/CNAME/etc.) in SOLIDserver by hostname/FQDN for enrichment.",
    action_type="investigate",
    read_only=True,
)
def get_dns_record(
    params: GetDnsRecordParams,
    soar: SOARClient,
    asset: Asset,
) -> GetDnsRecordOutput:
    data = _request(asset, "GET", "/ddi/dns_record", params={"name": params.name})

    return GetDnsRecordOutput(
        name=data["name"],
        record_type=data.get("type", ""),
        value=data.get("value", ""),
        zone=data.get("zone", ""),
        ttl=data.get("ttl", 0),
    )


if __name__ == "__main__":
    app.cli()
