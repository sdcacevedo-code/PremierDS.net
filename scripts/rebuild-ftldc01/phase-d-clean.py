#!/usr/bin/env python3
# -*- coding: ascii -*-
"""
Phase D - Surgical fixes for FTLPDC02 (v1.1.0)

Findings from Phase C + preflight-check:
  1. FTLPDC02 has multiple A records for itself in its own DNS zone:
     - 192.168.1.32   (correct, from Ethernet0)
     - 169.254.83.107 (APIPA, from the Tailscale tunnel NIC)
     When a client resolves FTLPDC02.domain.com it may get the APIPA
     address first, causing all authentication to time out.

  2. dnscmd / Get-DnsServer fail with Access Denied due to the broken
     machine-account Kerberos trust, so DNS must be edited via ADSI.

This script (v1.1.0 - updated after preflight-check):
  1. Disable DNS registration on ALL non-production NICs (keeps them
     online for remote management but stops them polluting DNS).
     Previously: disabled the NIC outright. That was wrong - Tailscale
     is a VPN tunnel we may still need for remote access.
  2. Delete the stale FTLPDC02 dnsNode via ADSI - probes all three
     partitions (DomainDnsZones, ForestDnsZones, CN=System) so it
     works regardless of where the zone lives.
  3. Re-register FTLPDC02's DNS records (only production IP now).
  4. Attempt machine-account password reset via netdom (best effort).
  5. Restart DNS + Netlogon.
  6. Verify resolution + dcdiag.

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

    r.section("STEP 2: Stop non-production NICs from registering in DNS")
    r.log("  Rather than disabling NICs (which could break remote access),")
    r.log("  we tell Windows not to register non-production NIC addresses.")
    r.log("  The production NIC is whichever one holds 192.168.1.32.")
    ps_nodnsreg = r"""
$ErrorActionPreference = 'Continue'
$production = '192.168.1.32'
$adapters = Get-NetAdapter | Where-Object Status -eq 'Up'
foreach ($a in $adapters) {
    $ips = Get-NetIPAddress -InterfaceAlias $a.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
           Select-Object -ExpandProperty IPAddress
    if ($ips -contains $production) {
        Write-Host ('KEEP DNS registration on: ' + $a.Name + ' (production NIC)')
        Set-DnsClient -InterfaceAlias $a.Name `
                      -RegisterThisConnectionsAddress $true `
                      -UseSuffixWhenRegistering $true `
                      -ErrorAction SilentlyContinue
    } else {
        Write-Host ('STOP DNS registration on : ' + $a.Name + '  (IPs: ' + ($ips -join ',') + ')')
        Set-DnsClient -InterfaceAlias $a.Name `
                      -RegisterThisConnectionsAddress $false `
                      -UseSuffixWhenRegistering $false `
                      -ErrorAction SilentlyContinue
    }
}
"""
    r.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps_nodnsreg],
        shell=False, timeout=30, label="configure per-NIC DNS registration"
    )

    # ====================================================================
    # Step 3: Delete stale DNS records via ADSI (bypasses dnscmd lockout)
    # ====================================================================
    r.section("STEP 3: Remove stale DNS records for FTLPDC02 via ADSI")
    r.log("  Bypasses dnscmd (Access Denied) by editing the AD-integrated")
    r.log("  DNS node directly via LDAP.")
    ps_dns = r"""
$ErrorActionPreference = 'Continue'
$zone = 'PremierDestinationServices.com'
$domainDn = 'DC=PremierDestinationServices,DC=com'
$candidates = @(
    "DC=FTLPDC02,DC=$zone,CN=MicrosoftDNS,DC=DomainDnsZones,$domainDn",
    "DC=FTLPDC02,DC=$zone,CN=MicrosoftDNS,DC=ForestDnsZones,$domainDn",
    "DC=FTLPDC02,DC=$zone,CN=MicrosoftDNS,CN=System,$domainDn"
)
$deleted = 0
foreach ($dn in $candidates) {
    Write-Host ('Probe: ' + $dn)
    try {
        $node = [ADSI]"LDAP://localhost/$dn"
        $null = $node.Name  # forces bind; throws if object does not exist
        Write-Host '  Found node - deleting entire FTLPDC02 dnsNode.'
        Write-Host '  Netlogon will re-register only the production NIC next step.'
        $node.DeleteTree()
        Write-Host '  Node deleted.'
        $deleted++
    } catch {
        Write-Host ('  Not present in this partition: ' + $_.Exception.Message.Trim())
    }
}
if ($deleted -eq 0) {
    Write-Host 'WARNING: FTLPDC02 dnsNode was not found in any AD-integrated partition.'
    Write-Host 'The zone may be file-backed, or DNS is not AD-integrated.'
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
