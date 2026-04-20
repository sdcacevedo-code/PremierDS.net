"""
Rebuild-FTLPDC01 Bootstrap

One-time setup that imports the phase scripts from the FTLPDC02 desktop
into the git repo, so future iterations are 'git pull' only -- no more
copy/paste of script contents.

Run on FTLPDC02 as local Administrator:
    python bootstrap.py

What it does:
  1. Verifies git is installed
  2. Clones sdcacevedo-code/premierds.net to the Desktop (branch: claude/rebuild-ftldc01-NGkrS)
  3. Copies known phase scripts from the Desktop into scripts/rebuild-ftldc01/
  4. Commits and pushes to the rebuild branch
  5. On subsequent runs, pulls latest and re-syncs any new Desktop scripts

Usage after bootstrap:
    cd %USERPROFILE%\Desktop\premierds.net
    git pull
    python scripts\rebuild-ftldc01\phase-d-clean.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/sdcacevedo-code/premierds.net.git"
BRANCH = "claude/rebuild-ftldc01-NGkrS"
DESKTOP = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
REPO_DIR = DESKTOP / "premierds.net"
SCRIPTS_SUBDIR = Path("scripts") / "rebuild-ftldc01"

SCRIPT_MAP = {
    "20260420_01_v1.0.0_PhaseA-FTLPDC02-AD-Health.py":             "phase-a-health.py",
    "RUN-ME-NOW-v2.py":                                            "phase-b-repair.py",
    "PHASE-C-DNS-FIX.py":                                          "phase-c-dns-fix.py",
    "PHASE-D-CLEAN.py":                                            "phase-d-clean.py",
    "20260419_04_v1.1.0_Rebuild-FTLPDC01-Phase4b-PromoteOnly.py":  "phase-4b-promote.py",
    "DIAG-dc-contact.py":                                          "diag-dc-contact.py",
}

GIT_CONFIG = {
    "user.email":              "admin@premierdestinationservices.com",
    "user.name":               "FTLPDC02-Admin",
    "credential.helper":       "manager-core",
}


def _print_header(text: str) -> None:
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True,
        capture: bool = False) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=capture,
    )
    if capture and result.stdout:
        for line in result.stdout.rstrip().splitlines():
            print(f"    {line}")
    if capture and result.stderr:
        for line in result.stderr.rstrip().splitlines():
            print(f"    {line}")
    if check and result.returncode != 0:
        print(f"  [FAIL] exit={result.returncode}")
        sys.exit(result.returncode)
    return result


def check_git() -> None:
    _print_header("Step 1: Verify git")
    if shutil.which("git") is None:
        print("  [FATAL] git is not installed.")
        print("  Install with:  winget install Git.Git")
        print("  Then close this window, open a NEW terminal, and re-run.")
        sys.exit(1)
    run(["git", "--version"], capture=True)


def configure_git() -> None:
    _print_header("Step 2: Configure git identity")
    for key, value in GIT_CONFIG.items():
        run(["git", "config", "--global", key, value], capture=True)


def clone_or_pull() -> None:
    _print_header("Step 3: Clone or pull repo")
    if (REPO_DIR / ".git").exists():
        print(f"  Repo exists at {REPO_DIR} -- pulling latest")
        run(["git", "checkout", BRANCH], cwd=REPO_DIR, check=False, capture=True)
        run(["git", "pull"], cwd=REPO_DIR)
    else:
        print(f"  Cloning into {REPO_DIR}")
        print("  First run will open a browser window for GitHub login.")
        DESKTOP.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "-b", BRANCH, REPO_URL, str(REPO_DIR)])


def copy_scripts() -> int:
    _print_header("Step 4: Copy scripts from Desktop")
    dest_dir = REPO_DIR / SCRIPTS_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src_name, dest_name in SCRIPT_MAP.items():
        src = DESKTOP / src_name
        dest = dest_dir / dest_name
        if not src.exists():
            print(f"  SKIP   : {src_name}  (not on Desktop)")
            continue
        shutil.copy2(src, dest)
        print(f"  copied : {src_name}  ->  {dest_name}")
        copied += 1
    if copied == 0:
        print("  [WARN] No scripts were found on the Desktop.")
    return copied


def commit_and_push() -> None:
    _print_header("Step 5: Commit and push")
    run(["git", "add", str(SCRIPTS_SUBDIR)], cwd=REPO_DIR)
    status = run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR, check=False)
    if status.returncode == 0:
        print("  No new changes to commit -- scripts already up to date.")
    else:
        run(
            ["git", "commit", "-m", "Import FTLPDC01 rebuild scripts from FTLPDC02 desktop"],
            cwd=REPO_DIR,
        )
    run(["git", "push", "-u", "origin", BRANCH], cwd=REPO_DIR)


def main() -> int:
    print("=" * 60)
    print("  Rebuild-FTLPDC01 Bootstrap (Python)")
    print("=" * 60)
    try:
        check_git()
        configure_git()
        clone_or_pull()
        copy_scripts()
        commit_and_push()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\n[FATAL] {type(exc).__name__}: {exc}")
        return 1

    _print_header("DONE")
    print(f"  Repo   : {REPO_DIR}")
    print(f"  Branch : {BRANCH}")
    print()
    print("  Next runs:")
    print(f"      cd /d {REPO_DIR}")
    print("      git pull")
    print("      python scripts\\rebuild-ftldc01\\phase-d-clean.py")
    return 0


if __name__ == "__main__":
    rc = main()
    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(rc)
