#!/usr/bin/env python3
"""Bisect the EfficientIP 401: is it the HTTP client, or is it SOAR?

The connector 401s against the real APIM where a hand-run curl does not. Three
things differ at once -- the SOAR platform, the Python/requests HTTP stack, and
the connector's own header set -- so neither observation can name a cause.

This script runs both clients back to back, in one process, against one
appliance, varying ONE thing at a time. Interleaving matters: "curl works" from
an hour ago is a memory, not a control. Here every Python attempt has a curl
attempt seconds away from it, so a gateway node or a cache entry cannot masquerade
as a client difference.

RUN IT WITH THE SOAR PYTHON, or the result does not transfer:

    sudo su - phantom
    export DDI_BASE=https://apim.internal.example
    export DDI_CLIENT_ID=... DDI_CLIENT_SECRET=...
    export DDI_USER=...      DDI_PASS=...
    export DDI_CERT=/path/client.pem DDI_KEY=/path/client-key.pem
    export DDI_CA=/path/ca.pem          # optional; omitted => no TLS verify
    /opt/phantom/bin/phenv python3 uc17_client_bisect.py

A system python3 has a different requests/urllib3/OpenSSL, so a green result
there says nothing about the connector. The banner prints which interpreter and
library versions actually ran -- check it before trusting any row.

Read-only: every call is a GET against a *_list service. Nothing is created,
modified or deleted. No credential is ever printed.
"""

import base64
import os
import ssl
import subprocess
import sys
import time
import urllib.request

import requests
import urllib3

if not (os.environ.get("DDI_CA") or "").strip():
    # No CA means verification is off by design here, and the warning it emits
    # per request would bury the table this script exists to print.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---- config -----------------------------------------------------------------

def _env(name, default=None, required=False):
    value = (os.environ.get(name) or default or "").strip()
    if required and not value:
        sys.exit("set {}".format(name))
    return value

BASE = _env("DDI_BASE", required=True).rstrip("/")
CERT = _env("DDI_CERT", required=True)
KEY = _env("DDI_KEY", required=True)
CA = _env("DDI_CA")

# The path known to answer 200 for a hand-run curl, and optionally the one that
# 401s. Running both through the same matrix separates "this client fails" from
# "this service fails".
PATH_OK = _env("PROBE_PATH_OK", "/rest/ip_block_subnet_list?limit=1")
PATH_BAD = _env("PROBE_PATH_BAD")

REPEATS = int(_env("PROBE_REPEATS", "3"))
TIMEOUT = 30

# Same construction as the connector: strip first, then base64. A pasted
# trailing newline otherwise survives into the credential and yields a 401
# indistinguishable from a wrong value.
def _b64(value):
    return base64.b64encode(value.encode()).decode()

AUTH = {
    "Authorization": "Basic {}".format(
        _b64("{}:{}".format(_env("DDI_CLIENT_ID", required=True),
                            _env("DDI_CLIENT_SECRET", required=True)))
    ),
    "X-DDI-Username": _b64(_env("DDI_USER", required=True)),
    "X-DDI-Password": _b64(_env("DDI_PASS", required=True)),
}

# What requests puts on the wire by default, spelled out so curl can wear it.
REQUESTS_UA = "python-requests/{}".format(requests.__version__)
REQUESTS_AE = "gzip, deflate"
CURL_UA = "curl/8.4.0"

# Headers the connector adds beyond auth.
CONNECTOR_EXTRA = {"Accept": "application/json", "Cache-Control": "no-cache"}

# Response headers worth reading back. Vary names the request headers the
# gateway says its answer depends on; the APIm id is the handle an APIM
# administrator can trace the transaction with.
ECHO_HEADERS = ("APIm-Debug-Trans-Id", "Vary", "Cache-Control", "X-Global-Transaction-ID")


