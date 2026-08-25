**Unreleased**

## 1.0.7 (2026-08-25, code-review fixes)

- Fixed unescaped user input in `list subnets`/`get ip pool`'s `WHERE`
  clauses (`_sql_escape()` was dropped when `get dns record` was removed,
  but the two new actions needed it too — a name containing a single quote
  would have broken the filter).
- Added `_ensure_list()` guard on all four record-returning actions
  (`get_ip_address`, `list_subnets`, `get_ip_pool`, `list_aliases`) — they
  all assumed `_request()` returns a bare JSON array; if the real APIM
  wraps results in an envelope instead (unconfirmed either way), this now
  fails with a clear `ActionFailure` message instead of a raw
  `KeyError`/`TypeError` traceback.

## 1.0.6 (2026-08-25, later still)

- Resolved the open filter-mechanism question from 1.0.5: the user confirmed
  `WHERE` is real and **required** on `ip_address_list`, settling it in
  favor of query-string filtering over `ip_alias_list`'s path-parameter
  style (which is a "list children of a known parent" shortcut, not the
  general convention).
- Added `ip_id` to `get ip address`'s output (from `ip_address_list`'s own
  `ip_id` field) so it can be chained into the new `list aliases` action.
- Added `list subnets` (`GET /rest/ip_block_subnet_list?WHERE=subnet_name=`)
  — field names follow `ip_address_list`'s confirmed `subnet_*` conventions.
- Added `get ip pool` (`GET /rest/ip_pool_list?WHERE=pool_name=`) — field
  names inferred by analogy, not independently vendor-confirmed; carries a
  `raw_json` fallback field.
- Added `list aliases` (`GET /rest/ip_alias_list/ip_id/{ip_id}`,
  path-parameter style, chained off `get ip address`'s new `ip_id` output)
  — field names inferred, not independently vendor-confirmed; carries a
  `raw_json` fallback field.
- Mock server (both copies) updated with subnet/pool/alias seed data and
  the three new endpoints.

## 1.0.5 (2026-08-25, later)

- Removed `get dns record` — no record-level DNS service was ever confirmed
  on the real APIM, only zone-level (`dns_zone_list`, user-observed).
  `dns_rr_list` was this project's own inference from public client docs
  and was never actually seen on the real system. Rebuild only once a real
  record-level endpoint is identified.
- `test_connectivity` now calls `GET /rest/ip_block_subnet_list` bare
  instead of `ip_address_list?limit=1` — the user directly confirmed
  `ip_block_subnet_list`, `ip_address_list`, `ip_alias_list/ip_id/{ip_id}`,
  `dns_zone_list`, and `ip_pool_list` exist on the real APIM;
  `ip_block_subnet_list` needs no filter params at all, making it the
  safest possible connectivity check among the confirmed-real endpoints.
- Flagged (not yet fixed, needs a real curl test to resolve): whether
  `get_ip_address`'s `WHERE=ip_addr='<hex>'` query-string filter is
  actually how the real APIM filters `ip_address_list`, since the one
  filtered endpoint the user has observed (`ip_alias_list/ip_id/{ip_id}`)
  uses a path-parameter style instead. That endpoint lists aliases of a
  known parent ID though, which may be a different convention from
  top-level list filtering — genuinely unresolved either way.

## 1.0.4 (2026-08-25)

- Fixed all three action endpoints: the original `/ddi/health`,
  `/ddi/ip_address`, `/ddi/dns_record` paths were pure invention and don't
  exist on the real backend — the first real airgapped `test_connectivity`
  run against the actual APIM failed with "not found" as a direct result.
  Rewritten to match SOLIDserver's real classic REST API convention (flat
  service names under `/rest/`, `WHERE=<field>='<value>'` filtering):
  `test_connectivity` now does a cheap `GET /rest/ip_address_list?limit=1`
  (no dedicated health service exists in the vendor API), `get ip address`
  calls `GET /rest/ip_address_list?WHERE=ip_addr='<hex>'` (address must be
  hex-encoded, not dotted-decimal), `get dns record` calls
  `GET /rest/dns_rr_list?WHERE=rr_name='<fqdn>'`. Output field mapping
  updated to the vendor's real field names (`subnet_name`, `site_name`,
  `multistatus`, `hostdev_name`, `mac_addr`, `ip_class_name`, `rr_name`,
  `rr_type`, `rr_value1`, `rr_ttl`, `zone_name`); `description` is now
  parsed out of the `ip_class_parameters` custom-attribute blob instead of
  assuming a plain field. Sourced from public EfficientIP client code
  (Ruby/Go SDKs), not a confirmed contract with this org's actual APIM —
  still needs real airgapped re-verification, including whether the APIM
  proxies `/rest/*` verbatim or under its own prefix, and IPv6 filtering
  (hex-encoding only vendor-confirmed for IPv4). Mock server
  (`mock_efficientip_ddi.py`, both copies) updated to the same convention.

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
