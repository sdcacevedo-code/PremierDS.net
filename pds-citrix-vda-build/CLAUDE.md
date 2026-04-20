# PDS Citrix VDA Build - Claude Code Project

## Purpose

Provision 9 non-persistent Citrix VDAs (FTLSCX01-09) via Citrix Cloud MCS
against FTLPVC01 (redeployed post-ransomware, April 2026). Main workflow is
in `src/build_vdas.py`. Run wrapper is `scripts/run.ps1`.

## Environment

- **Company:** Premier Destination Services (Fort Lauderdale, FL)
- **Execution host:** FTLPDC02 (192.168.1.32)
- **Domain:** PremierDestinationServices.com
- **Domain Controllers:** FTLPDC01 (192.168.1.31), FTLPDC02 (192.168.1.32)
- **Hypervisor:** FTLPVC01 (192.168.1.100) on ESX06
- **ESXi hosts:** 192.168.1.101-106 (FTLESX01-06)
- **Citrix Cloud customer:** qdz4f0ph8yaz
- **Cloud Connectors:** FTLPCC01, FTLPCC02
- **Gold Master:** FTLPGM01 (formerly FTLSCX00) on Datastore DS01 (shared NFS)
- **Snapshot:** "Sealed-Production" (BIS-F sealed)
- **Target OU:** OU=Production,OU=Citrix App Delivery,DC=PremierDestinationServices,DC=com

## Clusters

- `PremierDS-Citrix-Cluster` - ESX01-04 (VDA workload target)
- `PremierDS-Core-Cluster` - ESX05-06 (infrastructure)

## VDA Sizing (locked via Citrix Sizer)

| Setting           | Value |
|-------------------|-------|
| vCPU              | 4     |
| RAM               | 16 GB |
| Write cache disk  | 40 GB |
| Write cache mem   | 512 MB|
| Sessions per VM   | 6     |
| OS                | Windows Server 2025 |

Total capacity: 9 VDAs x 6 sessions = 54 concurrent users.

## Conventions (strict)

### Coding
- **Language:** Python for all automation. PowerShell only for Windows-native
  tasks where Python is insufficient.
- **Encoding:** Pure ASCII (0x00-0x7F) in ALL files. No em dashes, smart quotes,
  non-breaking spaces, or any Unicode character.
- **No interactive prompts:** Zero-touch execution. All credentials from
  Azure Key Vault (`DefaultAzureCredential` / managed identity).
- **Console pause:** Every entry point ends with `input("Press Enter to close...")`
  in a try/finally so nothing closes silently.

### Credentials
- **Storage:** Azure Key Vault ONLY
  - Vault: `PDS-VDI-Infrastructure-KV`
  - RG: `PDS-VDI-Infrastructure`
  - Tenant: `52f15f96-af82-4c90-a1c7-e3540f1fb06a`
  - Subscription: `5a84325e-8b13-49b4-b5f2-2780e8135327`
- **Never** hardcode secrets, use Windows Credential Manager, or any other vault.

### Logging ("Quantum Logging" - 5 destinations)
1. Console
2. Rotating file: `C:\Logs\<script>_<timestamp>.log`
3. Windows Event Log (Application, source `PDS-VDI-Automation`)
4. Splunk HEC: `FTLPUA01:8088`, index `uberagent`
5. Teams webhook (ERROR/CRITICAL/SUCCESS only)

Splunk has a circuit breaker: 3 consecutive failures -> 120s cooldown.

### Naming
- **Scripts:** `YYYYMMDD_Order_vMajor.Minor.Patch_Verb-Noun-Descriptor.py`
- **Deployment path:** `\\PremierDestinationServices.com\NETLOGON\Claude\`

### Active Directory
- Use `Get-ADComputer` / `Get-ADUser` from RSAT, or `ldap3` in Python.
- Always specify `-Server FTLPDC02` for AD queries (FTLPDC01 is currently offline).

### Known Issues / Workarounds
- `schtasks` fails on Server 2025 with "request not supported". Use `sc.exe`
  service creation to run PowerShell remotely instead.
- Azure Monitor Agent MSI blocked on Server OS (error 1603). Workaround:
  extract with `msiexec /a`, manually copy files and register service.
- Teams Incoming Webhook connector API is deprecated. Use Power Automate
  Workflows or direct Graph API channel messaging instead.
- Windows Server 2025 Start Menu pinning: use JSON via `ConfigureStartPins` CSP
  registry + copy `start2.bin` from admin profile to Default. Taskbar pins
  still use XML via GPO.
- PowerShell ISE on FTLPDC01 chokes on non-ASCII. Keep everything ASCII.

## Current Infrastructure State (April 2026)

Post-ransomware rebuild:
- vCenter FTLPVC01 redeployed on ESX06 (new MoRef IDs)
- 6 ESXi hosts re-added to vCenter, forensically verified clean
- Hosting connection in Citrix Cloud has **stale MoRef references** pointing
  at the old vCenter instance. The script detects this and rebuilds.
- MCS catalog `PremierDS-VDI-Production` may exist but VDAs are orphaned.
- IIS migration in progress (FTLPVT01 -> FTLPVT02), FTLPDC01 offline blocking
  DNS cutover. Not relevant to this script.
- SQL VM deployment in progress on FTLPVT02 / FTLQVT02. Not relevant to this script.

## Script Workflow (`src/build_vdas.py`)

Idempotent end-to-end:

1. Pull creds from AKV (Citrix API, vCenter, Splunk HEC, Teams webhook)
2. Connect to FTLPVC01 via pyVmomi. Validate:
   - Cluster `PremierDS-Citrix-Cluster` exists
   - Datastore `DS01` has free space (>= 9 * 90 GB)
   - Gold master `FTLPGM01` present with snapshot `Sealed-Production`
3. Authenticate to Citrix Cloud (customer `qdz4f0ph8yaz`), resolve site ID.
4. Check hosting connection `PremierDS-vSphere-Hosting`:
   - If state != `On` or address doesn't match redeployed FTLPVC01 -> delete + rebuild.
   - Otherwise use existing.
5. Check/create resource connection `PremierDS-Citrix-Resources` (cluster + network + DS01).
6. Check/create catalog `PremierDS-VDI-Production` with sizing 4/16/40/512
   and naming `FTLSCX##` into target OU.
