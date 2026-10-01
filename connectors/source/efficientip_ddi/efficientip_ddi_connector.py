# efficientip_ddi_connector.py
"""EfficientIP DDI SOAR Connector - IPAM enrichment against SOLIDserver via APIM.

Classic BaseConnector style, a recorded exemption from FR-01 in
docs/dev-rules.md: the App Debugger cannot dispatch actions for SDK-based apps,
and on an airgapped appliance that panel is the operator's only way to run an
action by hand. The README holds the field-name provenance and the history.

Auth (3 layers, every request):
  1. mTLS -- client_cert/client_key (+ optional client_ca).
  2. Authorization: Basic base64(client_id:client_secret) -- the APIM app
     credential. No OAuth token exchange.
  3. X-IPM-Username / X-IPM-Password -- each base64(value), forwarded by the
     APIM to SOLIDserver's own backend auth.
"""

import base64
import ipaddress
import json
import os
import tempfile
import time
from urllib.parse import parse_qsl

import requests

import phantom.app as phantom
from phantom.action_result import ActionResult
from phantom.base_connector import BaseConnector

from efficientip_ddi_consts import (
    APIM_TRANS_ID_HEADER,
    BACKSIDE_TRANSPORT_HEADER,
    BAD_REQUEST_STATUS,
    DDI_PASSWORD_HEADER,
    DDI_USERNAME_HEADER,
    DEFAULT_LIMIT,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_COUNT,
    DEFAULT_TIMEOUT,
    HTTP_STATUS_UNAUTHORIZED,
    IP_ADDRESS_LIST_PATH,
    IP_BLOCK_SUBNET_LIST_PATH,
    LIST_SUBNETS_FILTERS,
    MAX_RETRY_BACKOFF,
    MAX_RETRY_COUNT,
    RETRYABLE_STATUS,
)

# Characters of a response body shown in the debug line.
DEBUG_BODY_CHARS = 500


