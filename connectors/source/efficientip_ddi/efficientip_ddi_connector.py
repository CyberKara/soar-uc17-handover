# efficientip_ddi_connector.py
"""EfficientIP DDI SOAR Connector - IPAM enrichment against SOLIDserver via APIM.

Classic BaseConnector style, which is a recorded exemption from FR-01 in
docs/dev-rules.md: the App Debugger cannot dispatch actions for SDK-based apps
on SOAR 8.5, and on an airgapped appliance that panel is the operator's only
way to exercise an action by hand. See the README for field-name provenance.

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
    DEFAULT_LIMIT,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_COUNT,
    DEFAULT_TIMEOUT,
    HTTP_STATUS_UNAUTHORIZED,
    IP_ADDRESS_LIST_PATH,
    IP_ALIAS_LIST_PATH,
    IP_BLOCK_SUBNET_LIST_PATH,
    IP_POOL_LIST_PATH,
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
        query_addr = self._validate_ip(address, action_result)
        if query_addr is None:
            return action_result.get_status()
        limit = self._limit_from(param, action_result)
        if limit is None:
            return action_result.get_status()

        ret_val, records = self._make_rest_call(
            "GET", IP_ADDRESS_LIST_PATH,
            self._bounded_query(limit, "host_addr='{}'".format(query_addr)), action_result
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

    # ---- Diagnostics ----
    #
    # Everything below writes through save_progress, which is the only channel
    # that reaches an operator with no shell: it renders both in the App
    # Debugger panel and in a container action result. add_debug_data() does
    # NOT -- it is dropped before the action result is persisted (verified on
    # soar8 app_run 6507, where result_data carries no debug_data key), so the
    # response headers it collects have never been visible to anyone.

    # Values never printed. Request side: the three auth headers. Response
    # side: anything that hands back a session.
    _SENSITIVE_HEADERS = frozenset({
        "authorization", "x-ddi-username", "x-ddi-password",
        "set-cookie", "cookie", "proxy-authorization", "www-authenticate-token",
    })

    # Bodies are logged whole up to this, then truncated. Generous enough for a
    # gateway error page or a few IPAM records, short enough not to bury the
    # rest of the trace in the GUI panel.
    _BODY_LOG_LIMIT = 2000

    def _dbg(self, message):
        self.save_progress("DEBUG GUI: {}".format(message))

    def _body_preview(self, text):
        """Render a body for the log, flagging truncation explicitly.

        Silent truncation is worse than none: it invites reading a cut-off
        JSON document as a malformed one.
        """
        if not text:
            return "(empty)"
        if len(text) <= self._BODY_LOG_LIMIT:
            return text
        return "{} ... (truncated, {} chars total)".format(text[:self._BODY_LOG_LIMIT], len(text))

    def _fingerprint(self, material):
        """Identify PEM material without printing it.

        Enough to answer "is the cert the connector used this time the same one
        it used last time" across runs, which no log line could otherwise show
        without leaking the material itself.
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
        """List every address the APIM hostname resolves to.

        A name answering on several addresses is the first thing worth ruling
        in or out when calls fail intermittently with identical inputs: one
        node out of N behaving differently looks exactly like that from here.
        """
        try:
            parts = urlsplit(url)
            host = parts.hostname
            if not host:
                return "unparsable url"
            port = parts.port or (443 if parts.scheme == "https" else 80)
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            addresses = sorted({info[4][0] for info in infos})
            return "{} -> {}".format(host, ", ".join(addresses))
        except Exception as e:  # never let diagnostics fail an action
            return "resolution failed: {}".format(e)

    def _peer_address(self, response):
        """The address that actually served this call.

        Tells us WHICH of the resolved addresses answered, which is the
        difference between suspecting a bad node and naming it.

        Only readable while the connection is still held. requests releases it
        the instant the body is read, so the caller issues the request with
        stream=True and calls this BEFORE touching .content.

        Where the socket hangs off the response is a urllib3 private detail
        that has moved between versions -- on urllib3 1.26 `_connection.sock`
        is already None while `_fp.fp.raw._sock` is live -- and this connector
        is built on one host and run on another. So try the known layouts in
        order and take the first that answers. All of it is best-effort:
        diagnostics must never fail an action.
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

    def _dbg_ambient_env(self):
        """Report the ambient settings requests WOULD honour, and we disable.

        This is the difference between this connector and the curl the user
        runs by hand, and it is invisible from the request itself. With
        trust_env left on (the library default), requests will:

          - read ~/.netrc and, on a host match, REPLACE the Authorization
            header we just built with the netrc credentials. curl only does
            this with -n. A stale netrc entry is a silent 401.
          - route through HTTPS_PROXY/HTTP_PROXY. A proxy terminates TLS, so
            the client certificate never reaches the APIM -- also a 401, and
            an intermittent one if the proxy is itself load-balanced.
          - override `verify` from REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE.

        We now turn all of that off. Logging what was present says whether it
        was ever the cause, which matters more than silently fixing it.
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
        """Log the whole exchange, best-effort.

        Wrapped like every other helper here: a diagnostic must never be the
        reason an action fails. This one reads several attributes that a real
        requests.Response always has but a stand-in may not (`request`,
        `history`), so unguarded it turns a working action into an
        AttributeError.
        """
        try:
            self._dbg("attempt {}/{}: HTTP {} from peer {} -- {:.0f} ms to headers, {:.0f} ms total".format(
                attempt, attempts, response.status_code, peer, headers_ms, elapsed_ms,
            ))
            # What actually went on the wire, read back off the PreparedRequest
            # rather than off our own intent: this is the URL after requests
            # encoded the query string, and the headers after it added its own
            # (Host, User-Agent, Accept-Encoding, Connection). If the gateway is
            # rejecting the request's SHAPE, the difference shows up here and
            # nowhere else.
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
            # Logged on success as well as failure. Comparing the body of a call
            # that worked against one that did not is the whole point, and on a
            # gateway that answers non-auth problems with 401 the body is where
            # it says which problem it meant.
            self._dbg("received body ({} bytes): {}".format(
                len(response.content or b""), self._body_preview(response.text),
            ))
        except Exception as e:  # never let diagnostics fail an action
            self._dbg("diagnostics unavailable: {}: {}".format(type(e).__name__, e))

    # ---- Retry policy ----

    def _user_agent(self):
        """User-Agent to present, blank to keep the library default.

        Defaults to a curl string because curl is the client known to work
        against this org's APIM, and a gateway keying a policy on User-Agent
        (bot filters and per-client rate limits routinely do) is one of the few
        remaining differences between the two. Configurable so this can be
        tested both ways without a rebuild, and set back to blank once the
        question is settled either way.
        """
        return (self.get_config().get("user_agent") or "").strip()

    def _bounded_config_number(self, key, default, minimum, maximum):
        """Read a numeric asset-config value, clamped, never raising.

        A SOAR numeric field still arrives as whatever the operator typed, and
        a bad retry setting must not be the thing that takes an enrichment
        action down -- fall back to the default and say so.
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
        """Log how long since the last call that succeeded.

        This is the one number that separates the three surviving explanations
        for the intermittent 401, because each predicts a different
        relationship to it: an auth-cache expiry fails after a GAP, a quota
        policy fails under a BURST (the opposite), and a load-balanced node
        with inconsistent trust correlates with neither -- it shows up in the
        peer address instead. Recorded on every call so a failing one can be
        compared against a succeeding one.
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

        Retries an HTTP 401 up to the asset's configured attempt count. Every
        attempt is logged individually, and a call that only succeeded on a
        later attempt says so in the action result rather than passing silently
        -- the intermittency is an open investigation, so the retry has to stay
        visible instead of papering over the evidence.

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
        # Both from the vendor's own documented CURLOPT set for these services.
        # no-cache is the interesting one: the vendor's reference client asks for
        # a fresh answer on every call, which says caching is a live concern
        # somewhere on this path. That is *consistent with* one of the surviving
        # explanations for the intermittent 401 (an auth/response cache), but it
        # is not evidence for it and this header is not a fix -- it is here
        # because matching the reference client costs nothing and removes one
        # difference between us and the only implementation known to work.
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
            # With trust_env now off, a REQUESTS_CA_BUNDLE in the environment no
            # longer applies by itself. It previously did -- but only when no
            # client_ca was configured, because requests substitutes it solely
            # when verify is True. That made an optional asset field silently
            # decide whether the platform's CA bundle or the system trust store
            # verified the APIM, which is a miserable thing to debug on an
            # airgapped box. Honour it explicitly as a fallback so no working
            # asset regresses, and say so in the log.
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

            # An explicit Session, for two reasons that both bite silently.
            #
            # 1. requests.request() is `with Session() as s: return s.request(...)`
            #    -- the session, its adapters and its connection pools are CLOSED
            #    the moment it returns. Combined with stream=True (which we need,
            #    because the peer address is only readable before the body is
            #    read) that meant reading .content off a response whose pool was
            #    already torn down. Undefined behaviour at best.
            # 2. trust_env=False. With the library default of True, requests
            #    silently honours the ambient environment in ways curl does not:
            #    a matching ~/.netrc entry REPLACES the Authorization header we
            #    just built, and HTTPS_PROXY reroutes the call through a proxy
            #    that terminates TLS so the client certificate never reaches the
            #    APIM. Either one is an HTTP 401 that looks like a credential
            #    problem, and neither is visible in the request we think we sent.
            #    Proxies are also emptied explicitly, so a session-level default
            #    cannot reintroduce one.
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

                # Logged for every response, not just failures: an intermittent
                # fault is only legible by comparing a good call against a bad
                # one, so the good ones have to be on the record too. Splitting
                # the two timings separates a slow gateway decision (headers)
                # from a slow body transfer, and both from a fast reject.
                self._dbg_exchange(response, peer, headers_ms, elapsed_ms, attempt, attempts)

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
                    # Surfaced through save_progress, not only the debug log:
                    # a result that reads as a clean success while the gateway
                    # is rejecting a third of its calls hides the very symptom
                    # under investigation.
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

        # Which of the four branches below a response takes is not obvious from
        # the outcome -- an empty 204 and a JSON empty array both end as "no
        # records found" -- so name the branch taken.
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
            # The real APIM returns HTTP 204 No Content (empty body, no
            # Content-Type) for a "not found"/empty result on a list
            # endpoint -- not a 200 with an empty JSON
            # array. Every action here expects a list from _ensure_list(),
            # so default to [] here, not {} -- a dict would fail that
            # isinstance check and surface a confusing "unexpected response
            # shape" error instead of the intended friendly "No X found"
            # message.
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

        # This API uses only four codes and 403 is not the standard one, so the
        # error text names the meaning rather than leaving the operator to read
        # it as plain HTTP. Getting this wrong costs real time on an airgapped
        # appliance, where the message in the GUI is all the operator has.
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

        The gateway answers with {"message": ...}, but the SOLIDserver backend
        answers a bad WHERE with a LIST of dicts carrying its own codes
        ([{"errno": "50028", "sql_error": "7"}]) and no message at all. Those
        codes are the only lead available on an airgapped appliance, so pull
        them out rather than letting the whole body fall through as raw text.
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

    def _validate_ip(self, address, action_result):
        """Validate a caller-supplied address and return its normalised form.

        The dotted address goes on the wire as-is: `host_addr` is the
        filterable column for it (sibling of the hex-valued `ip_addr`), so no
        encoding step is needed. Normalising still matters for IPv6, where the
        same address has many spellings and only one compressed form.

        Returns None (with action_result already failed) for anything that is
        not a bare IP -- a hostname, CIDR range or typo would otherwise reach
        the WHERE clause verbatim, or raise a bare ValueError out of the
        handler.
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
        """Build the query params. `limit` ALWAYS goes on the wire.

        A list call carrying neither WHERE nor limit makes the backend attempt
        an unbounded full scan and time out server-side, so a bound is
        mandatory. limit is that bound, and it works server-side alongside a
        WHERE: confirmed against the real appliance, where a filtered call with
        limit=1 returns HTTP 200 and exactly one row.

        Do not reintroduce a "never send both" rule here. One was shipped once
        and disproven -- the curl observation behind it was a shell-quoting
        artefact, not appliance behaviour. See the UC17 plan.
        """
        # limit FIRST. Every curl confirmed working against the real appliance
        # puts it first, and this connector was putting it last. Ordering should
        # not matter to a correct parser -- but "should not matter" is exactly
        # the kind of assumption that has cost this connector three reverted
        # theories, and matching the known-good client costs nothing.
        return {"limit": limit, "WHERE": where} if where else {"limit": limit}

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

        connector = EfficientipDdiConnector()
        connector.print_progress_message = True
        result = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(result), indent=4))

    exit(0)


if __name__ == "__main__":
    main()