def _peer_address(response):
    """The address that actually served this call, best-effort.

    Which resolved address answered is the difference between suspecting a bad
    gateway node and naming it. Only readable while the connection is still
    held, so callers use stream=True and read this before touching the body.

    Where the socket hangs off the response is a urllib3 private detail that has
    moved between versions, so try the known layouts and take the first that
    answers. Mirrors the connector's own helper deliberately: a peer column that
    disagrees with the connector's log would be worse than none.
    """
    for path in ("_connection.sock", "_fp.fp.raw._sock",
                 "_original_response.fp.raw._sock", "_fp.fp._sock", "_sock"):
        try:
            target = response.raw
            for attribute in path.split("."):
                target = getattr(target, attribute)
            return target.getpeername()[0]
        except Exception:
            continue
    return ""


# ---- result ------------------------------------------------------------------

class Result:
    def __init__(self, code, peer="", headers=None, message="", ms=0.0, error=""):
        self.code = code
        self.peer = peer
        self.headers = headers or {}
        self.message = message
        self.ms = ms
        self.error = error

    def __str__(self):
        return self.error or str(self.code)


def _message_of(text):
    """The appliance's own error text, when it sends one."""
    try:
        import json
        data = json.loads(text or "")
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or "")[:120]
        if isinstance(data, list) and data:
            return "[{} record(s)]".format(len(data))
    except Exception:
        pass
    return (text or "").strip().replace("\n", " ")[:120]


# ---- clients -----------------------------------------------------------------

def call_curl(path, ua=None, accept_encoding=None, extra=None):
    """The known-working client. `ua`/`accept_encoding` let it impersonate requests."""
    cmd = [
        "curl", "-sS", "-o", "/dev/null", "-D", "-",
        "--max-time", str(TIMEOUT),
        "--cert", CERT, "--key", KEY,
    ]
    cmd += ["--cacert", CA] if CA else ["-k"]
    cmd += ["-w", "\n__CODE__%{http_code} __PEER__%{remote_ip} __MS__%{time_total}"]
    for name, value in list(AUTH.items()) + list((extra or {}).items()):
        cmd += ["-H", "{}: {}".format(name, value)]
    if ua:
        cmd += ["-A", ua]
    # curl sends no Accept-Encoding at all unless asked; requests always does.
    if accept_encoding:
        cmd += ["-H", "Accept-Encoding: {}".format(accept_encoding)]
    cmd.append(BASE + path)

    started = time.monotonic()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 10).stdout
    except Exception as e:
        return Result(0, error="{}: {}".format(type(e).__name__, e))
    ms = (time.monotonic() - started) * 1000

    code = peer = ""
    headers = {}
    for line in out.splitlines():
        if line.startswith("__CODE__"):
            for chunk in line.split():
                if chunk.startswith("__CODE__"):
                    code = chunk[8:]
                elif chunk.startswith("__PEER__"):
                    peer = chunk[8:]
        elif ":" in line:
            name, _, value = line.partition(":")
            if name.strip().lower() in {h.lower() for h in ECHO_HEADERS}:
                headers[name.strip()] = value.strip()
    return Result(int(code or 0), peer, headers, "", ms)


def call_requests(path, trust_env=True, ua=None, drop_accept_encoding=False, extra=None):
    """The connector's client. Each argument is one variable it differs by."""
    headers = dict(AUTH)
    headers.update(extra or {})
    if drop_accept_encoding:
        # None removes a default session header rather than sending it empty.
        headers["Accept-Encoding"] = None
    session = requests.Session()
    session.trust_env = trust_env
    if not trust_env:
        session.proxies = {}
    if ua:
        session.headers["User-Agent"] = ua

    started = time.monotonic()
    try:
        response = session.request(
            "GET", BASE + path, headers=headers,
            cert=(CERT, KEY), verify=CA if CA else False,
            timeout=TIMEOUT, stream=True,
        )
        peer = _peer_address(response)
        text = response.text
        ms = (time.monotonic() - started) * 1000
        echoed = {k: v for k, v in response.headers.items()
                  if k.lower() in {h.lower() for h in ECHO_HEADERS}}
        return Result(response.status_code, peer, echoed, _message_of(text), ms)
    except Exception as e:
        return Result(0, error="{}: {}".format(type(e).__name__, e))
    finally:
        session.close()


