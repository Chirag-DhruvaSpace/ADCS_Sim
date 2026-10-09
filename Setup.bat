@echo off
title LEAP-2 MBD Simulation - Setup
mode con: cols=100 lines=45 >nul 2>&1
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me after git clone
REM
REM  Only prerequisite: Python 3.12 (py launcher) + internet once.
REM  Setup downloads/builds EVERYTHING itself, proves the sim
REM  boots (HTTP 200), then stops and leaves the machine clean
REM  for VS Code (open folder -> new terminal -> python run_simulator.py).
REM
REM  Setup.bat                      full setup (fresh .venv)
REM  Setup.bat -ReuseVenv           keep existing .venv (fast re-run)
REM  Setup.bat -ViewerOnly          verify viewer-only mode instead
REM  Setup.bat -SkipFrontend        skip the npm build
REM  Setup.bat -NoSmoke             skip import smoke tests + warm-up
REM  Setup.bat -Plain               no colors/spinners (weird terminals)
REM  Setup.bat -BootTimeoutSec 600  more time for slow machines
REM
REM  Safe to re-run anytime - Setup stops any running sim first.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause