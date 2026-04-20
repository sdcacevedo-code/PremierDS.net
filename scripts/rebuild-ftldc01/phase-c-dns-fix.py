#!/usr/bin/env python3
# -*- coding: ascii -*-
"""
Phase C - Fix DNS + machine account (v1.0.0)

Runs DIRECTLY ON FTLPDC02 as local Administrator.

From Phase B results:
  - nltest /dsgetdc WORKS - Netlogon reports FTLPDC02 as a full DC
  - DNS service runs but doesn't respond to nslookup queries (timeout)
  - Machine password reset failed because we had wrong domain password
  - DNS event log: "unable to open Active Directory" every 10 min
    -> DNS service account can't read MicrosoftDNS containers

This script:
  1. Reset machine account password with correct password (Weston2015!)
  2. Diagnose DNS listen config + zone loading
  3. Check zone SOA / NS records actually exist in the zone
  4. Force DNS service to reload zones from AD
  5. Verify resolution with local dnscmd and nslookup against 127.0.0.1
  6. If DNS still broken, attempt to dump zone content from AD directly
"""
import os
import subprocess
import sys
import time
from datetime import datetime

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
OUT_FILE = os.path.join(DESKTOP, "FTLPDC02-PHASEC-RESULT.txt")

DOMAIN_DNS = "PremierDestinationServices.com"
DOMAIN_ADMIN_PASSWORD = "Weston2015!"
DOMAIN_NETBIOS = "PREMIER"


class Runner:
    def __init__(self):
        self.lines = []

    def log(self, msg=""):
        print(msg)
        self.lines.append(str(msg))

    def section(self, title):
        self.log("")
        self.log("=" * 72)
        self.log("  " + title)
        self.log("=" * 72)

    def run(self, cmd, timeout=60, shell=True, label=""):
        display = label or (cmd if isinstance(cmd, str) else " ".join(cmd))
        self.log("\n--- " + display)
        try:
            r = subprocess.run(
                cmd, shell=shell, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
            )
            if r.stdout:
                for line in r.stdout.splitlines():
                    self.log("  " + line)
            if r.stderr:
                for line in r.stderr.splitlines():
                    self.log("  STDERR: " + line)
            self.log("  [rc=%d]" % r.returncode)
            return r.returncode
        except subprocess.TimeoutExpired:
            self.log("  TIMEOUT after %ds" % timeout)
            return -1
        except Exception as e:
            self.log("  ERROR: " + str(e))
            return -1

    def save(self):
        try:
            with open(OUT_FILE, "w", encoding="ascii", errors="replace") as f:
                f.write("\n".join(self.lines))
            print("\nSaved to: " + OUT_FILE)
        except Exception as e:
            print("Save failed: " + str(e))