def call_urllib(path):
    """Stdlib only -- separates 'requests' from 'Python and its OpenSSL'.

    If requests 401s and this 200s, the fault is in requests' request shaping.
    If both 401 while curl passes, it is lower down: the TLS stack or the client
    certificate as this Python presents it.
    """
    context = ssl.create_default_context(cafile=CA or None)
    if not CA:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        context.load_cert_chain(CERT, KEY)
    except Exception as e:
        return Result(0, error="cert load: {}".format(e))

    request = urllib.request.Request(BASE + path, headers=dict(AUTH))
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            body = response.read().decode("utf-8", "replace")
            ms = (time.monotonic() - started) * 1000
            echoed = {k: v for k, v in response.headers.items()
                      if k.lower() in {h.lower() for h in ECHO_HEADERS}}
            return Result(response.status, "", echoed, _message_of(body), ms)
    except urllib.error.HTTPError as e:
        ms = (time.monotonic() - started) * 1000
        body = e.read().decode("utf-8", "replace")
        echoed = {k: v for k, v in (e.headers or {}).items()
                  if k.lower() in {h.lower() for h in ECHO_HEADERS}}
        return Result(e.code, "", echoed, _message_of(body), ms)
    except Exception as e:
        return Result(0, error="{}: {}".format(type(e).__name__, e))


# ---- matrix ------------------------------------------------------------------
#
# Ordered so each row adds exactly one difference to the row above it. The first
# row that flips 200 -> 401 names the cause.

VARIANTS = [
    ("A  curl, bare (control)",
     lambda p: call_curl(p)),

    ("B  curl wearing requests' UA + Accept-Encoding",
     lambda p: call_curl(p, ua=REQUESTS_UA, accept_encoding=REQUESTS_AE)),

    ("C  requests, library defaults (pre-1.0.6 shape)",
     lambda p: call_requests(p, trust_env=True)),

    ("D  requests, trust_env=False + no proxies (1.0.6)",
     lambda p: call_requests(p, trust_env=False)),

    ("E  D + User-Agent: curl/8.4.0",
     lambda p: call_requests(p, trust_env=False, ua=CURL_UA)),

    ("F  E + Accept-Encoding removed",
     lambda p: call_requests(p, trust_env=False, ua=CURL_UA, drop_accept_encoding=True)),

    ("G  F + Accept + Cache-Control (full connector shape)",
     lambda p: call_requests(p, trust_env=False, ua=CURL_UA, drop_accept_encoding=True,
                             extra=CONNECTOR_EXTRA)),

    ("H  urllib, stdlib only (no requests)",
     lambda p: call_urllib(p)),
]


def run_path(path, peer_index):
    """Print the readable table, and return one compact row per variant.

    The compact rows exist because the operator of an airgapped appliance may
    have no way to copy text off it -- they read the screen and retype. Anything
    they must retype has to be short enough to get right by hand, so the digest
    trades the table's readability for density and a mistyped character that is
    obvious rather than plausible.
    """
    print("\n{}\n  GET {}\n{}".format("=" * 78, path, "=" * 78))
    print("{:<52} {:<14} {:<16} {}".format("variant", "codes", "peer", "ms (median)"))
    print("-" * 100)

    notes = []
    digest = []
    for label, call in VARIANTS:
        codes, peers, times, extra = [], set(), [], {}
        for _ in range(REPEATS):
            result = call(path)
            codes.append(str(result))
            if result.peer:
                peers.add(result.peer)
            times.append(result.ms)
            if result.headers:
                extra.update(result.headers)
            if result.message:
                extra["message"] = result.message
        times.sort()
        print("{:<52} {:<14} {:<16} {:.0f}".format(
            label, ",".join(codes), ",".join(sorted(peers)) or "-",
            times[len(times) // 2] if times else 0,
        ))

        # Collapse identical repeats: three 401s are one fact, not three, and
        # three characters instead of eleven. Repeats that DISAGREE are the
        # interesting case, so those stay spelled out.
        row = label[0]
        unique_codes = sorted(set(codes))
        code_token = unique_codes[0] if len(unique_codes) == 1 else "/".join(codes)
        # Peers are numbered, not named. The operator retypes a digit instead of
        # a dotted quad, and their internal addressing does not need to travel.
        # Whether peers DIFFER is the signal; which addresses they are is not.
        peer_token = ""
        for peer in sorted(peers):
            peer_index.setdefault(peer, len(peer_index) + 1)
            peer_token += str(peer_index[peer])
        digest.append((row, code_token, peer_token or "-", extra.get("message", "")))
        for name, value in sorted(extra.items()):
            notes.append("    {:<48} {}: {}".format("", name, value))
        if extra:
            print("\n".join(notes[-len(extra):]))
    print()
    return digest


def main():
    print("interpreter : {}".format(sys.executable))
    print("python      : {}".format(sys.version.split()[0]))
    print("requests    : {}  urllib3: {}".format(
        requests.__version__,
        __import__("urllib3").__version__,
    ))
    print("openssl     : {}".format(ssl.OPENSSL_VERSION))
    print("base        : {}".format(BASE))
    print("verify      : {}".format(CA or "OFF (no DDI_CA set)"))
    print("repeats     : {} per variant".format(REPEATS))

    # Shared across both paths so a node keeps the same number throughout.
    peer_index = {}
    digest_ok = run_path(PATH_OK, peer_index)
    digest_bad = run_path(PATH_BAD, peer_index) if PATH_BAD else []

    print("""How to read this:
  B flips to 401           -> the gateway gates on User-Agent/Accept-Encoding.
                              Not our bug; an APIM policy question.
  C-G all 401, A stays 200 -> the fault is the Python HTTP stack, not SOAR.
                              The first row that flips names the header.
  H 401 too                -> below requests: TLS/client-cert as Python presents it.
  Everything 200           -> the fault is SOAR-side, not the client. Compare this
                              script's environment against the connector's.
  peer column differs      -> you are hitting more than one gateway node.

Hand the APIm-Debug-Trans-Id above to whoever administers the APIM. The policy
trace names the rejecting policy outright. That id does NOT need to leave this
machine or reach anyone else -- give it to your own APIM administrator.""")

    print_digest(digest_ok, digest_bad, peer_index)


def print_digest(digest_ok, digest_bad, peer_index):
    """The few lines worth retyping by hand off an airgapped console.

    Everything above this is for reading on the screen. This block is for
    copying with a pen: short tokens, one line per fact, no dotted quads and no
    opaque ids. It carries the whole result -- which client saw which status on
    which node -- in about five lines.
    """
    under_phenv = "phenv" in sys.executable or "/opt/phantom/" in sys.executable
    message = ""
    for _, _, _, msg in digest_ok + digest_bad:
        if msg:
            message = msg[:60]
            break

    print("\n" + "=" * 56)
    print("TRANSCRIBE THIS  (everything above is for reading only)")
    print("=" * 56)
    print("1 env  phenv={} py{} req{} ul{} ssl{}".format(
        "YES" if under_phenv else "NO-RERUN-WITH-PHENV",
        sys.version.split()[0],
        requests.__version__,
        __import__("urllib3").__version__,
        ssl.OPENSSL_VERSION.split()[1],
    ))
    print("2 ok   {}".format(" ".join(
        "{}{}".format(row, code) for row, code, _, _ in digest_ok)))
    if digest_bad:
        print("3 bad  {}".format(" ".join(
            "{}{}".format(row, code) for row, code, _, _ in digest_bad)))
    print("4 peer {}   ({} distinct)".format(
        " ".join("{}{}".format(row, peers) for row, _, peers, _ in digest_ok),
        len(peer_index) or "0",
    ))
    if message:
        print("5 msg  {}".format(message))
    print("=" * 56)
    print("Five short lines. A peer digit is a node, not an address -- rows")
    print("sharing a digit were served by the same one. If a row's repeats")
    print("disagreed it reads like C401/200/401; that is the real answer, not")
    print("a typo, so copy it as shown.")


if __name__ == "__main__":
    main()