class EfficientipDdiConnector(BaseConnector):
    """EfficientIP SOLIDserver via APIM connector for Splunk SOAR."""

    def __init__(self):
        super(EfficientipDdiConnector, self).__init__()
        self._base_url = None

    def initialize(self):
        self._base_url = self.get_config().get("base_url", "").rstrip("/")
        return phantom.APP_SUCCESS

    def finalize(self):
        return phantom.APP_SUCCESS

    def handle_action(self, param):
        action_id = self.get_action_identifier()
        self.debug_print("action_id", action_id)

        action_mapping = {
            "test_connectivity": self._handle_test_connectivity,
            "get_ip_address": self._handle_get_ip_address,
            "list_subnets": self._handle_list_subnets,
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

    # ---- Actions ----

    def _handle_test_connectivity(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("Testing connectivity to the APIM")

        # SOLIDserver has no health-check service; a bounded subnet list is the
        # cheapest call confirmed to work on the real APIM with no filter.
        ret_val, _ = self._make_rest_call(IP_BLOCK_SUBNET_LIST_PATH, {"limit": 1}, action_result)

        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS, "Test connectivity successful")

    def _handle_get_ip_address(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))

        address = param["address"]
        query_addr = self._validate_ip(address, action_result)
        if query_addr is None:
            return action_result.get_status()
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        # hostaddr is the dotted filter column (host_addr answers sql_error 7 on
        # the target appliance).
        ret_val, records = self._make_rest_call(
            IP_ADDRESS_LIST_PATH, self._bounded_query(limit, "hostaddr='{}'".format(query_addr)), action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            message = "No IP address record found in SOLIDserver for {}".format(address)
            if ipaddress.ip_address(query_addr).version == 6:
                # hostaddr is confirmed for IPv4 only.
                message += (
                    " (IPv6: lookups are unverified on this API -- SOLIDserver may keep "
                    "IPv6 addresses outside ip_address_list, so not found is not proof of absence)"
                )
            return action_result.set_status(phantom.APP_ERROR, message)

        # Raw pass-through: every key SOLIDserver returns is forwarded as-is
        # (curated field names were wrong several times). One data item per
        # record, so raising "limit" never silently drops rows.
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

        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        # Resolved before the call, so an ambiguous filter never reaches the APIM.
        # No filter is legal: it lists subnets bare, bounded by limit.
        ok, column, value = self._select_optional_filter(param, LIST_SUBNETS_FILTERS, action_result)
        if not ok:
            return action_result.get_status()

        where = "{}='{}'".format(column, self._sql_escape(value)) if column else None
        ret_val, records = self._make_rest_call(
            IP_BLOCK_SUBNET_LIST_PATH, self._bounded_query(limit, where), action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            where = " for {}='{}'".format(column, value) if column else ""
            return action_result.set_status(
                phantom.APP_ERROR, "No subnet found in SOLIDserver{}".format(where)
            )

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

    # ---- REST ----

    def _make_rest_call(self, path, params, action_result):
        """GET an APIM service with mTLS + 3-layer auth; returns (status, data).

        An HTTP 401 is retried (linear backoff, asset-configurable) unless the
        gateway reports it reached SOLIDserver: the APIM's backend leg fails on
        about one call in three and answers 401 itself (X-Backside-Transport:
        FAIL FAIL), and a retry re-picks a backend member.
        """
        config = self.get_config()
        url = "{}{}".format(self._base_url, path)
        headers = self._auth_headers(config)
        # No Content-Type: every call is a bodiless GET.
        headers["Accept"] = "application/json"
        headers["Cache-Control"] = "no-cache"  # as the vendor's reference client sends

        cert_path = key_path = ca_path = None
        session = None
        try:
            cert_path, key_path, ca_path = self._setup_cert_files()

            verify_ssl = config.get("verify_ssl", True)
            verify = ca_path if (verify_ssl and ca_path) else verify_ssl
            if verify is True:
                # trust_env is off below, so honour the platform's CA bundle
                # explicitly when no client_ca is set.
                verify = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE") or True

            # trust_env=False: requests would otherwise let ~/.netrc replace the
            # Authorization header and HTTPS_PROXY intercept the mTLS handshake,
            # both of which surface as a 401 that is invisible in the request.
            session = requests.Session()
            session.trust_env = False
            session.proxies = {}

            attempts, backoff = self._retry_plan()
            for attempt in range(1, attempts + 1):
                response = session.request(
                    "GET", url, headers=headers, params=params,
                    cert=(cert_path, key_path), verify=verify, timeout=DEFAULT_TIMEOUT,
                )
                self._debug_line(response)

                if response.status_code not in RETRYABLE_STATUS or self._backend_leg_ok(response):
                    break
                if attempt < attempts and backoff:
                    time.sleep(backoff * attempt)

            if response.ok and attempt > 1:
                # Visible on purpose: the operator reports the gateway fault upstream.
                self.save_progress("Succeeded on attempt {} of {} (earlier attempt(s) returned HTTP {})".format(
                    attempt, attempts, HTTP_STATUS_UNAUTHORIZED,
                ))

            return self._process_response(response, action_result, attempt)

        except requests.exceptions.SSLError as e:
            return action_result.set_status(phantom.APP_ERROR, "TLS/mTLS error connecting to APIM: {}".format(e)), None
        except requests.exceptions.ConnectionError as e:
            return action_result.set_status(phantom.APP_ERROR, "Could not reach APIM: {}".format(e)), None
        except requests.exceptions.RequestException as e:
            return action_result.set_status(phantom.APP_ERROR, "Error connecting to APIM: {}".format(e)), None
        finally:
            if session is not None:
                session.close()
            self._cleanup_temp_files(cert_path, key_path, ca_path)

    def _process_response(self, response, action_result, attempts=1):
        content_type = response.headers.get("Content-Type", "")

        if "json" in content_type:
            try:
                data = response.json()
            except ValueError as e:
                return action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response: {}".format(e)), None
        elif not response.content:
            # HTTP 204 (empty body) is the APIM's "no matching records".
            data = []
        elif response.ok:
            return action_result.set_status(
                phantom.APP_ERROR,
                "Unexpected non-JSON response (status {}, content-type {}): {}".format(
                    response.status_code, content_type or "unknown", response.text[:200]
                ),
            ), None
        else:
            data = {}

        if response.ok:
            return phantom.APP_SUCCESS, data

        detail = self._error_detail(data, response)

        if response.status_code in BAD_REQUEST_STATUS:
            # On this API 403 is the gateway's bad request, 400 the backend's.
            message = (
                "EfficientIP/APIM returned HTTP {}, which on this API means BAD REQUEST "
                "-- 403 is not a permissions problem and 400 comes from the SOLIDserver "
                "backend. Check the request itself (filter column names, WHERE syntax "
                "-- values must be single-quoted -- and limit) before checking "
                "credentials: {}".format(response.status_code, detail)
            )
        elif response.status_code == HTTP_STATUS_UNAUTHORIZED:
            message = "EfficientIP/APIM returned HTTP 401 (unauthorized){}: {}{}".format(
                "" if self._backend_leg_ok(response) else " on all {} attempt(s)".format(attempts),
                detail,
                self._unauthorized_hint(response),
            )
        else:
            message = "EfficientIP/APIM returned HTTP {}: {}".format(response.status_code, detail)

        return action_result.set_status(phantom.APP_ERROR, message), None

    def _error_detail(self, data, response):
        """The gateway answers {"message": ...}; the SOLIDserver backend answers a
        bad WHERE with [{"errno": ..., "sql_error": ...}] and no message."""
        if isinstance(data, dict) and data:
            return data.get("message") or response.text
        if isinstance(data, list) and data and isinstance(data[0], dict):
            fields = ", ".join("{}={}".format(k, v) for k, v in data[0].items() if v not in (None, ""))
            if fields:
                return "SOLIDserver error ({})".format(fields)
        return response.text

    def _backend_leg_ok(self, response):
        """True when the gateway reached SOLIDserver (X-Backside-Transport all OK):
        a 401 then is the backend's own credential verdict. FAIL, or no header,
        stays retryable."""
        tokens = (response.headers.get(BACKSIDE_TRANSPORT_HEADER) or "").upper().split()
        return bool(tokens) and all(token == "OK" for token in tokens)

    def _unauthorized_hint(self, response):
        """What a 401 means, read off the gateway's headers -- the two causes need
        opposite actions from the operator."""
        backside = response.headers.get(BACKSIDE_TRANSPORT_HEADER)
        trans_id = response.headers.get(APIM_TRANS_ID_HEADER)
        trans = " {}={}".format(APIM_TRANS_ID_HEADER, trans_id) if trans_id else ""
        if self._backend_leg_ok(response):
            return (
                " -- {}: {}, so SOLIDserver itself rejected the request: check "
                "ddi_username/ddi_password on the asset.{}".format(BACKSIDE_TRANSPORT_HEADER, backside, trans)
            )
        if backside and "FAIL" in backside.upper():
            return (
                " -- {}: {}, so the APIM could not reach its backend and answered 401 "
                "itself. Not a credential problem: escalate to the APIM administrator "
                "with this call's transaction id.{}".format(BACKSIDE_TRANSPORT_HEADER, backside, trans)
            )
        return " -- no {} header: check client_id/client_secret and the client certificate.{}".format(
            BACKSIDE_TRANSPORT_HEADER, trans,
        )

    def _debug_line(self, response):
        """One line per call when the asset's debug_logging is on, via
        save_progress (the only channel an operator without a shell sees).
        The URL carries only limit/WHERE; credentials are in headers, never shown."""
        if not self.get_config().get("debug_logging"):
            return
        sent = getattr(response, "request", None)
        body = (response.text or "")[:DEBUG_BODY_CHARS]
        self.save_progress("GET {} -> HTTP {}  {}={}  {}={}  body: {}".format(
            getattr(sent, "url", "?"), response.status_code,
            BACKSIDE_TRANSPORT_HEADER, response.headers.get(BACKSIDE_TRANSPORT_HEADER, "-"),
            APIM_TRANS_ID_HEADER, response.headers.get(APIM_TRANS_ID_HEADER, "-"),
            body or "(empty)",
        ))

    def _ensure_list(self, data, action_result):
        """List services return a bare JSON array; fail clearly on anything else."""
        if not isinstance(data, list):
            action_result.set_status(
                phantom.APP_ERROR,
                "Unexpected response shape from SOLIDserver (expected a JSON array, got {}): {}".format(
                    type(data).__name__, str(data)[:200]
                ),
            )
            return None
        return data

    # ---- Config / input helpers ----

    def _bounded_config_number(self, key, default, minimum, maximum):
        """A numeric asset field, clamped to [minimum, maximum]; default on bad input."""
        raw = self.get_config().get(key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return min(max(value, minimum), maximum)

    def _retry_plan(self):
        """(total attempts, base backoff seconds) for this asset."""
        attempts = int(self._bounded_config_number("retry_count", DEFAULT_RETRY_COUNT, 1, MAX_RETRY_COUNT))
        backoff = self._bounded_config_number("retry_backoff", DEFAULT_RETRY_BACKOFF, 0, MAX_RETRY_BACKOFF)
        return attempts, backoff

    def _auth_headers(self, config):
        # Stripped: a pasted trailing newline would otherwise become part of the
        # credential and fail as an indistinguishable 401.
        client_id = config["client_id"].strip()
        client_secret = config["client_secret"].strip()
        ddi_username = config["ddi_username"].strip()
        ddi_password = config["ddi_password"].strip()

        basic = base64.b64encode("{}:{}".format(client_id, client_secret).encode()).decode()
        return {
            "Authorization": "Basic {}".format(basic),
            DDI_USERNAME_HEADER: base64.b64encode(ddi_username.encode()).decode(),
            DDI_PASSWORD_HEADER: base64.b64encode(ddi_password.encode()).decode(),
        }

    def _validate_ip(self, address, action_result):
        """Return the normalised address (IPv6 compressed), or fail the action for
        anything that is not a single IP (hostname, CIDR, typo)."""
        try:
            return str(ipaddress.ip_address(address))
        except ValueError:
            action_result.set_status(
                phantom.APP_ERROR,
                "'{}' is not a valid IP address -- this action takes a single "
                "IPv4 or IPv6 address, not a hostname, CIDR range, or URL".format(address),
            )
            return None

    def _validate_int(self, value, field_name, action_result):
        """A positive whole number, accepting SOAR's 5.0 / "5" forms."""
        try:
            as_float = float(str(value).strip())
        except (TypeError, ValueError):
            as_float = None
        if as_float is None or as_float != int(as_float):
            action_result.set_status(
                phantom.APP_ERROR, "'{}' must be a whole number, got: {}".format(field_name, value)
            )
            return None
        parsed = int(as_float)
        if parsed < 1:
            action_result.set_status(
                phantom.APP_ERROR, "'{}' must be a positive whole number, got: {}".format(field_name, parsed)
            )
            return None
        return parsed

    def _limit_from(self, param, action_result):
        """Every list call is bounded (unbounded ones time out on the real APIM)."""
        return self._validate_int(param.get("limit", DEFAULT_LIMIT), "limit", action_result)

    def _parse_class_parameters(self, raw):
        """SOLIDserver packs custom attributes as 'key1=val1&key2=val2&'."""
        if not raw:
            return {}
        return dict(parse_qsl(raw.rstrip("&"), keep_blank_values=True))

    def _sql_escape(self, value):
        return value.replace("'", "''")

    def _bounded_query(self, limit, where=None):
        """limit ALWAYS goes on the wire (first, like the working curl); WHERE
        and limit together are fine on the real appliance."""
        return {"limit": limit, "WHERE": where} if where else {"limit": limit}

    def _select_optional_filter(self, param, filter_map, action_result):
        """At most one filter (only a single WHERE condition is confirmed).

        Returns (ok, where_column, value); (True, None, None) when none is set.
        """
        supplied = [(name, (param.get(name) or "").strip()) for name in filter_map]
        supplied = [(name, value) for name, value in supplied if value]

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

    # ---- Cert handling (PEM normalised to temp files, as cyberark_ccp) ----

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
            for part in pem_string.split(header):
                if footer in part:
                    body = "".join(part.split(footer, 1)[0].split())
                    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
                    normalized_blocks.append(header + "\n" + "\n".join(lines) + "\n" + footer)

        return "\n".join(normalized_blocks) if normalized_blocks else pem_string

    def _setup_cert_files(self):
        config = self.get_config()
        cert_pem = config.get("client_cert", "")
        key_pem = config.get("client_key", "")
        if not cert_pem or not key_pem:
            raise ValueError("client_cert and client_key are required for mTLS")

        ca_pem = config.get("client_ca", "")
        contents = [self._normalize_pem(cert_pem), self._normalize_pem(key_pem)]
        if ca_pem:
            contents.append(self._normalize_pem(ca_pem))

        written_paths = []
        try:
            for content in contents:
                handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
                written_paths.append(handle.name)
                handle.write(content)
                handle.close()
        except Exception:
            self._cleanup_temp_files(*written_paths)
            raise

        ca_path = written_paths[2] if ca_pem else None
        return written_paths[0], written_paths[1], ca_path

    def _cleanup_temp_files(self, *file_paths):
        for path in file_paths:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _get_error_message_from_exception(self, e):
        error_code = None
        error_message = "Error message unavailable"
        try:
            if hasattr(e, "args") and e.args:
                if len(e.args) > 1:
                    error_code, error_message = e.args[0], e.args[1]
                else:
                    error_message = e.args[0]
        except Exception:
            pass

        if not error_code:
            return "Error Message: {}".format(error_message)
        return "Error Code: {}. Error Message: {}".format(error_code, error_message)


def main():
    import argparse

    argparser = argparse.ArgumentParser()
    argparser.add_argument("input_test_json", help="Input Test JSON file")
    args = argparser.parse_args()

    with open(args.input_test_json) as f:
        in_json = json.loads(f.read())
        print(json.dumps(in_json, indent=4))

        connector = EfficientipDdiConnector()
        connector.print_progress_message = True
        result = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(result), indent=4))

    exit(0)


if __name__ == "__main__":
    main()
