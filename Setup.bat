@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me after git clone
REM
REM  Only prerequisite: Python 3.12 (py launcher) + internet once.
REM  Setup provisions EVERYTHING else itself: venv + deps, Java
REM  (jdk4py inside the venv), portable Node (no admin), frontend
REM  build, orekit-data, patches run_simulator.py if old, proves
REM  the sim boots (HTTP 200), then LAUNCHES the sim for you.
REM
REM  Setup.bat                      full setup + auto-launch sim at the end
REM  Setup.bat -ReuseVenv           keep existing .venv (fast re-run)
REM  Setup.bat -NoAutoRun           do NOT launch the sim at the end
REM  Setup.bat -NoPatchRunSim       do not auto-patch run_simulator.py
REM  Setup.bat -ViewerOnly          viewer-only proof + launch
REM  Setup.bat -KeepRunning         leave the proof sim running
REM  Setup.bat -SkipFrontend        skip the npm build
REM  Setup.bat -NoSmoke             skip import smoke tests + warm-up
REM  Setup.bat -BootTimeoutSec 600  more time for slow machines
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause