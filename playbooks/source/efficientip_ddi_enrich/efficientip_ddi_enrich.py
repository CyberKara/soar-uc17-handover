"""
Looks up the IP addresses of new artifacts in EfficientIP DDI (SOLIDserver) IPAM and writes one note with a table and a per-IP detail section. Each address is looked up once per container.
"""


import phantom.rules as phantom
import json
from datetime import datetime, timedelta


################################################################################
## Global Custom Code Start
################################################################################
################################################################################
################################################################################
################################################################################

import ipaddress
import re

# Addresses looked up per run; the rest are listed as skipped and looked up on
# the next run. Keeps the note readable and bounds one run's lookups.
DDI_MAX_ADDRESSES = 50
# Records asked per address ("limit" of get ip address). SOLIDserver can hold
# the same address in several spaces; a row reaching this count is flagged.
DDI_RECORD_LIMIT = 5
# The airgapped appliance cuts a note at about 22,000 characters
# (constraints.md); longer content is split into "Title (k/N)" notes.
DDI_NOTE_CAP = 19000
DDI_NOTE_TITLE = "EfficientIP DDI Enrichment"
DDI_NOT_FOUND_PREFIX = "No IP address record found"
DDI_TABLE_HEADER = [
    "| IP | Hostname | Aliases | Subnet | Parent subnet | Lookup |",
    "|---|---|---|---|---|---|",
]
# Lookup results that answer an address for good. A "failed" or "skipped" row
# does not, so that address is looked up again on the next run.
DDI_ANSWERED_PREFIXES = ("found", "not found")


def _ddi_valid_addresses(values):
    """Normalise artifact values to unique IP addresses, in order.

    A value may hold several addresses (commas, semicolons, spaces, new lines);
    anything that is not an address is ignored. IPv6 is compressed.
    """
    addresses = []
    for value in values:
        for part in re.split(r"[\s,;]+", str(value or "")):
            try:
                address = str(ipaddress.ip_address(part.strip()))
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
    return addresses


def _ddi_answered_addresses(note_bodies):
    """Addresses an earlier enrichment note already answered (found / not found).

    Reads the table rows: the first cell is the address, the last the lookup.
    Cells are escaped by _ddi_md(), so " | " only ever separates cells.
    """
    answered = set()
    for body in note_bodies:
        for line in str(body or "").splitlines():
            if not line.startswith("| ") or line.startswith("| IP |"):
                continue
            cells = line.strip().strip("|").split(" | ")
            if len(cells) < 2 or not cells[-1].strip().startswith(DDI_ANSWERED_PREFIXES):
                continue
            try:
                answered.add(str(ipaddress.ip_address(cells[0].strip())))
            except ValueError:
                continue
    return answered


def _ddi_md(value):
    """One markdown table cell / inline value: escaped, single line."""
    text = " ".join(str(value if value is not None else "").split())
    return re.sub(r"([\\`*_\[\]<>|#])", r"\\\1", text)


def _ddi_note_parts(lines):
    """Pack (text, in_table) lines into note bodies of at most DDI_NOTE_CAP
    characters, repeating the table header when a part starts inside it."""
    parts, current = [], []
    for text, in_table in lines:
        size = sum(len(line) + 1 for line in current)
        if current and size + len(text) + 1 > DDI_NOTE_CAP:
            parts.append("\n".join(current))
            current = list(DDI_TABLE_HEADER) if in_table else []
        current.append(text)
    if current:
        parts.append("\n".join(current))
    return parts

################################################################################
################################################################################
################################################################################
################################################################################
## Global Custom Code End
################################################################################

@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    # call 'collect_ips' block
    collect_ips(container=container)

    return

@phantom.playbook_block()
def collect_ips(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("collect_ips() called")

    ################################################################################
    # Collect the IPs of the new artifacts not already in an enrichment note.
    ################################################################################

    collect_ips__addresses = None

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################

    # Every value of an artifact field SOAR types as ip or ipv6 (the CEF
    # registry plus each artifact's own cef_types), from the artifacts in this
    # run's scope: the new ones when an artifact creation started the run.
    values = phantom.collect_from_contains(container=container, contains=["ip", "ipv6"]) or []
    addresses = _ddi_valid_addresses(values)

    # This playbook runs on every artifact created on the container: an address
    # an earlier note already answered (found / not found) is not looked up
    # again. A failed or skipped one is.
    answered = set()
    if addresses:
        url = phantom.build_phantom_rest_url("note")
        response = phantom.requests.get(
            url,
            params={
                "_filter_container": container["id"],
                "_filter_title__startswith": '"{}"'.format(DDI_NOTE_TITLE),
                "page_size": 0,
            },
            verify=False,
        )
        if response.status_code == 200:
            answered = _ddi_answered_addresses(
                note.get("content") for note in response.json().get("data", [])
                if str(note.get("title") or "").startswith(DDI_NOTE_TITLE)
            )
        else:
            phantom.debug("Could not read earlier enrichment notes (HTTP {}); looking up every address".format(response.status_code))

    pending = [address for address in addresses if address not in answered]
    if not pending:
        phantom.debug("No new IP address to enrich ({} seen, {} already in a note)".format(len(addresses), len(answered & set(addresses))))
        return

    collect_ips__addresses = pending[:DDI_MAX_ADDRESSES]
    phantom.save_run_data(key="get_ip_address:input", value=json.dumps({
        "addresses": collect_ips__addresses,
        "skipped": pending[DDI_MAX_ADDRESSES:],
    }))

    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="collect_ips:addresses", value=json.dumps(collect_ips__addresses))

    phantom.save_block_result(key="collect_ips_called", value="True")

    get_ip_address(container=container)

    return


@phantom.playbook_block()
def get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("get_ip_address() called")

    # phantom.debug('Action: {0} {1}'.format(action['name'], ('SUCCEEDED' if success else 'FAILED')))

    ################################################################################
    # Look up every collected IP in SOLIDserver's IPAM, one action result each.
    ################################################################################

    collect_ips__addresses = json.loads(_ if (_ := phantom.get_run_data(key="collect_ips:addresses")) != "" else "null")  # pylint: disable=used-before-assignment

    parameters = []

    if collect_ips__addresses is not None:
        parameters.append({
            "address": collect_ips__addresses,
        })

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################

    # Rebuild the parameters as one set per address, so the phantom.act() below
    # returns one action result per address (one app_run on whichever asset this
    # block selects). This lives here because a VPE save keeps this section and
    # rebuilds the generated code above from the bindings.
    run_input = json.loads(phantom.get_run_data(key="get_ip_address:input") or "{}")
    parameters = [{"address": address, "limit": DDI_RECORD_LIMIT} for address in run_input.get("addresses") or []]

    if not parameters:
        phantom.debug("No address to look up")
        return

    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.act("get ip address", parameters=parameters, name="get_ip_address", assets=["efficientip_ddi mock"], callback=finalize)

    return


