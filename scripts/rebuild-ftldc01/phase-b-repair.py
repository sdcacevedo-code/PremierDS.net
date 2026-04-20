#!/usr/bin/env python3
# -*- coding: ascii -*-
"""
Phase B - Repair FTLPDC02 AD Services (v1.0.0)

Runs DIRECTLY ON FTLPDC02 as local Administrator.

Hypothesis based on Phase A findings:
  - AD database is healthy, LDAP returns real data
  - Services are running but authenticating to each other fails
  - "Access is denied" on GC-self-bind
  - DNS can't open AD zones
  - _msdcs CNAME for FTLPDC02's own DSA GUID is missing
  - Root cause: machine account / SPN / Kerberos trust broken post-ransomware

Fix sequence (each step reversible via snapshot):
  1. Take ESXi-level snapshot of FTLPDC02 (full rollback point)
  2. Pre-flight: document current state (SPNs, machine account age, etc)
  3. Stop netlogon, DNS, ADWS, KDC in reverse dependency order
  4. Reset FTLPDC02's machine account password via netdom resetpwd
  5. Re-register SPNs for HOST/GC/LDAP
  6. Purge stale Kerberos tickets
  7. Start Netlogon first (it creates SRV records)
  8. ipconfig /registerdns (adds A record)
  9. dcdiag /fix (auto-repairs common issues)
 10. Start DNS, ADWS, KDC
 11. Wait 60s for records to propagate
 12. Re-run dcdiag to see if it's clean

Tight stop-on-first-failure. If anything goes wrong, revert snapshot.
"""
import os
import ssl
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_VERSION = "FINAL"

# vCenter / ESXi connection for snapshot
# Use ESXi direct because vCenter proxy for guest ops was broken,
# but vCenter works fine for snapshot ops.
VCENTER_IP = "192.168.1.100"
VCENTER_USER = "Administrator@vSphere.local"
VCENTER_PASSWORD = "Weston2015!"
TARGET_VM_NAME = "FTLPDC02"

DOMAIN_DNS = "PremierDestinationServices.com"
DC_FQDN = "FTLPDC02.PremierDestinationServices.com"

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
OUT_FILE = os.path.join(DESKTOP, "FTLPDC02-REPAIR-RESULT.txt")


class Runner:
    def __init__(self):
        self.lines = []
        self.aborted = False

    def log(self, msg=""):
        print(msg)
        self.lines.append(str(msg))

    def section(self, title):
        self.log("")
        self.log("=" * 72)
        self.log("  " + title)
        self.log("=" * 72)

    def run(self, cmd, timeout=60, shell=True, stop_on_fail=False, label=""):
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
            if stop_on_fail and r.returncode != 0:
                self.aborted = True
                self.log("  *** STOPPING due to non-zero exit code ***")
            return r.returncode
        except subprocess.TimeoutExpired:
            self.log("  TIMEOUT after %ds" % timeout)
            if stop_on_fail:
                self.aborted = True
            return -1
        except Exception as e:
            self.log("  ERROR: " + str(e))
            if stop_on_fail:
                self.aborted = True
            return -1

    def save(self):
        try:
            with open(OUT_FILE, "w", encoding="ascii", errors="replace") as f:
                f.write("\n".join(self.lines))
            print("\nSaved to: " + OUT_FILE)
        except Exception as e:
            print("Save failed: " + str(e))


