# efficientip_ddi — implementation notes

Why the connector is built the way it is, and what was learned getting it to work
against a real appliance. The source carries only short "why" comments; everything
else lives here. The connector's `README.md` is the reference for behaviour (auth
model, response codes, filters, asset fields); this file is the reasoning and the
history behind it.

The original long-form comments are in git history: the last version that carries
them is **v1.0.12** (the shipped handover package).

---

## 1. Request path

**URL.** `{base_url}/rest/<service>`. The APIM may publish the services under a path
prefix, which belongs in `base_url`: everything before `/rest`.

**Three auth layers on every request**, none cached, no token exchange:

| Layer | Carrier |
|---|---|
| mTLS | `client_cert` / `client_key` (+ optional `client_ca`), written to temp files per call and deleted afterwards |
| APIM app credential | `Authorization: Basic base64(client_id:client_secret)` |
| SOLIDserver backend credential | `X-IPM-Username` / `X-IPM-Password`, each `base64(value)` independently |

The backend-auth header **names matter**. They are constants in `efficientip_ddi_consts.py`
(`DDI_USERNAME_HEADER` / `DDI_PASSWORD_HEADER`) and drive three things that must stay in
step: the request builder, the debug-log redaction list, and the curl emitter. A header
that is renamed but missing from the redaction list would be printed in clear in the
GUI-visible log.

**Other headers.** `Accept: application/json` and `Cache-Control: no-cache` match the
vendor's reference client. No `Content-Type`: every action is a bodiless GET, and there
is no body for it to describe.

**Client construction.** An explicit `requests.Session` with `trust_env = False` and
`proxies = {}`:

- `requests.request()` closes its session as soon as it returns, which would leave a
  `stream=True` body to be read from a torn-down pool. `stream=True` exists only so the
  peer address can be read before the body (see section 5).
- `trust_env=False` keeps the ambient environment out of the call. With the library
  default, a matching `~/.netrc` entry *replaces* the `Authorization` header we built,
  and `HTTPS_PROXY` routes through a proxy that terminates TLS, so the client certificate
  never reaches the APIM. Both surface as an HTTP 401 that looks like a credential
  problem, and neither is visible in the request we think we sent.

**TLS verification.** `verify` is the configured `client_ca` when set, otherwise the
`requests` library's bundle. Because `trust_env` is off, `REQUESTS_CA_BUNDLE` /
`CURL_CA_BUNDLE` no longer apply on their own, so the connector honours them explicitly
as a fallback when no `client_ca` is set (and logs it). Otherwise an optional asset field
would silently decide which bundle verifies the APIM.

**PEM handling.** SOAR's config textareas mangle PEM whitespace, so `_normalize_pem()`
re-wraps `CERTIFICATE`, `PRIVATE KEY`, `RSA PRIVATE KEY` and `EC PRIVATE KEY` blocks
to 64 columns. Known limits: an `ENCRYPTED` or `OPENSSH` key passes through unchanged,
and in a field that mixes block types, blocks of an unrecognised type are dropped. The
connector presents only what is pasted into `client_cert`, so a leaf-only paste differs
from a chain file given to curl. A broken cert/key reads as a TLS error, never a 401:
seeing a 401 means the certificate loaded and was presented.

**Credentials are stripped.** All four hand-entered credentials are `.strip()`ped before
base64, since one pasted trailing newline would otherwise yield a wrong credential and a
401 indistinguishable from a wrong value.

## 2. Response contract

The API answers with four codes, one of which does not carry its usual meaning. See the
README's "Response codes" table. The reasoning behind how the connector treats them:

- **403 is BAD REQUEST, not "forbidden".** Read as plain HTTP it sends an operator
  hunting credentials. The error text names the real meaning, because on an airgapped
  appliance the GUI message is all the operator has. The SOLIDserver backend answers the
  same class of fault with 400; both are named as bad requests and never retried.
