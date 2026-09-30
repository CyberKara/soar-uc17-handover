"""
EfficientIP DDI Action Test (diagnostic)

Automation playbook exercising all 3 efficientip_ddi actions against known-good
mock seed values, in 3 independent parallel branches, each writing its own
pass/fail note. It goes through the real action_run dispatch path, the same one
playbooks and container runs use.

Trigger: manual -- launched by an analyst from a container with label
         efficientip_ddi (Playbooks > Run Playbook). An automation playbook, left
         inactive at import so it never starts by itself: an input (data)
         playbook cannot be launched from a container.
Input:   none
Output:  none (results are written as 3 container notes, one per branch)
"""


import phantom.rules as phantom


ASSET = "efficientip_ddi mock"


@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    run_test_connectivity(container=container)
    run_get_ip_address(container=container)
    run_list_subnets(container=container)

    return


@phantom.playbook_block()
def run_test_connectivity(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_test_connectivity() called")

    phantom.act("test connectivity", parameters=[{}], name="run_test_connectivity", assets=[ASSET], callback=note_test_connectivity)

    return


@phantom.playbook_block()
def note_test_connectivity(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_test_connectivity() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_test_connectivity:action_result.status",
            "run_test_connectivity:action_result.message",
        ]
    )
    status, message = (result[0][0], result[0][1]) if result else ("not run", "")
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - test connectivity - {}".format(mark),
        content="**test connectivity:** {}\n\n{}".format(mark, message),
    )

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


@phantom.playbook_block()
def run_get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_get_ip_address() called")

    ################################################################################
    # Static test address: the mock's seed record, so the found path is exercised.
    ################################################################################

    parameters = [{
        "address": "10.20.30.40",
    }]

    phantom.act("get ip address", parameters=parameters, name="run_get_ip_address", assets=[ASSET], callback=note_get_ip_address)

    return


@phantom.playbook_block()
def note_get_ip_address(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_get_ip_address() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_get_ip_address:action_result.status",
            "run_get_ip_address:action_result.message",
        ]
    )
    status, message = (result[0][0], result[0][1]) if result else ("not run", "")
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - get ip address - {}".format(mark),
        content="**get ip address:** {}\n\n{}".format(mark, message),
    )

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


@phantom.playbook_block()
def run_list_subnets(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_list_subnets() called")

    ################################################################################
    # Static test name: the mock's seed subnet. Subnet names are labels, not CIDRs.
    ################################################################################

    parameters = [{
        "subnet_name": "CORP_LAN-USERS",
    }]

    phantom.act("list subnets", parameters=parameters, name="run_list_subnets", assets=[ASSET], callback=note_list_subnets)

    return


@phantom.playbook_block()
def note_list_subnets(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_list_subnets() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_list_subnets:action_result.status",
            "run_list_subnets:action_result.message",
        ]
    )
    status, message = (result[0][0], result[0][1]) if result else ("not run", "")
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - list subnets - {}".format(mark),
        content="**list subnets:** {}\n\n{}".format(mark, message),
    )

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


def on_finish(container, summary):
    phantom.debug("on_finish() called")
    return
