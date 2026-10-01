# UC17 — EfficientIP DDI Enrichment — Air-Gapped Handover Package

Generated 2026-10-01 19:49 UTC from `efficientip_ddi_enrich` (source env: `soar8`).

This package is self-contained — everything needed to deploy this use case by hand
in an environment with no network access back to this repo or to `soar8`.

*(Version française : `HANDOVER_french.md` dans ce même dossier.)*

## Contents

| Path | What |
|------|------|
| `connectors/` | Connector app package(s): efficientip_ddi-v1.0.16.tgz |
| `connectors/source/` | Same connector(s), extracted — for reading, not for import |
| `playbooks/*.tgz` (PBs) | efficientip_ddi_enrich, efficientip_ddi_action_test |
| `playbooks/source/` | Same CFs/playbooks, extracted — for reading, not for import |
| `assets/*.json` | Asset config templates (credentials redacted — see below) |
| `diagnostics/` | Scripts you run on the target to answer questions about it — see below |
| `docs/` | Implementation plan doc, for full design context |

## [!] Upgrading over an earlier install — read this first

These apply only if this app is already installed on the target from a
previous package. On a completely fresh target, skip to Install order.

- **Which of these applies depends on what is already installed — check the Apps list first.** Open Apps and search for `EfficientIP`. If you see **exactly one** app (named `efficientip_ddi` / `EfficientIP DDI`), you installed the 2026-08-31 package or later: this one is a **normal in-place upgrade**. Install it over the existing app — same internal identifier — and your existing asset keeps working with every credential intact. **Do not delete anything and do not re-enter any credential.** If instead you see **two** apps (an `efficientip_ddi` and an `EfficientIP DDI (Classic)`), you are still on a package older than 2026-08-31, and the note below applies to you instead.

- **Connector v1.0.16 and `efficientip_ddi_enrich` changed (2026-10-01, later).** v1.0.16 changes only the outputs `get ip address` declares: it now lists `parent_subnet_name`, `site_class_name` and `ip_alias` (fields your SOLIDserver returns) and no longer lists `multistatus` (it does not). Install it over the existing app as an in-place upgrade (your asset and credentials stay). `efficientip_ddi_enrich` now takes one or more addresses in `ip` and writes one note with a table (see Verification); re-import it so it replaces the earlier version. **Its outputs changed.** `status` is now `success` (every address found), `partial` (some found), `not_found`, `failed` (at least one lookup failed) or `error`: `partial` is back, with this new meaning. Every other output (`hostname`, `subnet`, `space`, ...) is now a list with one entry per table row, and there are new outputs `lookup`, `aliases`, `parent_subnet` and `space_class`. A playbook of yours that reads these outputs must be changed.

- **Connector v1.0.15 and both playbooks changed (2026-10-01).** v1.0.15 is the same connector made simpler: the extra diagnostics built while chasing the HTTP 401 are gone, the `user_agent` asset field is gone (a value already saved in it is ignored), and `debug_logging` now adds one line per call (URL, status, `X-Backside-Transport`, `APIm-Debug-Trans-Id`, start of the body). It includes the v1.0.12 fix for the constant HTTP 401 on Test Connectivity (published 2026-09-30): the SOLIDserver credentials go out as `X-IPM-Username` / `X-IPM-Password` (they were `X-DDI-*`, which failed every call with "The specified document is not valid JSON data"), and `get ip address` filters on `hostaddr` (it used `host_addr`, which does not exist on the appliance). **Check the asset's `base_url`: it must include the APIM path prefix that comes before `/rest`** (for example `https://apim.example/prefix/segment`); the connector appends `/rest/<service>` to it. Install the connector over the existing app as an in-place upgrade (your asset and credentials stay), then re-import `efficientip_ddi_enrich` and `efficientip_ddi_action_test` so they replace the earlier versions. `efficientip_ddi_enrich`'s output `status` used to be `partial` for both "not in IPAM" and "lookup failed"; it is now `not_found` or `failed`. A playbook of yours that tested for `partial` must be changed. `efficientip_ddi_action_test` now takes optional `ip`/`subnet_name` inputs (see Verification). Both playbooks are built to survive a save, so re-pointing their action blocks to your own asset name is safe.

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
4. **Nothing to activate.** Every playbook in this package is an input (`data`)
   playbook — there is no automation trigger to enable and no **Run As** user to set.
   You run these by hand from a container: open the container, then Playbooks > Run
   Playbook and pick the one you want. See the implementation plan doc in `docs/`.

## Verification

1. **Run `efficientip_ddi_action_test` first, with values from your IPAM.** Open any container, then Playbooks > Run Playbook and pick it. It asks for two optional inputs: `ip`, an address that exists in your IPAM, and `subnet_name`, the NAME of one of your subnets (a label, not a CIDR). Left blank they fall back to the lab mock's values (`10.20.30.40`, `CORP_LAN-USERS`), which your IPAM does not hold, so those two checks then FAIL with "not found". It writes two notes, one per connector action (`get ip address`, `list subnets`), each PASS or FAIL with the action's own message. Expect two PASS. It does not run `test connectivity`: use the asset's own Test Connectivity button for that. A "not found" still proves the call reached SOLIDserver and back. An HTTP 401, TLS or BAD REQUEST message does not.

2. **Then run `efficientip_ddi_enrich` the same way.** It reads no artifact. Run Playbook asks for its one input, `ip`: one or more addresses, separated by commas, spaces or new lines (at most 50). It writes an `EfficientIP DDI Enrichment` note: a summary line, a table with one row per IPAM record (IP, Hostname, Aliases, Subnet, Space, MAC, Class, Description, Lookup), then a **Per-IP detail** list (parent subnet, space class, IP in hex, class parameters, and the message of any failed lookup). The Lookup column reads `found`, `not found`, `failed`, `invalid address` or `skipped`. An address held in several spaces gets one row per space (up to 5). Its output `status` says what happened: `success` (every address found), `partial` (some found), `not_found` (none found; the lookups worked), `failed` (at least one lookup itself failed: read its detail line), `error` (no valid address). A run where a lookup failed or found nothing may show as failed in the run list; the note is what to read. Please try one run with an address in your IPAM, an unused one and a typo, for example `<your IP>, <unused IP>, 10.0.0.999` (expect `found`, `not found`, `invalid address`, status `partial`), and, if your site has any, an IPv6 address that exists in your IPAM. Whether this SOLIDserver service returns IPv6 records is not yet known, so report what you get.

3. **An HTTP 401 now says which kind it is.** The message names the gateway's `X-Backside-Transport` header. `OK OK`: SOLIDserver itself refused the credentials, so check `ddi_username`/`ddi_password` (no retry). `FAIL FAIL`: the APIM could not reach its backend; not a credential problem, so give the `APIm-Debug-Trans-Id` in the message to the APIM administrator. No header: check `client_id`/`client_secret` and the client certificate. Please note which of the three you see.

If a run fails in a way the notes do not explain, check `playbook.log`/`actiond.log` on the target SOAR host. For more detail on any failing call, tick the asset's `debug_logging`: each action result then shows one line per call (URL, status, gateway headers, start of the body).

## Diagnostics

`diagnostics/` holds scripts meant to be run **on the target**, because the
questions they answer are about your environment and cannot be answered from
the environment that built this package.

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
