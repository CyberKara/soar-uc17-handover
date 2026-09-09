> **Note:** this copy has had 3 reference(s) to the source lab's own
> internal addresses replaced with `<lab-address-redacted>`. They named
> the lab that built this package, never a target system of yours.

# EfficientIP DDI Enrichment (UC17) — Implementation Plan

**Status:** [x] planned | [x] built | [x] E2E validated | [x] code review fixes | [x] VPE polish | [ ] released

> **Live ids move on every deploy — always resolve by name, never by an id
> written down here.** `./tools/uc17_verify.sh` does exactly that
> (`?_filter_name=`, highest version wins); so does
> `curl .../rest/playbook?_filter_name__icontains=efficientip`. Ids quoted in
> the dated sections below are historical records of what was live *that day*,
> not current state — see `[[project-soar85-gui-save-on-finish-output-clobber]]`.

> Design drafted 2026-08-24, approved 2026-08-25 (open questions below resolved by
> user). **Built + deployed + live-verified 2026-08-25 (later still)** — see
> "Build + live-verify (2026-08-25)" below.

## [!] SOLVED — the 401 was the gateway's backend leg, not this connector (2026-09-02)

**Read this before any other dated section below.** Everything under it that
treats the intermittent 401 as a connector, credential or header problem is
superseded. Do not reopen those threads.

### The evidence

`soar-connectors/tools/uc17_client_bisect.py` was run on the real airgapped
appliance under `phenv` (py3.13.11, requests 2.32.4, urllib3 1.26.19, OpenSSL
3.5.1) — eight client variants, three repeats each, one bounded URL:

```
2 ok   A401/401/200 B200 C200 D401/401/200 E401/200/401
       F200/200/401 G401/200/200 H200
4 peer A1 B1 C1 D1 E1 F1 G1 H-   (1 distinct)
5 msg  [1 record(s)]
```

Row A is **bare curl, the control**. It failed twice in three. Rows C
(requests at library defaults — the *pre*-1.0.6 shape) and H (stdlib `urllib`,
no requests at all) each passed 3/3.

A follow-up separated request rate from everything else:

```
burst  200 401 401 200 200 200 401 200 200 200   (3/10)
paced  200 200 401 401 200                        (2/5, 30s apart)
```

Pooled: **13 of 39 calls failed, ~33%, stable across three runs, two clients and
two request rates.**

Then a captured 401's response headers carried the answer:

```
X-Backside-Transport: FAIL FAIL
```

On IBM DataPower / API Connect that header reports the **backend leg**: `OK OK`
when the gateway reached its backend, `FAIL FAIL` when it did not. So on a
failing call the APIM accepted the client, attempted the backend, the backend
leg failed, and the gateway returned 401 on its own initiative.

### What this means

**The 401 was never an authentication verdict.** Every credential-shaped theory
this plan accumulated — leaked lab identities, the missing `.strip()`, the cert
path, `Content-Type`, `WHERE`+`limit`, `Vary`/header shape, `trust_env`, rate
limiting — was reading a gateway-synthesised status as an auth result. Six
causes were asserted over three weeks; the seventh was measured.

**No connector change fixes this.** The retry loop is the only mitigation
available on this side, and it is better justified now than when written: if the
gateway round-robins a backend pool, a retry re-picks a member. At ~33% per
attempt, `retry_count=3` leaves ~3.6% residual — a tuning decision, not a fix.

**It escalates, it does not get coded around.** Hand the APIM administrator the
`APIm-Debug-Trans-Id` of a `FAIL FAIL` 401; the assembly trace names the backend
member and why its leg failed. They are on the same side of the air gap as the
appliance.

**This finding is platform-independent.** It was established with bare curl on
the appliance, entirely outside SOAR, so unlike the rest of UC17's open items it
does **not** need re-pointing at SOAR 8.6.

### Consequence in code (connector v1.0.9)

The diagnostics built for this hunt are now behind an asset toggle,
`debug_logging`, **off by default** — kept rather than deleted because the fault
is an infrastructure one an operator may still need to observe. The same release
fixed the curl emitter, which replayed an allowlist of two headers and so
dropped `Accept-Encoding` and `Connection`; it now replays every header actually
on the wire.

See [[project-soar-efficientip-401-client-independent]].

## Client review — the cert path is cleared, one real defect found (2026-09-01, later)

A full read of the HTTP client (`_make_rest_call` -> `_process_response`) against
two hypotheses the user raised: that the instrumentation added this same day broke
the connector, and that the mTLS cert-file creation is failing.

### The cert path works — and a broken one cannot produce a 401

`_normalize_pem()` + `_setup_cert_files()` were driven against
`ssl.load_cert_chain()`, which is the exact call urllib3 makes for
`cert=(certfile, keyfile)`:

| Input | Result |
|---|---|
| RSA PKCS#8 key + cert | loads |
| EC key + cert | loads |
| RSA PKCS#1 (traditional) key | loads |
| Cert chain, leaf + intermediate | loads, block order preserved |
| CRLF line endings | loads |
| Leading/trailing whitespace | loads |
| **All newlines lost (single-line paste)** | loads |
| Key also pasted into the cert box | loads |

**The discriminator matters more than the pass list.** When the material *is* bad
the failure is not a 401: a cert or key field holding ciphertext — the stranded-value
case from `c9e9963` — raises `SSLError: [SSL] PEM lib`, which the client catches and
reports as **"TLS/mTLS error connecting to APIM"**. Two empty fields raise
`ValueError` before a socket is opened.

So, on the appliance: **if the operator is reading `401`, the client cert and key
loaded and were presented.** A failing cert path reads "TLS/mTLS error" instead. One
look at the error text eliminates the entire class, with no code change and no
further probe. This is a fifth cause *tested and excluded*, not a fifth cause
asserted.

Caveat: run on the build host's Python/OpenSSL with the SOAR runtime stubbed, not
under soar8's `phenv` Python 3.13. Re-run there before treating it as absolute.

### The instrumentation post-dates the original 401

The real-appliance 401s were observed **2026-08-26 to 2026-08-28**. Every bespoke
addition — diagnostics `b927e15`, retry `bc67bb8`, no-cache/30s `19ae77d`,
trust_env/session `33b38c1`, curl equivalent `b8a36de` — landed **2026-09-01**.
Code from the 1st cannot have caused a 401 from the 26th. It remains fair game as a
cause of any **new** 401 observed on v1.0.5+.

### [!] Real defect: `user_agent` ships defaulted to `curl/8.4.0`

`efficientip_ddi.json` declares `user_agent` with `"default": "curl/8.4.0"`, so
every asset created from this app forges a curl User-Agent on every request unless
the operator clears the field by hand. The connector's own comment says it was meant
to be *"set back to blank once the question is settled"* — it shipped defaulted
**on**. A gateway with a UA-keyed bot filter or client policy is exactly the kind of
thing that answers 401/403, so the field intended to *test* a theory is now
permanently *asserting* one on the wire. **This is the strongest candidate in the
added code for a 401 seen now.** Fix is one line: default to `""`.

### Retry amplification

Retrying 401 three times sends three failed authentications per action where the
appliance previously saw one. On a gateway with a failed-auth threshold that can
convert a transient 401 into a sustained lockout — making the symptom look more
persistent than its cause, which is the opposite of what the retry was built for.

### The diagnostics have no precedent in any vendor connector

Checked against the vendored reference corpus — 8 collections, 144 apps in Splunk's
own `phantom-apps` monorepo, **379 `*_connector.py` modules**, 1606 Python files:

| Pattern | Connector hits | What the hits actually are |
|---|---|---|
| `getaddrinfo` per request | **0** | 1 file: vendored `httplib2` transport |
| `gethostbyname` | 2 | both in `initialize()`, functional `127.` guard |
| `getpeername` | **0** | vendored `socks.py` *defining* the method |
| `raw._connection` / `_fp.fp` / `_original_response` | **0** | — |
| `response.request` read-back | **0** | 1: Akamai `edgegrid` *writing* an auth header |
| runtime curl synthesis | **0** | 1: a docstring example in `code42_connector.py` |
| `trust_env = False` | **0** | — |
| `stream=True` | 23 files | all file downloads; none peek at the socket |

`stream=True` is idiomatic — but every one of those 23 uses it to stream a file to
disk or the vault via `iter_content`/`copyfileobj`. Here it exists **only** to let
`_peer_address()` read the socket before the body. Remove that diagnostic and
`stream=True` goes with it, along with the torn-down-connection-pool hazard the
session comment defends against: three of the file's oddest constructs fall out
together.

Not everything unprecedented is wrong. **`trust_env = False` + `proxies = {}` should
stay** regardless of the count: a matching `~/.netrc` entry silently *replacing* the
`Authorization` header is real `requests` behaviour and a real 401 source. The
distinction is no-precedent-but-correct versus no-precedent-and-costly.

### Latent: unbounded DNS on the action path

`_resolve_peers()` calls `socket.getaddrinfo()`, which takes no timeout and cannot be
bounded from Python, once per `_make_rest_call` *before* the request. soar8's
`/etc/resolv.conf` lists three nameservers with no `options` line, so glibc defaults
apply (`timeout:5`, `attempts:2`) — worst case **30s prepended to every action**,
outside the retry accounting and outside the 30s the code advertises as its budget.
Currently costs nothing (`soar8.<lab-address-redacted>` resolves in 5.6 ms), so this is latent,
not live. `_peer_address()` already answers the real question — which node served
*this* call — from the actual socket; `_resolve_peers()` only answers what the name
*could* resolve to, and that is a static property better logged once at
`initialize()`.

### Status

No code changed. The `user_agent` default and the fate of the instrumentation block
are decisions for the user — logged in `/data/splunk/docs/next-steps.md`.

## Retry on 401 + the response-code contract — v1.0.2 (2026-09-01)

**New vendor information, and the first mitigation for the intermittent 401.**
The API returns exactly four codes:

| Code | Meaning | Notes |
|---|---|---|
| `200` | success | |
| `204` | no content | zero matching records on a list endpoint — not an error |
| `400` | **bad request** (backend) | body carries `errno`/`sql_error` |
| `401` | unauthorized | the **only** auth-layer code |
| `403` | **bad request** (gateway) | malformed/invalid request — **not** "forbidden" |

**Resolved 2026-09-01 (latest): `host_addr` is the dotted column — the hex round
trip is gone.** The analyst's "look this IP up by its dotted address" need is
answered by a sibling-column pair on `ip_address_list`:

| Column | Form | Used by |
|---|---|---|
| `host_addr` | dotted (`10.10.10.10`) | **this connector, since v1.0.5** |
| `ip_addr` | zero-padded hex (`0a0a0a0a`) | nothing here any more |

`get ip address` now builds `WHERE=host_addr='<dotted ip>'` and `_ip_to_hex()` is
replaced by `_validate_ip()`, which keeps the validation that mattered (reject
hostnames, CIDR ranges, typos before they reach the clause) and normalises IPv6
to its compressed form. Live-verified on soar8: `WHERE=host_addr%3D%2710.20.30.40%27`
observed on the wire, all 5 actions PASS, playbook end-to-end unchanged.

This retires the earlier reasoning in this section that treated the hex path as
the answer. That reasoning was not wrong about `ip_addr` — the `204` did prove it
a real column — it was just the harder of two available routes, and the mock
could not have revealed the easier one: its `ip_address_list` seed carried no
`host_addr` field at all until this change. **Both mock copies now seed and
filter it.** That is the same blind spot that masked three field-name bugs
before, hit for a fourth time.

**[!] If the deferred range filters are ever built, they must use the HEX
columns.** `WHERE` is SQL, so `<=`/`>=` on a dotted string compares
lexicographically: `"9.0.0.1" > "10.0.0.1"` is true as a string and wrong as an
address. Zero-padded hex sorts identically to numeric order, which is very
likely why both column families exist. Equality is safe in either form;
containment is not. This applies directly to the `subnet_start_hostaddr` /
`subnet_end_hostaddr` approach that was considered for IP-to-subnet
containment — those are the dotted columns, and using them for a range would
silently return wrong subnets at octet boundaries.

**Refined again 2026-09-01 (later still): the quoting rule is SQL typing, the
`=` encoding is irrelevant, and a `204` is a column-validity signal.** Four
probes now separate every variable that was previously confounded:

| # | Query | `=` | Quotes | Type | Result |
|---|---|---|---|---|---|
| A | `WHERE=ip_addr=<hex>` | raw | none | string | **400** `errno 50028` |
| B | `WHERE=ip_addr%3D%27<hex>%27` | encoded | yes | string | **204** |
| C | `WHERE=ip_id%3D1697182` | encoded | none | integer | **records** |
| D | `WHERE=ip_id=1697182` | raw | none | integer | **records** |

**C vs D** isolates the encoding: identical but for `%3D` vs `=`, identical
result — so percent-encoding the `=` makes no difference. **A vs D** isolates the
rest: both raw `=` and unquoted, differing only in the value's type — the string
fails, the integer works. Together these retire the caveat recorded earlier
today, that probes A and B differed in two ways and could not separate quoting
from encoding. They now can, and the answer is **quoting, entirely**.

So the clause types values the way SQL does: string values need quotes, integers
do not, and the `=` never needs encoding. The earlier `400` was an unquoted
*string* (a hex `ip_addr`), not a missing-quotes rule in general. Every column
currently exposed is string-typed, so `_bounded_query()` quoting unconditionally
is correct today, and letting `requests` handle URL encoding remains fine.

This also answers the analyst's "how do I search by dotted IP?" question, which
looked open only because of a wrong assumption:

- **The capability already ships.** `get ip address` takes a dotted IPv4 or IPv6
  and converts it to hex internally (`_ip_to_hex`) before building
  `WHERE=ip_addr='<hex>'`. The analyst never types hex: `10.10.10.10` becomes
  `0a0a0a0a`, `2001:db8::1` becomes `20010db8000000000000000000000001`.
- **`ip_addr` is already proven to be a real filterable column.** The 2026-09-01
  quoted probe returned **204**, not 400/403 — meaning the clause *parsed* and
  matched nothing. A bad column errors; it does not 204. So the hex path is
  syntactically confirmed and only the test *value* failed to match.
- **Do not read the filterable columns off the response body.** Already disproven
  on `ip_block_subnet_list` (`name` in the response, `subnet_name` in the filter).
  `hostaddr` being absent from an `ip_address_list` response is not evidence that
  it cannot be filtered on.

**Self-validating probe to close this** (uses only the appliance's own data, no
guessing): take the record already retrieved via `WHERE=ip_id=1697182`, read its
`ip_addr` value out of that response, then run
`?limit=25&WHERE=ip_addr='<that exact hex>'`. Returning the same record confirms
the dotted-IP path end to end. Worth running once for an IPv4 record and once for
an IPv6 one, since **hex encoding is vendor-confirmed for IPv4 only** and the
IPv6 form is still an analogy.

Optional ergonomic probe, if a dotted filter would suit the analyst better than
hex: `?limit=25&WHERE=hostaddr='10.10.10.10'`. Plausible by analogy with
`start_hostaddr`/`end_hostaddr` on `ip_block_subnet_list`, unconfirmed here, and
**the mock cannot validate it** — its `ip_address_list` seed carries no
`hostaddr` field at all.

**Corrected 2026-09-01 (later), by real-appliance probe.** The vendor-stated list
had four codes and did not include `400`; the appliance returns one. Two probes
against `ip_address_list`:

| Probe | Result |
|---|---|
| `?limit=1&WHERE=ip_addr=<hex>` (value unquoted) | **400**, body `[{"errno":"50028","sql_error":"7"}]` |
| `?limit=1&WHERE=ip_addr%3D%27<hex>%27` (value quoted) | **204**, empty |

So "bad request" arrives as **either** code. The likeliest reading is two layers
rejecting it — `403` from the APIM gateway, `400` from the SOLIDserver backend
behind it, which is why only the `400` body carries an `errno`. The connector
treats them identically: named as a bad request, never retried, with `errno` and
`sql_error` pulled out of the list-shaped error body into the message.

The operative variable between the two probes is the **quoting**, not the
encoding: unquoted, the value reaches SQL and is rejected there (`sql_error`);
quoted, it parses and returns a clean 204 for no match. Note the probes differ in
two ways at once — quotes *and* `=` encoding — so they do not separate those on
their own; encoded `WHERE` was already confirmed working on 2026-08-29, which is
what leaves quoting as the variable that moved. `_bounded_query()` has always
quoted, so no action was needed there.

Both probes also carried `WHERE` **and** `limit` and neither 401'd — an
independent reconfirmation of the shell-artefact revert.

### Why 403 matters more than it looks

`403` does not carry its standard HTTP meaning here. Read as plain HTTP it reads
as a permissions problem and sends an operator hunting credentials and
entitlements, which is the wrong half of the stack; on this API it means the
*request* was wrong — bad filter column, bad `WHERE` syntax, invalid parameter.
The connector's error text now says so in place of a bare `HTTP 403`, which
matters most on the airgapped appliance where that message is all the operator
has.

It also **narrows the open 401 investigation**, at no cost. Since a malformed
request returns `403`, a `401` cannot be the gateway's way of rejecting a bad
query — so every query-shaped explanation is ruled out by the contract alone.
That retroactively explains why the dead theories died: `WHERE` syntax, the
`limit` parameter and percent-encoding were all query-shaped, and a query fault
would have surfaced as `403`, never `401`. This is narrowing, not a fifth theory:
the 401 is auth-layer, which is consistent with the observed intermittency.

### The retry (user decision)

Retrying a 401 is normally an anti-pattern — it re-sends credentials the server
just rejected. What makes it correct here is the evidence in the section below:
the connector holds no per-call state, so identical inputs produce identical
bytes, and those identical bytes get 401 on one trigger and 200 on the next. That
is a transient gateway fault, not a wrong credential.

- **Every action, `test connectivity` included.** Asked for explicitly. The
  standing objection was that retrying there hides a genuinely broken asset
  config — the exact failure mode of 2026-08-28 — but per-attempt logging
  answers it: a real bad credential fails all attempts and the log shows each
  401. The only cost is latency on a genuinely broken asset.
- **`401` only.** `400` and `403` are deterministic; retrying them just
  multiplies latency before the same failure.
- **Linear backoff, low cap.** Rapid repeated auth failures are what trip gateway
  lockout and quota policies. Of the three surviving causes, retry helps two and
  actively harms the third (quota) — backoff and a cap of 3 keep that bounded.
  Operator-tunable per asset via `retry_count` / `retry_backoff`, because the
  right value depends on which cause it turns out to be.
- **Never silent.** Every attempt logs its peer address; a late success reports
  `Succeeded on attempt N of M` in the action result.

The retry is a mitigation, not a diagnosis, and is built so that running it
yields *better* evidence than not running it: attempt 1 failing at one peer and
attempt 2 succeeding at another identifies the load-balancer theory in a single
pair of log lines.

### `idle:` — the line that discriminates

A last-success timestamp now persists in `self._state`, and every call logs the
gap since it. Each surviving theory predicts a different relationship to that
number, so one failing/succeeding pair separates all three:

| Theory | Correlates with |
|---|---|
| Auth-cache expiry | a **gap** since the last successful call |
| Quota / rate-limit | **burst rate** — the opposite pattern |
| Load-balanced node with inconsistent trust | neither; shows up in the peer address |

Note there is **no client-side session to configure**: the connector opens a
fresh connection per call and holds no cookie or token, so if an auth cache is
the cause it lives on the APIM and its TTL cannot be set from here. What the
asset exposes instead is the retry *backoff*, which is the lever that actually
helps against a TTL gap.

### Status

Built, installed and verified on soar8 (app **209**, v1.0.3), `uc17_verify.sh`
green — all 5 actions PASS through real `action_run` dispatch, playbook
end-to-end unchanged. The three new log lines were confirmed rendering on the
live dispatch path, and the idle baseline confirmed persisting across action
runs. 56 unit tests pass (15 new, covering the retry sequences, the `400`/`403`
no-retry rule, `errno` extraction, `204` handling and config clamping).

**Not proven live: a real 401 escalating to attempt 2.** The mock returns 401
only for bad credentials, so forcing that on soar8 would mean either editing a
working asset's credentials or restarting the Ansible-owned mock service. Unit
tests cover the sequence; the real proof will come from the appliance.

**Handover impact:** the asset template gains two fields (`retry_count`,
`retry_backoff`). Both are optional with defaults, so an existing asset upgrades
cleanly and no operator re-entry is required.

## [!] Diagnostics build v1.0.1 (2026-09-01) — chasing an intermittent 401

**Connector v1.0.1 adds GUI-visible request/response logging and changes nothing
else.** No action, parameter, endpoint or auth behaviour is touched. It exists to
make one open problem legible from the airgapped appliance, where the operator has
the web UI and nothing else.

### The problem it is built for

The user reports, on the real appliance, from **both** the App Debugger panel and a
container action run:

- `test connectivity` and `list subnets` fail with **HTTP 401 on one trigger and
  succeed on the next**, apparently at random. Responses are fast, so nothing is
  timing out.
- A run of ten consecutive `limit=2` failures initially looked like the parameter
  was at fault. **It is not** — `limit=2` was retested later the same day and
  worked. The failures are bursty in time, and changing a parameter at the start of
  a bad burst impersonated a parameter-dependent bug.

**The connector cannot be the source of the intermittency.** Its request path holds
no per-call state: `_auth_headers()` recomputes every header from config on each
call, `self._state` carries only `app_version`, certs are written and deleted per
call, each call opens a new connection, and there is no retry logic. Identical
inputs produce identical bytes. So the variable is outside this code, and the log
exists to find out which.

### What is logged, and what each line is for

Everything goes through `save_progress`, the only channel that reaches an operator
with no shell — it renders in both the App Debugger panel and the container action
result. `add_action_result().add_debug_data()` does **not**: it is dropped before
the result is persisted (verified on soar8 `app_run` 6507), which is why the
response headers this connector had always collected were never visible to anyone.

| Line | Answers |
|---|---|
| `dns: <host> -> <addrs>` | Does the APIM name resolve to more than one node? |
| `HTTP <s> from peer <ip:port>` | **Which node served this call.** The decisive one: a 401 that follows one address while 200s follow another names the bad node. |
| `-- N ms to headers, M ms total` | A fast reject, a stalled auth decision and a slow body all look different here. |
| `client_cert len=… sha256:…` | Was the material identical on a call that worked and one that did not? Rules the asset in or out without re-entering anything. |
| `sent: <method> <url>` | The URL **as requests encoded it**, read back off the PreparedRequest — not our intent. |
| `sent headers` | Includes what requests added itself (Host, User-Agent, `Connection: keep-alive`). |
| `response headers` | `WWW-Authenticate`, quota/rate-limit counters, gateway request-ids. |
| `received body` | The gateway in its own words — logged on success **and** failure, because an intermittent fault is only readable by diffing a good call against a bad one. |
| `parse: <branch>` | Which of the four response branches was taken — an empty 204 and an empty JSON array both end as "no records found". |

Secrets never print: auth headers, cookies and PEM material are replaced by a
length and a SHA-256 prefix, asserted by a test.

### What to send back from the appliance

The `peer` line for one failing call and one succeeding call, taken close together.
That single pair distinguishes a load-balanced node with inconsistent trust from a
quota policy from a session-cache expiry — the three shapes this could still be.

### Leads already dead — do not re-open

- **Percent-encoding of the `WHERE` clause.** `%3D`/`%27` are accepted: the
  appliance returned 200 for `ip_address_list?WHERE=ip_addr%3D%27<hex>%27` on
  2026-08-29 (see "Ruling out the encoding" below).
- **The `limit` parameter**, per the retest above.
- Four causes have now been asserted for a UC17 401 and none has survived. **Do not
  adopt a fifth without evidence from the log above.**

Verified before shipping: `uc17_verify.sh` green (all 5 actions PASS through real
playbook dispatch), and the peer-address lookup works on both soar8's
`requests 2.32.4` and the build host's 2.25.1 — the socket's location is a urllib3
private detail that moved between versions, so five known layouts are tried in turn.

## [!] One connector, classic style — the SDK app was deleted (2026-08-31)

**User decision, taken after testing both connectors on the real airgapped
appliance.** This use case shipped two deliberately parallel connectors from
2026-08-26: `efficientip_ddi` (SOAR SDK) and `efficientip_ddi_classic` (classic
`BaseConnector` twin), carried across the air gap together so their behaviour
could be compared against the real SOLIDserver/APIM. That comparison is now
closed, in the classic app's favour.

**What the user found.** In the connector's GUI **edit/view mode**, running any
action from the left-hand panel fails for the SDK app — every action, every time.
The classic app's actions in that same panel *partially* work. The decision
followed directly: an app whose actions never run from that panel is worse than
one whose actions sometimes do.

**What that failure actually is.** That panel is the **App Debugger**
(`/rest/debug_action`), and SOAR 8.5 never registers action handlers for
SDK-based apps there — it answers "Action X not found" regardless of app
correctness or version. It is a **platform limitation, not a defect in the SDK
connector**, and it does not affect the real dispatch paths (asset Test
Connectivity, playbooks, `/rest/action_run`), which is why every verification
run in the dated sections below passed. See
`[[project-soar85-app-debugger-sdk-action-not-found]]`, where this was already
recorded on 2026-08-26 — as a debugging caveat, without anyone drawing the
conclusion that it makes an SDK app the wrong choice for an airgapped target.

**Why it decides the matter anyway.** On the airgapped appliance the operator has
the web UI and nothing else: no `curl`, no REST tooling, no playbook harness
against a mock. The App Debugger panel is their only hands-on way to run a single
action and read its result. A connector style that disables it removes the only
diagnostic loop available on the machine that matters. That is an operational
requirement the SDK app cannot meet on SOAR 8.5, independent of code quality.

### What changed

| | Before | After |
|---|---|---|
| Connectors | `efficientip_ddi` (SDK) + `efficientip_ddi_classic` (classic) | `efficientip_ddi` (classic) |
| Repo | `soar-connectors/connectors/efficientip_ddi/` (SDK) + `…_classic/` | `soar-connectors/connectors/efficientip_ddi/` — the classic app, renamed |
| App `appid` | `b847c7d1-…` (SDK) / `daa10f0c-…` (classic) | `33986f6c-2005-4c3a-aa8b-d7a83caa76d0` (fresh) |
| App display name | `efficientip_ddi` / `EfficientIP DDI (Classic)` | `EfficientIP DDI` |
| `app_version` | 1.0.4 (SDK) / 1.0.2 (classic) | **1.0.0** — reset with the identity |
| Diagnostic playbooks | `efficientip_ddi_action_test` (SDK) + `…_classic_action_test` | `efficientip_ddi_action_test` — the classic one, renamed |
| Asset | `efficientip_ddi mock` (28) + `efficientip_ddi_classic mock` (29) | `efficientip_ddi mock` |

- The SDK connector was **deleted from the repo**, not parked — source,
  `pyproject.toml`, `uv.lock`, `release_notes/`, its bundled wheel tree and its
  README are gone. Git history keeps them; nothing else does.
- The classic connector **took over the deleted app's name and role** and was
  given a **fresh `appid`** so the airgapped SOAR treats the package as a new app
  rather than reconciling it against stale GUI state, exactly as on 2026-08-29.
- The classic README was rebuilt from the deleted SDK app's, which was where the
  field-name provenance lived — `docs/dev-rules.md` and
  `efficientip_ddi_consts.py` both point at it.
- **FR-01 flipped for this connector.** It was a *temporary* exemption whose
  removal condition was "delete the classic app once the SDK one is confirmed
  working on the real appliance". That condition resolved the other way, so the
  exemption is now **permanent** and the SDK app is the one that was deleted.
  FR-01's own text now carries the operational caveat, so the next connector
  destined for the air gap gets to weigh it before a style is chosen.

### Not decided here

FR-01 itself still stands: **new connectors are SDK by default.** This is one
recorded exemption, driven by one target's operating constraints — not a
reversal of the 2026-07-18 decision. Whether the App Debugger limitation should
change the default for *every* airgapped-bound connector is a separate call, and
the user has not been asked it.

### Still open, unchanged by this

The real-appliance items the SDK/classic split was originally meant to help
settle are all still open, and now rest on the classic app alone: the
analogy-based field names on `ip_alias_list` and `get_ip_pool` (`raw_json`
covers them meanwhile), the deferred `list subnets` **range** filters, and the
unexplained `list subnets` 401 — three causes have been asserted for that 401 and
none survived, so do not adopt a fourth without evidence.

---

## Context

Analyst-driven IP/DNS lookup enrichment against EfficientIP SOLIDserver (DDI:
DNS/DHCP/IPAM), reached through an APIM gateway. The connector was built and
installed first, per explicit user request — this doc covers the playbook side
that calls it, the second half of the same `/kara-do-uc-create` session.

> **Reading the dated sections below.** They are a historical log. Everything
> before 2026-08-31 was written while this UC had **two** connectors, an SDK app
> and a classic twin, and quotes both by version and app id. Only the classic one
> survives — see the section above for what it is now called and how it is
> versioned. Treat "the SDK connector", "the classic twin", every `app_version`
> and every app/playbook id below as a record of that day, not current state.

