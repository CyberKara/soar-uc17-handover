# efficientip_ddi_classic_consts.py
"""Constants for EfficientIP DDI (Classic) SOAR Connector."""

DEFAULT_TIMEOUT = 15  # seconds, matches the SDK connector's _request() timeout
DEFAULT_LIMIT = 1  # fallback when the optional "limit" action param is omitted

# Endpoints -- same convention as the SDK connector's app.py, vendor-confirmed
# real on this org's APIM (see soar-connectors/connectors/efficientip_ddi/README.md)
IP_ADDRESS_LIST_PATH = "/rest/ip_address_list"
IP_BLOCK_SUBNET_LIST_PATH = "/rest/ip_block_subnet_list"
IP_POOL_LIST_PATH = "/rest/ip_pool_list"
IP_ALIAS_LIST_PATH = "/rest/ip_alias_list/ip_id/{ip_id}"

# Caller-facing filter parameter -> the WHERE column it actually filters on,
# for ip_block_subnet_list. Two entries are NOT identity mappings, which is why
# this is a table and not an f-string: "subnet_name" filters but the record
# comes back under "name", and the caller-facing "site_name" filters as
# "parent_site_name". Mirrors the SDK twin's LIST_SUBNETS_FILTERS -- keep the
# two in step.
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
