# UC17 — playbook implementation notes

Why the three UC17 playbooks are built the way they are. The playbook source carries
only short "why" comments; the reasoning lives here. The connector side is in
`efficientip_ddi_implementation_notes.md`; the dated history is in
`uc17_efficientip_ddi_enrich_implementation_plan.md`.

## 1. Roles

| Playbook | Type | Label | Role |
|---|---|---|---|
| `efficientip_ddi_lookup` | automation | `efficientip_ddi` | Analyst entry point: asks for an IP, validates it, calls `efficientip_ddi_enrich` |
| `efficientip_ddi_enrich` | input (`data`) | `events` (a save resets it to `*`) | Looks the IP up in SOLIDserver and writes the `EfficientIP DDI Enrichment` note |
| `efficientip_ddi_action_test` | automation | `efficientip_ddi` | Diagnostic: one pass/fail note per connector action |

Both automation playbooks import **inactive** and are run by hand from a container of
label `efficientip_ddi` (Playbooks > Run Playbook). Nothing fires them.

## 2. Why a launcher

An input (`data`) playbook cannot be launched from a container by an analyst on the
target, so `efficientip_ddi_enrich` could not be the entry point. The launcher is an
**automation** playbook scoped to a dedicated label, which is what Run Playbook offers.

### `efficientip_ddi_lookup`

```
[Code] ask_ip      phantom.prompt2, one required "message" response, callback read_ip
[Code] read_ip     reads the answer from GET /rest/approval; validates; stops with a note on a bad answer
[Code] run_enrich  phantom.playbook("local/efficientip_ddi_enrich", inputs={"ip": ...}, callback=finish_lookup)
[Code] finish_lookup  placeholder callback so the run waits for the child
```

- **The prompt is raised from a code block.** A native prompt block needs its approver
  fixed at design time; the launcher must ask whoever launched it
  (`phantom.get_effective_user()`, else the container owner, else `soar_local_admin`). A
  native prompt also has no Custom Code, and a save regenerates it whole. The `return`
  after `prompt2` stops the generated call to `read_ip`, which the callback makes instead.
- **The answer is read through `GET /rest/approval`**, filtered on the playbook run and the
  prompt's name, not through `collect2`: `collect2` does not return prompt results
  reliably (the same approach `proofpoint_trap_acknowledge` uses).
- **Validation is `ipaddress.ip_address()`**, single address only. A hostname, CIDR range,
  URL, an expired prompt or a missing approval record each write an
  `EfficientIP DDI Lookup - not run` note (markdown) and return before the child starts, so
  no SOLIDserver call is made. The IPv6 answer is normalised to its compressed form.
- **Timeout is 30 minutes** (short, so the expiry path is testable).
- **The child is called from a code block, not a native playbook block.** The repo has no
  8.6-VPE-generated export of a native playbook block binding an input to a code-block
  output, and code blocks are the one block type written by hand. The callback makes the
  run wait for the child.
- **Why inactive.** An active automation playbook with `artifact_created` fires on every new
  container or artifact of its label, and its prompt would then go to its Run As user. If
  an SOAR version does not offer an inactive playbook under Run Playbook, set it Active and
  set it back afterwards.

Generated to the shapes of `proofpoint_trap_acknowledge` (prompt + approval read-back) and
`proofpoint_trap_orchestrator` (automation, label-scoped, child called synchronously).

## 3. `efficientip_ddi_enrich`

- Flow: `check_input` (decision on `playbook_input:ip`) -> `get_ip_address` (native action) ->
  `format_summary` -> `finalize`; an empty input goes to `format_error` -> `note_error`.
- **Field names are the raw connector keys**: `name`, `subnet_name`, `site_name`,
  `mac_addr`, `ip_class_name`, `description`, `ip_id`. The output fields keep their
  caller-facing names (`hostname`, `subnet`, `space`, `mac_address`, `ddi_class`).
- **Outputs**: the playbook stores a JSON blob with `save_run_data` in `finalize` /
  `note_error`; `on_finish` populates the VPE-generated `output` dict from it. It must not
  call `save_playbook_output_data()` itself: the VPE appends its own call after the block,
  which overwrites anything saved inside. See `playbook-patterns.md`, "Playbook outputs".
- **A not-found address** still writes the note, with empty fields, and the output status is
  `partial`. The run itself shows as failed because the lookup action failed; that is the
  platform aggregating a failed action, not a fault.

## 4. `efficientip_ddi_action_test`

Three independent parallel branches from `on_start` (test connectivity, get ip address,
list subnets), each followed by a code block that reads its action result and writes a
PASS/FAIL note. It goes through the real `action_run` dispatch path, the same one
playbooks and container runs use, which is why it exists: the App Debugger panel is unreliable
for exercising actions by hand (it cannot dispatch them at all for SDK-based apps), so a
playbook is the repeatable check.

- Its test values (`10.20.30.40`, `CORP_LAN-USERS`) are the **mock's seed records**, so on a
  real appliance expect `test connectivity` to PASS and the other two to report "not found".
  A "not found" still proves the call reached SOLIDserver and back; an HTTP 401, TLS or BAD
  REQUEST message does not.
- Subnet names are labels, not CIDRs.
- `ASSET` is a module-level constant in the `.py`; a VPE save regenerates the header and
  drops it, but the action blocks' `phantom.act(...)` lines are regenerated from the
  blocks' selected asset, so nothing depends on it after a save.

## 5. Save safety (what a VPE save does to these)

- Logic lives only inside `## Custom Code Start/End`; `on_start` holds none.
- A node's function name equals its canvas label slugified; a label must not end in
  "artifacts" or "container".
- Action blocks are re-pointed to the importer's own asset by selecting it in the block
  and saving. That save keeps the Custom Code and the automation playbooks' label scope;
  it resets an input playbook's label scope to `*`.
- `check_vpe_shape.py` and `check_usercode_sync.py` pass for all three.

## 6. Not yet verified

The playbooks were written to the repo's canonical shapes and checked locally, but have not
been imported or opened in a VPE. The VPE open-and-look pass (no warnings) is still owed,
and a first GUI save is expected to produce a new version.
