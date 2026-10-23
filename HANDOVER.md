# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-10-23 18:11 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi-v1.0.18.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/` | Playbook package(s): efficientip_ddi_enrich |
| `playbooks/source/` | Same playbook(s), extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `diagnostics/` | Scripts you run on the target to answer questions about it — see below |
| `docs/` | Implementation plan doc, for full design context |

## [!] Upgrading over an earlier install — read this first

These apply only if this app is already installed on the target from a
previous package. On a completely fresh target, skip to Install order.

- **Which of these applies depends on what is already installed — check the Apps list first.** Open Apps and search for `EfficientIP`. If you see **exactly one** app (named `efficientip_ddi` / `EfficientIP DDI`), you installed the 2026-08-31 package or later: this one is a **normal in-place upgrade**. Install it over the existing app — same internal identifier — and your existing asset keeps working with every credential intact. **Do not delete anything and do not re-enter any credential.** If instead you see **two** apps (an `efficientip_ddi` and an `EfficientIP DDI (Classic)`), you are still on a package older than 2026-08-31, and the note below applies to you instead.

- **Connector 1.0.18: no retry on HTTP 401 (2026-10-23).** Install connector v1.0.18 over the existing EfficientIP DDI app (same identifier: the asset keeps its credentials). Each request is now sent once. The asset fields `retry_count` and `retry_backoff` are gone: SOAR removes them from the asset during the upgrade, so there is nothing to change on it. A 401 carrying `X-Backside-Transport: FAIL FAIL` now points at the mTLS client certificate first. No playbook to re-import.

- **One playbook (2026-10-15).** `efficientip_ddi_action_test` is no longer shipped: if you imported it, deactivate it, then delete it, and use the asset's Test Connectivity button instead (Verification step 1). Where an older note below says to re-import both playbooks, re-import `efficientip_ddi_enrich` only. Re-importing it from this package is optional: only its layout changed (the shape the VPE saves), not its behaviour. If you do, point its action block at your asset again and save, set its label(s) and **Run As** user, and **activate** it.

- **Connector 1.0.17 and shorter texts (2026-10-10).** Install connector v1.0.17 over the existing EfficientIP DDI app (same identifier: the asset keeps its credentials). Its texts are shorter, and `list subnets` now declares its filter parameters (`subnet_name`, `subnet_id`, `parent_subnet_name`, `site_name`) in place of a `name` that no result carried; nothing else changes. Re-import both playbooks: their descriptions, block notes and comments are shorter, their behaviour is unchanged. After re-importing `efficientip_ddi_enrich`, point its action block at your asset again and save, set its label(s) and its **Run As** user, and **activate** it. The implementation plan in `docs/` now describes the current design only, with a Setup Guide.

- **`efficientip_ddi_enrich` is now an automation playbook (2026-10-02).** It no longer has an `ip` input or any output: it runs by itself when an artifact is created on a container with its label, and looks up the IP addresses of the new artifacts (see Verification). Re-import it so it replaces the earlier version, point its action block at your asset again and save, set its label(s) to the label of the containers to enrich (`events` as shipped), set its **Run As** user and **activate** it. A playbook of yours that launched it with an `ip` input or read its outputs must be changed: it no longer takes them. The connector is still v1.0.16 (nothing to install).

- **`efficientip_ddi_enrich` note layout changed (2026-10-02).** The table now has the columns IP, Hostname, Aliases, Subnet, Parent subnet, Lookup; Space, MAC, Class and Description moved to the **Per-IP detail** section, now one block per record with one field per line (see Verification). The re-import described in the note above covers this change too.

- **Connector v1.0.16 and `efficientip_ddi_enrich` changed (2026-10-01, later).** v1.0.16 changes only the outputs `get ip address` declares: it now lists `parent_subnet_name`, `site_class_name` and `ip_alias` (fields your SOLIDserver returns) and no longer lists `multistatus` (it does not). Install it over the existing app as an in-place upgrade (your asset and credentials stay). `efficientip_ddi_enrich` now takes one or more addresses in `ip` and writes one note with a table (see Verification); re-import it so it replaces the earlier version. **Its outputs changed.** `status` is now `success` (every address found), `partial` (some found), `not_found`, `failed` (at least one lookup failed) or `error`: `partial` is back, with this new meaning. Every other output (`hostname`, `subnet`, `space`, ...) is now a list with one entry per table row, and there are new outputs `lookup`, `aliases`, `parent_subnet` and `space_class`. A playbook of yours that reads these outputs must be changed.

- **Connector v1.0.15 and both playbooks changed (2026-10-01).** v1.0.15 is the same connector made simpler: the extra diagnostics built while chasing the HTTP 401 are gone, the `user_agent` asset field is gone (a value already saved in it is ignored), and `debug_logging` now adds one line per call (URL, status, `X-Backside-Transport`, `APIm-Debug-Trans-Id`, start of the body). It includes the v1.0.12 fix for the constant HTTP 401 on Test Connectivity (published 2026-09-30): the SOLIDserver credentials go out as `X-IPM-Username` / `X-IPM-Password` (they were `X-DDI-*`, which failed every call with "The specified document is not valid JSON data"), and `get ip address` filters on `hostaddr` (it used `host_addr`, which does not exist on the appliance). **Check the asset's `base_url`: it must include the APIM path prefix that comes before `/rest`** (for example `https://apim.example/prefix/segment`); the connector appends `/rest/<service>` to it. Install the connector over the existing app as an in-place upgrade (your asset and credentials stay), then re-import `efficientip_ddi_enrich` and `efficientip_ddi_action_test` so they replace the earlier versions. `efficientip_ddi_enrich`'s output `status` used to be `partial` for both "not in IPAM" and "lookup failed"; it is now `not_found` or `failed`. A playbook of yours that tested for `partial` must be changed. `efficientip_ddi_action_test` now takes optional `ip`/`subnet_name` inputs (see Verification). Both playbooks are built to survive a save, so re-pointing their action blocks to your own asset name is safe.

