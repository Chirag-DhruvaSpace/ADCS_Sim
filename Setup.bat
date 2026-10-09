@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : double-click me to set up + verify
REM  Why this file exists: Windows blocks setup.ps1 by default
REM  (ExecutionPolicy). This .bat sidesteps that with -Bypass,
REM  so the user never types anything. PowerShell does the work.
REM  Usage:
REM    Setup.bat                  full setup (nuke .venv, reinstall all, prove it boots, then stop)
REM    Setup.bat -ReuseVenv        keep existing .venv (fast re-run)
REM    Setup.bat -KeepRunning      leave the sim running after proof
REM    Setup.bat -ViewerOnly       only prove the viewer (no physics/Java)
REM    Setup.bat -SkipFrontend     skip npm build
REM    Setup.bat -NoSmoke          skip import smoke tests
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