7. Add 9 machines via MCS (async job, polls up to 1hr).
8. Check/create delivery group `PremierDS-Production-Desktops`, apply
   `MaxSessionsPerVm=6`.
9. Poll VDA registration for 15 min.
10. Dump final inventory + flag any unregistered VDAs.

## Azure Key Vault Secrets Required

Before running, confirm these secrets exist in `PDS-VDI-Infrastructure-KV`:

| Secret name                        | Purpose                                  |
|------------------------------------|------------------------------------------|
| `citrix-cloud-api-client-id`       | CVAD API client ID                       |
| `citrix-cloud-api-client-secret`   | CVAD API client secret                   |
| `vcenter-administrator-user`       | Usually `Administrator@vSphere.local`    |
| `vcenter-administrator-password`   | vCenter password                         |
| `splunk-hec-token`                 | `8d3d27f5-b91e-4f88-b8dd-efc7b2f27ccf`   |
| `teams-webhook-vdi-alerts`         | Power Automate workflow URL              |

Create Citrix Cloud API client at: https://citrix.cloud.com -> Identity and
Access Management -> API Access.

## Running

```powershell
# From FTLPDC02
cd C:\Scripts\pds-citrix-vda-build
.\scripts\run.ps1
```

Or directly:

```powershell
python .\src\build_vdas.py
```

## Common Tasks

- **Add more VDAs:** Change `vda_count` in the `CONFIG` dict in `src/build_vdas.py`
  and re-run. Script is idempotent - only adds the delta.
- **Change sizing:** Edit `vda_cpu_count`, `vda_memory_mb`, `vda_wc_disk_gb`,
  `vda_wc_memory_mb` in CONFIG. Note: sizing changes only apply to new VMs.
- **Rebuild hosting connection only:** Manually delete the connection in Citrix
  Studio and re-run.
- **Validate without provisioning:** Comment out the `cc.add_machines_to_catalog`
  call in `provision_vdas()` for a dry-run of the validation chain.

## Troubleshooting

### VDAs not registering
1. DNS: `nslookup FTLPCC01.PremierDestinationServices.com` from the VDA
2. Firewall: ports 80, 443, 1494, 2598 VDA -> Cloud Connectors
3. BrokerAgent service: `Get-Service BrokerAgent` on the VDA
4. AD computer object: `Get-ADComputer FTLSCX01 -Server FTLPDC02`

### Citrix API 401/403
- Token expired (1hr lifetime) - script re-authenticates per run, just re-run
- Client secret rotated - update AKV secret

### MCS provisioning job fails
- Datastore DS01 space: `Get-Datastore DS01 | Select FreeSpaceGB`
- Gold master powered off: MUST be off during MCS provisioning
- AD OU permissions: MCS service account needs Create Computer Objects on target OU

## Do Not

- Do not ask for clarification before implementing - infer intent from context.
- Do not use Unicode anywhere (em dashes, smart quotes, emoji, box drawing).
- Do not hardcode passwords - always AKV.
- Do not run scripts on FTLPDC01 (offline). Use FTLPDC02.
- Do not modify gold master FTLPGM01 directly. Build new version in isolated VM.
- Do not suggest Windows Credential Manager - we use AKV exclusively.
- Do not use `schtasks` on Server 2025 - use `sc.exe` service creation.

## Related Files

- `\\PremierDestinationServices.com\NETLOGON\Claude\AutoConfig-uberAgent.ps1`
- `\\PremierDestinationServices.com\NETLOGON\Claude\BGInfo-Startup.vbs`
- `PDS-VDI-Overlay-v8_0.ps1`
- `PDS-Citrix-Sizer-v3.html`
- `FTLSCX00-Gold-Master-Handoff-Document.md`
