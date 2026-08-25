# efficientip_ddi — EfficientIP SOLIDserver via APIM (SOAR SDK)

Splunk SOAR SDK app for analyst-driven IP/DNS lookup enrichment against an
EfficientIP SOLIDserver DDI (DNS/DHCP/IPAM) backend that is reached through
an APIM gateway rather than called directly.

Endpoint paths and response shapes (`/ddi/ip_address`, `/ddi/dns_record`)
are this project's own invention, not vendor-confirmed — the DDI header
auth encoding below **is** confirmed against the real APIM (curl,
2026-08-25). Reconcile the endpoint/response contract against the real
SOLIDserver REST API before pointing this at production. Playbook design
that consumes this connector's actions hasn't been done yet — this
connector is a prerequisite step, built first per user request.

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
| `test connectivity` | test | — | pass/fail (`GET /ddi/health`) |
| `get ip address` | investigate | `address` | `address`, `subnet`, `space`, `status`, `hostname`, `mac_address`, `ddi_class`, `description` |
| `get dns record` | investigate | `name` | `name`, `record_type`, `value`, `zone`, `ttl` |

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
3-layer auth success on `/ddi/health`, `/ddi/ip_address`, and
`/ddi/dns_record`, and a 404 not-found path. **Not yet verified:** the
connector module itself against a real `splunk-soar-sdk` package in a
scratch venv (see `itsm_generic`'s README for that pattern — SDK
`@app.action`-decorated functions can't be called directly, only their
undecorated helpers), a `soarapps package build`, or any install/action-run
on soar8. Do all three before relying on this in a real playbook run.
