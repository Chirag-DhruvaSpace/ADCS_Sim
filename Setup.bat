@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me to set up + verify
REM  Runs setup.ps1 with -ExecutionPolicy Bypass so you never
REM  have to fight PowerShell policy.
REM
REM  Setup.bat                     full setup (fresh .venv, prove HTTP 200, stop)
REM  Setup.bat -ReuseVenv          keep existing .venv (fast re-run)
REM  Setup.bat -KeepRunning        leave the sim running after the proof
REM  Setup.bat -ViewerOnly         prove viewer only (no physics/Java)
REM  Setup.bat -SkipFrontend       skip the npm build
REM  Setup.bat -NoSmoke            skip import smoke tests
REM  Setup.bat -InstallNode        auto-install Node.js LTS via winget if missing
REM  Setup.bat -BootTimeoutSec 600 give the physics more time to boot
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause