#!/usr/bin/env bash
#
# uc17_airgapped_probe.sh — answer the EfficientIP questions that ONLY the real
# airgapped SOLIDserver/APIM can answer. Read-only: every call is a GET against
# a *_list service. Nothing is created, modified or deleted.
#
# Carry this across with the connector .tgz and run it on the airgapped side.
#
#   export DDI_BASE=https://apim.internal.example
#   export DDI_CLIENT_ID=... DDI_CLIENT_SECRET=...
#   export DDI_USER=...      DDI_PASS=...
#   export DDI_CERT=client.pem DDI_KEY=client-key.pem   # optional DDI_CA=ca.pem
#   # a real subnet name, a real IPv4, and a real ip_id from your IPAM:
#   export PROBE_SUBNET="10.20.30.0/24" PROBE_IP="10.20.30.40" PROBE_IP_ID=1001
#   ./uc17_airgapped_probe.sh
#
# What it settles:
#   1. Does ip_block_subnet_list filter on name= or subnet_name=?   (a coded guess)
#   2. Do list services return >1 row when limit allows it?         (multi-record fix)
#   3. Does `limit` actually bound the result?
#   4. What are the REAL field names on ip_alias_list / ip_block_subnet_list?
#   5. Is "not found" really 204 No Content?
#   6. WHY does `list subnets` 401 while `test connectivity` passes? (2026-08-29)
#      Two independent suspects, both tested in section 8:
#        a. the phantom `Content-Type: application/json` on a bodiless GET
#        b. the WHERE clause itself, encoded (%3D %27 %2F) vs raw
set -uo pipefail

: "${DDI_BASE:?set DDI_BASE}"; : "${DDI_CLIENT_ID:?}"; : "${DDI_CLIENT_SECRET:?}"
: "${DDI_USER:?}"; : "${DDI_PASS:?}"; : "${DDI_CERT:?}"; : "${DDI_KEY:?}"
PROBE_SUBNET="${PROBE_SUBNET:-}"; PROBE_IP="${PROBE_IP:-}"; PROBE_IP_ID="${PROBE_IP_ID:-}"

B=$(printf '%s:%s' "$DDI_CLIENT_ID" "$DDI_CLIENT_SECRET" | base64 -w0)
U=$(printf '%s' "$DDI_USER" | base64 -w0)
P=$(printf '%s' "$DDI_PASS" | base64 -w0)
CA_ARG=(); [ -n "${DDI_CA:-}" ] && CA_ARG=(--cacert "$DDI_CA") || CA_ARG=(-k)

# $1 = label, $2 = path+query
probe() {
  local label="$1" path="$2" body code
  body=$(curl -s --max-time 30 -w '\n%{http_code}' "${CA_ARG[@]}" \
          --cert "$DDI_CERT" --key "$DDI_KEY" \
          -H "Authorization: Basic $B" -H "X-IPM-Username: $U" -H "X-IPM-Password: $P" \
          "${DDI_BASE}${path}" 2>&1)
  code=$(printf '%s' "$body" | tail -n1)
  body=$(printf '%s' "$body" | sed '$d')
  printf '\n--- %s\n    GET %s\n    HTTP %s\n' "$label" "$path" "$code"
  printf '%s' "$body" | python3 -c "
import json,sys
raw=sys.stdin.read().strip()
if not raw:
    print('    <empty body>  <- this is what a 204 No Content looks like'); raise SystemExit
try:
    d=json.loads(raw)
except Exception:
    print('    non-JSON:',raw[:200]); raise SystemExit
if isinstance(d,list):
    print('    rows:',len(d))
    if d:
        print('    FIELD NAMES:',sorted(d[0].keys()))
        print('    first row  :',json.dumps(d[0])[:400])
else:
    print('    not a list -> type',type(d).__name__,':',json.dumps(d)[:300])
"
}

