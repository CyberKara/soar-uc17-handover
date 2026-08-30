# efficientip_ddi_classic_connector.py
"""EfficientIP DDI (Classic) SOAR Connector - classic BaseConnector twin of the
SDK-based efficientip_ddi app, built for side-by-side airgapped comparison.

Same auth model, same endpoints, same corrected field names as the SDK
version (soar-connectors/connectors/efficientip_ddi/src/app.py) -- see that
app's README for the full research/field-name provenance. This file exists
purely so both connector styles can be installed against the real airgapped
SOLIDserver instance and compared; it is not meant to replace the SDK
connector as the maintained implementation.

Auth (3 layers, every request):
  1. mTLS -- client_cert/client_key (+ optional client_ca) presented to APIM
     at the TLS layer.
  2. Authorization: Basic base64(client_id:client_secret) -- the APIM-level
     app credential. No OAuth token exchange.
  3. X-DDI-Username / X-DDI-Password headers -- forwarded by APIM to
     SOLIDserver's own backend auth, each value base64-encoded
     independently (not combined like the Basic Auth layer).
"""

import base64
import ipaddress
import json
import os
import tempfile
from urllib.parse import parse_qsl

import requests

import phantom.app as phantom
from phantom.action_result import ActionResult
from phantom.base_connector import BaseConnector

from efficientip_ddi_classic_consts import (
    DEFAULT_LIMIT,
    DEFAULT_TIMEOUT,
    IP_ADDRESS_LIST_PATH,
    IP_ALIAS_LIST_PATH,
    IP_BLOCK_SUBNET_LIST_PATH,
    IP_POOL_LIST_PATH,
    LIST_SUBNETS_FILTERS,
)


