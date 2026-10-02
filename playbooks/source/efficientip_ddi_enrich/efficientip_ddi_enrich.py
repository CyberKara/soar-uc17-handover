"""
Data playbook for EfficientIP DDI (SOLIDserver) IP address enrichment. Looks up one or more IPs in IPAM and writes a note with a table (one row per record) and a per-IP detail list. Output status: success (every address found), partial, not_found (no address found), failed (at least one lookup itself failed) or error (no valid ip input).
"""


import phantom.rules as phantom
import json
from datetime import datetime, timedelta


################################################################################
## Global Custom Code Start
################################################################################
################################################################################
################################################################################

import ipaddress
import re

# Addresses looked up per run; the rest are listed as skipped. Keeps the note
# readable and bounds the number of lookups one launch can start.
DDI_MAX_ADDRESSES = 50
# Records asked per address ("limit" of get ip address). SOLIDserver can hold
# the same address in several spaces; a row reaching this count is flagged.
DDI_RECORD_LIMIT = 5
# The airgapped appliance cuts a note at about 22,000 characters
# (constraints.md); longer content is split into "Title (k/N)" notes.
DDI_NOTE_CAP = 19000
DDI_NOT_FOUND_PREFIX = "No IP address record found"
DDI_TABLE_HEADER = [
    "| IP | Hostname | Aliases | Subnet | Parent subnet | Lookup |",
    "|---|---|---|---|---|---|",
]


def _ddi_split_addresses(values):
    """Split playbook_input:ip values into (valid, invalid, skipped) lists.

    Accepts commas, semicolons, spaces and new lines as separators; valid
    addresses are normalised (compressed IPv6) and de-duplicated in input order.
    """
    valid, invalid, skipped = [], [], []
    for value in values:
        for part in re.split(r"[\s,;]+", str(value or "")):
            part = part.strip()
            if not part:
                continue
            try:
                address = str(ipaddress.ip_address(part))
            except ValueError:
                if part not in invalid:
                    invalid.append(part)
                continue
            if address in valid or address in skipped:
                continue
            if len(valid) < DDI_MAX_ADDRESSES:
                valid.append(address)
            else:
                skipped.append(address)
    return valid, invalid, skipped


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
## Global Custom Code End
################################################################################

@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    # call 'check_input' block
    check_input(container=container)

    return