- **204 is an empty result**, not an error and not `200 []`. The parser defaults the body
  to `[]` (not `{}`) so `_ensure_list()` sees a list and the action reports a friendly
  "No X found".
- **The backend's own error body** is a list of dicts (`[{"errno": ..., "sql_error": ...}]`)
  with no `message`. Those codes are the only lead, so `_error_detail()` pulls them out.
- **401 is the only auth-layer code**, and a 401 cannot be the gateway's verdict on a bad
  query: a bad query is 400/403.

## 3. Retry on 401

Only 401 is retried. The appliance was seen answering 401 to a request that succeeded,
unchanged, moments later, and the connector holds no per-call state, so identical inputs
produce identical bytes: a retry re-asks a question with new odds, not a stale one.
Backoff is linear (1x, 2x, 3x) and capped, because rapid repeated auth failures are what
trip gateway lockouts and quotas. 400 and 403 are deterministic and never retried. The
retry is never silent: every attempt is logged, and a late success reports
`Succeeded on attempt N of M` in the action result. `retry_count = 1` disables it.

Retry is a mitigation, not a diagnosis. A *constant* 401 on every attempt (as opposed to
an intermittent one) is a different fault: see section 7.

## 4. Query building

- **Every list call carries a bound.** A call with neither `WHERE` nor `limit` makes the
  backend attempt an unbounded scan and time out server-side, so `limit` always goes on
  the wire (first in the query, matching every curl known to work).
- **`WHERE` and `limit` together are fine.** A "never send both" rule was shipped once and
  disproven: the observation behind it was a shell artefact (an unquoted `&` backgrounded
  curl, so both arms were identical `WHERE`-only requests). Do not reintroduce it.
- **Quoting is SQL typing.** String values are single-quoted, integers are not; `=` does
  not need percent-encoding. `_bounded_query()` and the filter builders quote every
  string, which is right for every column exposed today.
- **The dotted address column is `hostaddr`**, no underscore. `host_addr` is not a column:
  the appliance answers it with a SQL error (`sql_error` 7). `ip_addr` is its hex sibling.
  IPv6 is compressed to one canonical spelling before it goes out; whether the appliance
  stores that form is unverified.
- **Filterable column != selectable field.** On `ip_block_subnet_list` the record comes
  back with `name` but the filterable column is `subnet_name`, and the caller-facing
  `site_name` filters as `parent_site_name`. `LIST_SUBNETS_FILTERS` is a table, not an
  f-string, for exactly this reason. Do not infer filterable columns from a response body.
- **At most one filter.** Only a single `column='value'` condition is known to work; two
  are refused before any request.
- **Range filters are designed, not built.** They would have to use the **hex** columns:
  `WHERE` is SQL, so `<=` / `>=` on a dotted string compares lexicographically
  (`"9.0.0.1" > "10.0.0.1"`), while zero-padded hex sorts like the address does.
- **Raw pass-through.** Every key SOLIDserver returns is forwarded under
  `action_result.data.*.<key>`, one data item per record (`data.*` is a list datapath).
  The field names were wrong under manual mapping four times, and the mock had been
  seeded with the same wrong names, so every local test passed.

## 5. The debug-log channel

Turned on by the `debug_logging` asset field; off by default, because the full exchange
buries the action result on a normal run.

It writes through `save_progress`, the only channel that reaches an operator with no
shell: it renders in both the App Debugger panel and a container action result.
`add_debug_data()` does not: it is dropped before the result is persisted.

