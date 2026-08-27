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
