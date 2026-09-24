"""
EfficientIP DDI Action Test (diagnostic)

Data playbook exercising all 3 efficientip_ddi actions against known-good
mock seed values, in 3 independent parallel branches, each writing its own
pass/fail note. Built after the SOAR App Debugger's "view app" code/trigger-
action panel was found to always report "Action X not found" for SDK-based
apps regardless of whether the connector actually works (see memory
project-soar85-app-debugger-sdk-action-not-found) -- this playbook exercises
the real action_run dispatch path instead, the same one playbooks/asset
Test Connectivity/container runs actually use.

Trigger: none -- manually launched against any container.
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
    # Static test address -- 10.20.30.40 is the mock's known-good seed record
    # (has hostname/MAC/description), so this exercises the found path, not
    # just not-found.
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
    # Static test name -- CORP_LAN-USERS is the mock's known-good seed subnet.
    # Subnet names are LABELS, not CIDRs: a subnet's address lives in its range
    # fields, never in its name.
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