**No real SOLIDserver/APIM instance exists.** The connector's only backend is
`soar8/migration/mock-backend/mock_efficientip_ddi.py` (:8447), now deployed as
`mock-efficientip-ddi.service` on the ansible controller (`<lab-address-redacted>`, mTLS
left enabled — matching the real APIM's requirement, unlike the other mocks'
`--no-mtls` convenience), same pattern as the existing mock services, firewalled
to soar8's source IP only (Ansible-side fix, 2026-08-25 — see ansible project's
`docs/next-steps.md`). The `efficientip_ddi mock` SOAR asset (id 19) passes
`test connectivity` and all 5 actions complete the full mTLS+auth+HTTP round trip
against app id 205 (v1.0.0, appid `71a7abcc-...` — reset from the original
`414f081c-...` after an unrelated `soarapps package build` wheel-bundling bug,
see NFR-09 in `soar-connectors/docs/dev-rules.md`, required reinstalling anyway).

Connector actions available (as of app v1.0.0/appid `71a7abcc-...`, app id 205):
`test connectivity`, `get ip address` (IPAM lookup by IP — `ip_id`, subnet, space,
status, hostname, MAC, class, description), `list subnets`, `get ip pool`, `list
aliases` (aliases of a known `ip_id`, chained off `get ip address`'s output).
**`get dns record` does not exist** — no confirmed record-level DNS service was
ever found on the real APIM (only zone-level `dns_zone_list`), so the action was
removed rather than shipped on a guess. See
`soar8/soar-connectors/connectors/efficientip_ddi/README.md` for the full contract.

## Architecture (revised 2026-08-25 — `get dns record` removal)

**One Data playbook, no orchestrator, no CFs.** Two chained lookup actions with no
branching complexity between them doesn't justify a parent/child split or a custom
function — matches `constraints.md`'s bias toward the simplest structure that fits.

The original design paired an `ip` input with `get ip address` and a `hostname`
input with `get dns record` — that second half no longer has an action to call.
**User decision (2026-08-25):** drop the `hostname` input entirely; replace the
DNS-ish angle with `list aliases`, chained off `get ip address`'s `ip_id` output —
alias hostnames (e.g. `host01-alt.corp.local`) cover similar ground to a DNS
lookup for this use case's purposes, without inventing an unconfirmed endpoint.

- **`efficientip_ddi_enrich`** (Data playbook, `playbooks/efficientip_ddi_enrich/`)
  - **Trigger**: none — not automation-triggered. Runs either analyst-initiated
    (manually launched against an existing container) or chained from another UC's
    playbook via `phantom.playbook()`, the same role `ip_enrich` plays for UC2/UC3
    today.
  - **Inputs** (`playbook_input`): `ip` (required string) — single input now.
  - **Flow**:
    1. `on_start` — native **decision** block: if `ip` is empty, route to
       `format_error` (native **format** block → terminal note); otherwise continue.
    2. Native **action** block: `get ip address` on the `efficientip_ddi` asset,
       input bound to `playbook_input:ip`.
    3. Native **decision** block: if `get ip address` succeeded and its `ip_id`
       output is non-empty, continue to alias lookup; otherwise skip straight to
       the format/note step with just the IP result (or the failure noted) —
       partial success stays a first-class outcome, not an error (see resolved
       question 1 below, still applies to this chain).
    4. Native **action** block: `list aliases` on the same asset, input bound to
       `get_ip_address:action_result.data.*.ip_id` (the prior action's own output,
       not `playbook_input`).
    5. Both paths converge on a native **format** block assembling a
       human-readable summary (subnet/space/status/hostname/MAC/class/description
       from `get ip address`, plus alias name(s) from `list aliases` if that step
       ran), then `phantom.add_note()` on the container so an analyst running this
       manually sees the result without digging into action-run history.
    6. `phantom.save_playbook_output_data()` exposes the raw action-result fields
       (not just the formatted note) so a **parent** playbook that chains this one
       can consume individual fields directly — same pattern as
       `playbook-patterns.md`'s documented `output_spec` usage.
  - **Activation**: none needed — Data playbooks aren't automation-triggered, so
    there's nothing to `POST /rest/playbook/{id} {"active": true}` here.

## Open questions — resolved 2026-08-25

1. **Partial success is fine.** If `get ip address` succeeds but the alias lookup
   404s (or vice versa were both still independent), that is not a playbook
   failure — note the partial result in the summary rather than erroring out.
2. **Keeps its UC number — stays UC17**, not reclassified as an unnumbered
   Integration.
3. **No UC chains into this right away.** Ships standalone, buildable/testable
   on its own; wiring into a parent UC (if any) is deferred to later.
4. **(New, resolved same day) `hostname`/`get dns record` dropped, replaced by
   `ip`→`get ip address`→`list aliases` chaining** — see Architecture above.

## Testing strategy

Same mock-first approach as every other UC: against the now-reachable
`efficientip_ddi mock` asset (id 19, `mock-efficientip-ddi.service` on the ansible
controller), run the playbook against a test container with `ip` matching the
mock's seed data (`10.20.30.40`, `ip_id` 1001, alias `host01-alt.corp.local`),
confirm the note and `save_playbook_output_data()` fields both come back correct
for the full chain, then confirm the not-found path (e.g. `10.20.30.99`, which has
no alias seed data) produces the intended partial-success behavior per question 1.

## Build + live-verify (2026-08-25, later still)

Built exactly per the Architecture above (single Data playbook, no CFs, native
action/decision/format blocks per `vpe-block-reference.md`) and registered in
`deploy.py`/`pull_soar.py`/`snapshot.py`'s hardcoded `USE_CASES` (see
`project-soar-deploy-manifest-hardcoded` memory). Deployed to soar8 as
`efficientip_ddi_enrich` id=672 v3, labeled `events` (no dedicated
`efficientip_ddi` label exists yet — labels can't be created via REST, only
the SOAR Admin GUI; using the pre-existing generic `events` label kept this
launchable without a new admin step, since the design never mandated a
specific label). Connector-side prerequisite: `efficientip_ddi` v1.0.0→v1.0.1
fixed 3 field-name bugs found by cross-referencing SOLIDserver's real public
REST docs (`get ip address`'s hostname is `name` not `hostdev_name`,
`get ip pool`'s range fields are `start_hostaddr`/`end_hostaddr` not
`pool_start_hostaddr`/`pool_end_hostaddr`, `list aliases`' name field is
`alias_name` not `ip_alias`) — see `soar-connectors` README/app.py and commit
`25ff063`. Mock restarted to pick up the matching fix.

