# Runbook: Build Citrix VDAs (Post-Ransomware)

## Overview

Rebuilds FTLSCX01-09 non-persistent VDAs via Citrix Cloud MCS after the
April 2026 ransomware recovery. vCenter FTLPVC01 was redeployed, which means
the Citrix Cloud hosting connection has stale MoRef IDs.

## Pre-flight

### On FTLPVC01
- [ ] vCenter reachable at `https://192.168.1.100`
- [ ] Cluster `PremierDS-Citrix-Cluster` shows 4 hosts (ESX01-04)
- [ ] Datastore `DS01` has >= 810 GB free (9 VDAs * ~90 GB)
- [ ] `FTLPGM01` powered OFF
- [ ] `FTLPGM01` has snapshot named exactly `Sealed-Production`

### On FTLPDC02
- [ ] Python 3.10+ installed (`where.exe python` returns a path)
- [ ] `az login` completed OR managed identity attached
- [ ] Can resolve `api-us.cloud.com` (outbound 443)
- [ ] Can reach FTLPVC01 on 443
- [ ] Can reach AKV on 443

### In Azure Key Vault PDS-VDI-Infrastructure-KV
- [ ] `citrix-cloud-api-client-id`
- [ ] `citrix-cloud-api-client-secret`
- [ ] `vcenter-administrator-user`
- [ ] `vcenter-administrator-password`
- [ ] `splunk-hec-token`
- [ ] `teams-webhook-vdi-alerts`

### In Active Directory
- [ ] OU `OU=Production,OU=Citrix App Delivery,DC=PremierDestinationServices,DC=com` exists
- [ ] Citrix MCS service account has Create Computer Objects on that OU
- [ ] No existing AD computer objects named FTLSCX01-09 (delete if present)

### In Citrix Cloud
- [ ] API client created at Identity and Access Management -> API Access
- [ ] Cloud Connectors FTLPCC01/FTLPCC02 show as Connected

## Execution

```powershell
cd C:\Scripts\pds-citrix-vda-build
.\scripts\run.ps1
```

Expected runtime: 30-60 minutes (dominated by MCS VM provisioning).

## Expected Output Sequence

1. Azure Key Vault connection (< 5s)
2. vCenter validation (< 10s)
3. Citrix Cloud auth (< 5s)
4. Hosting connection rebuild (30-60s if needed)
5. Resource connection create (20-30s if needed)
6. Catalog create (10-20s)
7. **MCS machine provisioning (20-45 min for 9 VMs)**
8. Delivery group create + bind (20-30s)
9. Registration wait (up to 15 min)
10. Final inventory dump

## Success Criteria

Final inventory section shows all 9 VDAs:

```
FTLSCX01                       RegState=Registered   PowerState=On       InMaint=False
FTLSCX02                       RegState=Registered   PowerState=On       InMaint=False
...
FTLSCX09                       RegState=Registered   PowerState=On       InMaint=False
```

## Post-Flight Validation

```powershell
# From FTLPDC02, verify AD computer objects
1..9 | % { Get-ADComputer "FTLSCX0$_" -Server FTLPDC02 -Properties Created, IPv4Address |
    Select Name, Created, IPv4Address }

# From Citrix Cloud Studio, verify:
# - Machine Catalogs -> PremierDS-VDI-Production shows 9 machines
# - Delivery Groups -> PremierDS-Production-Desktops shows 9 machines, 54 sessions available
```

## Rollback

If provisioning fails partway:

```powershell
# Delete partial catalog via Citrix Cloud Studio UI, then:
Get-ADComputer -Filter "Name -like 'FTLSCX0*'" -Server FTLPDC02 |
    Where Name -ne "FTLSCX00" | Remove-ADComputer -Confirm:$false

# Delete VMs from vCenter (manual via vSphere client or pyVmomi)
# Re-run build_vdas.py
```

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` on Citrix auth | Bad client ID/secret in AKV | Regenerate at citrix.cloud.com, update AKV |
| `404 Not Found` on catalog endpoint | Wrong site ID | Script auto-resolves, check `/me` response |
| vCenter `SSLError` | Expired vCenter cert | Re-issue from internal CA |
| MCS job hangs at 90% | DS01 out of space | `Get-Datastore DS01`, free space, retry |
| VDA not registering | DNS broken on VDA | Verify DHCP option 006 points to FTLPDC02 |
| `Snapshot 'Sealed-Production' not found` | Snapshot renamed | Update `CONFIG["gold_master_snapshot"]` |
