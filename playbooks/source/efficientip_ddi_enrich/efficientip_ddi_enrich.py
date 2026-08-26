"""
EfficientIP DDI Enrichment (UC17)

Data playbook for analyst-driven IP/DNS lookup enrichment against EfficientIP
SOLIDserver (via APIM). Looks up an IP in IPAM ('get ip address'), then
chains into a DNS alias lookup ('list aliases') off the returned ip_id.
Partial success (IP found but no aliases, or IP not found at all) is a
first-class outcome, not an error.

Trigger: none — manually launched by an analyst, or called as a child
         playbook via phantom.playbook() from another use case.
Input:   ip
Output:  status, ip_address, hostname, subnet, space, mac_address,
         ddi_class, description, ip_id, alias_name
"""


import phantom.rules as phantom
import json


ASSET = "efficientip_ddi mock"


@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    check_input(container=container)

    return


@phantom.playbook_block()
def check_input(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("check_input() called")

    ip_provided = phantom.decision(
        container=container,
        conditions=[
            ["playbook_input:ip", "!=", ""]
        ])

    if ip_provided:
        get_ip_address(action=action, success=success, container=container, results=results, handle=handle)
        return

    format_error(action=action, success=success, container=container, results=results, handle=handle)

    return


@phantom.playbook_block()
def format_error(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("format_error() called")

    template = "EfficientIP DDI enrichment could not run: no 'ip' input was provided."

    phantom.format(container=container, template=template, parameters=[], name="format_error")

    note_error(container=container)

    return


@phantom.playbook_block()
def note_error(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_error() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    error_note = phantom.get_format_data(name="format_error")

    phantom.add_note(
        container=container,
        note_type="general",
        title="EfficientIP DDI Enrichment - Error",
        content=error_note,
    )

    # save_playbook_output_data() is only callable from on_finish() on SOAR 8.5
    # (RuntimeError otherwise) -- stash the output via save_run_data and let
    # on_finish() do the actual save. See playbook-patterns.md's documented
    # "save_run_data + on_finish output" pattern.
    phantom.save_run_data(key="playbook_output", value=json.dumps({
        "status": "error",
        "ip_address": "",
        "hostname": "",
        "subnet": "",
        "space": "",
        "mac_address": "",
        "ddi_class": "",
        "description": "",
        "ip_id": "",
        "alias_name": "",
    }))

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


@phantom.playbook_block()
def get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("get_ip_address() called")

    ################################################################################
    # Native action block — look up playbook_input:ip in SOLIDserver's IPAM.
    ################################################################################

    input_data = phantom.collect2(
        container=container,
        datapath=["playbook_input:ip"]
    )

    parameters = []
    for item in input_data:
        if item[0] is not None:
            parameters.append({
                "address": item[0],
            })

    phantom.act("get ip address", parameters=parameters, name="get_ip_address", assets=[ASSET], callback=check_ip_found)

    return


@phantom.playbook_block()
def check_ip_found(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("check_ip_found() called")

    ip_found = phantom.decision(
        container=container,
        conditions=[
            ["get_ip_address:action_result.data.*.ip_id", "!=", ""]
        ])

    if ip_found:
        list_aliases(action=action, success=success, container=container, results=results, handle=handle)
        return

    format_summary(action=action, success=success, container=container, results=results, handle=handle)

    return


@phantom.playbook_block()
def list_aliases(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("list_aliases() called")

    ################################################################################
    # Native action block — list DNS aliases for the ip_id returned by
    # get_ip_address (not playbook_input, per the design's chaining rule).
    ################################################################################

    input_data = phantom.collect2(
        container=container,
        datapath=["get_ip_address:action_result.data.*.ip_id"]
    )

    parameters = []
    for item in input_data:
        if item[0] is not None:
            parameters.append({
                "ip_id": item[0],
            })

    phantom.act("list aliases", parameters=parameters, name="list_aliases", assets=[ASSET], callback=format_summary)

    return


@phantom.playbook_block()
def format_summary(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("format_summary() called")

    template = (
        "# EfficientIP DDI Enrichment\n\n"
        "**IP Address:** {0}\n"
        "**Lookup Status:** {1}\n"
        "**Hostname:** {2}\n"
        "**Subnet:** {3}\n"
        "**Space:** {4}\n"
        "**MAC Address:** {5}\n"
        "**Class:** {6}\n"
        "**Description:** {7}\n\n"
        "**Alias:** {8}"
    )

    parameters = [
        "playbook_input:ip",
        "get_ip_address:action_result.status",
        "get_ip_address:action_result.data.*.hostname",
        "get_ip_address:action_result.data.*.subnet",
        "get_ip_address:action_result.data.*.space",
        "get_ip_address:action_result.data.*.mac_address",
        "get_ip_address:action_result.data.*.ddi_class",
        "get_ip_address:action_result.data.*.description",
        "list_aliases:action_result.data.*.alias_name",
    ]

    phantom.format(container=container, template=template, parameters=parameters, name="format_summary")

    finalize(container=container)

    return


@phantom.playbook_block()
def finalize(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("finalize() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    summary_note = phantom.get_format_data(name="format_summary")

    result = phantom.collect2(
        container=container,
        datapath=[
            "get_ip_address:action_result.status",
            "get_ip_address:action_result.data.*.ip_id",
            "get_ip_address:action_result.data.*.hostname",
            "get_ip_address:action_result.data.*.subnet",
            "get_ip_address:action_result.data.*.space",
            "get_ip_address:action_result.data.*.mac_address",
            "get_ip_address:action_result.data.*.ddi_class",
            "get_ip_address:action_result.data.*.description",
        ]
    )
    row = result[0] if result else [None] * 8
    status, ip_id, hostname, subnet, space, mac_address, ddi_class, description = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
    )

    alias_result = phantom.collect2(
        container=container,
        datapath=["list_aliases:action_result.data.*.alias_name"]
    )
    alias_name = alias_result[0][0] if alias_result and alias_result[0][0] else ""

    ip_input = phantom.collect2(container=container, datapath=["playbook_input:ip"])
    ip_address = ip_input[0][0] if ip_input and ip_input[0][0] else ""

    output_status = "success" if (status == "success" and ip_id) else "partial"

    phantom.add_note(
        container=container,
        note_type="general",
        title="EfficientIP DDI Enrichment",
        content=summary_note,
    )

    # save_playbook_output_data() is only callable from on_finish() on SOAR 8.5
    # (RuntimeError otherwise) -- stash the output via save_run_data and let
    # on_finish() do the actual save. See playbook-patterns.md's documented
    # "save_run_data + on_finish output" pattern.
    phantom.save_run_data(key="playbook_output", value=json.dumps({
        "status": output_status,
        "ip_address": ip_address,
        "hostname": hostname or "",
        "subnet": subnet or "",
        "space": space or "",
        "mac_address": mac_address or "",
        "ddi_class": ddi_class or "",
        "description": description or "",
        "ip_id": ip_id or "",
        "alias_name": alias_name,
    }))

    phantom.debug("EfficientIP DDI enrichment complete: status={}".format(output_status))

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


def on_finish(container, summary):
    phantom.debug("on_finish() called")

    raw_output = phantom.get_run_data(key="playbook_output")
    if raw_output:
        phantom.save_playbook_output_data(output=json.loads(raw_output))

    return