# Same as probe(), plus one extra header. Used to test whether a header alone
# changes the verdict, holding everything else identical.
# $1 = label, $2 = path+query, $3 = extra header
probe_hdr() {
  local label="$1" path="$2" hdr="$3" body code
  body=$(curl -s --max-time 30 -w '\n%{http_code}' "${CA_ARG[@]}" \
          --cert "$DDI_CERT" --key "$DDI_KEY" \
          -H "Authorization: Basic $B" -H "X-IPM-Username: $U" -H "X-IPM-Password: $P" \
          -H "$hdr" \
          "${DDI_BASE}${path}" 2>&1)
  code=$(printf '%s' "$body" | tail -n1)
  printf '\n--- %s\n    GET %s\n    +header: %s\n    HTTP %s\n' "$label" "$path" "$hdr" "$code"
  printf '%s' "$body" | sed '$d' | head -c 300 | sed 's/^/    /'
  printf '\n'
}

# Sends the WHERE value PERCENT-ENCODED, byte-identical to what python-requests
# puts on the wire (= -> %3D, ' -> %27, / -> %2F). curl's --data-urlencode
# encodes only the part after the first '=', exactly as requests does.
# The plain probe() above sends a RAW url, so the two together isolate encoding.
# $1 = label, $2 = service path, $3 = WHERE value, $4 = limit
probe_encoded() {
  local label="$1" path="$2" where="$3" lim="$4" body code
  body=$(curl -s --max-time 30 -w '\n%{http_code}' -G "${CA_ARG[@]}" \
          --cert "$DDI_CERT" --key "$DDI_KEY" \
          -H "Authorization: Basic $B" -H "X-IPM-Username: $U" -H "X-IPM-Password: $P" \
          --data-urlencode "WHERE=$where" --data-urlencode "limit=$lim" \
          "${DDI_BASE}${path}" 2>&1)
  code=$(printf '%s' "$body" | tail -n1)
  printf '\n--- %s\n    GET %s?WHERE=<encoded>&limit=%s\n    WHERE value: %s\n    HTTP %s\n' \
         "$label" "$path" "$lim" "$where" "$code"
  printf '%s' "$body" | sed '$d' | head -c 300 | sed 's/^/    /'
  printf '\n'
}

echo "=================================================================="
echo " EfficientIP airgapped probe — read-only"
echo " target: $DDI_BASE"
echo "=================================================================="

echo; echo "### 1. reachability / auth (what test connectivity does)"
probe "ip_block_subnet_list, bare limit=1" "/rest/ip_block_subnet_list?limit=1"

echo; echo "### 2. does 'limit' bound the result, and do we get >1 row?"
probe "ip_block_subnet_list limit=1" "/rest/ip_block_subnet_list?limit=1"
probe "ip_block_subnet_list limit=5" "/rest/ip_block_subnet_list?limit=5"
echo "    ^^ if limit=5 returns more rows than limit=1, multi-record + limit both work."

echo; echo "### 3. THE filter-key question: name= vs subnet_name= ?"
echo "    Read this one carefully. 'returns a row' is NOT the answer on its own:"
echo "    a backend that ignores an unknown WHERE column just returns everything,"
echo "    which looks identical to a successful filter. Hence the bogus-value"
echo "    controls below -- a REAL filter column returns 0 rows for a value that"
echo "    does not exist; an IGNORED column still returns rows."
if [ -n "$PROBE_SUBNET" ]; then
  esc=${PROBE_SUBNET//\'/\'\'}
  bogus="zzz-no-such-subnet-zzz"
  probe "[positive] WHERE name='$PROBE_SUBNET'"        "/rest/ip_block_subnet_list?WHERE=name%3D%27${esc// /%20}%27&limit=1"
  probe "[CONTROL ] WHERE name='$bogus'"               "/rest/ip_block_subnet_list?WHERE=name%3D%27${bogus}%27&limit=1"
  probe "[positive] WHERE subnet_name='$PROBE_SUBNET'" "/rest/ip_block_subnet_list?WHERE=subnet_name%3D%27${esc// /%20}%27&limit=1"
  probe "[CONTROL ] WHERE subnet_name='$bogus'"        "/rest/ip_block_subnet_list?WHERE=subnet_name%3D%27${bogus}%27&limit=1"
  cat <<'INTERP'

    HOW TO READ SECTION 3
      positive returns your subnet AND control returns 0 rows / empty  -> that key is the real filter column
      positive returns rows AND control ALSO returns rows              -> that key is being IGNORED, not filtering
      positive returns 0 rows                                          -> that key is wrong (or the subnet name does not match exactly)
      both keys filter correctly                                       -> either works; leave the connector on name=
    The connector currently sends name=. If only subnet_name= filters, that is a
    real bug to fix in list_subnets() in both connectors.
INTERP
else
  echo "    (skipped — set PROBE_SUBNET to a real subnet name)"
fi

echo; echo "### 4. ip_address_list — hex filter + real field names"
if [ -n "$PROBE_IP" ]; then
  hex=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_address(sys.argv[1]).packed.hex())" "$PROBE_IP")
  probe "WHERE ip_addr='$hex' ($PROBE_IP)" "/rest/ip_address_list?WHERE=ip_addr%3D%27${hex}%27&limit=1"
else
  echo "    (skipped — set PROBE_IP)"
fi

echo; echo "### 5. ip_alias_list — multi-record + real field names"
if [ -n "$PROBE_IP_ID" ]; then
  probe "aliases of ip_id=$PROBE_IP_ID, limit=10" "/rest/ip_alias_list/ip_id/${PROBE_IP_ID}?limit=10"
  echo "    ^^ FIELD NAMES here settle whether 'alias_name' is right (it is analogy-based)."
else
  echo "    (skipped — set PROBE_IP_ID, from the ip_id in section 4's output)"
fi

echo; echo "### 6. ip_pool_list — real field names"
probe "ip_pool_list limit=5" "/rest/ip_pool_list?limit=5"

echo; echo "### 7. not-found — is it really 204 No Content?"
probe "aliases of a bogus ip_id" "/rest/ip_alias_list/ip_id/999999999?limit=1"

echo; echo "### 8. THE 401 ON 'list subnets' — two suspects (2026-08-29)"
echo "    Context: test connectivity passes, list subnets returns 401 with"
echo "    the appliance saying 'The specified document is not valid JSON data'."

echo; echo "  8a. Is the phantom Content-Type the trigger?"
echo "      Identical calls; the ONLY difference is one header."
probe     "control: bare call, no Content-Type" "/rest/ip_block_subnet_list?limit=1"
probe_hdr "same call + the connector's header"  "/rest/ip_block_subnet_list?limit=1" \
          "Content-Type: application/json"
echo "      -> control passes + header 401s = the header is the cause (fixed in 1.0.12)."
echo "      -> both pass = header exonerated; the WHERE clause is the suspect (8b)."

echo; echo "  8b. Is the WHERE clause the trigger, and does ENCODING matter?"
echo "      Each pair is the same clause raw, then percent-encoded as the connector sends it."
probe         "no quotes, no slash     (raw)" "/rest/ip_block_subnet_list?WHERE=subnet_id=2001&limit=1"
probe_encoded "no quotes, no slash (encoded)" "/rest/ip_block_subnet_list" "subnet_id=2001" 1
probe         "quoted numeric          (raw)" "/rest/ip_block_subnet_list?WHERE=subnet_id='2001'&limit=1"
probe_encoded "quoted numeric      (encoded)" "/rest/ip_block_subnet_list" "subnet_id='2001'" 1
if [ -n "$PROBE_SUBNET" ]; then
  probe         "quoted subnet w/ slash  (raw)" "/rest/ip_block_subnet_list?WHERE=subnet_name='$PROBE_SUBNET'&limit=1"
  probe_encoded "quoted subnet w/ slash (enc)" "/rest/ip_block_subnet_list" "subnet_name='$PROBE_SUBNET'" 1
else
  echo "    (slash case skipped — set PROBE_SUBNET to a real CIDR-style subnet name)"
fi
echo "      -> first failure names the trigger: any WHERE / the quote / the slash."
echo "      -> raw passes + encoded 401s = it is the percent-encoding (%2F or %3D),"
echo "         which is a gateway rule, not something a connector change can fix."

echo
echo "=================================================================="
echo " Report back: section 3 (which filter key worked), the FIELD NAMES"
echo " lines from 4/5/6, whether 7 came back empty-bodied, and the full"
echo " HTTP-code pattern from section 8 (that is the 401 diagnosis)."
echo "=================================================================="
