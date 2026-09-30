"""
Automation playbook for label efficientip_ddi, launched by an analyst from a container (Playbooks > Run Playbook). Asks the analyst to type an IPv4 or IPv6 address, checks it, then runs efficientip_ddi_enrich on it, which looks the address up in SOLIDserver and writes the EfficientIP DDI Enrichment note. Inactive by default, so it never starts on its own. Stops with a note when the prompt expires or the answer is not an IP address.
"""


import phantom.rules as phantom
import json
from datetime import datetime, timedelta


################################################################################
## Global Custom Code Start
################################################################################



# Design notes (kept here because a VPE save replaces the module docstring):
# EfficientIP DDI Lookup
#
# Automation playbook, label efficientip_ddi, launched by hand from a container.
# efficientip_ddi_enrich is a data (input) playbook, which an analyst cannot
# launch from a container, so this playbook is the entry point: it asks for the
# IP, validates it and calls efficientip_ddi_enrich as a child, which does the
# lookup and writes the note. Left inactive at import so it never starts on a
# new container or artifact by itself.
#
# Trigger: Manual run by analyst

################################################################################
## Global Custom Code End
################################################################################

@phantom.playbook_block()
def on_start(container):
    phantom.debug('on_start() called')

    # call 'ask_ip' block
    ask_ip(container=container)

    return

@phantom.playbook_block()
def ask_ip(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("ask_ip() called")

    ################################################################################
    # Ask whoever launched the playbook to type the IP address to look up.
    ################################################################################

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    # The prompt is raised from code, not from a native prompt block: a native
    # block needs its approver fixed when the playbook is designed, but this
    # playbook is launched by hand and must ask whoever launched it, and a VPE
    # save regenerates prompt blocks whole. The callback continues the flow; the
    # return below stops the generated call to read_ip from also running right
    # away.
    user = None
    try:
        user_id = phantom.get_effective_user()
        user_url = phantom.build_phantom_rest_url("ph_user", user_id)
        user = phantom.requests.get(uri=user_url, verify=False).json().get("username")
    except Exception as e:
        phantom.debug("Could not resolve the launching user: {}".format(str(e)))
    if not user:
        user = container.get("owner_name", None) or "soar_local_admin"
    role = None
    respond_in_mins = 30
    message = """**EfficientIP DDI lookup**
Container: {0}

Type the IPv4 or IPv6 address to look up in SOLIDserver."""

    parameters = [
        "container:name",
    ]

    response_types = [
        {
            "prompt": "IP address",
            "options": {
                "type": "message",
                "required": True,
            },
        },
    ]

    phantom.prompt2(container=container, user=user, role=role, message=message, respond_in_mins=respond_in_mins, name="ask_ip", parameters=parameters, response_types=response_types, callback=read_ip)

    return

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="ask_ip_called", value="True")

    read_ip(container=container)

    return



@phantom.playbook_block()
def read_ip(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("read_ip() called")

    ################################################################################
    # Read the analyst's answer and check it is an IP address.
    ################################################################################

    read_ip__ip = None

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    run_id = phantom.get_playbook_run_id_()

    answer = ""
    prompt_status = "expired"

    try:
        approval_url = phantom.build_phantom_rest_url("approval") + \
            "?_filter_playbook_run={}&_filter_name=\"ask_ip\"&sort=id&order=desc&page_size=1".format(run_id)
        approvals = phantom.requests.get(uri=approval_url, verify=False).json().get("data") or []
    except Exception as e:
        phantom.error("Could not fetch approval record for playbook_run {}: {}".format(run_id, str(e)))
        approvals = []

    if approvals:
        approval = approvals[0]
        responses = approval.get("responses") or []
        if approval.get("status") == "approved" and responses and responses[0]:
            answer = str(responses[0]).strip()
            prompt_status = "answered"
        else:
            phantom.debug("Approval status '{}' for playbook_run {} -- treating as expired/no response".format(approval.get("status"), run_id))
    else:
        phantom.error("No approval record found for playbook_run {}".format(run_id))

    # One address only: a hostname, CIDR range or URL is refused here, before the
    # child playbook and the SOLIDserver lookup are started.
    import ipaddress

    ip = None
    problem = None
    if prompt_status != "answered":
        problem = "No answer was given before the prompt expired."
    else:
        try:
            ip = str(ipaddress.ip_address(answer))
        except ValueError:
            shown = answer[:100].replace("`", "'")
            problem = "`{}` is not an IPv4 or IPv6 address. Type one address, not a hostname, CIDR range or URL.".format(shown)

    if problem:
        phantom.add_note(
            container=container,
            note_type="general",
            title="EfficientIP DDI Lookup - not run",
            content="EfficientIP DDI lookup did not run. {}".format(problem),
            note_format="markdown",
        )
        phantom.debug("EfficientIP DDI lookup stopped: {}".format(problem))
        return

    read_ip__ip = ip

    # Also saved as run data: run_enrich reads this key.
    phantom.save_run_data(key="read_ip:ip", value=json.dumps(read_ip__ip))

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="read_ip:ip", value=json.dumps(read_ip__ip))

    phantom.save_block_result(key="read_ip_called", value="True")

    run_enrich(container=container)

    return



@phantom.playbook_block()
def run_enrich(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("run_enrich() called")

    ################################################################################
    # Run efficientip_ddi_enrich on the IP, which looks it up and writes the enrichment note.
    ################################################################################

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    ip = json.loads(phantom.get_run_data(key="read_ip:ip") or '""')

    # efficientip_ddi_enrich is a data playbook with one input, ip. It looks the
    # address up and writes the "EfficientIP DDI Enrichment" note itself. The
    # callback makes this run wait for it; the return stops the generated call to
    # finish_lookup from also running right away.
    phantom.playbook(
        playbook="local/efficientip_ddi_enrich",
        container=container,
        name="run_enrich",
        inputs={
            "ip": ip,
        },
        callback=finish_lookup,
    )

    return

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="run_enrich_called", value="True")

    finish_lookup(container=container)

    return



@phantom.playbook_block()
def finish_lookup(action=None, success=None, container=None, results=None, handle=None, filtered_artifacts=None, filtered_results=None, custom_function=None, loop_state_json=None, **kwargs):
    phantom.debug("finish_lookup() called")

    ################################################################################
    # Callback of run_enrich: the child playbook has finished.
    ################################################################################

    ################################################################################
    ## Custom Code Start
    ################################################################################
    ################################################################################

    phantom.debug("EfficientIP DDI lookup finished")

    ################################################################################
    ################################################################################
    ## Custom Code End
    ################################################################################

    phantom.save_block_result(key="finish_lookup_called", value="True")

    return


@phantom.playbook_block()
def on_finish(container, summary):
    phantom.debug("on_finish() called")

    ################################################################################
    ## Custom Code Start
    ################################################################################
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
    ################################################################################
    ## Custom Code End
    ################################################################################

    return
