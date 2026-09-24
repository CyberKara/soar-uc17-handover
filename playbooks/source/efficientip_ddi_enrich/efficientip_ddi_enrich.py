"""
Data playbook for EfficientIP DDI (SOLIDserver) IP address enrichment. Looks up an IP in IPAM and writes a summary note.
"""


import phantom.rules as phantom
import json
from datetime import datetime, timedelta


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
    # Look up the playbook_input ip in SOLIDserver's IPAM.
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

    # Write your custom code here...

    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.act("get ip address", parameters=parameters, name="get_ip_address", assets=["efficientip_ddi mock"], callback=format_summary)

    return


@phantom.playbook_block()
def format_summary(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("format_summary() called")

    template = """# EfficientIP DDI Enrichment\n\n**IP Address:** {0}\n**Lookup Status:** {1}\n**Hostname:** {2}\n**Subnet:** {3}\n**Space:** {4}\n**MAC Address:** {5}\n**Class:** {6}\n**Description:** {7}"""

    # parameter list for template variable replacement
    parameters = [
        "playbook_input:ip",
        "get_ip_address:action_result.status",
        "get_ip_address:action_result.data.*.name",
        "get_ip_address:action_result.data.*.subnet_name",
        "get_ip_address:action_result.data.*.site_name",
        "get_ip_address:action_result.data.*.mac_addr",
        "get_ip_address:action_result.data.*.ip_class_name",
        "get_ip_address:action_result.data.*.description"
    ]

    ################################################################################
    ## Custom Code Start
    ################################################################################

    # Write your custom code here...

    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.format(container=container, template=template, parameters=parameters, name="format_summary", drop_none=True)

    finalize(container=container)

    return


@phantom.playbook_block()
def finalize(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("finalize() called")

    ################################################################################
    # Write the enrichment note and expose raw fields for a parent playbook.
    ################################################################################

    get_ip_address_result_data = phantom.collect2(container=container, datapath=["get_ip_address:action_result.status","get_ip_address:action_result.data.*.ip_id","get_ip_address:action_result.data.*.name","get_ip_address:action_result.data.*.subnet_name","get_ip_address:action_result.data.*.site_name","get_ip_address:action_result.data.*.mac_addr","get_ip_address:action_result.data.*.ip_class_name","get_ip_address:action_result.data.*.description"], action_results=results)
    format_summary = phantom.get_format_data(name="format_summary")

    get_ip_address_result_item_0 = [item[0] for item in get_ip_address_result_data]
    get_ip_address_result_item_1 = [item[1] for item in get_ip_address_result_data]
    get_ip_address_result_item_2 = [item[2] for item in get_ip_address_result_data]
    get_ip_address_result_item_3 = [item[3] for item in get_ip_address_result_data]
    get_ip_address_result_item_4 = [item[4] for item in get_ip_address_result_data]
    get_ip_address_result_item_5 = [item[5] for item in get_ip_address_result_data]
    get_ip_address_result_item_6 = [item[6] for item in get_ip_address_result_data]
    get_ip_address_result_item_7 = [item[7] for item in get_ip_address_result_data]

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    summary_note = phantom.get_format_data(name="format_summary")

    result = phantom.collect2(
        container=container,
        datapath=[
            "get_ip_address:action_result.status",
            "get_ip_address:action_result.data.*.ip_id",
            "get_ip_address:action_result.data.*.name",
            "get_ip_address:action_result.data.*.subnet_name",
            "get_ip_address:action_result.data.*.site_name",
            "get_ip_address:action_result.data.*.mac_addr",
            "get_ip_address:action_result.data.*.ip_class_name",
            "get_ip_address:action_result.data.*.description",
        ]
    )
    row = result[0] if result else [None] * 8
    status, ip_id, hostname, subnet, space, mac_address, ddi_class, description = (
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
    )

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
    }))

    phantom.debug("EfficientIP DDI enrichment complete: status={}".format(output_status))

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="finalize__inputs:0:format_summary:formatted_data", value=json.dumps(format_summary))
    phantom.save_block_result(key="finalize__inputs:1:get_ip_address:action_result.status", value=json.dumps(get_ip_address_result_item_0))
    phantom.save_block_result(key="finalize__inputs:2:get_ip_address:action_result.data.*.ip_id", value=json.dumps(get_ip_address_result_item_1))
    phantom.save_block_result(key="finalize__inputs:3:get_ip_address:action_result.data.*.name", value=json.dumps(get_ip_address_result_item_2))
    phantom.save_block_result(key="finalize__inputs:4:get_ip_address:action_result.data.*.subnet_name", value=json.dumps(get_ip_address_result_item_3))
    phantom.save_block_result(key="finalize__inputs:5:get_ip_address:action_result.data.*.site_name", value=json.dumps(get_ip_address_result_item_4))
    phantom.save_block_result(key="finalize__inputs:6:get_ip_address:action_result.data.*.mac_addr", value=json.dumps(get_ip_address_result_item_5))
    phantom.save_block_result(key="finalize__inputs:7:get_ip_address:action_result.data.*.ip_class_name", value=json.dumps(get_ip_address_result_item_6))
    phantom.save_block_result(key="finalize__inputs:8:get_ip_address:action_result.data.*.description", value=json.dumps(get_ip_address_result_item_7))

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
    }))

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
        "status": None,
        "ip_address": None,
        "hostname": None,
        "subnet": None,
        "space": None,
        "mac_address": None,
        "ddi_class": None,
        "description": None,
        "ip_id": None,
    }

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    # Populate the generated `output` dict; do NOT call
    # phantom.save_playbook_output_data() here. The VPE appends its own
    # save_playbook_output_data(output=output) immediately after this block, so
    # anything saved from inside the block is silently overwritten with the
    # all-None dict above on any GUI save -- the run still reports success and
    # still passes validation, and every consumer just gets nulls.
    raw_output = phantom.get_run_data(key="playbook_output")
    if raw_output:
        output.update(json.loads(raw_output))

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_playbook_output_data(output=output)

    return
