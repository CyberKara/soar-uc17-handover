# efficientip_ddi_consts.py
"""Constants for the EfficientIP DDI SOAR Connector."""

# The vendor's reference client uses 30s for these list calls; a slow,
# under-bounded scan cut off sooner would surface as a connection error.
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_LIMIT = 1  # fallback when the optional "limit" action param is omitted

# ---- Response status semantics ----
#
#   200  success
#   204  no content -- zero matching records (not a 200 with an empty array)
#   400  BAD REQUEST from the SOLIDserver backend; body carries errno/sql_error
#   401  unauthorized -- the ONLY auth-layer code
#   403  BAD REQUEST from the APIM gateway -- *not* "forbidden"
#
# Read as standard HTTP, 403 sends an operator hunting credentials, the wrong
# half of the stack. No status is retried: each request is sent once.
#
# WHERE is SQL: a string value must be single-quoted (unquoted it returns 400,
# errno 50028 / sql_error 7); an integer needs no quotes (ip_id=1697182). The
# action handlers quote every value, subnet_id included (a quoted integer is
# untested).
HTTP_STATUS_UNAUTHORIZED = 401
# Both mean bad request; see the note above.
BAD_REQUEST_STATUS = frozenset({400, 403})

# Tells a 401's producer apart: "OK OK" means the gateway reached SOLIDserver,
# so the 401 is its credential verdict; "FAIL FAIL" means the APIM's backend
# leg failed and the gateway answered 401 itself: check the mTLS client
# certificate first.
BACKSIDE_TRANSPORT_HEADER = "X-Backside-Transport"
# IBM API Connect's per-call id; the APIM administrator traces a call by it.
APIM_TRANS_ID_HEADER = "APIm-Debug-Trans-Id"

# Backend (SOLIDserver) credential headers, each carrying base64(value): the
# names the APIM reads. Sent as X-DDI-*, every call answers HTTP 401 "The
# specified document is not valid JSON data". See the README, "Auth model".
DDI_USERNAME_HEADER = "X-IPM-Username"
DDI_PASSWORD_HEADER = "X-IPM-Password"

# Endpoints (see README.md)
IP_ADDRESS_LIST_PATH = "/rest/ip_address_list"
IP_BLOCK_SUBNET_LIST_PATH = "/rest/ip_block_subnet_list"

# Caller-facing filter parameter -> the WHERE column it filters on, for
# ip_block_subnet_list: "site_name" filters as "parent_site_name", and a
# record filtered on "subnet_name" comes back under "name".
#
# Also filterable but NOT exposed: start_ip_addr/end_ip_addr (hex) and
# start_hostaddr/end_hostaddr (dotted). A range filter needs AND and comparison
# operators, neither confirmed; see the probes in the UC17 plan's Known
# limitations.
LIST_SUBNETS_FILTERS = {
    "subnet_name": "subnet_name",
    "subnet_id": "subnet_id",
    "parent_subnet_name": "parent_subnet_name",
    "site_name": "parent_site_name",
}