| Line | Answers |
|---|---|
| `idle: Ns since last successful call` | Whether a failure follows a gap, a burst, or neither |
| `retry plan` | What the asset is configured to do |
| `attempt N/M: HTTP s from peer <ip:port>` | Which node served this call |
| `dns: <host> -> <addrs>` | Whether the APIM name resolves to several nodes |
| `sent:` / `sent headers` | The request as `requests` encoded it, read off the `PreparedRequest`, not our intent |
| `response headers` / `received body` | The gateway in its own words, logged on success too: a bad call is only readable next to a good one |
| `parse: <branch>` | Which response branch was taken |
| `client_cert/key/ca len=… sha256:…` | Whether the PEM material is the same across runs, without printing it |
| `ambient env` | Proxy/netrc/CA-bundle settings present but ignored (`trust_env=False`) |
| `curl equivalent` | A runnable curl for this exact request; the three credentials are shell variables, never values |

Secrets never print: auth headers, cookies and PEM material are replaced by a length and a
SHA-256 prefix.

Implementation details worth knowing:

- **Peer address** is read from the socket, which hangs off the response at different
  private paths across urllib3 versions (on 1.26 `_connection.sock` is already `None`
  while `_fp.fp.raw._sock` is live), so the known layouts are tried in order. It must be
  read before the body, which is why the request uses `stream=True`.
- **Every diagnostic is best-effort.** A diagnostic must never be the reason an action
  fails; each helper is guarded.
- **The curl emitter replays every header actually on the wire**, read back off the
  `PreparedRequest`, not an allowlist: an earlier allowlist dropped `Accept-Encoding` and
  `Connection` and "reproduced" a request that differed from the real one.
- **`getaddrinfo` has no timeout** and runs once per call before the request; with a slow
  resolver this can prepend tens of seconds. It is a candidate to log once at
  `initialize()` instead.

If the diagnostics are ever removed: `stream=True` and the explicit-session close ordering
go with the peer lookup, but **keep `trust_env=False` and `proxies = {}`**, which are
correct regardless.

## 6. Test connectivity

There is no health-check service. `GET /rest/ip_block_subnet_list?limit=1` is the one
endpoint that needs no filter; `limit=1` is required (see section 4).

## 7. History of the HTTP 401

Kept short; the detailed evidence is in the UC17 implementation plan.

1. **First real-appliance run: 401 on Test Connectivity.** The package shipped secrets as
   placeholders but the *identities* (client id, DDI username) from the lab mock. Real
   secrets paired with lab identities authenticate as nothing. Fixed in the asset config
   and in the export tool (identities are now placeholdered too).
2. **`list subnets` 401, `test connectivity` fine.** Theories asserted, none confirmed
   at the time: `WHERE` syntax, `limit`, percent-encoding, `Content-Type`, header
   shape, `trust_env`, rate limiting. Several were ruled out by direct evidence.
3. **Intermittent ~1-in-3 failures** measured with bare curl as well, so not a client
   fault; the evidence pointed at a gateway-side backend-leg failure. The retry and the
   diagnostics above were the response; escalation to the APIM administrator was the
   recommended path.
4. **Constant 401 on every call, `"The specified document is not valid JSON data"`.**
   The operator's working curl sent `x-ipm-username` / `x-ipm-password`; renaming only
   those two headers to `X-DDI-*` reproduced the 401 exactly. The connector had always
   sent `X-DDI-*`. v1.0.12 sends `X-IPM-*`. The same curl filtered `hostaddr`, not
   `host_addr`, which was also fixed.

**Lessons that generalise**

- When a working request and a failing one exist, **diff the exact wire bytes first**
  (headers by name, path, query) before building instrumentation or theories.
- **A mock that agrees with the connector proves nothing** about names neither has seen
  on the real system: both the header names and `host_addr` were wrong in the connector
  and seeded identically in the mock.
- A gateway may answer with a message that sounds like a body or schema problem for what
  is really an unrecognised header; do not read the text literally.

## 8. Open items

- IPv6 filtering on `hostaddr` is unverified.
- Range filters on `list subnets` need three read-only appliance probes before they are
  built (does `WHERE` accept `AND`; do comparison operators work; which representation do
  the range columns want). See the UC17 plan.
- Whether the diagnostics should be trimmed, per section 5.