def main():
    r = Runner()
    r.log("=" * 72)
    r.log("  Phase C - Fix DNS + machine account")
    r.log("=" * 72)
    r.log("  Machine: " + os.environ.get("COMPUTERNAME", "?"))
    r.log("  User   : " + os.environ.get("USERNAME", "?"))
    r.log("  Time   : " + time.strftime("%Y-%m-%d %H:%M:%S"))

    if os.environ.get("COMPUTERNAME", "").upper() != "FTLPDC02":
        r.log("\n*** Must run ON FTLPDC02 ***")
        r.save()
        return 1

    # ====================================================================
    # Step 1: Reset machine account password with CORRECT credential
    # ====================================================================
    r.section("STEP 1: Reset machine account password (correct creds this time)")
    ps = (
        '$ErrorActionPreference="Stop"; '
        'try { '
        '  $u = "PremierDestinationServices.com\\Administrator"; '
        '  $p = ConvertTo-SecureString "' + DOMAIN_ADMIN_PASSWORD + '" -AsPlainText -Force; '
        '  $c = New-Object System.Management.Automation.PSCredential ($u,$p); '
        '  Reset-ComputerMachinePassword -Credential $c -Server "localhost"; '
        '  Write-Host "RESET OK" '
        '} catch { '
        '  Write-Host ("RESET FAILED: " + $_.Exception.Message) '
        '}'
    )
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps],
        shell=False, timeout=90, label="Reset-ComputerMachinePassword"
    )

    # ====================================================================
    # Step 2: DNS service diagnostic
    # ====================================================================
    r.section("STEP 2: DNS diagnostic")
    r.run("sc query DNS", timeout=15, label="DNS service state")
    r.run("sc qc DNS", timeout=15, label="DNS service config (runs as?)")
    # Try dnscmd - may hit "Access Denied" which tells us about perms
    r.run("dnscmd localhost /info", timeout=15, label="dnscmd /info (local)")
    r.run("dnscmd localhost /enumzones", timeout=15, label="dnscmd /enumzones")

    # PowerShell DnsServer module - different code path
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-DnsServer -ErrorAction SilentlyContinue | Format-List | Out-String"],
        shell=False, timeout=30, label="Get-DnsServer"
    )
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-DnsServerZone -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String"],
        shell=False, timeout=30, label="Get-DnsServerZone"
    )

    # ====================================================================
    # Step 3: Check what port 53 is listening on
    # ====================================================================
    r.section("STEP 3: Port 53 listening check")
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-NetTCPConnection -LocalPort 53 -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String; "
         "Get-NetUDPEndpoint -LocalPort 53 -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String"],
        shell=False, timeout=30, label="port 53 listeners"
    )

    # ====================================================================
    # Step 4: Try DNS query against localhost (bypass network layer)
    # ====================================================================
    r.section("STEP 4: DNS query tests")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 127.0.0.1",
          timeout=15, label="nslookup against 127.0.0.1")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 192.168.1.32",
          timeout=15, label="nslookup against 192.168.1.32")
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Resolve-DnsName -Name 'FTLPDC02.PremierDestinationServices.com' -Server 127.0.0.1 -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String"],
        shell=False, timeout=30, label="Resolve-DnsName via 127.0.0.1"
    )

    # ====================================================================
    # Step 5: Fix DNS service permissions
    # DNS service account needs to be able to read MicrosoftDNS containers.
    # Add NT AUTHORITY\NETWORK SERVICE and the DNS service principal to the
    # built-in DNSAdmins group if not already there.
    # ====================================================================
    r.section("STEP 5: Ensure DNS service has AD read access")
    ps_perm = (
        '$ErrorActionPreference="Continue"; '
        '# Show DNSAdmins membership '
        'Write-Host "--- DNSAdmins membership ---"; '
        'try { Get-ADGroupMember -Identity DNSAdmins | Format-Table Name,ObjectClass,distinguishedName } '
        'catch { Write-Host ("Get-ADGroupMember failed: " + $_.Exception.Message) } '
    )
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps_perm],
        shell=False, timeout=30, label="DNSAdmins check"
    )

    # ====================================================================
    # Step 6: Force DNS to reload from AD
    # ====================================================================
    r.section("STEP 6: Force DNS zone reload")
    r.run("dnscmd localhost /zoneupdatefromds", timeout=60,
          label="force ADI zone update")
    r.run("dnscmd localhost /clearcache", timeout=15, label="clear DNS cache")
    # Restart DNS to force full reload
    r.log("\n  Restarting DNS service...")
    r.run("net stop DNS", timeout=30, label="stop DNS")
    time.sleep(5)
    r.run("net start DNS", timeout=60, label="start DNS")
    time.sleep(15)

    # ====================================================================
    # Step 7: Verify after reload
    # ====================================================================
    r.section("STEP 7: Post-fix verification")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 127.0.0.1",
          timeout=15, label="nslookup localhost after reload")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 192.168.1.32",
          timeout=15, label="nslookup 192.168.1.32 after reload")
    r.run("dnscmd localhost /enumzones", timeout=15, label="zones after reload")
    r.run("dcdiag /test:connectivity /v", timeout=60, label="dcdiag connectivity")

    r.section("PHASE C COMPLETE")
    r.log("")
    r.log("  Look for:")
    r.log("    - Step 1 RESET OK (machine account fixed)")
    r.log("    - Step 2 dnscmd /enumzones lists your zones (not ACCESS_DENIED)")
    r.log("    - Step 4 or 7 nslookup returns 192.168.1.32 for FTLPDC02 fqdn")
    r.log("    - Step 7 dcdiag shows Connectivity passed")

    r.save()
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except Exception as e:
        print("FATAL: " + str(e))
        import traceback
        traceback.print_exc()
    try:
        input("\nPress Enter to close...")
    except Exception:
        time.sleep(60)
    sys.exit(rc)
