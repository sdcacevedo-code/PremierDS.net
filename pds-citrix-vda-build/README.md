# PDS Citrix VDA Build

Provisions 9 non-persistent Citrix VDAs (FTLSCX01-09) via Citrix Cloud MCS
against FTLPVC01. Rebuilds stale hosting connections from ransomware recovery.

## Quick start

```powershell
# On FTLPDC02
cd C:\Scripts\pds-citrix-vda-build
pip install -r requirements.txt
.\scripts\run.ps1
```

## Prereqs

1. Python 3.10+ on FTLPDC02 (check with `where.exe python`)
2. AKV secrets populated (see `CLAUDE.md` for list)
3. Azure login on FTLPDC02: `az login` (or managed identity attached)
4. Citrix Cloud API client created at https://citrix.cloud.com
5. Target AD OU exists with MCS service account delegation
6. Gold master `FTLPGM01` powered off with snapshot `Sealed-Production`

## Files

| Path                                    | What it does                                    |
|-----------------------------------------|-------------------------------------------------|
| `CLAUDE.md`                             | Project context for Claude Code                 |
| `src/build_vdas.py`                     | Main provisioning script                        |
| `scripts/run.ps1`                       | PowerShell wrapper with pip install + logging   |
| `requirements.txt`                      | Python dependencies                             |
| `docs/runbook.md`                       | Pre-flight, execution, rollback                 |
| `.gitignore`                            | Excludes logs, venv, pyc                        |

## Config

All configuration is in the `CONFIG` dict at the top of `src/build_vdas.py`.
Change values there, not via env vars.

## Support

Logs: `C:\Logs\Build-Citrix-VDAs-MCS-Provision_*.log`
Splunk: `index=uberagent sourcetype=pds:vdi:automation`
