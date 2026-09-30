# efficientip_ddi_connector.py
"""EfficientIP DDI SOAR Connector - IPAM enrichment against SOLIDserver via APIM.

Classic BaseConnector style (see the README). Auth, on every request:
  1. mTLS -- client_cert/client_key (+ optional client_ca) presented to APIM.
  2. Authorization: Basic base64(client_id:client_secret) -- the APIM app credential.
  3. X-IPM-Username / X-IPM-Password -- forwarded by APIM to SOLIDserver's own
     backend auth, each value base64-encoded independently.

Design notes and investigation history:
docs/efficientip_ddi_implementation_notes.md
"""

import base64
import hashlib
import ipaddress
import json
import os
import socket
import tempfile
import time
from urllib.parse import parse_qsl, urlsplit

import requests

import phantom.app as phantom
from phantom.action_result import ActionResult
from phantom.base_connector import BaseConnector

from efficientip_ddi_consts import (
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


class EfficientipDdiConnector(BaseConnector):
    """EfficientIP SOLIDserver via APIM connector for Splunk SOAR."""

    def __init__(self):
        super(EfficientipDdiConnector, self).__init__()
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

        # No health-check service exists. ip_block_subnet_list needs no filter;
        # limit=1 is required, since a list call with neither WHERE nor limit
        # times out server-side.
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
        query_addr = self._validate_ip(address, action_result)
        if query_addr is None:
            return action_result.get_status()
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        ret_val, records = self._make_rest_call(
            "GET", IP_ADDRESS_LIST_PATH,
            self._bounded_query(limit, "hostaddr='{}'".format(query_addr)), action_result
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

        # Raw pass-through, one data item per record: SOLIDserver's own field
        # names were wrong under manual mapping, and data.* is a list datapath.
        # address and description (from ip_class_parameters) are added as
        # convenience keys.
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

        # Resolved before the call, so an ambiguous filter fails without
        # touching the APIM. No filter is legal: a bounded bare list.
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
        if not records:
            where = " for {}='{}'".format(column, value) if column else ""
            return action_result.set_status(
                phantom.APP_ERROR, "No subnet found in SOLIDserver{}".format(where)
            )

        # Raw pass-through, one data item per record (see
        # _handle_get_ip_address).
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

    # ---- REST Call Wrapper ----

    # ---- Diagnostics ----
    #
    # Written through save_progress, the only channel that reaches an operator
    # with no shell (App Debugger panel and action result). add_debug_data() is
    # dropped before the result is persisted.

    # Values never printed. Request side: the three auth headers. Response
    # side: anything that hands back a session.
    _SENSITIVE_HEADERS = frozenset({
        "authorization", DDI_USERNAME_HEADER.lower(), DDI_PASSWORD_HEADER.lower(),
        "set-cookie", "cookie", "proxy-authorization", "www-authenticate-token",
    })

    # Response bodies are logged whole up to this limit, then truncated with a
    # marker.
    _BODY_LOG_LIMIT = 2000

    def _dbg(self, message):
        """Emit a diagnostic line when the asset's debug_logging is on.

        Off by default: the full exchange (request, headers, peer, timings,
        body) buries the action result on a normal run.
        """
        if not self.get_config().get("debug_logging"):
            return
        self.save_progress("DEBUG GUI: {}".format(message))

    def _body_preview(self, text):
        """Render a body for the log, flagging truncation explicitly."""
        if not text:
            return "(empty)"
        if len(text) <= self._BODY_LOG_LIMIT:
            return text
        return "{} ... (truncated, {} chars total)".format(text[:self._BODY_LOG_LIMIT], len(text))

    def _fingerprint(self, material):
        """Identify PEM material without printing it (length + SHA-256 prefix), so
        runs can be compared.
        """
        if not material:
            return "absent"
        digest = hashlib.sha256(material.encode()).hexdigest()[:16]
        return "len={} sha256:{}".format(len(material), digest)

    def _format_headers(self, headers):
        """Render headers with sensitive values replaced by their length."""
        rendered = []
        for name, value in dict(headers or {}).items():
            if name.lower() in self._SENSITIVE_HEADERS:
                rendered.append("{}=<redacted len={}>".format(name, len(value or "")))
            else:
                rendered.append("{}={}".format(name, value))
        return "; ".join(rendered) if rendered else "(none)"

    def _resolve_peers(self, url):
        """List every address the APIM hostname resolves to (one bad node of
        several looks intermittent).
        """
        try:
            parts = urlsplit(url)
            host = parts.hostname
            if not host:
                return "unparsable url"
            port = parts.port or (443 if parts.scheme == "https" else 80)
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            addresses = sorted({info[4][0] for info in infos})
            summary = "{} -> {}".format(host, ", ".join(addresses))
            if len(addresses) > 1:
                # Several addresses behind one name: compare the peer line
                # across a failing and a succeeding run.
                summary += "  [!] {} addresses -- compare the peer line across a failing and a succeeding run".format(
                    len(addresses),
                )
            return summary
        except Exception as e:  # never let diagnostics fail an action
            return "resolution failed: {}".format(e)

    def _peer_address(self, response):
        """The address that actually served this call.

        Only readable while the connection is held, so the request is issued
        with stream=True and this is called before .content is read. The socket
        hangs off the response at different private paths across urllib3
        versions, so the known layouts are tried in turn. Best-effort:
        diagnostics never fail an action.
        """
        candidate_paths = (
            "_connection.sock",
            "_fp.fp.raw._sock",
            "_original_response.fp.raw._sock",
            "_fp.fp._sock",
            "_sock",
        )
        for path in candidate_paths:
            try:
                target = response.raw
                for attribute in path.split("."):
                    target = getattr(target, attribute)
                peer = target.getpeername()
                return "{}:{}".format(peer[0], peer[1])
            except Exception:
                continue
        return "unavailable"

    # curl supplies these itself. Lowercased: requests preserves the case that
    # set a header.
    _CURL_SUPPLIED_HEADERS = frozenset({"host", "content-length"})
    # Replayed as shell variables further down, never as values.
    _SECRET_HEADERS = frozenset({"authorization", DDI_USERNAME_HEADER.lower(), DDI_PASSWORD_HEADER.lower()})

    def _dbg_curl_equivalent(self, response):
        """Print a runnable curl equivalent of this exact request.

        URL and headers are read back off the PreparedRequest. The client cert
        is a placeholder and the three credentials are shell variables, never
        values, so the log carries no secret.
        """
        try:
            sent = getattr(response, "request", None)
            if sent is None:
                return
            config = self.get_config()
            parts = [
                # No backslash escapes in this line: it travels through a JSON
                # log record.
                "curl -sS -o /dev/null -D -",
                "--cert <your client_cert>.pem --key <your client_key>.pem",
            ]
            if config.get("client_ca"):
                parts.append("--cacert <your client_ca>.pem")
            # Every header actually on the wire, read off the PreparedRequest
            # (requests adds Accept-Encoding and Connection itself), not an
            # allowlist.
            for name, value in sent.headers.items():
                lowered = name.lower()
                if lowered in self._CURL_SUPPLIED_HEADERS or lowered in self._SECRET_HEADERS:
                    continue
                parts.append("-H '{}: {}'".format(name, value))
            parts.extend([
                '-H "Authorization: Basic $BASIC_B64"',
                '-H "{}: $DDI_USER_B64"'.format(DDI_USERNAME_HEADER),
                '-H "{}: $DDI_PASS_B64"'.format(DDI_PASSWORD_HEADER),
                "'{}'".format(sent.url),
            ])
            self._dbg("curl equivalent (export the 3 vars first): {}".format(" ".join(parts)))
            self._dbg(
                "  BASIC_B64=$(printf %s '<client_id>:<client_secret>' | base64 -w0); "
                "DDI_USER_B64=$(printf %s '<ddi_username>' | base64 -w0); "
                "DDI_PASS_B64=$(printf %s '<ddi_password>' | base64 -w0)"
            )
        except Exception as e:
            self._dbg("curl equivalent unavailable: {}: {}".format(type(e).__name__, e))

    def _dbg_ambient_env(self):
        """Report the ambient settings requests would honour and this connector
        disables.

        With trust_env on, requests would replace the Authorization header from
        ~/.netrc, route through HTTPS_PROXY (terminating TLS ahead of the APIM)
        and override verify from REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE. Logging
        what was present says whether any was in play.
        """
        try:
            names = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                     "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy",
                     "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
            present = {n: os.environ[n] for n in names if os.environ.get(n)}
            self._dbg("ambient env (ignored, trust_env=False): {}".format(present or "(none set)"))
            netrc_found = [
                path for path in (
                    os.path.expanduser("~/.netrc"), os.path.expanduser("~/_netrc"),
                )
                if os.path.exists(path)
            ]
            self._dbg("netrc (ignored, trust_env=False): {}".format(
                ", ".join(netrc_found) if netrc_found else "(none present)",
            ))
        except Exception as e:
            self._dbg("ambient env unreadable: {}: {}".format(type(e).__name__, e))

    def _dbg_exchange(self, response, peer, headers_ms, elapsed_ms, attempt=1, attempts=1):
        """Log the whole exchange, best-effort: a diagnostic must never fail an
        action.
        """
        try:
            self._dbg("attempt {}/{}: HTTP {} from peer {} -- {:.0f} ms to headers, {:.0f} ms total".format(
                attempt, attempts, response.status_code, peer, headers_ms, elapsed_ms,
            ))
            # Read back off the PreparedRequest: the URL as encoded and every
            # header requests added.
            sent = getattr(response, "request", None)
            if sent is not None:
                self._dbg("sent: {} {}".format(sent.method, sent.url))
                self._dbg("sent headers: {}".format(self._format_headers(sent.headers)))
                if sent.body:
                    self._dbg("sent body: {}".format(self._body_preview(
                        sent.body.decode("utf-8", "replace") if isinstance(sent.body, bytes) else str(sent.body),
                    )))

            history = getattr(response, "history", None)
            self._dbg("redirects: {}".format(
                " -> ".join("{} {}".format(r.status_code, r.url) for r in history)
                if history else "(none)",
            ))
            self._dbg("response headers: {}".format(self._format_headers(response.headers)))
            # Logged on success too: a good call is only readable next to a bad
            # one.
            self._dbg("received body ({} bytes): {}".format(
                len(response.content or b""), self._body_preview(response.text),
            ))
        except Exception as e:  # never let diagnostics fail an action
            self._dbg("diagnostics unavailable: {}: {}".format(type(e).__name__, e))

    # ---- Retry policy ----

    def _user_agent(self):
        """User-Agent to present; blank keeps the HTTP library default."""
        return (self.get_config().get("user_agent") or "").strip()

    def _bounded_config_number(self, key, default, minimum, maximum):
        """Read a numeric asset-config value, clamped, never raising: a bad retry
        setting must not take an action down.
        """
        raw = self.get_config().get(key)
        if raw is None or raw == "":
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            self._dbg("{}={!r} is not a number, using default {}".format(key, raw, default))
            return default
        if value < minimum or value > maximum:
            clamped = min(max(value, minimum), maximum)
            self._dbg("{}={} out of range [{}, {}], clamped to {}".format(
                key, value, minimum, maximum, clamped,
            ))
            return clamped
        return value

    def _retry_plan(self):
        """(total attempts, base backoff seconds) for this asset."""
        attempts = int(self._bounded_config_number(
            "retry_count", DEFAULT_RETRY_COUNT, 1, MAX_RETRY_COUNT,
        ))
        backoff = self._bounded_config_number(
            "retry_backoff", DEFAULT_RETRY_BACKOFF, 0, MAX_RETRY_BACKOFF,
        )
        return attempts, backoff

    def _log_idle_gap(self):
        """Log the seconds since the last successful call, so a failing call can
        be compared with a succeeding one.
        """
        last = self._state.get("last_success_epoch") if isinstance(self._state, dict) else None
        if not last:
            self._dbg("idle: no previous successful call on record")
            return
        try:
            self._dbg("idle: {:.1f}s since last successful call".format(time.time() - float(last)))
        except (TypeError, ValueError):
            self._dbg("idle: unreadable last-success timestamp {!r}".format(last))

    def _record_success(self):
        if isinstance(self._state, dict):
            self._state["last_success_epoch"] = time.time()

    def _make_rest_call(self, method, path, params, action_result):
        """Execute an APIM call with mTLS cert setup + 3-layer auth, cleanup.

        Retries HTTP 401 up to the asset's configured attempts. Every attempt
        is logged, and a call that only succeeded on a later attempt says so in
        the action result.

        Returns:
          tuple: (status, response_data) - RetVal pattern
        """
        config = self.get_config()
        url = "{}{}".format(self._base_url, path)
        headers = self._auth_headers(config)
        # No Content-Type: every action is a bodiless GET. Add it per request
        # if a body is ever sent.
        #
        # A 401 "The specified document is not valid JSON data" is the APIM
        # rejecting backend-auth headers it does not recognise (see
        # DDI_USERNAME_HEADER), not this header.
        headers["Accept"] = "application/json"
        # Accept and Cache-Control match the vendor's reference client.
        headers["Cache-Control"] = "no-cache"

        cert_path = key_path = ca_path = None
        session = None
        try:
            self._dbg("=== request {} {} ===".format(method, url))
            self._dbg("params: {}".format(params if params else "(none)"))
            self._dbg("request headers: {}".format(self._format_headers(headers)))
            self._dbg("dns: {}".format(self._resolve_peers(url)))

            cert_path, key_path, ca_path = self._setup_cert_files()
            self._dbg("client_cert {}".format(self._fingerprint(config.get("client_cert", ""))))
            self._dbg("client_key  {}".format(self._fingerprint(config.get("client_key", ""))))
            self._dbg("client_ca   {}".format(self._fingerprint(config.get("client_ca", ""))))

            verify_ssl = config.get("verify_ssl", True)
            verify = ca_path if (verify_ssl and ca_path) else verify_ssl
            # With trust_env off, REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE no longer
            # applies by itself. Honour it explicitly when no client_ca is set,
            # so an optional asset field does not silently change which bundle
            # verifies the APIM.
            if verify is True:
                env_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
                if env_bundle:
                    verify = env_bundle
                    self._dbg("no client_ca set; falling back to CA bundle from environment: {}".format(env_bundle))
            self._dbg("verify_ssl={} verify={} timeout={}s".format(
                verify_ssl, "ca bundle" if isinstance(verify, str) else verify, DEFAULT_TIMEOUT,
            ))

            attempts, backoff = self._retry_plan()
            self._log_idle_gap()
            self._dbg_ambient_env()
            self._dbg("retry plan: up to {} attempt(s), {}s linear backoff, retrying {}".format(
                attempts, backoff, sorted(RETRYABLE_STATUS),
            ))

            # Explicit Session: requests.request() closes its session before a
            # stream=True body is read, and trust_env=False keeps ~/.netrc (it
            # would REPLACE the Authorization header) and HTTPS_PROXY (it would
            # terminate TLS ahead of the APIM) out of the call. Proxies are
            # also emptied explicitly so a session default cannot reintroduce
            # one.
            session = requests.Session()
            session.trust_env = False
            session.proxies = {}
            if self._user_agent():
                session.headers["User-Agent"] = self._user_agent()

            for attempt in range(1, attempts + 1):
                started = time.monotonic()
                response = session.request(
                    method, url, headers=headers, params=params,
                    cert=(cert_path, key_path), verify=verify, timeout=DEFAULT_TIMEOUT,
                    stream=True,
                )
                headers_ms = (time.monotonic() - started) * 1000
                peer = self._peer_address(response)
                response.content  # noqa: B018 - forces the read, releases the connection
                elapsed_ms = (time.monotonic() - started) * 1000

                # Logged for every response, good or bad, so calls can be
                # compared.
                self._dbg_exchange(response, peer, headers_ms, elapsed_ms, attempt, attempts)
                if attempt == 1:
                    self._dbg_curl_equivalent(response)

                if response.status_code not in RETRYABLE_STATUS:
                    break

                if attempt == attempts:
                    self._dbg("HTTP {} on attempt {} of {} -- attempts exhausted".format(
                        response.status_code, attempt, attempts,
                    ))
                    break

                delay = backoff * attempt
                self._dbg("HTTP {} on attempt {} of {} -- retrying in {:.1f}s".format(
                    response.status_code, attempt, attempts, delay,
                ))
                if delay:
                    time.sleep(delay)

            if response.ok:
                self._record_success()
                if attempt > 1:
                    # Through save_progress, not only the debug log: a late
                    # success must not read as a clean one.
                    self.save_progress(
                        "Succeeded on attempt {} of {} (earlier attempt(s) returned HTTP {})".format(
                            attempt, attempts, HTTP_STATUS_UNAUTHORIZED,
                        )
                    )

            return self._process_response(response, action_result, attempts)

        except requests.exceptions.SSLError as e:
            self._dbg("SSLError ({}): {}".format(type(e).__name__, e))
            return (
                action_result.set_status(phantom.APP_ERROR, "TLS/mTLS error connecting to APIM: {}".format(e)),
                None,
            )
        except requests.exceptions.ConnectionError as e:
            self._dbg("ConnectionError ({}): {}".format(type(e).__name__, e))
            return (
                action_result.set_status(phantom.APP_ERROR, "Could not reach APIM: {}".format(e)),
                None,
            )
        except requests.exceptions.RequestException as e:
            self._dbg("RequestException ({}): {}".format(type(e).__name__, e))
            return (
                action_result.set_status(phantom.APP_ERROR, "Error connecting to APIM: {}".format(e)),
                None,
            )
        finally:
            if session is not None:
                session.close()
            self._cleanup_temp_files(cert_path, key_path, ca_path)
            self._dbg("=== end request ===")

    def _process_response(self, response, action_result, attempts=1):
        action_result.add_debug_data({
            "r_status_code": response.status_code,
            "r_text": response.text,
            "r_headers": dict(response.headers),
        })

        content_type = response.headers.get("Content-Type", "")

        # Name the branch taken: an empty 204 and an empty JSON array both end
        # as "no records".
        if "json" in content_type:
            self._dbg("parse: JSON body (content-type {})".format(content_type))
            try:
                data = response.json()
            except ValueError as e:
                return (
                    action_result.set_status(phantom.APP_ERROR, "Unable to parse JSON response: {}".format(e)),
                    None,
                )
        elif not response.content:
            # A list endpoint answers no match with HTTP 204 and an empty body,
            # not 200 with []. Default to [] (not {}) so _ensure_list() sees a
            # list and the action reports "No X found".
            self._dbg("parse: empty body, treated as zero records")
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
            self._dbg("parse: error response, non-JSON body (content-type {})".format(
                content_type or "unset",
            ))
            data = {}

        if response.ok:
            return (phantom.APP_SUCCESS, data)

        detail = self._error_detail(data, response)

        # 403 means BAD REQUEST on this API, not permissions: say so, since the
        # GUI message is all an airgapped operator has.
        if response.status_code in BAD_REQUEST_STATUS:
            message = (
                "EfficientIP/APIM returned HTTP {}, which on this API means BAD REQUEST "
                "-- 403 is not a permissions problem and 400 comes from the SOLIDserver "
                "backend. Check the request itself (filter column names, WHERE syntax "
                "-- values must be single-quoted -- and limit) before checking "
                "credentials: {}".format(response.status_code, detail)
            )
        elif response.status_code == HTTP_STATUS_UNAUTHORIZED:
            message = (
                "EfficientIP/APIM returned HTTP 401 (unauthorized) on all {} attempt(s): "
                "{}".format(attempts, detail)
            )
        else:
            message = "EfficientIP/APIM returned HTTP {}: {}".format(response.status_code, detail)

        return (action_result.set_status(phantom.APP_ERROR, message), None)

    def _error_detail(self, data, response):
        """Best available explanation of a failure, for the operator.

        The gateway answers {"message": ...}; the SOLIDserver backend answers a
        bad WHERE with a list of dicts carrying its own codes ([{"errno":
        "50028", "sql_error": "7"}]). Those codes are the only lead on an
        airgapped appliance, so surface them.
        """
        if isinstance(data, dict) and data:
            return data.get("message") or response.text
        if isinstance(data, list) and data and isinstance(data[0], dict):
            fields = ", ".join(
                "{}={}".format(k, v) for k, v in data[0].items() if v not in (None, "")
            )
            if fields:
                return "SOLIDserver error ({})".format(fields)
        return response.text

    def _ensure_list(self, data, action_result):
        """Fail with a clear message if a list service did not return a bare JSON
        array, rather than a KeyError/TypeError on records[0].
        """
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
        # Credentials are hand-entered and base64-encoded, so stray whitespace
        # would survive into a wrong credential and an indistinguishable 401:
        # strip all four.
        client_id = config["client_id"].strip()
        client_secret = config["client_secret"].strip()
        ddi_username = config["ddi_username"].strip()
        ddi_password = config["ddi_password"].strip()

        basic = base64.b64encode(
            "{}:{}".format(client_id, client_secret).encode()
        ).decode()
        return {
            "Authorization": "Basic {}".format(basic),
            DDI_USERNAME_HEADER: base64.b64encode(ddi_username.encode()).decode(),
            DDI_PASSWORD_HEADER: base64.b64encode(ddi_password.encode()).decode(),
        }

    def _validate_ip(self, address, action_result):
        """Validate a caller-supplied address and return its normalised form.

        The dotted address goes on the wire as-is: hostaddr is the filterable
        column (sibling of the hex ip_addr); host_addr with an underscore is
        not a column. IPv6 is compressed to its one canonical spelling.

        Returns None (action_result already failed) for anything that is not a
        bare IP: a hostname, CIDR range or typo would otherwise reach the WHERE
        clause.
        """
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
        """Coerce a numeric param to a real int, or fail the action (SOAR often
        hands numerics through as float or str, and limit=5.0 is not safe to
        interpolate).
        """
        try:
            # float() first, not int(): SOAR hands numbers through as 1001.0,
            # which int("1001.0") rejects.
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
        """Every list call is bounded; the bound is the caller's to raise, not a
        hardcoded 1.
        """
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
        """Build the query params. `limit` ALWAYS goes on the wire.

        A list call with neither WHERE nor limit scans unbounded and times out
        server-side. limit works alongside WHERE; do not add a "never send
        both" rule (it was disproven).
        """
        # limit first, matching every curl known to work against the appliance.
        return {"limit": limit, "WHERE": where} if where else {"limit": limit}

    def _select_optional_filter(self, param, filter_map, action_result):
        """Pick at most one supplied filter, returning (ok, where_column, value).

        No filter is a legal call (a bounded bare list): ok with column None.
        More than one is refused before any request, since only a single
        column='value' condition is known to work. ok is False only on that
        refusal, with action_result already failed.
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

        connector = EfficientipDdiConnector()
        connector.print_progress_message = True
        result = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(result), indent=4))

    exit(0)


if __name__ == "__main__":
    main()
