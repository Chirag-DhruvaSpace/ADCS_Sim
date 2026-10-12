@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me after git clone
REM
REM  Only prerequisite: Python 3.12 (py launcher) + internet once.
REM  Setup downloads/builds EVERYTHING itself (venv + deps, Java
REM  via jdk4py inside the venv, portable Node, frontend build,
REM  orekit-data if missing), proves the sim boots (HTTP 200),
REM  then STOPS everything and leaves the machine clean.
REM
REM  Run the sim afterwards in VS Code as usual:
REM  open folder -> new terminal -> python run_simulator.py
REM
REM  Setup.bat                      full setup (fresh .venv)
REM  Setup.bat -ReuseVenv           keep existing .venv (fast re-run)
REM  Setup.bat -ViewerOnly          verify viewer-only mode instead
REM  Setup.bat -SkipFrontend        skip the npm build
REM  Setup.bat -NoSmoke             skip import smoke tests + warm-up
REM  Setup.bat -BootTimeoutSec 600  more time for slow machines
REM
REM  Safe to re-run anytime - Setup stops any running sim first.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause