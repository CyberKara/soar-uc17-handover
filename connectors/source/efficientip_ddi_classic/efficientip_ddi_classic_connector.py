# efficientip_ddi_classic_connector.py
"""EfficientIP DDI (Classic) SOAR Connector - classic BaseConnector twin of the
SDK-based efficientip_ddi app, built for side-by-side airgapped comparison.

Same auth model, same endpoints, same corrected field names as the SDK
version (soar-connectors/connectors/efficientip_ddi/src/app.py) -- see that
app's README for the full research/field-name provenance. This file exists
purely so the user can install both connector styles against the real
airgapped SOLIDserver instance and compare behavior; it is not meant to
replace the SDK connector as the maintained implementation.

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
    DEFAULT_TIMEOUT,
    IP_ADDRESS_LIST_PATH,
    IP_ALIAS_LIST_PATH,
    IP_BLOCK_SUBNET_LIST_PATH,
    IP_POOL_LIST_PATH,
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
        # real APIM that needs no filter/params at all.
        ret_val, _ = self._make_rest_call("GET", IP_BLOCK_SUBNET_LIST_PATH, None, action_result)

        if phantom.is_fail(ret_val):
            self.save_progress("Test Connectivity Failed")
            return action_result.get_status()

        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS, "Test connectivity successful")

    def _handle_get_ip_address(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting get ip address action")

        address = param["address"]
        hex_addr = self._ip_to_hex(address)

        ret_val, records = self._make_rest_call(
            "GET", IP_ADDRESS_LIST_PATH, {"WHERE": "ip_addr='{}'".format(hex_addr)}, action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            return action_result.set_status(
                phantom.APP_ERROR, "No IP address record found in SOLIDserver for {}".format(address)
            )

        record = records[0]
        class_params = self._parse_class_parameters(record.get("ip_class_parameters", ""))

        action_result.add_data({
            "address": address,
            "ip_id": record.get("ip_id", ""),
            "subnet": record.get("subnet_name", ""),
            "space": record.get("site_name", ""),
            "status": record.get("multistatus", ""),
            "hostname": record.get("name", ""),
            "mac_address": record.get("mac_addr", ""),
            "ddi_class": record.get("ip_class_name", ""),
            "description": class_params.get("description", ""),
        })
        summary = action_result.update_summary({})
        summary["total_objects"] = 1
        summary["total_objects_successful"] = 1

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully retrieved IP address record")

    def _handle_list_subnets(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting list subnets action")

        name = param["name"]
        ret_val, records = self._make_rest_call(
            "GET", IP_BLOCK_SUBNET_LIST_PATH, {"WHERE": "subnet_name='{}'".format(self._sql_escape(name))}, action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            return action_result.set_status(phantom.APP_ERROR, "No subnet found in SOLIDserver for {}".format(name))

        record = records[0]
        class_params = self._parse_class_parameters(record.get("subnet_class_parameters", ""))

        action_result.add_data({
            "subnet_id": record.get("subnet_id", ""),
            "subnet_name": record.get("subnet_name", name),
            "parent_subnet": record.get("parent_subnet_name", ""),
            "space": record.get("site_name", ""),
            "start_address": record.get("subnet_start_ip_addr", ""),
            "end_address": record.get("subnet_end_ip_addr", ""),
            "size": str(record.get("subnet_size", "")),
            "ddi_class": record.get("subnet_class_name", ""),
            "description": class_params.get("description", ""),
            "raw_json": json.dumps(record),
        })
        summary = action_result.update_summary({})
        summary["total_objects"] = 1
        summary["total_objects_successful"] = 1

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully retrieved subnet record")

    def _handle_get_ip_pool(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting get ip pool action")

        name = param["name"]
        ret_val, records = self._make_rest_call(
            "GET", IP_POOL_LIST_PATH, {"WHERE": "pool_name='{}'".format(self._sql_escape(name))}, action_result
        )
        if phantom.is_fail(ret_val):
            return action_result.get_status()

        records = self._ensure_list(records, action_result)
        if records is None:
            return action_result.get_status()
        if not records:
            return action_result.set_status(phantom.APP_ERROR, "No IP pool found in SOLIDserver for {}".format(name))

        record = records[0]
        class_params = self._parse_class_parameters(record.get("pool_class_parameters", ""))

        action_result.add_data({
            "pool_id": record.get("pool_id", ""),
            "pool_name": record.get("pool_name", name),
            "subnet": record.get("subnet_name", ""),
            "space": record.get("site_name", ""),
            "start_address": record.get("start_hostaddr", ""),
            "end_address": record.get("end_hostaddr", ""),
            "ddi_class": record.get("pool_class_name", ""),
            "description": class_params.get("description", ""),
            "raw_json": json.dumps(record),
        })
        summary = action_result.update_summary({})
        summary["total_objects"] = 1
        summary["total_objects_successful"] = 1

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully retrieved IP pool record")

    def _handle_list_aliases(self, param):
        action_result = self.add_action_result(ActionResult(dict(param)))
        self.save_progress("DEBUG GUI: Starting list aliases action")

        ip_id = param["ip_id"]
        ret_val, records = self._make_rest_call(
            "GET", IP_ALIAS_LIST_PATH.format(ip_id=ip_id), None, action_result
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

        action_result.add_data({
            "ip_id": str(ip_id),
            "alias_name": records[0].get("alias_name", ""),
            "raw_json": json.dumps(records),
        })
        summary = action_result.update_summary({})
        summary["total_objects"] = 1
        summary["total_objects_successful"] = 1

        return action_result.set_status(phantom.APP_SUCCESS, "Successfully retrieved alias record")

    # ---- REST Call Wrapper ----

    def _make_rest_call(self, method, path, params, action_result):
        """Execute an APIM call with mTLS cert setup + 3-layer auth, cleanup.

        Returns:
            tuple: (status, response_data) - RetVal pattern
        """
        config = self.get_config()
        url = "{}{}".format(self._base_url, path)
        headers = self._auth_headers(config)
        headers["Content-Type"] = "application/json"

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
            data = {}
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
        basic = base64.b64encode(
            "{}:{}".format(config["client_id"], config["client_secret"]).encode()
        ).decode()
        return {
            "Authorization": "Basic {}".format(basic),
            "X-DDI-Username": base64.b64encode(config["ddi_username"].encode()).decode(),
            "X-DDI-Password": base64.b64encode(config["ddi_password"].encode()).decode(),
        }

    def _ip_to_hex(self, address):
        """SOLIDserver's ip_addr filter field takes the address as hex, not
        dotted-decimal."""
        return ipaddress.ip_address(address).packed.hex()

    def _parse_class_parameters(self, raw):
        """SOLIDserver packs custom attributes as a query-string-style blob,
        e.g. 'key1=val1&key2=val2&'."""
        if not raw:
            return {}
        return dict(parse_qsl(raw.rstrip("&"), keep_blank_values=True))

    def _sql_escape(self, value):
        """Escape a value for SOLIDserver's SQL-ANSI-style WHERE clause."""
        return value.replace("'", "''")

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
