**Unreleased**

## 1.0.3 (2026-08-25)

- Fixed the DDI backend auth layer: `X-DDI-Username`/`X-DDI-Password` are now
  base64-encoded independently (`base64(ddi_username)`, `base64(ddi_password)`
  — not combined, not folded into the Basic Auth layer), confirmed against
  the real APIM via curl. Previously sent as plain text, which would have
  failed against the real backend. Mock server (`mock_efficientip_ddi.py`,
  both copies) updated to match and round-trip verified via curl.

## 1.0.2 (2026-08-24)

- Replaced the hand-rolled `urllib`/`ssl.SSLContext` HTTP layer in `_request()`
  with `requests` (`cert=`/`verify=` handle mTLS natively — no manual
  `SSLContext` needed). This was a pure simplification, not a new dependency:
  `requests` (+ `urllib3`/`idna`/`certifi`/`charset-normalizer`) was already
  forced into the bundle by `splunk-soar-sdk` itself (see 1.0.1), so using it
  in our own code costs nothing extra.
- Added `_process_response()` with real content-type detection (JSON / empty /
  unexpected), closing the FR-05 gap the old raw `json.loads()` had — a
  non-JSON 2xx response from APIM no longer crashes with an unhandled
  `JSONDecodeError`.
- Removed now-unused `ssl`, `json`, `urllib.error`, `urllib.request` imports
  and the `_ssl_ctx()` helper.
- Verified the same way as 1.0.1: clean-room venv, manifest-declared wheels
  only, `app.py --help` runs end-to-end.

## 1.0.1 (2026-08-24)

- Fixed bundled dependency set: removed the unused Outlook `.msg`/OLE/RTF-parsing
  chain (`extract-msg`, `oletools`, `msoffcrypto-tool`, `pcodedmp`, `rtfde`,
  `olefile`, `compressed-rtf`, `ebcdic`) pulled in transitively by
  `splunk-soar-sdk` but never exercised by this connector's own actions.
- Added `idna`, `requests`, `urllib3`, `certifi`, `charset-normalizer` — genuinely
  required by `soar_sdk.app_cli_runner`'s `requests` import at load time, but
  missing from the original bundle despite being correctly resolved in
  `uv.lock`. Without these, the app fails to import in an isolated
  (air-gapped-equivalent) environment.
- Verified via a clean-room venv: installed only the wheels the manifest
  declares, then imported `app.py` and ran its CLI entry point end-to-end.
