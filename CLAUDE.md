# PremierDS.net — Citrix VDA Build Context

Drop-in context for Claude Code sessions working on the Citrix VDA build-out
for Premier Destination Services. Claude Code auto-loads `CLAUDE.md` from the
repo root; you can also paste this into any new chat.

## Organization

- **Org**: Premier Destination Services
- **Domain**: PremierDestinationServices.com
- **Site**: Fort Lauderdale, FL
- **Admin**: Sam D'Arrigo
- **Automation share**: `\\PremierDestinationServices.com\NETLOGON\Claude`

## Current Task

Build / bring online the Citrix VDA fleet. As of the last inventory export
(`00_Summary.json`, 2026-01-14): **0 / 18 VDAs online**.

Sub-goals (tick as completed):

- [ ] Provision or repair 15 Production VDAs: `FTLCTX01`–`FTLCTX15`
- [ ] Provision or repair 3 Session Hosts: `FTLSCX01`–`FTLSCX03`
- [ ] Register VDAs with Cloud Connectors `FTLPCC01` / `FTLPCC02`
- [ ] Create / validate Machine Catalogs, Delivery Groups, Policies
  (all three arrays are currently empty in `01_Citrix_VDI_Complete.json`)
- [ ] Confirm FSLogix profile containers mount on each VDA
- [ ] Validate Microsoft Teams VDI optimization + uberAgent telemetry

## Inventory Snapshot

### Citrix
| Role            | Host(s)                  | Status  |
|-----------------|--------------------------|---------|
| Cloud Connector | FTLPCC01, FTLPCC02       | Online  |
| Production VDA  | FTLCTX01–FTLCTX15        | Offline |
| Session Host    | FTLSCX01–FTLSCX03        | Offline |

- Cloud Connector OS: Windows Server 2025 Datacenter, 1 vCPU / 8 GB RAM
- Machine Catalogs, Delivery Groups, Applications, Policies, Resource
  Locations: **all empty** — need to be created.

### Supporting Infra
- **Active Directory**: 2 DCs, 416 users (335 enabled), 141 computers, 224 GPOs
- **VMware**: 6 ESXi hosts, ~22 VMs (see `02_VMware_ESXi_Complete.json`,
  `ESX06.json`)
- **Apps**: FSLogix (configured), Teams (VDI-optimized), uberAgent→Splunk,
  TeamViewer

## Key Files

| File                              | What it contains                          |
|-----------------------------------|-------------------------------------------|
| `00_Summary.json`                 | Top-level infra rollup                    |
| `01_Citrix_VDI_Complete.json`     | Citrix inventory (VDAs, connectors, …)    |
| `01_Citrix_VDA_Servers.csv`       | VDA list (malformed — PS object dump)     |
| `01_Citrix_Cloud_Connectors.csv`  | Connector list                            |
| `02_VMware_ESXi_Complete.json`    | vSphere inventory                         |
| `03_ActiveDirectory_Complete.json`| AD users, groups, OUs, GPOs               |
| `04_FSLogix_Complete.json`        | FSLogix config                            |
| `05_Applications_Complete.json`   | Installed/published apps                  |
| `06_Network_Complete.json`        | Network / subnet info                     |
| `07_Monitoring_Automation_Complete.json` | Monitoring + automation state      |

> Note: most JSON files are UTF-16 LE with a BOM (PowerShell
> `Out-File` default). Read with `Get-Content -Encoding Unicode` or
> `iconv -f UTF-16 -t UTF-8`. The `01_Citrix_VDA_Servers.csv` is a
> hashtable dump and should be regenerated via
> `Select-Object Name,FQDN,Type,Status,LastCheck | Export-Csv`.

## Conventions

- Hostnames: `FTL` (Fort Lauderdale) + role code + 2-digit index
  - `CTX` = Citrix VDA, `SCX` = Session host Citrix, `PCC` = Cloud Connector
- PowerShell scripts live under the NETLOGON `Claude` share (110+ scripts).
- Prefer idempotent PowerShell; log to the same export path pattern
  `…\InfrastructureExports\yyyyMMdd_HHmmss`.

## Preferred Build Approach

1. **Base image** on ESXi (Server 2022/2025) with:
   Citrix VDA agent, FSLogix, Teams VDI pack, uberAgent, TeamViewer host.
2. **Machine Creation Services (MCS)** from Citrix Cloud → pointed at the
   two Cloud Connectors as the Resource Location.
3. **Machine Catalog** per workload (single-session Win11 for CTX,
   multi-session Server for SCX).
4. **Delivery Group** + **Application** publishing driven by the data in
   `05_Applications_Complete.json`.
5. **GPOs / Citrix Policies**: reuse AD GPOs where already present
   (224 GPOs in the export); add Citrix policies via Studio or
   `Set-BrokerAccessPolicyRule` / `New-BrokerMachineCommand`.

## Open Questions (to confirm before building)

- VDA version target? (CR vs LTSR, e.g. 2402 LTSR CU1)
- Single-session (Win 11) vs multi-session (Server 2022/2025) split per host
- MCS, PVS, or manual provisioning?
- Is this Citrix Cloud (DaaS) or on-prem Delivery Controllers?
  (Presence of Cloud Connectors suggests Cloud / DaaS.)
- Storefront URL / Workspace URL for end-user access?

---
_Last updated: 2026-04-20_
