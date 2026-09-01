# efficientip_ddi_consts.py
"""Constants for the EfficientIP DDI SOAR Connector."""

# 30s to match the vendor's own reference client (their documented CURLOPT set
# for ip_block_subnet_list uses timeout 30). Was 15, which is under half what
# the vendor budgets for these calls: a list call that is merely slow -- this
# backend does full scans when under-bounded -- would have been cut off client
# side and surfaced as a connection error rather than a slow success.
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_LIMIT = 1  # fallback when the optional "limit" action param is omitted

# ---- Response status semantics ----
#
# Vendor-stated codes: 200 success, 204 no content, 401 unauthorized,
# 403 bad request. Observed on the real appliance 2026-09-01: a malformed
# WHERE also returns **400** with a SOLIDserver SQL-layer body
# ([{"errno": "50028", "sql_error": "7"}]).
#
# So "bad request" arrives as either code, and the likeliest reading is that
# they are two different layers rejecting it -- 403 from the APIM gateway,
# 400 from the SOLIDserver backend behind it, which is why only the 400 body
# carries an errno. Both are treated identically here: named as a bad request,
# never retried.
#
#   200  success
#   204  no content -- a list endpoint with zero matching records. Not an
#        error, and not a 200 with an empty JSON array.
#   400  BAD REQUEST (backend/SQL layer) -- body carries errno/sql_error.
#   401  unauthorized -- the ONLY auth-layer code.
#   403  BAD REQUEST (gateway layer) -- *not* "forbidden".
#
# The 403 mapping is the one that misleads: read as standard HTTP it looks
# like a permissions problem and sends an operator hunting credentials, which
# is the wrong half of the stack. Neither code is in RETRYABLE_STATUS -- a
# malformed request is deterministic and fails identically every time.
#
# Known cause of a 400 here: an unquoted STRING value in the WHERE clause.
# The clause is SQL, and it types values the way SQL does:
#
#   ip_addr='0a0a0a0a'   string  -> quotes REQUIRED (bare 400s at the SQL layer)
#   ip_id=1697182        integer -> quotes not needed (confirmed live 2026-09-01)
#
# _bounded_query() quotes, which is correct for every column currently exposed
# -- all of them are string-typed. An integer column added later does not need
# quoting, though quoting one is generally harmless in SQL (implicit cast) and
# has not been tested here.
HTTP_STATUS_UNAUTHORIZED = 401
# Both mean bad request; see the note above.
BAD_REQUEST_STATUS = frozenset({400, 403})

# Only 401 is retried, and only because the real appliance has been observed
# returning it for a request that succeeds unchanged moments later. The
# connector holds no per-call state (headers are recomputed from config every
# call, no session, no cookie, no token), so identical inputs produce identical
# bytes -- which is what makes a retry meaningful here rather than a way of
# re-asking a question already answered.
RETRYABLE_STATUS = frozenset({HTTP_STATUS_UNAUTHORIZED})

# Total attempts, including the first. Operator-tunable per asset because the
# right value depends on the cause, which is still open: a load-balanced node
# with inconsistent trust wants more attempts, a quota policy wants fewer.
DEFAULT_RETRY_COUNT = 3
MAX_RETRY_COUNT = 10

# Base seconds between attempts; the wait grows linearly (1x, 2x, 3x ...).
# Backoff rather than immediate re-fire because rapid repeated auth failures
# are what trips gateway lockout and quota policies -- and because if the cause
# is an auth-cache TTL gap, the wait is the part that actually helps.
DEFAULT_RETRY_BACKOFF = 2.0
MAX_RETRY_BACKOFF = 30.0

# Endpoints -- vendor-confirmed real on this org's APIM (see README.md)
IP_ADDRESS_LIST_PATH = "/rest/ip_address_list"
IP_BLOCK_SUBNET_LIST_PATH = "/rest/ip_block_subnet_list"
IP_POOL_LIST_PATH = "/rest/ip_pool_list"
IP_ALIAS_LIST_PATH = "/rest/ip_alias_list/ip_id/{ip_id}"

# Caller-facing filter parameter -> the WHERE column it actually filters on,
# for ip_block_subnet_list. Two entries are NOT identity mappings, which is why
# this is a table and not an f-string: "subnet_name" filters but the record
# comes back under "name", and the caller-facing "site_name" filters as
# "parent_site_name".
#
# Also filterable but deliberately NOT exposed: start_ip_addr/end_ip_addr (hex)
# and start_hostaddr/end_hostaddr (dotted IP). A useful range filter needs
# comparison operators and/or AND-composition, neither of which is supported as
# far as anyone has established. See the probe list in the UC17 plan first.
LIST_SUBNETS_FILTERS = {
    "subnet_name": "subnet_name",
    "subnet_id": "subnet_id",
    "parent_subnet_name": "parent_subnet_name",
    "site_name": "parent_site_name",
}
