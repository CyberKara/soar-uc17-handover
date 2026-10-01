"""
Diagnostic data playbook for the EfficientIP DDI connector. Runs get ip address and list subnets through the real action dispatch path and writes one PASS/FAIL note per action. Optional inputs ip and subnet_name pick values that exist in your IPAM; blank uses the lab mock&#39;s seed values. Test connectivity is not run here: use the asset's own Test Connectivity button.
"""


import phantom.rules as phantom
import json
from datetime import datetime, timedelta


@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    # call 'run_get_ip_address' block
    run_get_ip_address(container=container)
    # call 'run_list_subnets' block
    run_list_subnets(container=container)

    return

@phantom.playbook_block()
def run_get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("run_get_ip_address() called")

    # phantom.debug('Action: {0} {1}'.format(action['name'], ('SUCCEEDED' if success else 'FAILED')))

    ################################################################################
    # Run 'get ip address' on the ip input (blank: the mock seed 10.20.30.40).
    ################################################################################

    playbook_input_ip = phantom.collect2(container=container, datapath=["playbook_input:ip"])

    parameters = []

    # build parameters list for 'run_get_ip_address' call
    for playbook_input_ip_item in playbook_input_ip:
        if playbook_input_ip_item[0] is not None:
            parameters.append({
                "address": playbook_input_ip_item[0],
            })

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    # Blank input: the lab mock's seed record 10.20.30.40, which carries every
    # field (hostname, MAC, description), so the found path is exercised.
    parameters = [item for item in parameters if item.get("address")] or [{"address": "10.20.30.40"}]

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.act("get ip address", parameters=parameters, name="run_get_ip_address", assets=["efficientip_ddi mock"], callback=note_get_ip_address)

    return


@phantom.playbook_block()
def note_get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("note_get_ip_address() called")

    ################################################################################
    # Write the PASS/FAIL note for get ip address.
    ################################################################################

    run_get_ip_address_result_data = phantom.collect2(container=container, datapath=["run_get_ip_address:action_result.status","run_get_ip_address:action_result.message"], action_results=results)

    run_get_ip_address_result_item_0 = [item[0] for item in run_get_ip_address_result_data]
    run_get_ip_address_result_message = [item[1] for item in run_get_ip_address_result_data]

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_get_ip_address:action_result.status",
            "run_get_ip_address:action_result.message",
            "run_get_ip_address:action_result.parameter.address",
        ],
        action_results=results,
    )
    # No action result means SOAR refused to dispatch the action (it creates no
    # app_run); the reason is in this playbook run's log, not in a result.
    status, message, address = (result[0][0], result[0][1], result[0][2]) if result else (
        "failed", "No action result: SOAR did not dispatch the action. See this playbook run's log for the reason.", "",
    )
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - get ip address - {}".format(mark),
        content="**get ip address:** {}\n\n**Address:** {}\n\n{}".format(mark, address or "", message or ""),
        note_format="markdown",
    )
    phantom.save_run_data(key="get_ip_address", value=json.dumps(mark))

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="note_get_ip_address__inputs:0:run_get_ip_address:action_result.status", value=json.dumps(run_get_ip_address_result_item_0))
    phantom.save_block_result(key="note_get_ip_address__inputs:1:run_get_ip_address:action_result.message", value=json.dumps(run_get_ip_address_result_message))

    phantom.save_block_result(key="note_get_ip_address_called", value="True")

    return


@phantom.playbook_block()
def run_list_subnets(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("run_list_subnets() called")

    # phantom.debug('Action: {0} {1}'.format(action['name'], ('SUCCEEDED' if success else 'FAILED')))

    ################################################################################
    # Run 'list subnets' on the subnet_name input (blank: the mock seed CORP_LAN-USERS).
    ################################################################################

    playbook_input_subnet_name = phantom.collect2(container=container, datapath=["playbook_input:subnet_name"])

    parameters = []

    # build parameters list for 'run_list_subnets' call
    for playbook_input_subnet_name_item in playbook_input_subnet_name:
        parameters.append({
            "subnet_name": playbook_input_subnet_name_item[0],
        })

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    # Blank input: the lab mock's seed subnet. Subnet names are LABELS, not
    # CIDRs -- a subnet's address lives in its range fields, never in its name.
    parameters = [item for item in parameters if item.get("subnet_name")] or [{"subnet_name": "CORP_LAN-USERS"}]

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.act("list subnets", parameters=parameters, name="run_list_subnets", assets=["efficientip_ddi mock"], callback=note_list_subnets)

    return


@phantom.playbook_block()
def note_list_subnets(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("note_list_subnets() called")

    ################################################################################
    # Write the PASS/FAIL note for list subnets.
    ################################################################################

    run_list_subnets_result_data = phantom.collect2(container=container, datapath=["run_list_subnets:action_result.status","run_list_subnets:action_result.message"], action_results=results)

    run_list_subnets_result_item_0 = [item[0] for item in run_list_subnets_result_data]
    run_list_subnets_result_message = [item[1] for item in run_list_subnets_result_data]

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_list_subnets:action_result.status",
            "run_list_subnets:action_result.message",
            "run_list_subnets:action_result.parameter.subnet_name",
        ],
        action_results=results,
    )
    # No action result means SOAR refused to dispatch the action (it creates no
    # app_run); the reason is in this playbook run's log, not in a result.
    status, message, subnet_name = (result[0][0], result[0][1], result[0][2]) if result else (
        "failed", "No action result: SOAR did not dispatch the action. See this playbook run's log for the reason.", "",
    )
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - list subnets - {}".format(mark),
        content="**list subnets:** {}\n\n**Subnet name:** {}\n\n{}".format(mark, subnet_name or "", message or ""),
        note_format="markdown",
    )
    phantom.save_run_data(key="list_subnets", value=json.dumps(mark))

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="note_list_subnets__inputs:0:run_list_subnets:action_result.status", value=json.dumps(run_list_subnets_result_item_0))
    phantom.save_block_result(key="note_list_subnets__inputs:1:run_list_subnets:action_result.message", value=json.dumps(run_list_subnets_result_message))

    phantom.save_block_result(key="note_list_subnets_called", value="True")

    return


@phantom.playbook_block()
def on_finish(container, summary):
    phantom.debug("on_finish() called")

    output = {
        "status": [],
        "get_ip_address": [],
        "list_subnets": [],
    }

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    # Populate the generated `output` dict; the save after Custom Code End emits it.
    # A branch that recorded nothing stopped before its note: report it FAIL.
    for key in ("get_ip_address", "list_subnets"):
        raw = phantom.get_run_data(key=key)
        output[key] = json.loads(raw) if raw else "FAIL"
    output["status"] = "pass" if all(
        output[key] == "PASS" for key in ("get_ip_address", "list_subnets")
    ) else "fail"

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_playbook_output_data(output=output)

    return
