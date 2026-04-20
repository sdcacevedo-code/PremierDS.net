#!/usr/bin/env python3
"""
Post-reboot DNS + machine-account check for FTLPDC02.

Read-mostly (only performs one mutating action: ipconfig /registerdns,
which is safe and idempotent).

Reports:
  1. Is DNS service answering queries on 127.0.0.1?
  2. Does the domain itself resolve?
  3. Does FTLPDC02's A record exist?
  4. Is the zone AD-integrated or primary standalone?
  5. What's actually inside the zone?
  6. Secure-channel state (nltest /sc_query)
  7. dcdiag Connectivity test result

Run on FTLPDC02 as local Administrator:
    cd /d C:\\Users\\Administrator.PREMIER\\Desktop\\premierds.net
    git pull
    python scripts\\rebuild-ftldc01\\post-reboot-check.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
OUT_FILE = DESKTOP / "POST-REBOOT-CHECK.txt"
DOMAIN = "PremierDestinationServices.com"
HOST = "FTLPDC02"
PROD_IP = "192.168.1.32"


class Runner:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, msg: str = "") -> None:
        print(msg)
        self.lines.append(msg)

    def section(self, title: str) -> None:
        self.log("")
        self.log("=" * 72)
        self.log(f"  {title}")
        self.log("=" * 72)

    def run(self, cmd, label: str = "", timeout: int = 30, shell: bool = False) -> int:
        display = label or (cmd if isinstance(cmd, str) else " ".join(cmd))
        self.log(f"\n--- {display}")
        try:
            r = subprocess.run(
                cmd, shell=shell, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
            )
            for line in (r.stdout or "").splitlines():
                self.log(f"  {line}")
            for line in (r.stderr or "").splitlines():
                self.log(f"  STDERR: {line}")
            self.log(f"  [rc={r.returncode}]")
            return r.returncode
        except subprocess.TimeoutExpired:
            self.log(f"  TIMEOUT after {timeout}s")
            return -1
        except Exception as exc:
            self.log(f"  ERROR: {exc}")
            return -1

    def ps(self, command: str, label: str = "", timeout: int = 30) -> int:
        return self.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", command],
            label=label, timeout=timeout,
        )

    def save(self) -> None:
        try:
            OUT_FILE.write_text("\n".join(self.lines), encoding="utf-8")
            print(f"\nSaved to: {OUT_FILE}")
        except Exception as exc:
            print(f"Save failed: {exc}")


def main() -> int:
    r = Runner()
    r.log("=" * 72)
    r.log("  Post-reboot DNS + machine-account check")
    r.log("=" * 72)
    r.log(f"  Host : {os.environ.get('COMPUTERNAME', '?')}")
    r.log(f"  User : {os.environ.get('USERNAME', '?')}")
    r.log(f"  Time : {datetime.now().isoformat(timespec='seconds')}")

    if os.environ.get("COMPUTERNAME", "").upper() != HOST:
        r.log(f"  [FATAL] Must run on {HOST}")
        r.save()
        return 1

    r.section("STEP 1: Force DNS registration (dynamic update)")
    r.run("ipconfig /registerdns", label="ipconfig /registerdns", shell=True, timeout=20)
    r.log("  Waiting 15s for Netlogon/DNS to settle...")
    time.sleep(15)

    r.section("STEP 2: Resolve via own DNS (127.0.0.1)")
    r.run(f"nslookup {HOST}.{DOMAIN} 127.0.0.1", label="nslookup host", shell=True, timeout=15)
    r.run(f"nslookup {DOMAIN} 127.0.0.1", label="nslookup domain", shell=True, timeout=15)
    r.run(f"nslookup -type=SRV _ldap._tcp.{DOMAIN} 127.0.0.1",
          label="nslookup SRV _ldap._tcp", shell=True, timeout=15)
    r.run(f"nslookup -type=SRV _kerberos._tcp.{DOMAIN} 127.0.0.1",
          label="nslookup SRV _kerberos._tcp", shell=True, timeout=15)

    r.section("STEP 3: List DNS zones + integration status")
    r.ps("Get-DnsServerZone | Format-Table ZoneName,ZoneType,IsDsIntegrated,IsAutoCreated,DynamicUpdate | Out-String",
         label="Get-DnsServerZone", timeout=30)

    r.section(f"STEP 4: List records in {DOMAIN} zone")
    r.ps(f"Get-DnsServerResourceRecord -ZoneName '{DOMAIN}' -ErrorAction Stop | "
         "Format-Table HostName,RecordType,@{N='Data';E={$_.RecordData | ForEach-Object {$_.PSObject.Properties | "
         "Where-Object Name -notmatch '^(Type|MemberType|TypeName)$' | ForEach-Object {$_.Value}} -join ','}} | Out-String",
         label="records in forward zone", timeout=45)

    r.section("STEP 5: Machine-account secure channel")
    r.run("nltest /sc_query:PremierDestinationServices.com",
          label="nltest /sc_query", shell=True, timeout=20)
    r.run("nltest /dsgetdc:PremierDestinationServices.com",
          label="nltest /dsgetdc", shell=True, timeout=20)
    r.run("klist -li 0x3e7", label="computer Kerberos tickets", shell=True, timeout=15)

    r.section("STEP 6: dcdiag connectivity")
    r.run("dcdiag /test:connectivity", label="dcdiag", shell=True, timeout=60)

    r.section("STEP 7: Directory Service + DNS Server event log (last 10)")
    r.ps("Get-WinEvent -LogName 'Directory Service' -MaxEvents 10 -ErrorAction SilentlyContinue | "
         "Select-Object TimeCreated,Id,LevelDisplayName,@{N='Msg';E={$_.Message.Split([Environment]::NewLine)[0]}} | "
         "Format-Table -Wrap | Out-String", label="Directory Service log", timeout=30)
    r.ps("Get-WinEvent -LogName 'DNS Server' -MaxEvents 10 -ErrorAction SilentlyContinue | "
         "Select-Object TimeCreated,Id,LevelDisplayName,@{N='Msg';E={$_.Message.Split([Environment]::NewLine)[0]}} | "
         "Format-Table -Wrap | Out-String", label="DNS Server log", timeout=30)

    r.section("VERDICT")
    r.log("")
    r.log("  Look for in the output above:")
    r.log(f"  1. Step 2: '{HOST}.{DOMAIN}' resolves to {PROD_IP}")
    r.log("     -> Yes: DNS + dynamic update are working")
    r.log("     -> No:  Netlogon update is failing")
    r.log("  2. Step 3: IsDsIntegrated=True on main zone")
    r.log("     -> Yes + records missing = DNS cannot read AD -> Phase E needed")
    r.log("     -> False = zone is file-backed (less good but simpler to edit)")
    r.log("  3. Step 4: Does NOT say 'Access Denied'")
    r.log("     -> Yes (lists records) = DNS management permissions restored")
    r.log("     -> Access Denied = machine account still broken")
    r.log("  4. Step 5: nltest /sc_query returns Success")
    r.log("     -> Yes = secure channel OK, we can promote FTLPDC01")
    r.log("     -> Fail = still blocked, need to repair or convert zones")

    r.save()
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
    try:
        input("\nPress Enter to close...")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(rc)