- **This package removes two connector actions: `get ip pool` and `list aliases`** (connector v1.0.11). The connector now calls only two SOLIDserver services: `ip_address_list` (`get ip address`) and `ip_block_subnet_list` (`list subnets`, `test connectivity`). After upgrading, any playbook that still calls a removed action fails at that step. That includes the `efficientip_ddi_enrich` and `efficientip_ddi_action_test` playbooks from any earlier package, so re-import both from this package so they replace the earlier versions. If you built playbooks of your own on `get ip pool` or `list aliases`, rework them before upgrading. Your asset and its credentials are not affected. The new `efficientip_ddi_enrich` also fixes its summary note: with packages from 2026-08-31 to 2026-09-09, hostname, subnet, space, MAC address and class came back empty. They are filled in now.

- **Only if the Apps list showed TWO apps.** Up to 2026-08-31 this use case shipped two: `efficientip_ddi` (SDK-based) and `EfficientIP DDI (Classic)`. The SDK app has been withdrawn, because its actions cannot be run from the connector's edit/view page in the SOAR web interface — a limitation of the platform, not of the app. The classic app is now the only one, and it has taken the `efficientip_ddi` name under a new internal identifier, so SOAR installs it as a brand-new app rather than upgrading anything. After installing: delete BOTH old apps and their assets through the web interface (Apps > the app > Delete), then create a fresh asset for the new app from the template in this package. Re-enter every credential by hand; secret fields do not carry across in the template.

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
   | `efficientip_ddi mock` | EfficientIP DDI | `efficientip_ddi_enrich` | `assets/efficientip_ddi_mock.json` |

3. **Import the playbooks** from `playbooks/*.tgz`, via *Import Playbook* on the Playbooks
   page of the target SOAR GUI. (`playbooks/source/` is the same code extracted for reading — don't
   import from there, the GUI needs the `.tgz`.)
4. **Activate automation playbooks** (`efficientip_ddi_enrich`) and set their **Run As** user per the
   implementation plan doc's Setup Guide (see `docs/`).

## Verification

1. **Test Connectivity** on the EfficientIP DDI asset. It lists one subnet (`ip_block_subnet_list`), so a pass proves `base_url`, the credentials and the client certificate. An HTTP 401 is explained in step 3.

2. **Then check `efficientip_ddi_enrich`, which now runs by itself.** It is an automation playbook: once active, it runs whenever an artifact is created on a container whose label is in its label list (`events` as shipped; set your own label(s) in the playbook settings). It looks up every value of an artifact field SOAR types as an IP address (`sourceAddress`, `destinationAddress`, ...), at most 50 per run, and writes an `EfficientIP DDI Enrichment` note: a summary line, a table with one row per IPAM record (IP, Hostname, Aliases, Subnet, Parent subnet, Lookup), then a **Per-IP detail** section: one block per record, the IP then one line each for space, space class, MAC, class, description, IP in hex and class parameters (`-` when empty); a failed lookup's block gives its message. The Lookup column reads `found`, `not found`, `failed` or `skipped`. An address held in several spaces gets one row per space (up to 5). An address a note on the container already answered (`found` or `not found`) is not looked up again; a `failed` or `skipped` one is, on the next artifact. Please try it on a test container with your label: add one artifact with an address in your IPAM in `sourceAddress` and an unused one in `destinationAddress` (expect one note: `found`, `not found`), then a second artifact with the same two addresses (expect no new note), and, if your site has any, an IPv6 address that exists in your IPAM. Whether this SOLIDserver service returns IPv6 records is not yet known, so report what you get.

3. **An HTTP 401 now says which kind it is.** The message names the gateway's `X-Backside-Transport` header. `OK OK`: SOLIDserver itself refused the credentials, so check `ddi_username`/`ddi_password` (no retry). `FAIL FAIL`: the APIM could not reach its backend; not a credential problem, so give the `APIm-Debug-Trans-Id` in the message to the APIM administrator. No header: check `client_id`/`client_secret` and the client certificate. Please note which of the three you see.

If a run fails in a way the notes do not explain, check `playbook.log`/`actiond.log` on the target SOAR host. For more detail on any failing call, tick the asset's `debug_logging`: each action result then shows one line per call (URL, status, gateway headers, start of the body).

## Diagnostics

`diagnostics/` holds scripts meant to be run **on the target**, because the
questions they answer are about your environment and cannot be answered from
the environment that built this package.

- **`uc17_airgapped_probe.sh`** — Answers the API-shape questions only the real appliance can answer: real field names, whether a filter is honoured, what 'not found' returns.

Each script is read-only (every call is a GET), reads its credentials from
environment variables and prints none. Set the variables first:

```bash
sudo su - phantom
export DDI_BASE=https://<your apim host>
export DDI_CLIENT_ID=... DDI_CLIENT_SECRET=...
export DDI_USER=...      DDI_PASS=...
export DDI_CERT=/path/client.pem DDI_KEY=/path/client-key.pem
export DDI_CA=/path/ca.pem     # optional; omit to skip TLS verification
```

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
