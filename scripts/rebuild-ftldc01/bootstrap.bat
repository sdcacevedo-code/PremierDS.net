@echo off
setlocal enabledelayedexpansion
title Rebuild-FTLPDC01 Bootstrap

echo =========================================================
echo  Rebuild-FTLPDC01 - Bootstrap
echo  Commits your Desktop scripts to the rebuild branch so
echo  you never have to copy/paste another script again.
echo =========================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [FATAL] git is not installed.
    echo Install it with:   winget install Git.Git
    echo Then close this window, open a NEW CMD, and re-run this.
    pause
    exit /b 1
)

git config --global user.email "admin@premierdestinationservices.com" >nul 2>&1
git config --global user.name  "FTLPDC02-Admin"                       >nul 2>&1
git config --global credential.helper manager-core                    >nul 2>&1
git config --global init.defaultBranch main                           >nul 2>&1

set "DESK=C:\Users\Administrator.PREMIER\Desktop"
set "REPO=%DESK%\premierds.net"
set "BRANCH=claude/rebuild-ftldc01-NGkrS"

cd /d "%DESK%" || goto :error

if not exist "%REPO%\.git" (
    echo [1/5] Cloning repo ^(first run will prompt for GitHub login^)...
    git clone -b %BRANCH% https://github.com/sdcacevedo-code/premierds.net.git
    if errorlevel 1 goto :error
) else (
    echo [1/5] Repo exists - pulling latest...
    cd /d "%REPO%"
    git checkout %BRANCH% 2>nul
    git pull || goto :error
)

cd /d "%REPO%"
if not exist scripts\rebuild-ftldc01 mkdir scripts\rebuild-ftldc01

echo.
echo [2/5] Copying scripts from Desktop into repo...
call :copyone "20260420_01_v1.0.0_PhaseA-FTLPDC02-AD-Health.py"              phase-a-health.py
call :copyone "RUN-ME-NOW-v2.py"                                             phase-b-repair.py
call :copyone "PHASE-C-DNS-FIX.py"                                           phase-c-dns-fix.py
call :copyone "PHASE-D-CLEAN.py"                                             phase-d-clean.py
call :copyone "20260419_04_v1.1.0_Rebuild-FTLPDC01-Phase4b-PromoteOnly.py"   phase-4b-promote.py
call :copyone "DIAG-dc-contact.py"                                           diag-dc-contact.py

echo.
echo [3/5] Staging...
git add scripts\rebuild-ftldc01

echo.
echo [4/5] Committing...
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Import FTLPDC01 rebuild scripts from FTLPDC02 desktop"
    if errorlevel 1 goto :error
) else (
    echo   Nothing new to commit - scripts already up to date.
)

echo.
echo [5/5] Pushing to %BRANCH%...
git push -u origin %BRANCH%
if errorlevel 1 goto :error

echo.
echo =========================================================
echo  DONE. Scripts are now in git.
echo  Repo path: %REPO%
echo  Branch   : %BRANCH%
echo.
echo  From now on, to get the latest scripts:
echo      cd /d %REPO%
echo      git pull
echo      python scripts\rebuild-ftldc01\phase-d-clean.py
echo =========================================================
pause
exit /b 0

:copyone
if exist "%DESK%\%~1" (
    copy /Y "%DESK%\%~1" "scripts\rebuild-ftldc01\%~2" >nul
    echo   copied: %~1  -^>  %~2
) else (
    echo   SKIP  : %~1  ^(not on desktop^)
)
exit /b 0

:error
echo.
echo =========================================================
echo  FAILED - see error above.
echo =========================================================
pause
exit /b 1