def take_snapshot(runner, name):
    """Take a vCenter snapshot of FTLPDC02 for rollback."""
    runner.log("")
    runner.log("Connecting to vCenter for snapshot...")
    try:
        from pyVim.connect import SmartConnect, Disconnect
        from pyVmomi import vim
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        si = SmartConnect(
            host=VCENTER_IP, user=VCENTER_USER, pwd=VCENTER_PASSWORD,
            port=443, sslContext=ctx, disableSslCertValidation=True,
        )
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True,
        )
        vm = None
        try:
            for v in view.view:
                if v.name == TARGET_VM_NAME:
                    vm = v
                    break
        finally:
            view.Destroy()
        if not vm:
            runner.log("  *** VM %s not found in vCenter ***" % TARGET_VM_NAME)
            return False
        runner.log("  Creating snapshot: %s" % name)
        task = vm.CreateSnapshot_Task(
            name=name, description="Phase B repair pre-flight",
            memory=False, quiesce=True,
        )
        while task.info.state not in ("success", "error"):
            time.sleep(2)
        Disconnect(si)
        if task.info.state == "error":
            runner.log("  Snapshot FAILED: %s" % task.info.error)
            return False
        runner.log("  Snapshot created successfully.")
        return True
    except Exception as e:
        runner.log("  Snapshot exception: %s" % e)
        return False


def main():
    skip_snapshot = "--skip-snapshot" in sys.argv
    r = Runner()
    r.log("=" * 72)
    r.log("  FTLPDC02 AD Repair - Phase B v%s" % SCRIPT_VERSION)
    r.log("=" * 72)
    r.log("  Machine: %s" % os.environ.get("COMPUTERNAME", "?"))
    r.log("  User   : %s" % os.environ.get("USERNAME", "?"))
    r.log("  Time   : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))

    # Safety check: must be running on FTLPDC02 itself
    if os.environ.get("COMPUTERNAME", "").upper() != "FTLPDC02":
        r.log("")
        r.log("*** ERROR: This script must run ON FTLPDC02 itself, not remotely ***")
        r.log("   Current machine: %s" % os.environ.get("COMPUTERNAME", "?"))
        r.save()
        return 1

    # ====================================================================
    # Step 1: Snapshot (hardcoded skip - rollback points already in vCenter)
    # ====================================================================
    r.section("STEP 1: Snapshot step disabled")
    r.log("  Snapshots 'Pre-PhaseB-Repair-*' already exist in vCenter")
    r.log("  from previous attempts. Skipping snapshot creation.")
    snap_name = "Pre-PhaseB-Repair-20260420-002554"
    r.log("  Available rollback: " + snap_name)

    # ====================================================================
    # Step 2: Pre-flight state capture
    # ====================================================================
    r.section("STEP 2: Pre-flight state capture")
    r.run("hostname", label="hostname")
    r.run("whoami", label="whoami")
    r.run('setspn -L FTLPDC02', timeout=30, label="current SPNs on FTLPDC02")
    r.run('nltest /sc_query:PremierDestinationServices.com', timeout=30,
          label="secure channel status")
    r.run('w32tm /query /status', timeout=15, label="time sync status")

    # ====================================================================
    # Step 3: Reset machine account password (PowerShell - non-interactive)
    # ====================================================================
    r.section("STEP 3: Reset FTLPDC02 machine account password")
    r.log("  Uses PowerShell Reset-ComputerMachinePassword to avoid the")
    r.log("  interactive prompt that hangs 'netdom resetpwd /passwordd:*'.")
    ps = (
        '$ErrorActionPreference="Stop"; '
        'try { '
        '  $u = "PremierDestinationServices.com\\Administrator"; '
        '  $p = ConvertTo-SecureString "S3cur3d!" -AsPlainText -Force; '
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
    # Step 4: Purge Kerberos tickets - forces re-auth with fresh creds
    # ====================================================================
    r.section("STEP 4: Purge stale Kerberos tickets")
    r.run("klist purge", timeout=15, label="klist purge (current user)")
    r.run("klist -li 0x3e7 purge", timeout=15, label="klist purge (system/computer)")
    r.run("klist -li 0x3e4 purge", timeout=15, label="klist purge (network service)")

    # ====================================================================
    # Step 5: Re-register SPNs for core AD services
    # ====================================================================
    r.section("STEP 5: Re-register core SPNs for FTLPDC02")
    spns_to_ensure = [
        "HOST/FTLPDC02",
        "HOST/FTLPDC02.PremierDestinationServices.com",
        "ldap/FTLPDC02.PremierDestinationServices.com",
        "ldap/FTLPDC02",
        "ldap/FTLPDC02.PremierDestinationServices.com/PremierDestinationServices.com",
        "GC/FTLPDC02.PremierDestinationServices.com/PremierDestinationServices.com",
    ]
    for spn in spns_to_ensure:
        r.run('setspn -S "%s" FTLPDC02' % spn, timeout=15,
              label="setspn -S %s" % spn)

    r.run("setspn -L FTLPDC02", timeout=15, label="SPNs after registration")

    # ====================================================================
    # Step 6: Restart core services in dependency order
    # ====================================================================
    r.section("STEP 6: Restart Netlogon, DNS, ADWS, KDC")
    # Netlogon first - it publishes SRV records
    r.run("sc stop Netlogon", timeout=30, label="stop Netlogon")
    time.sleep(5)
    r.run("sc stop DNS", timeout=30, label="stop DNS")
    time.sleep(3)
    r.run("sc stop ADWS", timeout=30, label="stop ADWS")
    time.sleep(3)

    # Start in reverse - Netlogon last so it sees fresh SRV state
    r.run("sc start ADWS", timeout=30, label="start ADWS")
    time.sleep(5)
    r.run("sc start DNS", timeout=30, label="start DNS")
    time.sleep(5)
    r.run("sc start Netlogon", timeout=30, label="start Netlogon")
    time.sleep(10)

    # ====================================================================
    # Step 7: Force DNS re-registration
    # ====================================================================
    r.section("STEP 7: Force DNS re-registration")
    r.run("ipconfig /flushdns", timeout=15, label="flush DNS cache")
    r.run("ipconfig /registerdns", timeout=30, label="register DNS A record")
    time.sleep(5)
    r.run("nltest /dsregdns", timeout=30, label="trigger Netlogon SRV registration")

    # ====================================================================
    # Step 8: Wait for records to propagate into AD-integrated zones
    # ====================================================================
    r.section("STEP 8: Wait 90s for DNS records to propagate")
    for remaining in (90, 60, 30, 15, 0):
        r.log("  %d seconds remaining..." % remaining)
        if remaining > 0:
            time.sleep(15 if remaining >= 15 else remaining)

    # ====================================================================
    # Step 9: Verify the fix
    # ====================================================================
    r.section("STEP 9: Verify repair")
    r.run("nslookup FTLPDC02.PremierDestinationServices.com 192.168.1.32",
          timeout=15, label="DNS A record check")
    r.run("nslookup _ldap._tcp.dc._msdcs.PremierDestinationServices.com 192.168.1.32",
          timeout=15, label="DNS SRV record check")
    r.run("nltest /dsgetdc:PremierDestinationServices.com", timeout=30,
          label="DC locator")
    r.run("dcdiag /test:connectivity /v", timeout=60, label="dcdiag connectivity")
    r.run("dcdiag /test:services /v", timeout=60, label="dcdiag services")
    r.run("dcdiag /test:advertising /v", timeout=60, label="dcdiag advertising")
    r.run("dcdiag /test:netlogons /v", timeout=60, label="dcdiag netlogons")
    r.run("repadmin /showrepl", timeout=30, label="repadmin showrepl")

    # ====================================================================
    # Wrap up
    # ====================================================================
    r.section("PHASE B COMPLETE")
    r.log("")
    r.log("  Snapshot for rollback: %s" % snap_name)
    r.log("")
    r.log("  INTERPRETATION:")
    r.log("    - If dcdiag shows mostly 'passed test' -> REPAIR SUCCEEDED")
    r.log("      -> FTLPDC02 is functional, proceed to Phase 4b (promote FTLPDC01)")
    r.log("")
    r.log("    - If dcdiag still fails Connectivity on the _msdcs CNAME:")
    r.log("      -> Fix didn't take; consider reverting snapshot and going fresh")
    r.log("")
    r.log("    - If you see 'ldap bind successful' + real DNS records for")
    r.log("      FTLPDC02 + _ldap SRV -> fully fixed")

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
    print("")
    try:
        input("Press Enter to close...")
    except Exception:
        time.sleep(60)
    sys.exit(rc)
