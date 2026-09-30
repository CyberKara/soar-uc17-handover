# efficientip_ddi_consts.py
"""Constants for the EfficientIP DDI SOAR Connector."""

# 30s matches the vendor's reference client. A merely slow list call must not
# be cut off client side and surface as a connection error.
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_LIMIT = 1  # fallback when the optional "limit" action param is omitted

# ---- Response status semantics ----
#
#   200  success
#   204  no content -- a list endpoint with zero matching records. Not an
#         error, and not a 200 with an empty JSON array.
#   400  BAD REQUEST (backend/SQL layer) -- body carries errno/sql_error.
#   401  unauthorized -- the ONLY auth-layer code.
#   403  BAD REQUEST (gateway layer) -- not "forbidden".
#
# Both bad-request codes are named as such and never retried: a malformed
# request fails identically every time. Read as plain HTTP, 403 would send an
# operator hunting credentials.
#
# A string value in a WHERE clause must be single-quoted (the clause is SQL);
# an integer column needs no quotes. _bounded_query() quotes, which is right
# for every column currently exposed.
HTTP_STATUS_UNAUTHORIZED = 401
# Both mean bad request; see the note above.
BAD_REQUEST_STATUS = frozenset({400, 403})

# Only 401 is retried: the appliance has answered it for a request that
# succeeds unchanged moments later. The connector holds no per-call state, so
# identical inputs produce identical bytes, which is what makes a retry
# meaningful.
RETRYABLE_STATUS = frozenset({HTTP_STATUS_UNAUTHORIZED})

# Total attempts, including the first; tunable per asset.
DEFAULT_RETRY_COUNT = 3
MAX_RETRY_COUNT = 10

# Base seconds between attempts; the wait grows linearly (1x, 2x, 3x ...).
# Backoff, not an immediate re-fire: rapid repeated auth failures trip gateway
# lockout and quota policies.
DEFAULT_RETRY_BACKOFF = 2.0
MAX_RETRY_BACKOFF = 30.0

# Backend (SOLIDserver) credential headers, each carrying base64(value). These
# are the names the APIM reads: under any other name it answers HTTP 401 "The
# specified document is not valid JSON data" on every call. See the README,
# "Auth model".
DDI_USERNAME_HEADER = "X-IPM-Username"
DDI_PASSWORD_HEADER = "X-IPM-Password"

# Endpoints (see README.md)
IP_ADDRESS_LIST_PATH = "/rest/ip_address_list"
IP_BLOCK_SUBNET_LIST_PATH = "/rest/ip_block_subnet_list"

# Caller-facing filter parameter -> the WHERE column it filters on, for
# ip_block_subnet_list. Two entries are not identities: "subnet_name" filters
# while the record comes back under "name", and "site_name" filters as
# "parent_site_name".
#
# Filterable but not exposed: start_ip_addr/end_ip_addr (hex) and
# start_hostaddr/end_hostaddr (dotted). A range filter needs comparison
# operators and/or AND-composition, which are not established.
LIST_SUBNETS_FILTERS = {
    "subnet_name": "subnet_name",
    "subnet_id": "subnet_id",
    "parent_subnet_name": "parent_subnet_name",
    "site_name": "parent_site_name",
}