@phantom.playbook_block()
def check_input(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("check_input() called")

    # check for 'if' condition 1
    found_match_1 = phantom.decision(
        container=container,
        conditions=[
            ["playbook_input:ip", "!=", ""]
        ],
        conditions_dps=[
            ["playbook_input:ip", "!=", ""]
        ],
        name="check_input:condition_1",
        delimiter=",")

    # call connected blocks if condition 1 matched
    if found_match_1:
        get_ip_address(action=action, success=success, container=container, results=results, handle=handle)
        return

    # check for 'else' condition 2
    format_error(action=action, success=success, container=container, results=results, handle=handle)

    return


@phantom.playbook_block()
def get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("get_ip_address() called")

    # phantom.debug('Action: {0} {1}'.format(action['name'], ('SUCCEEDED' if success else 'FAILED')))

    ################################################################################
    # Look up every playbook_input ip in SOLIDserver's IPAM, one action result per 
    # address.
    ################################################################################

    playbook_input_ip = phantom.collect2(container=container, datapath=["playbook_input:ip"])

    parameters = []

    # build parameters list for 'get_ip_address' call
    for playbook_input_ip_item in playbook_input_ip:
        if playbook_input_ip_item[0] is not None:
            parameters.append({
                "address": playbook_input_ip_item[0],
            })

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################

    # The input may hold several addresses (comma/space/new-line separated, or
    # several values). Rebuild the parameters as one set per valid address, so
    # the phantom.act() below returns one action result per address (one app_run
    # on whichever asset this block selects). This lives here because a VPE save keeps this section
    # and rebuilds the generated code above from the bindings.
    raw_values = [item[0] for item in phantom.collect2(container=container, datapath=["playbook_input:ip"])]
    addresses, invalid, skipped = _ddi_split_addresses(raw_values)
    phantom.save_run_data(key="get_ip_address:input", value=json.dumps({
        "addresses": addresses,
        "invalid": invalid,
        "skipped": skipped,
    }))

    parameters = [{"address": address, "limit": DDI_RECORD_LIMIT} for address in addresses]

    if not parameters:
        # Nothing valid to look up: no action, straight to the note.
        finalize(container=container)
        return

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
    # Write the enrichment note (table + per-IP detail) and expose the rows for a 
    # parent playbook.
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

    run_input = json.loads(phantom.get_run_data(key="get_ip_address:input") or "{}")
    addresses = run_input.get("addresses") or []
    invalid = run_input.get("invalid") or []
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
    rows = []  # one per table row, for the outputs
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
        rows.append({
            "lookup": lookup,
            "ip_address": address,
            "hostname": record.get("name") or "",
            "aliases": record.get("ip_alias") or "",
            "subnet": record.get("subnet_name") or "",
            "parent_subnet": record.get("parent_subnet_name") or "",
            "space": record.get("site_name") or "",
            "space_class": record.get("site_class_name") or "",
            "mac_address": record.get("mac_addr") or "",
            "ddi_class": record.get("ip_class_name") or "",
            "description": record.get("description") or "",
            "ip_id": str(record.get("ip_id") or ""),
        })

    for address in addresses:
        lookup = lookups.get(address)
        records = [r for r in (lookup or {}).get("records", []) if isinstance(r, dict)]
        if lookup and lookup["status"] == "success" and records:
            counts["found"] += 1
            label = "found" if len(records) < DDI_RECORD_LIMIT else "found ({}+ records, more may exist)".format(DDI_RECORD_LIMIT)
            for record in records:
                add_row(address, record, label)
                where = " (space {})".format(_ddi_md(record.get("site_name"))) if len(records) > 1 else ""
                # Every field the appliance returns is in the note (user
                # requirement) except ip_id, a bare identifier (outputs only).
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
    for part in invalid:
        add_row(part, None, "invalid address")
    for address in skipped:
        add_row(address, None, "skipped (over {} addresses)".format(DDI_MAX_ADDRESSES))

    if not addresses:
        output_status = "error"
    elif counts["failed"]:
        output_status = "failed"
    elif counts["found"] == len(addresses) and not invalid and not skipped:
        output_status = "success"
    elif counts["found"]:
        output_status = "partial"
    else:
        output_status = "not_found"

    summary = "{} address(es): {} found, {} not found, {} failed".format(
        len(addresses), counts["found"], counts["not_found"], counts["failed"])
    if invalid:
        summary += ", {} invalid".format(len(invalid))
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

    title = "EfficientIP DDI Enrichment"
    parts = _ddi_note_parts(lines)
    for index, body in enumerate(parts, start=1):
        phantom.add_note(
            container=container,
            note_type="general",
            title=title if len(parts) == 1 else "{} ({}/{})".format(title, index, len(parts)),
            content=body,
            note_format="markdown",
        )

    # on_finish() fills the VPE-generated output dict from this run data.
    output = {"status": output_status}
    for key in ["lookup", "ip_address", "hostname", "aliases", "subnet", "parent_subnet",
                "space", "space_class", "mac_address", "ddi_class", "description", "ip_id"]:
        output[key] = [row[key] for row in rows]
    phantom.save_run_data(key="playbook_output", value=json.dumps(output))

    phantom.debug("EfficientIP DDI enrichment complete: status={}, {}".format(output_status, summary))

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
def format_error(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("format_error() called")

    template = """EfficientIP DDI enrichment could not run: no 'ip' input was provided."""

    # parameter list for template variable replacement
    parameters = []

    ################################################################################
    ## Custom Code Start
    ################################################################################

    # Write your custom code here...

    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.format(container=container, template=template, parameters=parameters, name="format_error", drop_none=True)

    note_error(container=container)

    return


@phantom.playbook_block()
def note_error(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("note_error() called")

    ################################################################################
    # Record the missing-input error on the container.
    ################################################################################

    format_error = phantom.get_format_data(name="format_error")

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################

    error_note = phantom.get_format_data(name="format_error")

    phantom.add_note(
        container=container,
        note_type="general",
        title="EfficientIP DDI Enrichment - Error",
        content=error_note,
        note_format="markdown",
    )

    # on_finish() fills the VPE-generated output dict from this run data; the
    # per-row outputs stay empty (normalised to null there).
    phantom.save_run_data(key="playbook_output", value=json.dumps({"status": "error"}))

    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="note_error__inputs:0:format_error:formatted_data", value=json.dumps(format_error))

    phantom.save_block_result(key="note_error_called", value="True")

    return


@phantom.playbook_block()
def on_finish(container, summary):
    phantom.debug("on_finish() called")

    output = {
        "status": [],
        "lookup": [],
        "ip_address": [],
        "hostname": [],
        "aliases": [],
        "subnet": [],
        "parent_subnet": [],
        "space": [],
        "space_class": [],
        "mac_address": [],
        "ddi_class": [],
        "description": [],
        "ip_id": [],
    }

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################

    # Populate the generated `output` dict; do NOT call
    # phantom.save_playbook_output_data() here. The VPE appends its own
    # save_playbook_output_data(output=output) immediately after this block, so
    # anything saved from inside the block is silently overwritten with the
    # empty dict above on any GUI save -- the run still reports success and
    # still passes validation, and every consumer just gets nulls.
    # Every field except status is a list with one entry per note table row.
    raw_output = phantom.get_run_data(key="playbook_output")
    if raw_output:
        output.update(json.loads(raw_output))
    # The 8.6 VPE initialises every output above to [] (8.5 wrote None), so an
    # output no block set is normalised to null here, whichever form a save wrote.
    for key, value in output.items():
        if value == []:
            output[key] = None
    if output["status"] is None:
        output["status"] = "error"

    ################################################################################
    ################################################################################
    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_playbook_output_data(output=output)

    return
