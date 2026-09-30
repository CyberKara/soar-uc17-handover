# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-09-24 12:48 UTC from `efficientip_ddi_enrich` (source env: `soar8`).
Updated 2026-09-30: connector v1.0.13 and the new `efficientip_ddi_lookup` playbook, built from
the source repo, not from a fresh export of `soar8`. `efficientip_ddi_enrich` and the asset
template are unchanged from the 2026-09-24 export.

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi-v1.0.13.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/*.tgz` (PBs) | efficientip_ddi_enrich, efficientip_ddi_lookup, efficientip_ddi_action_test |
| `playbooks/source/` | Same CFs/playbooks, extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `diagnostics/` | Scripts you run on the target to answer questions about it — see below |
| `docs/` | Implementation plan doc, for full design context |

## [!] Upgrading over an earlier install — read this first

These apply only if this app is already installed on the target from a
previous package. On a completely fresh target, skip to Install order.

- **Which of these applies depends on what is already installed — check the Apps list first.** Open Apps and search for `EfficientIP`. If you see **exactly one** app (named `efficientip_ddi` / `EfficientIP DDI`), you installed the 2026-08-31 package or later: this one is a **normal in-place upgrade**. Install it over the existing app — same internal identifier — and your existing asset keeps working with every credential intact. **Do not delete anything and do not re-enter any credential.** If instead you see **two** apps (an `efficientip_ddi` and an `EfficientIP DDI (Classic)`), you are still on a package older than 2026-08-31, and the note below applies to you instead.

- **Connector v1.0.12 fixes a constant HTTP 401 on Test Connectivity** (this package carries v1.0.13: the same code, with condensed comments). The connector sent the two SOLIDserver credential headers as `X-DDI-Username` / `X-DDI-Password`; the APIM reads `X-IPM-Username` / `X-IPM-Password`, and with the wrong names every call failed with HTTP 401 and the message "The specified document is not valid JSON data". It also fixes `get ip address`, which filtered on a column (`host_addr`) that does not exist on the appliance; it now uses `hostaddr`. The connector upgrade is a normal in-place one: same app, same asset, no credential to re-enter. Install it over the existing app. One thing to check on the asset: **`base_url` must include the APIM path prefix that comes before `/rest`** (for example `https://apim.example/prefix/segment`); the connector appends `/rest/<service>` to it.

- **Two playbooks are new or changed.** `efficientip_ddi_lookup` is new: an automation playbook, label `efficientip_ddi`, that an analyst launches from a container and that asks for the IP address. `efficientip_ddi_action_test` is now an automation playbook with that label too: it was an input playbook, which an analyst cannot launch from a container. `efficientip_ddi_enrich` is unchanged. Import the two, after creating the label (see the activation step below). If SOAR keeps the old input-type `efficientip_ddi_action_test` after the import, delete it under Playbooks and import it again.

- **This package removes two connector actions: `get ip pool` and `list aliases`** (connector v1.0.11). The connector now calls only two SOLIDserver services: `ip_address_list` (`get ip address`) and `ip_block_subnet_list` (`list subnets`, `test connectivity`). After upgrading, any playbook that still calls a removed action fails at that step. That includes the `efficientip_ddi_enrich` and `efficientip_ddi_action_test` playbooks from any earlier package, so re-import both from this package so they replace the earlier versions. If you built playbooks of your own on `get ip pool` or `list aliases`, rework them before upgrading. Your asset and its credentials are not affected. The new `efficientip_ddi_enrich` also fixes its summary note: with packages from 2026-08-31 to 2026-09-09, hostname, subnet, space, MAC address and class came back empty. They are filled in now.

- **Only if the Apps list showed TWO apps.** Up to 2026-08-31 this use case shipped two: `efficientip_ddi` (SDK-based) and `EfficientIP DDI (Classic)`. The SDK app has been withdrawn, because its actions cannot be run from the connector's edit/view page in the SOAR web interface — a limitation of the platform, not of the app. The classic app is now the only one, and it has taken the `efficientip_ddi` name under a new internal identifier, so SOAR installs it as a brand-new app rather than upgrading anything. After installing: delete BOTH old apps and their assets through the web interface (Apps > the app > Delete), then create a fresh asset for the new app from the template in this package. Re-enter every credential by hand; secret fields do not carry across in the template.

- **Two new asset fields, both optional.** `retry_count` (default 3) and `retry_backoff` (default 2 seconds) control how a request answered with HTTP 401 is retried. They have working defaults, so an in-place upgrade needs no action: leave them alone unless you want to tune them. Set `retry_count` to 1 to disable retrying entirely.

## Install order

1. **Install the connector app(s)** — Apps > Install App, upload each file in `connectors/`.
   (`connectors/source/` is the same code extracted for reading — don't import from there,
   the GUI needs the `.tgz`.)
2. **Configure assets from the templates in `assets/`** — Apps > Configure New Asset for
   each. Fields marked in a template's `redacted_fields` list are placeholders
   (`<<SET ME...>>`) — **you must fill these in yourself**; they were never exported
   with usable values. Two different reasons appear in that list, and each placeholder
   says which one applies:

   - **Secrets** (passwords, API keys, certificates/keys) — take these from your own
     vault/CMDB. SOAR encrypts `password`-type fields at rest, so the export process
     cannot read them back in usable form even in principle.
   - **Identities and addresses** (usernames, client/app ids, endpoint URLs) — these
     are not secret, but they belonged to the source environment and are meaningless
     here. Enter the values *your* target system expects. **An identity must match the
     credential you enter beside it** — a real password paired with a leftover username
     from the source environment authenticates as nothing and returns HTTP 401.

   **The playbooks ship pointed at the asset names below.** Either create your assets
   with these names, or keep your own names and re-point each playbook's action blocks
   to your assets in the VPE, then save: every playbook in this package is built to
   survive a save. (A save makes a manually-run playbook available on every container
   label; re-importing it restores the label.)

   | Asset name | App | Used by | Template |
   |---|---|---|---|
   | `efficientip_ddi mock` | EfficientIP DDI | `efficientip_ddi_action_test`, `efficientip_ddi_enrich` | `assets/efficientip_ddi_mock.json` |

3. **Import the playbooks** from `playbooks/*.tgz`, via *Import Playbook* on the Playbooks
   page of the target SOAR GUI. (`playbooks/source/` is the same code extracted for reading — don't
   import from there, the GUI needs the `.tgz`.)
4. **Create the `efficientip_ddi` label, then launch from a container.** Add the label first (Administration > Event Settings > Labels). `efficientip_ddi_lookup` and `efficientip_ddi_action_test` are **automation** playbooks scoped to that label, and they import **inactive**: leave them that way, nothing has to trigger them. `efficientip_ddi_enrich` is an input (`data`) playbook, which an analyst cannot launch from a container; `efficientip_ddi_lookup` is the entry point and calls it. To use them, open a container whose label is `efficientip_ddi` (Sources > Add Event, choose that label), then Playbooks > Run Playbook and pick one. Before the first run, open `efficientip_ddi_enrich` and `efficientip_ddi_action_test` in the playbook editor, select your own EfficientIP DDI asset in each action block (as shipped they point at `efficientip_ddi mock`), and save. If your SOAR does not offer an inactive playbook under Run Playbook, set it Active, but an active one also starts by itself on each new container of that label and its prompt then goes to its Run As user, so set it back to inactive afterwards.

## Verification

1. **Check the connector, then run `efficientip_ddi_action_test`.** On the EfficientIP DDI asset run *Test Connectivity*. Then open a container labelled `efficientip_ddi`, Playbooks > Run Playbook, and pick `efficientip_ddi_action_test`. It takes no input and writes three notes, one per connector action (`test connectivity`, `get ip address`, `list subnets`), each marked PASS or FAIL with the action's own message. Its test values (`10.20.30.40`, `CORP_LAN-USERS`) come from the lab mock, so against your IPAM expect `test connectivity` to PASS and the other two to report "not found" unless those values happen to exist. A "not found" still proves the call reached SOLIDserver and back. An HTTP 401, TLS or BAD REQUEST message does not.

2. **Then run `efficientip_ddi_lookup` the same way.** A prompt asks you for an IP address (answer within 30 minutes; it is also listed under Approvals). Type an IPv4 address that exists in your IPAM. The playbook runs `efficientip_ddi_enrich` on it and writes an `EfficientIP DDI Enrichment` note with hostname, subnet, space, MAC address, class and description. For an address that is not in your IPAM the note is still written, with those fields empty, and the enrich run shows as failed because the lookup action failed: expected, not a fault. A hostname, a CIDR range or no answer ends the run with an `EfficientIP DDI Lookup - not run` note and no SOLIDserver call.

If a run fails in a way the notes do not explain, check `playbook.log`/`actiond.log` on the target SOAR host. For an HTTP 401 on any action, see Diagnostics below.

## Diagnostics

`diagnostics/` holds scripts meant to be run **on the target**, because the
questions they answer are about your environment and cannot be answered from
the environment that built this package.

- **`uc17_client_bisect.py`** — Runs curl and Python against the appliance back to back, varying one thing per row, to locate an HTTP 401 that only one of the two clients sees.
- **`uc17_airgapped_probe.sh`** — Answers the API-shape questions only the real appliance can answer: real field names, whether a filter is honoured, what 'not found' returns.

All of them are read-only (every call is a GET), they read credentials from
environment variables, and they print none. Set the variables once and both
will pick them up:

```bash
sudo su - phantom
export DDI_BASE=https://<your apim host>
export DDI_CLIENT_ID=... DDI_CLIENT_SECRET=...
export DDI_USER=...      DDI_PASS=...
export DDI_CERT=/path/client.pem DDI_KEY=/path/client-key.pem
export DDI_CA=/path/ca.pem     # optional; omit to skip TLS verification
```

Run `uc17_client_bisect.py` with the SOAR Python, not the system one — a different
Python has different HTTP and TLS libraries, so a result from the system
interpreter says nothing about how the connector behaves:

```bash
/opt/phantom/bin/phenv python3 diagnostics/uc17_client_bisect.py
```

Optional, for this script only:

- `PROBE_PATH_OK` — a request path known to succeed (default: a bounded subnet list)
- `PROBE_PATH_BAD` — the path that returns 401, if you have one — runs the same matrix against it
- `PROBE_REPEATS` — attempts per row (default 3) — raise it if the fault is intermittent

Run `uc17_airgapped_probe.sh`:

```bash
bash diagnostics/uc17_airgapped_probe.sh
```

Optional, for this script only:

- `PROBE_SUBNET` — a real subnet name from your IPAM — sections needing one are skipped without it
- `PROBE_IP` — a real IPv4 address from your IPAM
- `PROBE_IP_ID` — a real ip_id from your IPAM

Send the output back to whoever maintains this use case. It is safe to share as
printed — no credential appears in it.

## What was deliberately NOT exported

- Real credential values for any `password`-type config field (see step 2 above).
- Anything not explicitly listed in Contents above.
