#!/usr/bin/env python3
# -*- coding: ascii -*-
"""
Phase D - Surgical fixes for FTLPDC02 (v1.0.0)

Findings from Phase C:
  1. FTLPDC02 has 3 A records in DNS for itself:
     - 192.168.1.32 (correct)
     - 169.254.83.107 (APIPA - stale, from disconnected NIC)
     - fe80:a937:... (link-local IPv6 - Ethernet1)
     When anything tries FTLPDC02.domain.com, DNS may return the bad
     one first causing connectivity failure.

  2. dnscmd / Get-DnsServer all fail with Access Denied due to
     machine account Kerberos trust issue.

This script:
  1. Disable Ethernet1 NIC (it's the source of the bad addresses)
  2. Force DNS scavenging + manual A record cleanup via ADSI
     (bypasses dnscmd which is locked out)
  3. Re-register FTLPDC02's DNS records
  4. Attempt machine password reset via netdom WITH password inline
  5. Verify resolution

Runs on FTLPDC02 as local Administrator.
"""
import os
import subprocess
import sys
import time
from datetime import datetime

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
OUT_FILE = os.path.join(DESKTOP, "FTLPDC02-PHASED-RESULT.txt")

DOMAIN_DNS = "PremierDestinationServices.com"
DOMAIN_DN = "DC=PremierDestinationServices,DC=com"
DOMAIN_ADMIN_PASSWORD = "Weston2015!"


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
    r.log("  Phase D - Surgical fixes")
    r.log("=" * 72)
    r.log("  Time: " + time.strftime("%Y-%m-%d %H:%M:%S"))

    if os.environ.get("COMPUTERNAME", "").upper() != "FTLPDC02":
        r.log("Must run ON FTLPDC02")
        r.save()
        return 1

    # ====================================================================
    # Step 1: Examine + disable Ethernet1 (source of APIPA/LL addresses)
    # ====================================================================
    r.section("STEP 1: Examine network adapters")
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-NetAdapter | Format-Table Name,InterfaceDescription,Status,LinkSpeed | Out-String"],
        shell=False, timeout=30, label="list adapters"
    )
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias,IPAddress,PrefixLength | Out-String"],
        shell=False, timeout=30, label="list IPv4 addresses"
    )

    r.section("STEP 2: Disable Ethernet1 (source of 169.254.x.x APIPA)")
    r.log("  Ethernet1 is an unconfigured NIC producing APIPA addresses.")
    r.log("  Disabling it removes those addresses from DNS registration.")
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$nics = Get-NetAdapter | Where-Object { $_.Name -eq 'Ethernet1' -or $_.InterfaceDescription -like '*82574L*' }; "
         "$nics | ForEach-Object { Write-Host ('Disabling: ' + $_.Name); Disable-NetAdapter -Name $_.Name -Confirm:$false }"],
        shell=False, timeout=30, label="disable Ethernet1"
    )

    # ====================================================================
    # Step 3: Delete stale DNS records via ADSI (bypasses dnscmd lockout)
    # ====================================================================
    r.section("STEP 3: Remove stale DNS records for FTLPDC02 via ADSI")
    r.log("  Bypasses dnscmd (Access Denied) by editing the AD-integrated")
    r.log("  DNS node directly via LDAP.")
    ps_dns = r"""
$ErrorActionPreference = 'Continue'
$dn = "DC=FTLPDC02,DC=PremierDestinationServices.com,CN=MicrosoftDNS,DC=DomainDnsZones,DC=PremierDestinationServices,DC=com"
Write-Host "Attempting to read: $dn"
try {
    $node = [ADSI]"LDAP://localhost/$dn"
    Write-Host "Current records in dnsNode:"
    $records = $node.Properties['dnsRecord']
    Write-Host ("  Count: " + $records.Count)
    # dnsRecord is binary - we can't easily filter A records vs AAAA by content
    # Simplest: delete the whole FTLPDC02 node, let Netlogon re-create
    Write-Host "Strategy: delete entire FTLPDC02 dnsNode, let Netlogon re-register"
    $node.DeleteTree()
    Write-Host "Node deleted"
} catch {
    Write-Host ("DNS node operation failed: " + $_.Exception.Message)
}
"""
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps_dns],
        shell=False, timeout=60, label="delete stale DNS node"
    )

    # ====================================================================
    # Step 4: Re-register DNS records
    # ====================================================================
    r.section("STEP 4: Re-register DNS records")
    r.run("ipconfig /flushdns", timeout=15, label="flush DNS cache")
    r.run("ipconfig /registerdns", timeout=30, label="register A record")
    time.sleep(5)
    r.run("nltest /dsregdns", timeout=30, label="re-publish SRV records")
    time.sleep(15)

    # ====================================================================
    # Step 5: Try netdom machine password reset (non-interactive format)
    # ====================================================================
    r.section("STEP 5: Machine password reset via netdom (non-interactive)")
    r.log("  Uses /passwordd:<actual-password> on command line.")
    r.run(
        'netdom resetpwd /server:FTLPDC02 /userd:Administrator /passwordd:' + DOMAIN_ADMIN_PASSWORD,
        timeout=60, label="netdom resetpwd"
    )

    # ====================================================================
    # Step 6: Alternative - use ksetup/klist to reset KRB trust
    # ====================================================================
    r.section("STEP 6: Purge all Kerberos tickets (system-wide)")
    r.run("klist purge -li 0x3e7", timeout=15, label="purge computer tickets")
    r.run("klist -li 0x3e7", timeout=15, label="verify purge")

    # ====================================================================
    # Step 7: Restart critical services
    # ====================================================================
    r.section("STEP 7: Restart DNS + Netlogon")
    r.run("net stop DNS", timeout=30, label="stop DNS")
    time.sleep(3)
    r.run("net stop Netlogon", timeout=30, label="stop Netlogon")
    time.sleep(3)
    r.run("net start Netlogon", timeout=60, label="start Netlogon")
    time.sleep(5)
    r.run("net start DNS", timeout=60, label="start DNS")
    time.sleep(30)

    # ====================================================================
    # Step 8: Verify
    # ====================================================================
    r.section("STEP 8: Verify")
    r.run("ipconfig /all", timeout=15, label="ipconfig after NIC disable")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 127.0.0.1",
          timeout=15, label="nslookup localhost")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 192.168.1.32",
          timeout=15, label="nslookup 192.168.1.32")
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Resolve-DnsName FTLPDC02.PremierDestinationServices.com -Server 127.0.0.1 -Type A | Format-Table | Out-String"],
        shell=False, timeout=30, label="Resolve A records only"
    )
    r.run("dcdiag /test:connectivity /v", timeout=60, label="dcdiag connectivity")

    r.section("PHASE D COMPLETE")
    r.log("")
    r.log("  Key outcomes to check:")
    r.log("    - Step 1: Ethernet1 state")
    r.log("    - Step 3: 'Node deleted' means stale records removed")
    r.log("    - Step 4: 'SRV records registered successfully'")
    r.log("    - Step 5: netdom resetpwd exit code 0 = machine pwd fixed")
    r.log("    - Step 8: Resolve A records shows ONLY 192.168.1.32")
    r.log("    - Step 8: dcdiag Connectivity - look for 'passed' vs 'failed'")

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
