@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me to set up + verify
REM
REM  Setup.bat                      full setup (fresh .venv, prove HTTP 200, stop)
REM  Setup.bat -ReuseVenv           keep existing .venv (fast re-run)
REM  Setup.bat -KeepRunning         leave the sim running after the proof
REM  Setup.bat -ViewerOnly          prove viewer only (no physics/Java)
REM  Setup.bat -SkipFrontend        skip the npm build
REM  Setup.bat -NoSmoke             skip import smoke tests
REM  Setup.bat -InstallNode         force a system-wide Node install via winget
REM  Setup.bat -BootTimeoutSec 600  give the physics more time to boot
REM  Setup.bat -NodeVersion 20.18.1 which portable Node to fetch if missing
REM  Setup.bat -DistUrl <url>       fetch prebuilt frontend/dist zip (no Node)
REM
REM  If Node is missing, setup fetches a PORTABLE Node into tools\node
REM  (no admin rights, nothing installed system-wide) and builds with it.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause