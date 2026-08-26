"""
EfficientIP DDI Action Test (diagnostic)

Data playbook exercising all 5 efficientip_ddi actions against known-good
mock seed values, in 4 independent parallel branches, each writing its own
pass/fail note. Built after the SOAR App Debugger's "view app" code/trigger-
action panel was found to always report "Action X not found" for SDK-based
apps regardless of whether the connector actually works (see memory
project-soar85-app-debugger-sdk-action-not-found) -- this playbook exercises
the real action_run dispatch path instead, the same one playbooks/asset
Test Connectivity/container runs actually use.

Trigger: none -- manually launched against any container.
Input:   none
Output:  none (results are written as 4 container notes, one per branch)
"""


import phantom.rules as phantom


ASSET = "efficientip_ddi mock"


@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    run_test_connectivity(container=container)
    run_get_ip_address(container=container)
    run_list_subnets(container=container)
    run_get_ip_pool(container=container)

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
    # (has hostname/MAC/description AND an alias) so the chained list_aliases
    # call below also has something real to find, not just a not-found path.
    ################################################################################

    parameters = [{
        "address": "10.20.30.40",
    }]

    phantom.act("get ip address", parameters=parameters, name="run_get_ip_address", assets=[ASSET], callback=run_list_aliases)

    return


@phantom.playbook_block()
def run_list_aliases(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_list_aliases() called")

    ################################################################################
    # Chained off run_get_ip_address's own ip_id output, per the same
    # chaining rule as efficientip_ddi_enrich (not a literal input).
    ################################################################################

    input_data = phantom.collect2(
        container=container,
        datapath=["run_get_ip_address:action_result.data.*.ip_id"]
    )

    parameters = []
    for item in input_data:
        if item[0] is not None:
            parameters.append({
                "ip_id": item[0],
            })

    phantom.act("list aliases", parameters=parameters, name="run_list_aliases", assets=[ASSET], callback=note_ip_and_alias)

    return


@phantom.playbook_block()
def note_ip_and_alias(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_ip_and_alias() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    ip_result = phantom.collect2(
        container=container,
        datapath=[
            "run_get_ip_address:action_result.status",
            "run_get_ip_address:action_result.message",
        ]
    )
    ip_status, ip_message = (ip_result[0][0], ip_result[0][1]) if ip_result else ("not run", "")
    ip_mark = "PASS" if ip_status == "success" else "FAIL"

    alias_result = phantom.collect2(
        container=container,
        datapath=[
            "run_list_aliases:action_result.status",
            "run_list_aliases:action_result.message",
            "run_list_aliases:action_result.data.*.alias_name",
        ]
    )
    alias_status, alias_message, alias_name = (
        (alias_result[0][0], alias_result[0][1], alias_result[0][2]) if alias_result else ("not run", "", "")
    )
    alias_mark = "PASS" if alias_status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - get ip address / list aliases - {}/{}".format(ip_mark, alias_mark),
        content=(
            "**get ip address:** {} -- {}\n\n"
            "**list aliases:** {} -- {} (alias_name={!r})"
        ).format(ip_mark, ip_message, alias_mark, alias_message, alias_name),
    )

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


@phantom.playbook_block()
def run_list_subnets(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_list_subnets() called")

    ################################################################################
    # Static test name -- 10.20.30.0/24 is the mock's known-good seed subnet.
    ################################################################################

    parameters = [{
        "name": "10.20.30.0/24",
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


@phantom.playbook_block()
def run_get_ip_pool(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("run_get_ip_pool() called")

    ################################################################################
    # Static test name -- finance-dhcp-pool is the mock's known-good seed pool.
    ################################################################################

    parameters = [{
        "name": "finance-dhcp-pool",
    }]

    phantom.act("get ip pool", parameters=parameters, name="run_get_ip_pool", assets=[ASSET], callback=note_get_ip_pool)

    return


@phantom.playbook_block()
def note_get_ip_pool(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, **kwargs):
    phantom.debug("note_get_ip_pool() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################

    result = phantom.collect2(
        container=container,
        datapath=[
            "run_get_ip_pool:action_result.status",
            "run_get_ip_pool:action_result.message",
        ]
    )
    status, message = (result[0][0], result[0][1]) if result else ("not run", "")
    mark = "PASS" if status == "success" else "FAIL"

    phantom.add_note(
        container=container,
        note_type="general",
        title="efficientip_ddi action test - get ip pool - {}".format(mark),
        content="**get ip pool:** {}\n\n{}".format(mark, message),
    )

    ################################################################################
    ## Custom Code End
    ################################################################################

    return


def on_finish(container, summary):
    phantom.debug("on_finish() called")
    return