**Real bug found and fixed during first live run:** `phantom.save_playbook_output_data()`
raises `RuntimeError: ... only allowed within the "on_finish"` when called from
a regular `@phantom.playbook_block()` function — confirmed via a real traceback
in `decided.log`. The Architecture's step 6 (and `tie_attack_detail.py`'s
`build_enrichment_note`, which this design partly modeled) call it from a
non-`on_finish` block; that pattern is apparently untested against a real
SOAR 8.5 GUI/live run (consistent with `tie_attack_detail` never having had
"a real GUI open-and-look pass", per existing memory). Fixed by switching to
the documented `save_run_data` → `on_finish` → `save_playbook_output_data`
pattern (`playbook-patterns.md`'s "save_run_data + on_finish output" section)
in both `finalize` and `note_error`. **This may be a broader latent bug** —
any other playbook in this repo calling `save_playbook_output_data()` outside
`on_finish` would hit the same RuntimeError on a real run; worth a repo-wide
grep, not chased here (out of UC17's scope).

> **Repo-wide grep DONE 2026-08-27** (commit `dd6bba9`). Only offender was
> `tie_attack_detail.py`'s `build_enrichment_note`. But the audit turned up a
> second, worse problem in the fix *itself*: moving the call into `on_finish`
> is not sufficient, because `on_finish` was written with no
> `## Custom Code Start/End` markers. `userCode` is built only from text
> between those markers, so the call lived in `.py` alone — it deploys and runs,
> but the first VPE open-and-save regenerates `on_finish` empty and the playbook
> silently emits **no output at all**. That would have fired on this very
> document's outstanding "VPE GUI open-and-look pass". `check_usercode_sync.py`
> reported clean throughout because it skipped marker-less functions; it now
> reports `NOMARKERS` and exits non-zero. Fixed here and in three `tenable_ad`
> playbooks. See `docs/vpe-dev/constraints.md`.

**Live-verified against soar8 + mock (container 1835, playbook id 672),
4 real `/rest/playbook_run` calls:**
- `ip=10.20.30.40` (has alias): full chain, all 9 output fields populated
  correctly, note written, overall run `status: success`.
- `ip=10.20.30.99` (no hostname/mac/alias in seed but ip_id found): partial
  fields correctly empty, `alias_name` empty since no alias seed exists for
  `ip_id=1002`, note written, overall run `status: success` (get_ip_address
  itself succeeded).
- `ip=10.20.30.200` (not in mock at all): `check_ip_found` correctly routed
  around `list_aliases`, saved output correctly shows `status: partial`, note
  written — but the **overall `playbook_run.status` shows `failed`**, because
  `get_ip_address` itself raised `ActionFailure` (connector's "not found"
  convention) and SOAR's run-level status aggregates from constituent action
  statuses regardless of downstream graceful handling. This is a platform
  behavior, not a playbook bug — `on_finish` still runs and the saved output
  data is correct either way — but it means an analyst/parent playbook reading
  only the coarse run status (not `save_playbook_output_data`'s own `status`
  field) would see a not-found lookup as "failed" rather than "partial". Not
  fixed (would require the connector to stop raising on not-found, a
  connector-design decision out of this playbook's scope) — flagged here for
  awareness.
- Empty `ip`: `check_input` correctly routed to the error path, note written,
  saved output `status: error`, overall run `status: success` (no action ever
  ran, nothing to fail).

No parent UC currently chains into this, per resolved question 3.

---

## Open items (from the 2026-08-27 code review)

### Resolved 2026-08-27 (connector v1.0.7 / classic v1.0.5 — built, NOT yet installed)

- [x] **`list aliases` / `list subnets` returned only `records[0]`.** All four
  record-returning actions on both connectors now emit one row per record
  (`list[ActionOutput]` on the SDK side, a per-record `add_data()` loop on the
  classic side, with `total_objects` reporting the true count instead of a
  hardcoded `1`).
- [x] **`limit` is now a real action parameter** (numeric, optional, default 1)
  on all four, replacing the hardcoded `limit=1` — this was the already-agreed
  design from 2026-08-26 and it is also what makes the multi-record fix
  reachable, since `limit=1` would otherwise guarantee the truncation stayed.
  A bound still always goes on the wire (unbounded calls time out on the real
  APIM); raising it is now the caller's to do. At the default, behavior is
  identical to v1.0.6, so nothing calling these actions today changes.
  `test connectivity` keeps a fixed `limit=1` — no parameter surface.
- [x] **`ip_id` type split.** `list aliases`' parameter is now a string on both
  connectors, matching `get ip address`' string output, so the chain the action
  descriptions instruct users to build is actually wireable in the VPE.
- [x] **Classic `param["ip_id"]` interpolated raw into the URL path.** Both
  connectors now run it through a `_validate_int()` (the `proofpoint_trap`
  `_validate_integer()` precedent), so a float `1001.0` can no longer become
  `/rest/ip_alias_list/ip_id/1001.0` and a false "no aliases". `1001.5` is
  rejected rather than truncated.
- [x] **`_ip_to_hex()` raised a bare `ValueError`** for a hostname/CIDR/typo.
  Both connectors now fail the action cleanly with a message saying what the
  parameter actually takes, and without calling the API at all.
- [x] **Mock `_WHERE_RE` never un-doubled `''`.** Fixed in both mock copies,
  which now also honor `limit`, seed a two-alias IP, and seed a pool name
  containing an apostrophe — the escaping path previously had no seed data that
  could exercise it.
- [x] **The escaping path had no regression coverage.** Added
  `efficientip_ddi_classic/tests/` (23 tests) and
  `soar-connectors/test/test_mock_efficientip_ddi.py` (16 tests). This paid for
  itself immediately: the float-`ip_id` test failed against the first draft of
  `_validate_int()`, which used `int(str(value))` and so rejected `1001.0` —
  exactly the case it was written to absorb.
- [x] **Playbook `finalize()` kept only `alias_result[0][0]`.** Now collects
  every alias. Output spec gains `alias_names` (comma-separated, all) and
  `alias_count`; `alias_name` still carries the first, so existing callers are
  unaffected. The summary note's line is relabelled "Aliases".
- [x] **`check_ip_found` gated on `ip_id != ""` only.** Now also requires
  `get_ip_address:action_result.status == "success"`, matching what the
  Architecture section always said. Fixed in both the `.py` and the decision
  node's JSON conditions (a native block's config does not live in `userCode`,
  so `check_usercode_sync.py --fix` would not have caught it).
- [x] **`docs/dev-rules.md` inventory row was stale** (app id 204,
  `get dns record`, "no playbook built yet"). Rewritten, and
  `efficientip_ddi_classic` added to the table for the first time.
- [x] **FR-01 exemption for the classic twin was unrecorded.** Now written into
  FR-01 itself as the one standing exemption, with its scope ("not a maintained
  implementation, do not extend") and an explicit removal condition.

### Found while doing the above — corrects a standing project belief

- [x] **The "NFR-09 `soarapps package build` wheel-drop bug" is not a bug.**
  The 7 omitted packages (`requests`, `urllib3`, `certifi`, `idna`,
  `charset_normalizer`, `beautifulsoup4`, `soupsieve`) are entries in the SDK's
  own `DEPENDENCIES_TO_SKIP`, documented in its source as *"provided by the
  Python runner"* and sourced from Splunk's SOAR FAQ. It therefore happens on
  **every** build by design — which is why three sessions of hand-re-adding the
  wheels each silently reverted on the next rebuild. Corrected in dev-rules
  NFR-09, and automated: new `soar-connectors/tools/build_sdk_app.py` runs the
  SDK's own build with the skip-list emptied and then verifies the result,
  failing non-zero if any platform-provided wheel is missing. The v1.0.7
  package it produces has a wheel set identical to the last known-good build
  (65 packages).
- [ ] **Still unresolved:** the real appliance threw `ModuleNotFoundError:
  requests` on a build that lacked those wheels, which contradicts the SDK's
  skip-list premise. We keep bundling them until that is settled **against the
  real appliance** — `build_sdk_app.py --stock` builds the SDK-stock variant for
  exactly that A/B test.

### Shipped 2026-08-27 (later still)

The user uninstalled all three EfficientIP apps in the GUI — the stale 204 **and**
both live ones — then approved a clean-slate reinstall.

- [x] **App 204 uninstalled by the user**, closing the item REST could never do.
  Left disabled; the reinstall did not touch it.
- [x] **Connectors installed in place** via `tools/install_app.sh`:
  `efficientip_ddi` v1.0.7 → app id 205, `efficientip_ddi_classic` v1.0.5 → app
  id 206. Both `disabled: false`, 5 registered actions each (checked on
  `/rest/app_action?_filter_app=`, the endpoint that actually reports them).
- [x] **Assets re-bound.** Uninstalling orphaned assets 19 and 22 (`app: None`
  on the detail endpoint, not just the list view) and **reinstalling did not
  re-bind them** — worth knowing, since that was the obvious assumption. Their
  `configuration` survived fully intact, so no credentials had to be re-entered.
  Fixed with `POST /rest/asset/<id> {"app_id": <app>}`, a shape first tested on
  a throwaway asset because the REST-quirks memory warns that a `POST` without
  `configuration` resets every field. It does not, for this shape: all 9 keys
  and their byte-lengths were unchanged, on the scratch asset and then on both
  real ones. Scratch asset deleted afterwards.
- [x] **Playbook deployed.** `efficientip_ddi_enrich` id=**678** v6,
  `passed_validation: true`, `active: false` (correct for a data playbook).
  Verified the *live* copy carries this session's changes rather than trusting
  the deploy: grepped the post-deploy assembled snapshot for `alias_names`,
  `alias_count`, the multi-alias `collect2` loop, the two-condition
  `check_ip_found` and the "Aliases" label, and read `output_spec` back over
  REST (12 fields, both new ones present). **This closes the GUI-save
  `on_finish` hazard on the live copy**, which was the "do this first" item.

### Still open

- [x] **Live functional test of the multi-record fix — DONE.** Was blocked on a
  mock restart: `mock-efficientip-ddi.service` was active on the ansible
  controller and reachable from soar8 (asset 19 → `https://<lab-address-redacted>:8447`),
  but the running process predated the seed change and still returned **1**
  alias for `ip_id` 1001. The unit was restarted (approved) and the chain
  re-run: `list aliases` at `limit` > 1 returns **2 rows** through SOAR and
  `efficientip_ddi_enrich` reports `alias_count: 2` with both names. See the
  "GUI-test readiness" section below.
### GUI-test readiness (2026-08-27, prepared)

Everything needed for a GUI pass is deployed and pre-verified over REST, so a
GUI run should be a confirmation rather than a debugging session.

- Live ids *at the time of this section* (2026-08-27): `efficientip_ddi_enrich`
  684 v8, `efficientip_ddi_action_test` 685 v5,
  `efficientip_ddi_classic_action_test` 686 v4 — all `passed_validation: true`.
  **Superseded by later deploys; verified 2026-08-28 as 711 v18 / 712 v11 /
  713 v10.** Resolve by name rather than trusting either set. Apps: 205 v1.0.8
  (SDK), 206 v1.0.6 (classic), 5 actions each, assets 19/22 bound with
  `verify_ssl: false` — those have held.
- **Verified end to end after the mock restart:** `list aliases` returns 2 rows
  through SOAR, the enrich playbook reports `alias_count: 2` with both names,
  8/8 actions PASS on both connectors. `./tools/uc17_verify.sh` runs the lot.
- **Both action-test playbooks updated for the new connector contract.** Their
  `list aliases` node still declared `ip_id` as `data_type: "numeric"`, which is
  exactly what stops the VPE binding `get ip address`'s now-string `ip_id`
  output to it — fixed to `string` in both. They also never passed `limit`, so
  at the default of 1 they could not tell a working multi-record result from
  the old truncation bug; both now pass `limit: "10"` and their note reports the
  alias **count** and every name, with a line saying what a count of 1 would
  mean.
- Pre-run over REST: all 8 actions across both connectors PASS, and
  `efficientip_ddi_enrich` completes emitting `alias_names`/`alias_count`.
- [x] **The wildcard-datapath GUI-save hazard — resolved by conversion, not by
  policing saves.** All three playbooks have an action node whose `ip_id` binds
  to a wildcard datapath (`...:action_result.data.*.ip_id`), which is the shape
  `[[project-soar-gui-regen-action-param-corruption]]` warns a VPE save can
  comma-join into one malformed parameter. This section originally carried that
  as "a GUI save here is a **mandatory redeploy**". **Superseded:** all three
  were converted to VPE-canonical form and now pass `check_vpe_shape.py`, and
  the user confirmed live that a save on a fully canonical playbook produces
  **no new version at all** — SOAR computes an identical payload and stores
  nothing. The detector is still worth running (`tools/uc17_verify.sh hazards`
  lists the bindings) but the blanket redeploy rule no longer applies to these
  three. Redeploy if a save *does* produce a new version:
  `./tools/deploy.sh --use-case efficientip_ddi_enrich`.
- [x] **VPE GUI open-and-look pass DONE 2026-08-28 — zero warnings.** Performed
  by the user on the live copy (711 v18); everything rendered clean. This was
  the last gate owed under `[[feedback-playbook-build-process-gate]]`, and it
  also confirms the VPE-canonical conversion held end to end.
- [x] Mock service restarted; live seed confirmed at 2 aliases, and
  `list subnets` now passes *genuinely* rather than by fallthrough.
- [x] **The enrich playbook itself was stale too — caught only by running it.**
  After the restart the raw action returned 2 rows while the playbook still
  reported `alias_count: 1`: its `list aliases` node passed no `limit` (so the
  connector default of 1 truncated) and still declared `ip_id` as `numeric`.
  The same two defects were in all three playbooks; the enrich one was missed
  on the first pass because only the two test playbooks were being reviewed.
  Now sends `limit: "50"` — bounded but generous, since its own
  `alias_names`/`alias_count` outputs are meaningless at 1 and an unbounded call
  times out on the real APIM.
- [x] **Mock hardened so this class of bug fails loudly.** An unrecognised
  `WHERE` column used to return every record — which is why `WHERE=name=` passed
  locally for two versions — and is now a 400 naming the valid columns. The mock
  also encodes the vendor-confirmed filter-to-record-key mapping including the
  two WHERE≠SELECT cases (`subnet_name`→`name`, `parent_site_name`→`site_name`).
  Deliberately stricter than the real API, whose behavior for an unknown column
  is unknown: the permissive option demonstrably hides real bugs.
- [x] ~~`WHERE`-filter-key hypothesis for `ip_block_subnet_list`~~ —
  **RESOLVED 2026-08-27 by asking the user, and it was a real bug.** `name` is
  not a filterable column at all, only the SELECT column the record returns
  under; the filterable column is `subnet_name`. Fixed in both connectors
  (1.0.8 / 1.0.6) and both mocks, with regression tests from both sides. The
  mock could never have caught it: it matched on `name`, *and* it falls through
  to returning every record on an unmatched `WHERE`, so even a probe asking
  "did it return a row?" would have answered yes for either key.
- [ ] Real airgapped retest of everything else — neither connector has been run
  against the real SOLIDserver/APIM since the field-name fixes. Confirmed from
  the user meanwhile: the response is a bare JSON array (what `_ensure_list()`
  assumes), and `limit=1` returns exactly one record. Still unconfirmed:
  `ip_alias_list`'s own field names — `alias_name` remains analogy-based, and
  the user had no `ip_id` with aliases to check against, so this cannot be
  settled from their side yet. `raw_json` covers it meanwhile.
- [ ] The two action-test playbooks are 271 lines differing by ~5 (the `ASSET`
  constant and 4 note titles); `ASSET` as a `playbook_input` would collapse
  them. **Deliberately not done** — it trades a diagnostic playbook's
  zero-argument launch for a typed input on every manual run, and touching
  their block structure risks a GUI regression on playbooks whose only job is
  diagnosing one. Worth revisiting only if a third connector variant appears.
- [x] ~~Open design item: purpose-built `WHERE` filter parameters~~ —
  **DESIGNED AND BUILT 2026-08-29 for the equality columns; ranges deferred
  behind three appliance probes.** See the section below.

## Purpose-built `WHERE` filters on `list subnets` (2026-08-29)

Closes the item deferred at connector 1.0.8. `list subnets` took a single
required `name` param, so the only question it could answer was "tell me about
this exact subnet" — the 2026-08-27 filter needs (by parent, by site, by range)
had nowhere to go.

### Shape (agreed with the user before building)

Four optional named parameters, **exactly one required at runtime**:

| Parameter | WHERE column | Answers |
|---|---|---|
| `subnet_name` | `subnet_name` | this exact subnet (replaces `name`) |
| `subnet_id` | `subnet_id` | this subnet by id |
| `parent_subnet_name` | `parent_subnet_name` | the subnets under a parent |
| `site_name` | `parent_site_name` | the subnets in a space/site |

Two mappings are deliberately **not** identities, so they live in a
`LIST_SUBNETS_FILTERS` table rather than an f-string: `subnet_name` filters but
the record returns its name under `name`, and the caller-facing `site_name`
filters as `parent_site_name`. This is precisely the mismatch that shipped as
`WHERE=name='...'` and passed locally for two versions.

**Why exactly one, not any combination.** Whether this service's `WHERE`
accepts `AND` at all has never been confirmed on the real APIM, and the mock
cannot settle it — `_WHERE_RE` parses a single `col='val'` and nothing more.
Composing two filters would be another coded guess of exactly the kind that has
been wrong every previous time. Two filters is therefore a clean refusal, not a
silently-dropped condition.

**Why not zero either** (user decision, against allowing a bare browse): a bare
bounded call is legal on the APIM — `test_connectivity` makes one — but as a
*lookup* it returns arbitrary rows, so a playbook that lost its filter binding
would enrich against a random subnet and look like it had worked. Both the
zero- and two-filter refusals happen **before** any HTTP call.

### Ranges: designed, deliberately not built

`start_ip_addr`/`end_ip_addr` (hex) and `start_hostaddr`/`end_hostaddr` (dotted
IP) are vendor-confirmed filterable, and a range lookup is the case that
motivated making `limit` caller-controlled in the first place. It is still not
buildable without two facts nobody has, both marked `None` ("real but not
implemented") in the mock's own `_FILTER_COLUMNS`.

**Three curl probes on the real appliance would settle it** (all read-only,
all bounded):

1. **Does `WHERE` accept `AND`?**
   `GET /rest/ip_block_subnet_list?WHERE=parent_site_name='<site>' AND parent_subnet_name='<parent>'&limit=5`
   — a 200 with correctly-narrowed rows means composition works; a **403**
   (this API's code for a bad request, *not* 400) or an ignored second
   condition means the one-filter rule stays permanent.
2. **Does it accept comparison operators?**
   `GET /rest/ip_block_subnet_list?WHERE=start_hostaddr>='10.20.0.0'&limit=5`
   — anything other than a 200 with narrowed rows means ranges are impossible
   through this column regardless of what 1 says.
3. **Which representation do the range columns want?** Run 2 again against
   `start_ip_addr` with the hex form (`0a140000`). The connector already has
   `_ip_to_hex()`, so whichever answers correctly is cheap to adopt — but
   guessing between them is not.

Until all three are answered, the range columns stay unexposed. Answer them and
the work is small: extend `LIST_SUBNETS_FILTERS`, relax `_select_single_filter`
to the confirmed composition rule, and teach the mock's `_WHERE_RE` the
operator/AND grammar so it can still fail loudly.

### Breaking change and blast radius

`name` → `subnet_name` on `list subnets` only. `get ip pool` keeps its own
`name` param, untouched. Both diagnostic playbooks updated on both sides (`.py`
and `.json`, with `requiredParameters` now `[]` to match the manifest);
`check_usercode_sync.py` clean across all 21 playbooks. **Nothing else binds
this action** — `efficientip_ddi_enrich`, the actual UC deliverable, never
called it, so the enrich flow is untouched.

The mock gained a **second subnet under the same parent and site**. Without it a
parent/site filter returns one row and proves nothing — the same trap the
single-alias seed set for two versions. Applied to both mock copies (they are an
unsynced mirror by design).

### Verification

- Classic connector suite **32 passing** (was 24): parent filter, the
  `site_name`→`parent_site_name` non-identity mapping, subnet_name still works,
  apostrophe escaping through a non-default filter, and both refusals asserting
  `requests.request` was never called.
- Mock suite **26 passing** (was 22): parent filter returns both children, site
  filter returns both, raw `site_name` as a WHERE column is still a loud 400,
  plus a guard on the seed itself so collapsing it back to one record fails.
- `check_usercode_sync.py` clean; both connectors and both mocks parse.
- **Both packages built** (2026-08-29): `efficientip_ddi.tgz` at **1.0.10**,
  py 3.13, 70 wheels with **7/7 platform-provided bundled**;
  `dist/efficientip_ddi_classic-v1.0.7.tgz`. The SDK manifest was regenerated
  from the decorators and inspected — all four filters present, optional, in
  order, with `limit` numeric/default 1, matching the classic manifest exactly.
- **Deployed and live-verified 2026-08-29.** Apps **205 @ 1.0.10** and
  **206 @ 1.0.7** installed in place (5 actions registered each, confirmed via
  `/rest/app_action` — `/rest/app/<id>` reports `actions: 0` for every app and
  is not a registration check). Playbooks redeployed: **722** (enrich, v19),
  **723** (SDK action test, v12), **724** (classic action test, v11), all
  `validation=True`. `mock-efficientip-ddi.service` restarted (approved) and now
  serves both subnets.
- **`uc17_verify.sh` green against the new code** — enrich 722 reports
  `alias_count: 2`, both action-test playbooks PASS on all four actions.

### Every new filter exercised through SOAR's real action dispatch

`uc17_verify.sh` only covers `subnet_name`, so the rest were driven directly via
`POST /rest/action_run` against **both** apps. All ten results correct:

| Filter | SDK (205) | Classic (206) |
|---|---|---|
| `parent_subnet_name='10.20.0.0/16'` | 2 rows | 2 rows |
| `site_name='Corporate'` → `parent_site_name` | 2 rows | 2 rows |
| `subnet_name='10.20.30.0/24'` | 1 row | 1 row |
| no filter | failed, correct message | failed, correct message |
| two filters | failed, names both | failed, names both |

The two 2-row results are the ones that matter: they prove the parent filter
genuinely narrows *and* returns every child rather than truncating, and that the
non-identity `site_name`→`parent_site_name` mapping resolves correctly against a
real backend response — neither of which the single-subnet seed could show.

## [!] The `WHERE` + `limit` rule was WRONG — reverted 2026-08-31

**Read this before any section below that discusses the `list subnets` 401.**

The rule "never send `WHERE` and `limit` together" (SDK 1.0.14 / classic 1.0.11)
is **disproven and reverted** in SDK 1.0.3 / classic 1.0.2. The real appliance
returns **HTTP 200** for a filtered call carrying `limit=1`, and bounds it to
exactly one row — confirmed on `ip_block_subnet_list` *and* `ip_address_list`.

**It was a shell artefact, not backend behaviour.** The rule rested on one
observation: a filtered call "with `limit=1`" terminated early and returned,
while the same call without it waited. An unquoted URL splits at `&`:

```bash
curl https://host/rest/ip_block_subnet_list?WHERE=subnet_name='X'&limit=1
#  -> curl runs IN THE BACKGROUND with WHERE only; `limit=1` is a separate
#     shell statement and never reaches curl. The prompt returns instantly --
#     that is the "it terminates the process" symptom.

curl 'https://host/rest/ip_block_subnet_list?WHERE=subnet_name=X&limit=1'
#  -> whole URL reaches curl, foreground, HTTP 200, limit=1 returns 1 row.
```

Both arms sent **identical `WHERE`-only requests**. The observation carried no
information about `limit`.

**What stands:** a list call must always carry a bound. With neither `WHERE`
nor `limit` the backend scans unbounded and times out. `limit` now always goes
on the wire, and the client-side truncation helper is gone — with it the
"accepted limitation" that multi-match filters transferred every row.

**What is now unexplained:** the original 401 on `list subnets` at classic
1.0.6 was real and came through `requests` with no shell involved. `limit` is
exonerated and **no replacement cause is established**. Candidates that changed
since, none proven: `name` → `subnet_name` (1.0.8), `Content-Type` → `Accept`
(1.0.12), the credential `.strip()` (1.0.10), and a target-side asset-config
fix. Three causes have now been asserted for this 401 and none survived — the
next one needs evidence first.

## Second real-appliance 401 — on `list subnets` only (SUPERSEDED — see above)

> **Its stated resolution — `WHERE` + `limit` together — is now DISPROVEN.** — see the
> WHERE/limit section. The theorising below is kept because the sequence of
> wrong turns is the useful part, but read it as a record of the investigation,
> not as a description of the fault.

User testing **classic v1.0.6** against the real appliance: `test connectivity`
passes, `list subnets` returns **HTTP 401**.

### This cannot be a credential problem, and the code proves it

Both actions go through the same `_make_rest_call()`, to the **same URL**
(`/rest/ip_block_subnet_list`), with **byte-identical** auth material — same
`_auth_headers(config)`, same mTLS cert/key/CA, same `verify`. Diff the two
calls and only the query string differs:

| Action | Query |
|---|---|
| `test connectivity` | `?limit=1` |
| `list subnets` | `?WHERE=subnet_name='10.20.30.0/24'&limit=N` |

So whatever returns 401 is reacting to **the `WHERE` parameter**, not to any
credential. Same reasoning that made the first 401 informative: ask which code
path did *not* differ.

### Leading theory: the gateway, not SOLIDserver

`WHERE=subnet_name='...'` is a single-quoted SQL-ish clause — a textbook
injection signature for an API gateway WAF. The value also contains `/`, which
`requests` percent-encodes to `%2F`, and rejecting encoded slashes in a query
string is common default gateway behaviour. Gateways commonly answer both cases
with 401 rather than 400/403, which is exactly what makes this read like an auth
failure when it is not.

If this holds, it is a **gateway policy** issue, not a connector bug and not a
SOLIDserver one — and no connector change fixes it. It would also cast doubt on
the whole `WHERE` filtering approach against this APIM.

### Appliance datapoint: unfiltered `list subnets` works (2026-08-29, later)

User edited classic **v1.0.6** in place on the appliance, removed the `WHERE`
clause from `_handle_list_subnets` so the call carries only `limit` — **returns
results.**

**What it confirms:** the unfiltered mode added in 1.0.11 (filters optional,
`limit` alone is a legal call) is correct against the real appliance. Good, but
this was already implied by `test_connectivity`, which has always made exactly
that call.

**Hypothesis (a) is CONFIRMED — `WHERE` alone works.** The user had already
reported it, in the same message that described the timing: *"if I ask for
target subnet_name and specify limit=1 it will terminate process and then send
back response, but if I don't use limit=1 it holds off until I get back the
response."* That second clause is the result — a filtered `subnet_name` lookup
with no `limit` returns the response.

So the rule is settled and **1.0.14 is correct**: on a filtered call, send
`WHERE` and drop `limit`; on an unfiltered call, send `limit`. Filtering is
preserved, and the client-side-filtering fallback is not needed.

> **Process failure, recorded because it repeated.** That confirmation was
> requested from the user a second time after it had already been supplied — the
> same thing that happened with the `Content-Type` probe, where both arms of the
> experiment already existed. Twice in one session, evidence already in hand was
> written up as an open question with a test attached. **Before proposing any
> probe, re-read what the user has already reported.** The cost is not just
> wasted effort; being asked to re-prove something you already said reads as not
> being believed.


## Ruling out the encoding (2026-08-29) — and a "decisive" conclusion that was wrong

> **This section's original conclusion — "it is the service" — was DISPROVEN.**
> `ip_block_subnet_list` accepts `WHERE` perfectly well; what it will not accept
> is `WHERE` alongside `limit`. The evidence below is sound and the encoding
> theory really was killed here; the *inference* drawn from it (per-service
> gateway policy) was not. Left in place deliberately: a confidently-titled
> wrong conclusion is exactly the thing worth being able to re-read later.

User, from the real appliance:

```
GET /rest/ip_address_list?WHERE=ip_addr%3D%27<hex>%27      -> 200, returns data
```

**That single result kills the encoding theory.** `%3D` — the percent-encoded
`=` operator that `requests` produces — is accepted on `ip_address_list`. A fix
to send the operator literally was written and **reverted before shipping**: it
would have changed a wire format that demonstrably works, risking a regression
in `get ip address`, the one WHERE-using action known to be fine.

### The evidence table, which now points somewhere narrow

| Service | `WHERE` | Result |
|---|---|---|
| `ip_block_subnet_list` | none (`limit` only) | **200** |
| `ip_block_subnet_list` | `subnet_name='...'` | **401** |
| `ip_address_list` | `ip_addr='<hex>'` (same encoding) | **200** |

Ruled out, each by evidence rather than argument: **credentials** (both services
reachable), **percent-encoding** (`%3D` works on one service), **Content-Type**
(set on every call including the passing ones), **base64 of the DDI headers**
(present in source since 1.0.3).

What is left is specific to **`ip_block_subnet_list` + a `WHERE` clause**.

**Leading theory: per-operation parameter policy at the APIM.** Gateways
commonly validate requests against a published spec and reject undeclared query
parameters — and commonly answer a policy denial with 401 rather than 400/403.
If this org's APIM publishes `ip_block_subnet_list` without a `WHERE` parameter
while publishing `ip_address_list` with one, this is exactly what you would see.

### The one probe that settles it

A third service breaks the tie:

```
GET /rest/ip_pool_list?WHERE=pool_name%3D%27<a real pool>%27&limit=1
```

- **200** → only `ip_block_subnet_list` rejects `WHERE`. Per-service gateway
  policy, near-certain. Nothing in the connector can fix it; it is an APIM
  configuration question.
- **401** → `ip_address_list` is the *exception*, not subnet the outlier, and
  the question becomes which services the gateway publishes `WHERE` for at all.

Also worth one attempt: `ip_block_subnet_list` with a *different* column
(`WHERE=subnet_id%3D%271%27`). If every column 401s, the parameter itself is
what is refused, not its content.

### If `WHERE` is genuinely unavailable on this service

Then `list subnets` cannot filter server-side on this appliance at all, and the
options are: fetch bare with a generous `limit` and **filter client-side in the
connector**, or drop subnet filtering as a capability here. The user's request
earlier the same day — *"only `limit` is required to be set"* — already shipped
in 1.0.11 and turns out to be the only mode that works against this gateway.

### New evidence: the appliance's own error text (2026-08-29, later)

The appliance's 401 body carries
`"message": "The specified document is not valid JSON data"`.

**Two things this settles** (and see the exoneration note below — the
Content-Type theory this evidence raised was closed without a probe).

1. **`X-DDI-Username`/`X-DDI-Password` ARE base64-encoded in 1.0.6.** That was
   the first hypothesis and it is wrong — the 1.0.3 fix is present in the
   source. Now pinned permanently by `test_ddi_headers_are_base64_encoded`,
   which decodes the header back rather than just asserting it is non-empty.
2. **The message is not ours.** It appears nowhere in this repo. Traced through
   `_process_response()`: on a non-OK response with a JSON content-type it
   parses the body and surfaces `data.get("message")` — so this is the
   appliance's own JSON error body, and the appliance is saying it tried to
   parse a *document* and failed.

**The only JSON document this connector ever claimed to send** was the one
announced by `headers["Content-Type"] = "application/json"`, set
unconditionally in `_make_rest_call()` on every action — all of which are
**bodiless GETs**. A strict server honouring that header reads an empty body as
a JSON document and rejects it, which is exactly this error.

Fixed in **1.0.12 / classic 1.0.9**: `Content-Type` replaced with `Accept:
application/json`, which is what was meant. `Content-Type` describes a body;
there is none.

> **CONTENT-TYPE EXONERATED — no probe needed, the experiment was already run.**
> `_make_rest_call()` sets this header on *every* request, `test connectivity`
> included. So the two calls that settle it already exist: the user's bare
> `?limit=1` curl **without** the header returns 200, and `test connectivity` —
> the identical call **with** it — passes. Same request, header the only
> difference, both succeed. The header is not the cause of anything.
>
> The 1.0.12 fix stands on its own merits (a `Content-Type` describing a body
> that does not exist is simply wrong), but it is **not** a 401 fix and must not
> be recorded as one.
>
> Process note worth keeping: this was deducible from evidence already in hand,
> and was instead written up as an open suspect with a probe attached. The hole
> in the theory ("test connectivity sends the same header and passes") was even
> stated explicitly — and then not followed to its conclusion. **A stated
> anomaly is a lead, not a caveat to park.**

### What actually goes on the wire (confirmed, not assumed)

Everything after `WHERE=` is **one opaque parameter value**, so `requests`
percent-encodes all of it — including the inner `=`. Verified two ways: by
preparing the request through `requests` directly, and against the mock's own
access log, which recorded exactly this URL.

```
python  : WHERE = subnet_name='10.20.30.0/24'
wire    : WHERE=subnet_name%3D%2710.20.30.0%2F24%27&limit=1
```

| Char | Encoded | Where it appears |
|---|---|---|
| `=` | `%3D` | the operator between field and value |
| `'` | `%27` | both quotes |
| `/` | `%2F` | inside any CIDR-style subnet name |

`subnet_name` itself stays literal. **Three** characters get encoded, not just
the slash — so `%3D` is as much a suspect as `%2F`.

### Discriminating probes (read-only, same certs as the working call)

**Each probe must be run BOTH ways.** A raw curl URL is sent unencoded and is a
genuinely different HTTP request from what the connector sends, so a raw curl
that passes proves nothing on its own. This is the primary discriminator:

- **Form A (encoded, byte-identical to the connector):**
  `curl -G ... --data-urlencode "WHERE=subnet_name='10.20.30.0/24'" --data-urlencode "limit=1"`
  — `--data-urlencode "name=content"` encodes only the part after the first
  `=`, exactly as `requests` does.
- **Form B (raw):** the same clause literal in the URL.

| # | `WHERE` value | Isolates |
|---|---|---|
| 1 | *(none, just `limit=1`)* | baseline — known to pass |
| 2 | `subnet_id=2001` | a `WHERE` at all — no quotes, no slash |
| 3 | `subnet_id='2001'` | adds the **quote** (`%27`) |
| 4 | `parent_site_name='Corporate'` | quotes + letters, still no slash |
| 5 | `subnet_name='10.20.30.0/24'` | the failing case — adds **`/` → `%2F`** |

Reading the result:

- **A fails, B passes** → the **encoding** is the trigger (`%2F`, possibly
  `%3D`). Gateway rule; no connector change fixes it.
- **Both fail** → the clause itself is rejected regardless of form; walk 2→5 to
  find which character.
- **Both pass** → it is not the `WHERE` clause, and the appliance's exact
  failing request is needed.

### Mitigation already shipped

Connector **1.0.11 / classic 1.0.8** makes every `list subnets` filter optional
(user decision, see release notes), so an unfiltered `?limit=N` call — the shape
already proven to work on this appliance — is now a first-class way to use the
action. That is a genuine workaround if the `WHERE` path stays blocked, though
it does not restore filtering.

> **The appliance is running classic 1.0.6**, which predates all of today's
> work. Whatever the probes show, the version under test is three releases
> behind on this action.

## 401 RESOLVED (2026-08-29) — it was the asset config

User updated the asset configuration on the real appliance and **Test
Connectivity now passes**. Reported cause: previously-hidden (password-type)
fields did not carry across as usable values — what arrived was not a real
value, and the asset had to be filled in properly on the target side.

**This lands squarely on candidate 1's axis: the asset config that crossed the
air gap, not the code.** It does not finger the exact mechanism between "lab
identity leaked into `client_id`/`ddi_username`" and "placeholdered secret never
correctly re-entered" — both are the same failure surface, and the export fix
addresses both by forcing every non-portable field to be re-entered
deliberately. Candidate 2 (`_auth_headers()` not stripping) is **not
implicated** and remains a fixed latent risk rather than a proven cause.

**What this now confirms, outside the mock, for the first time:** the full auth
stack works end to end on the real appliance — mTLS handshake, the Basic APIM
app credential, and the forwarded `X-DDI-*` backend auth all accepted, on top of
the packaging/network/bounded-call layers the 401 had already proven. Every
layer of the connector's request path is now exercised against real hardware.

> **The appliance still runs 1.0.8.** It has neither the `.strip()` fix nor the
> new `list subnets` filter surface — both landed in 1.0.10, which has never
> been carried across. A re-export is what delivers them.

## First real airgapped-appliance run (2026-08-28) — HTTP 401

The handover package (bundled connector v1.0.8) was exported, carried across
the air gap and installed by the user. `Test Connectivity` on the asset
returned **HTTP 401**.

**A 401 is the good failure.** Read against `_request()`'s exception ladder,
everything beneath the auth layer passed — and all of it is confirmed outside
the mock for the first time:

| Layer | Evidence |
|---|---|
| Packaging | No `ModuleNotFoundError`. `requests` is imported at module level, so reaching an HTTP status proves the import resolved. |
| mTLS | No `SSLError` → *"TLS/mTLS error connecting to APIM"*. `_normalize_pem()` handled hand-typed PEMs; the appliance trusted the client cert. |
| Network | No `ConnectionError` → *"Could not reach APIM"*. |
| Bounded call | `test_connectivity`'s bare `ip_block_subnet_list` at `limit=1` reached the APIM rather than hanging. |

**On the wheels question:** bundling is now confirmed *sufficient* on the
appliance. It does **not** show the appliance provides the 7 platform packages
— we shipped them. Stock stays untested there; always bundle.

**The 401 — two candidates, neither confirmed.** Needs the full error body,
which the connector appends (`EfficientIP/APIM returned HTTP 401: <detail>`)
and which may name the rejected layer.

1. **The export ships lab-specific identities.** `export_template_assets()`
   redacts what is *secret*, never what is *ours* — so `client_secret`,
   `ddi_password` and all three PEMs arrived as `<<SET ME>>` while `client_id`
   and `ddi_username` arrived carrying the lab mock's values. Real secrets +
   lab usernames = this exact 401.
2. **`_auth_headers()` does not strip its inputs** — the four credential fields
   are base64-encoded raw, so one pasted trailing newline silently produces a
   wrong credential.

Full analysis in memory `[[project-soar-efficientip-airgapped-first-run]]`.

### Both fixes implemented (2026-08-29)

Neither confirms the 401 — that still needs the full APIM error body — but both
were real defects on their own terms, and both are now closed.

**Fix 1 — the export redacts on one axis, now on two.**
`export_handover.py`'s `export_template_assets()` asked only *"is this
secret?"* (password-typed field, `-----BEGIN` blob, lab address, mock
`base_url`). It now also asks *"is this ours?"*: a new `IDENTITY_FIELD_RE`
placeholders identity-shaped field **names** — `username`, `user`, `login`,
`client_id`, `app_id`, `account`, `principal`, `sender`, `email` and their
prefixed forms — with a message that says it was the lab's identity rather than
a secret. Matching is on the name, not the value, because an identity value
looks like nothing in particular. `IDENTITY_FIELD_EXCEPTIONS` keeps
non-identities the pattern would otherwise catch (`user_agent`,
`email_subject`) out of it, so no operator goes hunting for a value unrelated to
their credentials. Checked against UC17's real asset field set: `client_id` and
`ddi_username` are now placeheld; `base_url`, `verify_ssl` and the PEM/password
fields are unaffected (the latter were already caught upstream).

The generated `HANDOVER.md` install step (**both** the EN and FR texts) now
splits its redaction explanation into the two axes and states the failure mode
explicitly — a real password beside a leftover source-environment username
authenticates as nothing and returns HTTP 401 — since the previous wording sent
the operator to a vault/CMDB for values no vault holds.

**Fix 2 — credentials are stripped at the point of use.** `_auth_headers()`
base64-encoded all four credential fields exactly as stored, while the three PEM
fields were whitespace-normalised by `_normalize_pem()`. On an airgapped box
every one of these is hand-entered, and base64 preserves whatever surrounds the
value, so one trailing newline produced a wrong-by-one-byte credential and an
indistinguishable 401. Both connectors now `.strip()` all four. **SDK 1.0.9 →
1.0.10, classic 1.0.6 → 1.0.7** (live is 205 @ 1.0.8 and 206 @ 1.0.6, so both
numbers clear the install gate).

Two regression tests added to `efficientip_ddi_classic/tests/`: whitespace
around any of the four must not change the encoded headers, and stripping must
not flatten a genuinely different value into a matching one. The first was
confirmed to fail against the pre-fix connector. Suite is 26 passing (was 24);
the 22 mock-server tests still pass.

**Not built, not installed, not re-exported.** The version bumps are source-only
so far — soar8 still runs 1.0.8/1.0.6, and the handover package the user holds
still carries the lab identities. A fresh export is what actually delivers Fix 1
to the appliance.

> **Connector v1.0.9 is built but NOT installed on soar8.** It is a version bump
> only (no code change), made to clear the install gate so the bundled build
> could replace the stock one on app 205. `install_app.sh` was denied by a
> permission classifier and not worked around, so soar8 still runs stock 1.0.8.

### Verification performed this session (soar8 + mock only)

- 23 classic-connector unit tests, 16 mock-server tests — all passing.
- 13 live end-to-end checks driving **both** connectors' real request path
  against a running mock over real mTLS: multi-alias retrieval at `limit=10`,
  bounding at `limit=1`, the apostrophe-name escaping round trip, `204 No
  Content` → empty list, float-`ip_id` absorption, hostname rejection, and the
  classic twin's raw pass-through keeping real SOLIDserver key names.
- `check_usercode_sync.py` clean across all 3 UC17 playbooks.
- SDK manifest regenerated and inspected: `ip_id` string, `limit` numeric
  default 1 on all four data actions, `data.*` output shape unchanged.