@phantom.playbook_block()
def finalize(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("finalize() called")

    ################################################################################
    # Write the enrichment note: a table plus a per-IP detail section.
    ################################################################################

    get_ip_address_result_data = phantom.collect2(container=container, datapath=["get_ip_address:action_result.parameter.address","get_ip_address:action_result.status","get_ip_address:action_result.message","get_ip_address:action_result.data"], action_results=results)

    get_ip_address_parameter_address = [item[0] for item in get_ip_address_result_data]
    get_ip_address_result_item_1 = [item[1] for item in get_ip_address_result_data]
    get_ip_address_result_message = [item[2] for item in get_ip_address_result_data]
    get_ip_address_result_item_3 = [item[3] for item in get_ip_address_result_data]

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################

    run_input = json.loads(phantom.get_run_data(key="get_ip_address:input") or "{}")
    addresses = run_input.get("addresses") or []
    skipped = run_input.get("skipped") or []

    # One entry per action result, keyed by the address it was dispatched with.
    # An address with no entry was refused by SOAR before dispatch (no result):
    # that is a failure, never "not found".
    lookups = {}
    for row in phantom.collect2(
        container=container,
        datapath=[
            "get_ip_address:action_result.parameter.address",
            "get_ip_address:action_result.status",
            "get_ip_address:action_result.message",
            "get_ip_address:action_result.data",
        ],
        action_results=results,
    ):
        if row[0]:
            lookups[row[0]] = {"status": row[1], "message": row[2] or "", "records": row[3] or []}

    table, detail = [], []
    counts = {"found": 0, "not_found": 0, "failed": 0}

    def add_row(address, record, lookup):
        record = record or {}
        table.append("| " + " | ".join(_ddi_md(value) for value in [
            address,
            record.get("name"),
            record.get("ip_alias"),
            record.get("subnet_name"),
            record.get("parent_subnet_name"),
            lookup,
        ]) + " |")

    for address in addresses:
        lookup = lookups.get(address)
        records = [r for r in (lookup or {}).get("records", []) if isinstance(r, dict)]
        if lookup and lookup["status"] == "success" and records:
            counts["found"] += 1
            label = "found" if len(records) < DDI_RECORD_LIMIT else "found ({}+ records, more may exist)".format(DDI_RECORD_LIMIT)
            for record in records:
                add_row(address, record, label)
                where = " (space {})".format(_ddi_md(record.get("site_name"))) if len(records) > 1 else ""
                # Every field the appliance returns is in the note except ip_id,
                # a bare identifier.
                detail.append("\n".join(["**{}**{}".format(_ddi_md(address), where)] + [
                    "- {}: {}".format(label_text, _ddi_md(record.get(key)) or "-")
                    for label_text, key in [
                        ("space", "site_name"),
                        ("space class", "site_class_name"),
                        ("MAC", "mac_addr"),
                        ("class", "ip_class_name"),
                        ("description", "description"),
                        ("IP (hex)", "ip_addr"),
                        ("class parameters", "ip_class_parameters"),
                    ]
                ]))
        elif lookup and lookup["message"].startswith(DDI_NOT_FOUND_PREFIX):
            counts["not_found"] += 1
            add_row(address, None, "not found")
            if ":" in address:
                detail.append("**{}**\n- not found: IPv6 lookups are unverified on this API, so this is not proof of absence".format(_ddi_md(address)))
        else:
            counts["failed"] += 1
            if lookup:
                add_row(address, None, "failed")
                detail.append("**{}**\n- lookup failed: {}".format(_ddi_md(address), _ddi_md(lookup["message"][:300]) or "no message"))
            else:
                add_row(address, None, "failed (not dispatched)")
                detail.append("**{}**\n- SOAR did not run the lookup; the reason is in this playbook run".format(_ddi_md(address)))
    for address in skipped:
        add_row(address, None, "skipped (over {} addresses, next run)".format(DDI_MAX_ADDRESSES))

    summary = "{} address(es): {} found, {} not found, {} failed".format(
        len(addresses), counts["found"], counts["not_found"], counts["failed"])
    if skipped:
        summary += ", {} skipped".format(len(skipped))

    lines = [("**Lookup:** {}".format(summary), False), ("", False)]
    lines += [(line, True) for line in DDI_TABLE_HEADER + table]
    if detail:
        lines += [("", False), ("### Per-IP detail", False)]
        # One block per record (bold IP + its field list), a blank line before
        # each so the next IP never reads as part of the previous list. A block
        # is one entry, so a note split never cuts through it.
        for block in detail:
            lines += [("", False), (block, False)]

    parts = _ddi_note_parts(lines)
    for index, body in enumerate(parts, start=1):
        phantom.add_note(
            container=container,
            note_type="general",
            title=DDI_NOTE_TITLE if len(parts) == 1 else "{} ({}/{})".format(DDI_NOTE_TITLE, index, len(parts)),
            content=body,
            note_format="markdown",
        )

    phantom.debug("EfficientIP DDI enrichment complete: {}".format(summary))

    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="finalize__inputs:0:get_ip_address:action_result.parameter.address", value=json.dumps(get_ip_address_parameter_address))
    phantom.save_block_result(key="finalize__inputs:1:get_ip_address:action_result.status", value=json.dumps(get_ip_address_result_item_1))
    phantom.save_block_result(key="finalize__inputs:2:get_ip_address:action_result.message", value=json.dumps(get_ip_address_result_message))
    phantom.save_block_result(key="finalize__inputs:3:get_ip_address:action_result.data", value=json.dumps(get_ip_address_result_item_3))

    phantom.save_block_result(key="finalize_called", value="True")

    return


@phantom.playbook_block()
def on_finish(container, summary):
    phantom.debug("on_finish() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    # This function is called after all actions are completed.
    # summary of all the action and/or all details of actions
    # can be collected here.

    # summary_json = phantom.get_summary()
    # if 'result' in summary_json:
        # for action_result in summary_json['result']:
            # if 'action_run_id' in action_result:
                # action_results = phantom.get_action_results(action_run_id=action_result['action_run_id'], result_data=False, flatten=False)
                # phantom.debug(action_results)

    ################################################################################
    ## Custom Code End
    ################################################################################

    return