class EfficientipDdiClassicConnector(BaseConnector):
    """EfficientIP SOLIDserver via APIM connector for Splunk SOAR (classic style)."""

    def __init__(self):
        super(EfficientipDdiClassicConnector, self).__init__()
        self._state = None
        self._base_url = None

    def initialize(self):
        self._state = self.load_state()
        if not isinstance(self._state, dict):
            self.debug_print("Resetting corrupted state file")
            self._state = {"app_version": self.get_app_json().get("app_version")}

        config = self.get_config()
        self._base_url = config.get("base_url", "").rstrip("/")

        return phantom.APP_SUCCESS

    def finalize(self):
        self.save_state(self._state)
        return phantom.APP_SUCCESS

    def handle_action(self, param):
        action_id = self.get_action_identifier()
        self.debug_print("action_id", action_id)

        action_mapping = {
            "test_connectivity": self._handle_test_connectivity,
            "get_ip_address": self._handle_get_ip_address,
            "list_subnets": self._handle_list_subnets,
            "get_ip_pool": self._handle_get_ip_pool,
            "list_aliases": self._handle_list_aliases,
        }

        action = action_mapping.get(action_id)
        if action:
            return action(param)

        return phantom.APP_ERROR

    def handle_exception(self, exception):
        self.set_status(
            phantom.APP_ERROR,
            "Unhandled exception: {}".format(self._get_error_message_from_exception(exception)),
        )
        return phantom.APP_ERROR

    # ---- Action Handlers ----

    def _handle_test_connectivity(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting test connectivity action")

        # No dedicated health-check service exists in SOLIDserver's real API.
        # ip_block_subnet_list is the one endpoint confirmed to exist on the
        # real APIM that needs no filter/params at all. limit=1 is required,
        # not optional: a bare list call with no WHERE *and* no limit times
        # out server-side on the real APIM; limit alone (no WHERE) works.
        ret_val, _ = self._make_rest_call("GET", IP_BLOCK_SUBNET_LIST_PATH, {"limit": 1}, action_result)

        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS, "Test connectivity successful")

    def _handle_get_ip_address(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting get ip address action")

        address = param["address"]
        hex_addr = self._ip_to_hex(address, action_result)
        if hex_addr is None:
            return action_result.get_status()
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        ret_val, records = self._make_rest_call(
            "GET", IP_ADDRESS_LIST_PATH, self._bounded_query(limit, "ip_addr='{}'".format(hex_addr)), action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        records = self._apply_client_limit(records, limit, "ip_addr")
        if not records:
            return action_result.set_status(
                phantom.APP_ERROR, "No IP address record found in SOLIDserver for {}".format(address)
            )

        # Raw pass-through, not a curated field mapping: the real API's own
        # field names have been wrong under manual mapping multiple times
        # (subnet_name vs name, start_hostaddr vs pool_start_hostaddr, etc.)
        # -- every real key SOLIDserver returns is forwarded as-is under
        # action_result.data.*.<key>, no guessing required. address and
        # description (parsed from the ip_class_parameters blob) are added
        # as convenience keys on top.
        #
        # One data item per record, not just records[0]: data.* is a list
        # datapath, so truncating here would silently drop every row past
        # the first whenever the caller raises "limit".
        for record in records:
            class_params = self._parse_class_parameters(record.get("ip_class_parameters", ""))
            record["description"] = class_params.get("description", "")
            record["address"] = address
            action_result.add_data(record)

        summary = action_result.update_summary({})
        summary["total_objects"] = len(records)
        summary["total_objects_successful"] = len(records)

        return action_result.set_status(
            phantom.APP_SUCCESS, "Successfully retrieved {} IP address record(s)".format(len(records))
        )

    def _handle_list_subnets(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting list subnets action")

        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        # Resolved before the call, so an ambiguous filter fails without ever
        # touching the APIM. LIST_SUBNETS_FILTERS carries the param -> WHERE
        # column mapping, including the two that deliberately differ. No filter
        # is legal: it lists subnets bare, bounded by limit.
        ok, column, value = self._select_optional_filter(param, LIST_SUBNETS_FILTERS, action_result)
        if not ok:
            return action_result.get_status()

        where = "{}='{}'".format(column, self._sql_escape(value)) if column else None
        query = self._bounded_query(limit, where)

        ret_val, records = self._make_rest_call(
            "GET", IP_BLOCK_SUBNET_LIST_PATH, query, action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        records = self._apply_client_limit(records, limit, where)
        if not records:
            where = " for {}='{}'".format(column, value) if column else ""
            return action_result.set_status(
                phantom.APP_ERROR, "No subnet found in SOLIDserver{}".format(where)
            )

        # Raw pass-through, one data item per record -- see
        # _handle_get_ip_address for both rationales.
        for record in records:
            class_params = self._parse_class_parameters(record.get("subnet_class_parameters", ""))
            record["description"] = class_params.get("description", "")
            action_result.add_data(record)

        summary = action_result.update_summary({})
        summary["total_objects"] = len(records)
        summary["total_objects_successful"] = len(records)

        return action_result.set_status(
            phantom.APP_SUCCESS, "Successfully retrieved {} subnet record(s)".format(len(records))
        )

    def _handle_get_ip_pool(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting get ip pool action")

        name = param["name"]
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        ret_val, records = self._make_rest_call(
            "GET", IP_POOL_LIST_PATH, self._bounded_query(limit, "pool_name='{}'".format(self._sql_escape(name))), action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        records = self._apply_client_limit(records, limit, "pool_name")
        if not records:
            return action_result.set_status(phantom.APP_ERROR, "No IP pool found in SOLIDserver for {}".format(name))

        # Raw pass-through, one data item per record -- see
        # _handle_get_ip_address for both rationales.
        for record in records:
            class_params = self._parse_class_parameters(record.get("pool_class_parameters", ""))
            record["description"] = class_params.get("description", "")
            action_result.add_data(record)

        summary = action_result.update_summary({})
        summary["total_objects"] = len(records)
        summary["total_objects_successful"] = len(records)

        return action_result.set_status(
            phantom.APP_SUCCESS, "Successfully retrieved {} IP pool record(s)".format(len(records))
        )

    def _handle_list_aliases(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting list aliases action")

        # Validated, not interpolated raw: ip_id is declared as a string
        # param (so the "get ip address" chain is wireable in the VPE), and a
        # stray float like 1001.0 would otherwise become
        # /rest/ip_alias_list/ip_id/1001.0 and a false "no aliases".
        ip_id = self._validate_int(param["ip_id"], "ip_id", action_result)
        if ip_id is None:
            return action_result.get_status()
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        ret_val, records = self._make_rest_call(
            "GET", IP_ALIAS_LIST_PATH.format(ip_id=ip_id), {"limit": limit}, action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            return action_result.set_status(
                phantom.APP_ERROR, "No aliases found in SOLIDserver for ip_id {}".format(ip_id)
            )

        # Raw pass-through, one data item per alias -- an IP with two DNS
        # aliases must report two rows, not silently just the first.
        for record in records:
            record["ip_id"] = str(ip_id)
            action_result.add_data(record)

        summary = action_result.update_summary({})
        summary["total_objects"] = len(records)
        summary["total_objects_successful"] = len(records)

        return action_result.set_status(
            phantom.APP_SUCCESS, "Successfully retrieved {} alias record(s)".format(len(records))
        )

    # ---- REST Call Wrapper ----

    def _make_rest_call(self, method, path, params, action_result):
        """Execute an APIM call with mTLS cert setup + 3-layer auth, cleanup.

        Returns:
            tuple: (status, response_data) - RetVal pattern
        """
        config = self.get_config()
        url = "{}{}".format(self._base_url, path)
        headers = self._auth_headers(config)
        # No Content-Type header. It describes a request BODY, and every action
        # here is a bodiless GET -- declaring "application/json" on a request
        # with no body invites a strict server to parse the empty body as a
        # JSON document and reject it. The real appliance was seen returning
        # HTTP 401 with `"message": "The specified document is not valid JSON
        # data"`. Add Content-Type back per-request if a body is ever
        # actually sent.
        headers["Accept"] = "application/json"

        cert_path = key_path = ca_path = None
        try:
            cert_path, key_path, ca_path = self._setup_cert_files()
            self.save_progress("DEBUG GUI: Cert files created")

            verify_ssl = config.get("verify_ssl", True)
            verify = ca_path if (verify_ssl and ca_path) else verify_ssl

            self.save_progress("DEBUG GUI: {} {}".format(method, url))
            response = requests.request(
                method, url, headers=headers, params=params,
                cert=(cert_path, key_path), verify=verify, timeout=DEFAULT_TIMEOUT,
            )
            self.save_progress("DEBUG GUI: HTTP {} received".format(response.status_code))

            return self._process_response(response, action_result)

        except requests.exceptions.SSLError as e:
            return (
                action_result.set_status(phantom.APP_ERROR, "TLS/mTLS error connecting to APIM: {}".format(e)),
                None,
            )
        except requests.exceptions.ConnectionError as e:
            return (
                action_result.set_status(phantom.APP_ERROR, "Could not reach APIM: {}".format(e)),
                None,
            )
        except requests.exceptions.RequestException as e:
            return (
                action_result.set_status(phantom.APP_ERROR, "Error connecting to APIM: {}".format(e)),
                None,
            )
        finally:
            self._cleanup_temp_files(cert_path, key_path, ca_path)
            self.save_progress("DEBUG GUI: Cert files cleaned up")

    def _process_response(self, response, action_result):
        action_result.add_debug_data({
            "r_status_code": response.status_code,
            "r_text": response.text,
            "r_headers": dict(response.headers),
        })

        content_type = response.headers.get("Content-Type", "")

        if "json" in content_type:
            try:
                data = response.json()
            except ValueError as e:
                return (
                    action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response: {}".format(e)),
                    None,
                )
        elif not response.content:
            # The real APIM returns HTTP 204 No Content (empty body, no
            # Content-Type) for a "not found"/empty result on a list
            # endpoint -- not a 200 with an empty JSON
            # array. Every action here expects a list from _ensure_list(),
            # so default to [] here, not {} -- a dict would fail that
            # isinstance check and surface a confusing "unexpected response
            # shape" error instead of the intended friendly "No X found"
            # message.
            data = []
        elif response.ok:
            return (
                action_result.set_status(
                    phantom.APP_ERROR,
                    "Unexpected non-JSON response (status {}, content-type {}): {}".format(
                        response.status_code, content_type or "unknown", response.text[:200]
                    ),
                ),
                None,
            )
        else:
            data = {}

        if response.ok:
            return (phantom.APP_SUCCESS, data)

        detail = data.get("message") if isinstance(data, dict) and data else response.text
        return (
            action_result.set_status(
                phantom.APP_ERROR, "EfficientIP/APIM returned HTTP {}: {}".format(response.status_code, detail)
            ),
            None,
        )

    def _ensure_list(self, data, action_result):
        """_make_rest_call() is assumed to return a bare JSON array for list
        services -- not yet confirmed against the real APIM, which might wrap
        results in an envelope instead. Fail with a clear message here rather
        than a raw KeyError/TypeError on records[0]."""
        if not isinstance(data, list):
            action_result.set_status(
                phantom.APP_ERROR,
                "Unexpected response shape from SOLIDserver (expected a JSON array, got {}): {}".format(
                    type(data).__name__, str(data)[:200]
                ),
            )
            return None
        return data

    # ---- Auth / Encoding Helpers ----

    def _auth_headers(self, config):
        # Every one of these four is hand-entered into a SOAR text field, and all
        # four get base64-encoded, so surrounding whitespace survives into the
        # credential instead of being rejected at entry. A single pasted trailing
        # newline yields a wrong credential and an HTTP 401 indistinguishable from
        # a genuinely wrong value.
        client_id = config["client_id"].strip()
        client_secret = config["client_secret"].strip()
        ddi_username = config["ddi_username"].strip()
        ddi_password = config["ddi_password"].strip()

        basic = base64.b64encode(
            "{}:{}".format(client_id, client_secret).encode()
        ).decode()
        return {
            "Authorization": "Basic {}".format(basic),
            "X-DDI-Username": base64.b64encode(ddi_username.encode()).decode(),
            "X-DDI-Password": base64.b64encode(ddi_password.encode()).decode(),
        }

    def _ip_to_hex(self, address, action_result):
        """SOLIDserver's ip_addr filter field takes the address as hex, not
        dotted-decimal. Returns None (with action_result already failed) for
        anything that isn't a bare IP -- a hostname, CIDR range or typo would
        otherwise raise a bare ValueError out of the handler."""
        try:
            return ipaddress.ip_address(address).packed.hex()
        except ValueError:
            action_result.set_status(
                phantom.APP_ERROR,
                "'{}' is not a valid IP address -- this action takes a single "
                "IPv4 or IPv6 address, not a hostname, CIDR range, or URL".format(address),
            )
            return None

    def _validate_int(self, value, field_name, action_result):
        """Coerce a numeric param to a real int, or fail the action.

        SOAR hands numeric params through as float or str often enough that
        raw interpolation is unsafe: a float 1001.0 interpolated into a URL
        path yields /rest/ip_alias_list/ip_id/1001.0 and a false "no aliases".
        Same precedent as proofpoint_trap's _validate_integer().
        """
        try:
            # float() first, not int(): SOAR hands a numeric param through as
            # 1001.0 often enough that int("1001.0") -- which raises -- would
            # reject the very case this helper exists to absorb.
            as_float = float(str(value).strip())
        except (TypeError, ValueError):
            action_result.set_status(
                phantom.APP_ERROR,
                "'{}' must be a whole number, got: {}".format(field_name, value),
            )
            return None
        if as_float != int(as_float):
            action_result.set_status(
                phantom.APP_ERROR,
                "'{}' must be a whole number, got: {}".format(field_name, value),
            )
            return None
        parsed = int(as_float)
        if parsed < 1:
            action_result.set_status(
                phantom.APP_ERROR,
                "'{}' must be a positive whole number, got: {}".format(field_name, parsed),
            )
            return None
        return parsed

    def _limit_from(self, param, action_result):
        """Every list call is bounded -- an unbounded call times out
        server-side on the real APIM -- but the bound is the caller's to
        raise, not a hardcoded 1."""
        return self._validate_int(param.get("limit", DEFAULT_LIMIT), "limit", action_result)

    def _parse_class_parameters(self, raw):
        """SOLIDserver packs custom attributes as a query-string-style blob,
        e.g. 'key1=val1&key2=val2&'."""
        if not raw:
            return {}
        return dict(parse_qsl(raw.rstrip("&"), keep_blank_values=True))

    def _sql_escape(self, value):
        """Escape a value for SOLIDserver's SQL-ANSI-style WHERE clause."""
        return value.replace("'", "''")

    def _bounded_query(self, limit, where=None):
        """Build the query params. NEVER send `WHERE` and `limit` together.

        The backend's behaviour across the four combinations:

            WHERE   limit   result
            no      no      times out -- unbounded full scan (v1.0.2)
            no      yes     works     -- what test_connectivity does
            yes     no      works     -- slower, the filter is doing real work
            yes     yes     FAILS     -- backend aborts, returns HTTP 401

        A WHERE already bounds the query, so limit alongside one is redundant
        and actively harmful.

        A caller's limit is still honoured on a filtered call, applied
        client-side after the response -- see _apply_client_limit.
        """
        return {"WHERE": where} if where else {"limit": limit}

    def _apply_client_limit(self, records, limit, where):
        """Honour `limit` on a filtered call, where it cannot go on the wire.

        Only truncates when a WHERE was sent; an unfiltered call was already
        bounded server-side.
        """
        return records[:limit] if where else records

    def _select_optional_filter(self, param, filter_map, action_result):
        """Pick at most one supplied filter, returning (where_column, value).

        Returns (None, None) when nothing is set, which is a legal call, not an
        error: ip_block_subnet_list needs no filter params at all -- that bare
        bounded shape is what test connectivity has always used and the one
        confirmed to work on the real APIM. It is also what to fall back to
        when a WHERE clause is rejected by the gateway rather than the backend.

        At most one, never two: the WHERE clause has only ever been confirmed
        carrying a single column='value' condition, so composing two would be a
        coded guess of the same kind that shipped as WHERE=name='...'.

        Returns (ok, column, value). ok is False only on the two-filter error,
        with action_result already failed -- "no filter" is a success with
        column None, so the caller never has to infer intent from status.
        """
        supplied = []
        for name in filter_map:
            value = param.get(name) or ""
            if value.strip():
                supplied.append((name, value.strip()))

        if not supplied:
            return True, None, None
        if len(supplied) > 1:
            action_result.set_status(
                phantom.APP_ERROR,
                "Set exactly ONE filter, got {}. This service is only confirmed to accept "
                "a single WHERE condition; combining filters is not supported.".format(
                    ", ".join(name for name, _ in supplied)
                ),
            )
            return False, None, None

        param_name, value = supplied[0]
        return True, filter_map[param_name], value

    # ---- Cert Handling (same PEM-normalize-to-tempfile pattern as cyberark_ccp) ----

    def _normalize_pem(self, pem_string):
        if not pem_string:
            return pem_string

        pem_string = pem_string.strip()
        normalized_blocks = []

        block_types = [
            ("-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"),
            ("-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"),
            ("-----BEGIN RSA PRIVATE KEY-----", "-----END RSA PRIVATE KEY-----"),
            ("-----BEGIN EC PRIVATE KEY-----", "-----END EC PRIVATE KEY-----"),
        ]

        for header, footer in block_types:
            parts = pem_string.split(header)
            for part in parts:
                if footer in part:
                    body, _ = part.split(footer, 1)
                    body = "".join(body.split())
                    lines = []
                    while body:
                        lines.append(body[:64])
                        body = body[64:]
                    block = header + "\n" + "\n".join(lines) + "\n" + footer
                    normalized_blocks.append(block)

        if not normalized_blocks:
            return pem_string

        return "\n".join(normalized_blocks)

    def _setup_cert_files(self):
        config = self.get_config()
        cert_pem = config.get("client_cert", "")
        key_pem = config.get("client_key", "")

        if not cert_pem or not key_pem:
            raise ValueError("client_cert and client_key are required for mTLS")

        cert_pem = self._normalize_pem(cert_pem)
        key_pem = self._normalize_pem(key_pem)
        ca_pem = config.get("client_ca", "")
        if ca_pem:
            ca_pem = self._normalize_pem(ca_pem)

        written_paths = []
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
            self._cleanup_temp_files(*written_paths)
            raise

        return cert_file.name, key_file.name, ca_path

    def _cleanup_temp_files(self, *file_paths):
        for path in file_paths:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    # ---- Utility ----

    def _get_error_message_from_exception(self, e):
        error_code = None
        error_message = "Error message unavailable"
        try:
            if hasattr(e, "args") and e.args:
                if len(e.args) > 1:
                    error_code = e.args[0]
                    error_message = e.args[1]
                elif len(e.args) == 1:
                    error_message = e.args[0]
        except Exception:
            pass

        if not error_code:
            return "Error Message: {}".format(error_message)
        return "Error Code: {}. Error Message: {}".format(error_code, error_message)


# ---- Entry Point ----

def main():
    import argparse

    argparser = argparse.ArgumentParser()
    argparser.add_argument("input_test_json", help="Input Test JSON file")
    args = argparser.parse_args()

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = EfficientipDdiClassicConnector()
        connector.print_progress_message = True
        result = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(result), indent=4))

    exit(0)


if __name__ == "__main__":
    main()
