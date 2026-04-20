#!/usr/bin/env python3
"""
Pre-flight check before running Phase D.

Read-only. Makes no changes. Reports:
  1. Which .py scripts are still on the Desktop (for bootstrap filename map)
  2. Every network adapter with its name, MAC, status, IPv4 addresses
  3. Which NIC holds 192.168.1.32 (the production address)
  4. Which NIC(s) are producing APIPA (169.254.x.x) addresses
  5. Recommendation for which NIC Phase D should disable

Run on FTLPDC02 as local Administrator:
    cd /d C:\\Users\\Administrator.PREMIER\\Desktop\\premierds.net
    git pull
    python scripts\\rebuild-ftldc01\\preflight-check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
OUT_FILE = DESKTOP / "PREFLIGHT-RESULT.txt"
PRODUCTION_IP = "192.168.1.32"


def log(buf: list[str], msg: str = "") -> None:
    print(msg)
    buf.append(msg)


def section(buf: list[str], title: str) -> None:
    log(buf, "")
    log(buf, "=" * 72)
    log(buf, "  " + title)
    log(buf, "=" * 72)


def run_ps(ps_command: str, timeout: int = 30) -> tuple[int, str, str]:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_command],
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return result.returncode, result.stdout or "", result.stderr or ""


def list_desktop_scripts(buf: list[str]) -> None:
    section(buf, "1. Python scripts on Desktop")
    log(buf, f"  Desktop: {DESKTOP}")
    py_files = sorted(DESKTOP.glob("*.py"))
    if not py_files:
        log(buf, "  (no .py files found)")
        return
    for p in py_files:
        size_kb = p.stat().st_size / 1024
        log(buf, f"  {p.name}  ({size_kb:.1f} KB)")


def list_adapters(buf: list[str]) -> list[dict]:
    section(buf, "2. Network adapters")
    ps = (
        "Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,"
        "MacAddress,LinkSpeed,InterfaceIndex | ConvertTo-Json -Compress"
    )
    rc, out, err = run_ps(ps)
    if rc != 0:
        log(buf, f"  ERROR: Get-NetAdapter failed (rc={rc})")
        if err:
            log(buf, f"  STDERR: {err.strip()}")
        return []
    try:
        data = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        log(buf, f"  ERROR: could not parse adapter JSON")
        log(buf, f"  raw: {out.strip()}")
        return []
    if isinstance(data, dict):
        data = [data]
    for a in data:
        log(buf, "")
        log(buf, f"  Name        : {a.get('Name')}")
        log(buf, f"  Description : {a.get('InterfaceDescription')}")
        log(buf, f"  Status      : {a.get('Status')}")
        log(buf, f"  MacAddress  : {a.get('MacAddress')}")
        log(buf, f"  LinkSpeed   : {a.get('LinkSpeed')}")
        log(buf, f"  IfIndex     : {a.get('InterfaceIndex')}")
    return data


def list_ip_addresses(buf: list[str]) -> list[dict]:
    section(buf, "3. IPv4 addresses per adapter")
    ps = (
        "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
        "Select-Object InterfaceAlias,IPAddress,PrefixLength,AddressState,"
        "SkipAsSource | ConvertTo-Json -Compress"
    )
    rc, out, err = run_ps(ps)
    if rc != 0 or not out.strip():
        log(buf, f"  ERROR: Get-NetIPAddress failed (rc={rc})")
        if err:
            log(buf, f"  STDERR: {err.strip()}")
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        log(buf, "  ERROR: could not parse IP JSON")
        return []
    if isinstance(data, dict):
        data = [data]
    for ip in data:
        log(buf,
            f"  {ip.get('InterfaceAlias','?'):<20} "
            f"{ip.get('IPAddress','?'):<18} "
            f"/{ip.get('PrefixLength','?')}  "
            f"{ip.get('AddressState','?')}"
        )
    return data


def analyze(buf: list[str], adapters: list[dict], ips: list[dict]) -> None:
    section(buf, "4. Analysis + recommendation")
    by_alias: dict[str, list[str]] = {}
    for ip in ips:
        alias = ip.get("InterfaceAlias", "")
        addr = ip.get("IPAddress", "")
        if alias and addr:
            by_alias.setdefault(alias, []).append(addr)

    production_nic = None
    apipa_nics: list[str] = []
    for alias, addrs in by_alias.items():
        has_prod = PRODUCTION_IP in addrs
        has_apipa = any(a.startswith("169.254.") for a in addrs)
        log(buf, f"  {alias}: {', '.join(addrs) or '(no IPv4)'}")
        if has_prod:
            production_nic = alias
            log(buf, f"    -> PRODUCTION: holds {PRODUCTION_IP}")
        if has_apipa:
            apipa_nics.append(alias)
            log(buf, f"    -> APIPA: disconnected or DHCP-failed")

    log(buf, "")
    if not production_nic:
        log(buf, f"  [WARN] No NIC holds {PRODUCTION_IP} - cannot recommend safely.")
        log(buf, "         DO NOT run Phase D until you understand why.")
        return
    log(buf, f"  Production NIC: {production_nic}  (keep this one)")
    if not apipa_nics:
        log(buf, "  No APIPA NICs detected - Phase D Step 2 will have nothing to disable.")
        return
    safe_to_disable = [n for n in apipa_nics if n != production_nic]
    if not safe_to_disable:
        log(buf, "  [WARN] APIPA is on the production NIC - Phase D would disable production.")
        log(buf, "         DO NOT run Phase D as-is.")
        return
    log(buf, "  NIC(s) safe to disable:")
    for n in safe_to_disable:
        log(buf, f"    - {n}")
    log(buf, "")
    log(buf, "  Phase D currently targets 'Ethernet1' by name or Intel 82574L driver.")
    if "Ethernet1" in safe_to_disable:
        log(buf, "  -> MATCH: Phase D's default target is correct. Safe to run.")
    else:
        log(buf, "  -> MISMATCH: Phase D targets 'Ethernet1' but the APIPA NIC is named")
        log(buf, f"     {safe_to_disable}.  Either rename the NIC or update Phase D before running.")


def save(buf: list[str]) -> None:
    try:
        OUT_FILE.write_text("\n".join(buf), encoding="utf-8")
        print(f"\nSaved to: {OUT_FILE}")
    except Exception as exc:
        print(f"Save failed: {exc}")


def main() -> int:
    buf: list[str] = []
    log(buf, "=" * 72)
    log(buf, "  Pre-flight check (read-only)")
    log(buf, "=" * 72)
    log(buf, f"  Host: {os.environ.get('COMPUTERNAME', '?')}")
    log(buf, f"  User: {os.environ.get('USERNAME', '?')}")
    log(buf, f"  Time: {datetime.now().isoformat(timespec='seconds')}")

    list_desktop_scripts(buf)
    adapters = list_adapters(buf)
    ips = list_ip_addresses(buf)
    analyze(buf, adapters, ips)

    save(buf)
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
