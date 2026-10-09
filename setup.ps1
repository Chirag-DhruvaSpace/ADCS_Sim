# ============================================================================
#  setup.ps1 - LEAP-2 MBD Simulation - one-click setup (v7)
#  Flow: git clone repo -> double-click Setup.bat -> sim starts itself.
#  Only prerequisite on the machine: Python 3.12 (py launcher).
#
#  v7 vs v6 - fixes "Could not delete old .venv ... The directory is not empty":
#   * .venv deletion is now bulletproof:
#       - kills ONLY processes whose executable lives inside .venv (no more
#         killing every python.exe on the machine by name), plus the
#         Run-Sim.bat / run-sim.ps1 wrapper windows (so no auto-restart races)
#         and whatever serves port 5000
#       - deletes with cmd's rmdir /s /q (immune to the PowerShell
#         Remove-Item -Recurse "directory not empty" race), with retries and
#         a rename-then-delete fallback
#   * re-running Setup while last time's sim is still running is now SAFE -
#     setup stops the sim itself before rebuilding the venv.
#  v6 kept: run_simulator.py auto-patch (boot shield), auto-launch at the end,
#  orekit-data auto-download, portable-Node auto-fetch, proxy-immune
#  000/503/200 boot probe, boot-log capture + auto-diagnosis.
# ============================================================================
param(
  [switch]$ReuseVenv,
  [switch]$KeepRunning,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke,
  [switch]$InstallNode,
  [switch]$NoAutoRun,
  [switch]$NoPatchRunSim,
  [int]$BootTimeoutSec = 300,
  [string]$NodeVersion = '22.14.0',
  [string]$DistUrl = ''
)

 $ErrorActionPreference = 'Stop'
 $ProgressPreference = 'SilentlyContinue'
 $Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
 $LogFile    = Join-Path $Root 'setup.log'
 $VenvDir    = Join-Path $Root '.venv'
 $VenvPy     = Join-Path $VenvDir 'Scripts\python.exe'
 $DistIndex  = Join-Path $Root 'frontend\dist\index.html'
 $BootOut    = Join-Path $Root 'sim-boot.out.log'
 $BootErr    = Join-Path $Root 'sim-boot.err.log'
 $ToolsDir   = Join-Path $Root 'tools'
 $PortableNodeDir = Join-Path $ToolsDir 'node'
 $StepTotal  = 8; $StepNo = 0
 $FrontendMissing = $false

function Log([string]$m)  { Add-Content -Path $LogFile -Value $m -Encoding UTF8 }
function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c; Log $m }
function Ok([string]$m)   { Say "  [OK] $m" Green }
function Warn([string]$m) { Say "  [!!] $m" Yellow }
function Fail([string]$m) { Say "  [FAIL] $m" Red; throw $m }
function Step([string]$t) {
  $script:StepNo++
  Write-Host ''
  Write-Host "===== [$($script:StepNo)/$StepTotal] $t =====" -ForegroundColor Cyan
  Log "STEP $($script:StepNo)/$StepTotal : $t"
}
function Run([string]$exe, [string[]]$argList) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $exe @argList 2>&1 | ForEach-Object { $ln = "$_"; Write-Host "  $ln" -ForegroundColor DarkGray; Log "  $ln" } }
  finally { $ErrorActionPreference = $prev }
  return $LASTEXITCODE
}
function Get-HttpCode([int]$Port = 5000) {
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $code = (& curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' --max-time 5 "http://127.0.0.1:$Port/" 2>$null)
    $code = ("$code").Trim()
    if ($code -match '^\d{3}$') { return $code }
    return '000'
  }
  $t = New-Object System.Net.Sockets.TcpClient
  try { $t.Connect('127.0.0.1', $Port); return 'LISTENING' } catch { return '000' }
  finally { $t.Close() }
}
function Get-HttpBody([int]$Port = 5000) {
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    return (& curl.exe -s --noproxy '*' --max-time 5 "http://127.0.0.1:$Port/" 2>$null | Out-String).Trim()
  }
  return ''
}
function Get-ApiCode([string]$path = '/api/latest') {
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $c = & curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' --max-time 5 "http://127.0.0.1:5000$path" 2>$null
    return ("$c").Trim()
  }
  return '???'
}
function Test-PortFree([int]$Port) {
  try { Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Out-Null; return $false }
  catch { return $true }
}
function Kill-Port([int]$Port) {
  try { Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } } catch {}
}
function Test-Npm {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { $null = npm.cmd --version 2>&1; return ($LASTEXITCODE -eq 0) }
  catch { return $false } finally { $ErrorActionPreference = $prev }
}
function Test-PortableNode { Test-Path (Join-Path $PortableNodeDir 'npm.cmd') }
function Get-Py312 {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    $out = & py -V:3.12 --version 2>&1 | Out-String
    if ($out -match '3\.12') { return @{ Exe = 'py'; Args = @('-V:3.12') } }
    $out = & python --version 2>&1 | Out-String
    if ($out -match '3\.12') { return @{ Exe = 'python'; Args = @() } }
  } catch {} finally { $ErrorActionPreference = $prev }
  return $null
}
function Tail-File([string]$path, [int]$n = 20) {
  if ($path -and (Test-Path $path)) { return (Get-Content $path -Tail $n) -join "`n" }
  return ''
}
function Refresh-PathFromMachine {
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}

# ---------- v7: bulletproof venv teardown -----------------------------------
# Kills ONLY what actually runs from inside the venv (plus the launcher
# wrappers and the port-5000 server). Never kills unrelated python.exe by name.
function Stop-VenvProcesses([string]$venvDir) {
  Say '  stopping the sim + anything running from inside .venv ...' DarkCyan
  try {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($venvDir, [StringComparison]::OrdinalIgnoreCase)) -or
      ($_.CommandLine -and $_.CommandLine -match 'run-sim\.ps1|Run-Sim\.bat|open-when-ready\.ps1')
    }
    foreach ($p in $procs) {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Log "  stopped pid $($p.ProcessId): $($_ = $p.ExecutablePath; if (-not $_) { $p.CommandLine } else { $_ })"
    }
  } catch { Log "  process scan failed: $($_.Exception.Message)" }
  try {
    Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Log "  stopped port-5000 owner pid $($_.OwningProcess)" }
  } catch {}
  Start-Sleep -Seconds 2
}
# cmd's rmdir /s /q does not have the PowerShell Remove-Item -Recurse race
# ("The directory is not empty"). Retries + rename-then-delete as fallback.
function Remove-Tree([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return $true }
  for ($i = 1; $i -le 4; $i++) {
    $null = & cmd.exe /c rmdir /s /q "$path" 2>&1
    if (-not (Test-Path -LiteralPath $path)) { return $true }
    Start-Sleep -Seconds (2 * $i)
  }
  try {
    $dead = Join-Path (Split-Path -Parent $path) ('._delete_me_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    Rename-Item -LiteralPath $path -NewName (Split-Path $dead -Leaf) -ErrorAction Stop
    for ($i = 1; $i -le 3; $i++) {
      $null = & cmd.exe /c rmdir /s /q "$dead" 2>&1
      if (-not (Test-Path -LiteralPath $dead)) { return $true }
      Start-Sleep -Seconds 2
    }
  } catch {}
  return (-not (Test-Path -LiteralPath $path))
}

function Install-NodeViaWinget {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Warn 'winget not available on this machine.'; return $false }
  Say '  winget install OpenJS.NodeJS.LTS (system-wide, may ask for elevation) ...' DarkCyan
  $null = Run winget @('install','-e','--id','OpenJS.NodeJS.LTS','--accept-source-agreements','--accept-package-agreements','--silent')
  Refresh-PathFromMachine
  if (Test-Npm) { Ok 'Node.js installed via winget and visible now'; return $true }
  $std = 'C:\Program Files\nodejs'
  if (Test-Path (Join-Path $std 'npm.cmd')) { $env:Path = "$std;$env:Path"; Ok "winget installed Node; using it directly from $std"; return $true }
  Warn 'winget reported success but npm is still not usable - trying portable Node next.'
  return $false
}
function Install-PortableNode([string]$Version) {
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
  $zipUrl  = "https://nodejs.org/dist/v$Version/node-v$Version-win-x64.zip"
  $zipPath = Join-Path $ToolsDir "node-v$Version-win-x64.zip"
  New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
  Say "  downloading portable Node $Version (~30 MB, one-time; cached in tools\node) ..." DarkCyan
  Log "  url: $zipUrl"
  try { Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing }
  catch { Warn "download failed: $($_.Exception.Message) (no internet, or nodejs.org blocked by proxy/IT)"; return $false }
  Say '  extracting ...' DarkCyan
  $tmp = Join-Path $ToolsDir 'node-extract'
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Expand-Archive -Path $zipPath -DestinationPath $tmp -Force
  $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
  if (-not $inner) { Warn 'Node zip had unexpected layout.'; return $false }
  if (Test-Path $PortableNodeDir) { Remove-Item -Recurse -Force $PortableNodeDir }
  Move-Item $inner.FullName $PortableNodeDir
  Remove-Item -Recurse -Force $tmp
  Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
  if (-not (Test-PortableNode)) { Warn 'portable Node extraction incomplete.'; return $false }
  Get-ChildItem $PortableNodeDir -Recurse -File | ForEach-Object { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue }
  $nv = (& (Join-Path $PortableNodeDir 'node.exe') --version) 2>&1 | Out-String
  Ok "portable Node ready: $PortableNodeDir ($($nv.Trim())) - nothing installed system-wide"
  return $true
}
function Install-OrekitData {
  $url = 'https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip'
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
  New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
  $zip = Join-Path $ToolsDir 'orekit-data.zip'
  Say '  downloading orekit-data from Orekit GitLab (one-time, ~100 MB) ...' DarkCyan
  Log "  url: $url"
  try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing }
  catch { Warn "download failed: $($_.Exception.Message)"; return $false }
  $tmp = Join-Path $ToolsDir 'orekit-extract'
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $inner = Join-Path $tmp 'orekit-data-main'
  if (-not (Test-Path $inner)) { Warn 'unexpected orekit-data zip layout.'; return $false }
  $dest = Join-Path $Root 'orekit-data'
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Move-Item $inner $dest
  Remove-Item -Recurse -Force $tmp
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  Get-ChildItem $dest -Recurse -File | ForEach-Object { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue }
  return $true
}

# --- patches run_simulator.py if the clone has the fragile version ---------
function Ensure-RunSimShield {
  $rs = Join-Path $Root 'run_simulator.py'
  if (-not (Test-Path $rs)) { Warn 'run_simulator.py not found - skipping patch step.'; return }
  $raw = Get-Content $rs -Raw
  if ($raw -match 'LEAP2_BOOT_SHIELD') { Ok 'run_simulator.py is self-sufficient already (boot shield present)'; return }
  if (($raw -notmatch 'Run physics and the viewer with shared command state') -or
      ($raw -notmatch 'from satellite_flight_visualisation import run_simulation, _telemetry_publisher') -or
      ($raw -notmatch 'run_simulation\(\)')) {
    Warn 'run_simulator.py not recognized as the known original - NOT patching. Commit the shielded run_simulator.py.'
    return
  }
  if ($NoPatchRunSim) { Warn 'run_simulator.py lacks the boot shield (-NoPatchRunSim given).'; return }
  Copy-Item $rs "$rs.orig" -Force
  $new = @'
"""Run physics and the viewer with shared command state; no Flask reloader."""
# LEAP2_BOOT_SHIELD v1 -- marker checked by setup.ps1; do not remove.
import os
import signal
import threading
from threading import Thread


def _ensure_java():
    """Make the venv self-sufficient: no JAVA_HOME needed in any terminal."""
    if os.environ.get('JAVA_HOME'):
        return
    try:
        import jdk4py
        home = str(jdk4py.JAVA_HOME)
        if os.path.isdir(home):
            os.environ['JAVA_HOME'] = home
            os.environ['PATH'] = (
                os.path.join(home, 'bin') + os.pathsep
                + os.environ.get('PATH', ''))
    except Exception:
        pass


_stop_heartbeat = threading.Event()


def _heartbeat():
    n = 0
    while not _stop_heartbeat.wait(10):
        n += 10
        print(f'  ... still starting up ({n}s) - normal, do not close this window',
              flush=True)


def main():
    print('LEAP-2 sim booting: importing the physics stack (heartbeat below; '
          'can take 1-3 min on corporate laptops). Ctrl+C is ignored until '
          'the sim is up.', flush=True)
    _ensure_java()
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    threading.Thread(target=_heartbeat, name='boot-heartbeat',
                     daemon=True).start()
    try:
        # Keep JVM/physics initialization and propagation on the main thread.
        from satellite_flight_visualisation import run_simulation, _telemetry_publisher
        from app import app, accept_telemetry_snapshot
    finally:
        _stop_heartbeat.set()
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except Exception:
        pass
    _telemetry_publisher.set_sink(accept_telemetry_snapshot)
    try:
        from waitress import serve
        server = lambda: serve(app, host='127.0.0.1', port=5000, threads=4)
    except ImportError:
        server = lambda: app.run(host='127.0.0.1', port=5000, threaded=True,
                                 debug=False, use_reloader=False)
    Thread(target=server, name='viewer-http', daemon=True).start()
    print('Viewer: http://127.0.0.1:5000', flush=True)
    run_simulation()


if __name__ == '__main__':
    main()
'@
  $new | Out-File -FilePath $rs -Encoding utf8
  Ok 'run_simulator.py PATCHED (backup: run_simulator.py.orig). COMMIT the shielded file once.'
}

# ---- writes the everyday launcher (Run-Sim.bat + run-sim.ps1 + opener) ----
function Write-Launchers {
  New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
  $runSimBat = @'
@echo off
REM ============================================================
REM  LEAP-2 MBD Simulation : DOUBLE-CLICK ME TO RUN THE SIM
REM  (auto-created by Setup.bat - run Setup.bat once first)
REM
REM  Run-Sim.bat               full sim (physics + viewer)
REM  Run-Sim.bat -ViewerOnly   viewer only (no physics / no Java)
REM
REM  Needs NO environment setup: JAVA_HOME is resolved from the
REM  venv itself. Auto-restarts if the sim dies while booting.
REM  Browser opens automatically.
REM ============================================================
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [!] Virtual environment not found. Run Setup.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-sim.ps1" %*
echo.
pause
'@
  $runSimPs1 = @'
# run-sim.ps1 - LEAP-2 everyday launcher (auto-created by setup.ps1)
param([switch]$ViewerOnly)
 $ErrorActionPreference = 'Continue'
 $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
 $VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) { Write-Host '[!] .venv missing - run Setup.bat first.' -ForegroundColor Red; exit 1 }

 $ToolsDir = Join-Path $Root 'tools'
 $flag = Join-Path $ToolsDir 'sim-was-up.flag'

# already running? -> just open the browser
 $busy = $false
try { Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop | Out-Null; $busy = $true } catch {}
if ($busy) {
  Write-Host '[!] Port 5000 already serving - the sim looks ALREADY RUNNING.' -ForegroundColor Yellow
  Write-Host '    Opening http://127.0.0.1:5000 . Close the other sim window to restart it.' -ForegroundColor Yellow
  Start-Process 'http://127.0.0.1:5000'
  exit 0
}

# belt-and-suspenders env (run_simulator.py also does this itself now)
 $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
 $jdk = (& $VenvPy -c "import jdk4py; print(jdk4py.JAVA_HOME)" 2>$null | Out-String).Trim()
 $ErrorActionPreference = $prev
 $jdk = ($jdk -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
if ($jdk) { $jdk = $jdk.Trim() }
if ($jdk -and (Test-Path $jdk)) { $env:JAVA_HOME = $jdk; $env:Path = "$jdk\bin;$env:Path" }
 $env:OREKIT_DATA = Join-Path $Root 'orekit-data'

 $sim = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
Remove-Item $flag -Force -ErrorAction SilentlyContinue
 $opener = Join-Path $ToolsDir 'open-when-ready.ps1'
if (Test-Path $opener) {
  Start-Process powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$opener`"") -WindowStyle Hidden
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
if ($ViewerOnly) { Write-Host ' LEAP-2 sim : VIEWER-ONLY (no physics, no Java)' -ForegroundColor Cyan }
else             { Write-Host ' LEAP-2 sim : FULL SIM (physics + viewer)' -ForegroundColor Cyan }
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' Startup prints a heartbeat every 10 s. Browser opens by itself' -ForegroundColor Gray
Write-Host ' at http://127.0.0.1:5000 . If the sim dies while booting it' -ForegroundColor Gray
Write-Host ' AUTO-RESTARTS (up to 3 tries). To stop it later: Ctrl+C once.' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Cyan

for ($a = 1; $a -le 3; $a++) {
  & $VenvPy -u $sim 2>&1 | Tee-Object -FilePath (Join-Path $Root 'sim-run.log')
  $ec = $LASTEXITCODE
  if ($ec -eq 0)       { Write-Host 'sim stopped.' -ForegroundColor Gray; exit 0 }
  if (Test-Path $flag) { Write-Host 'sim stopped (it had been running).' -ForegroundColor Gray; exit 0 }
  if ($a -lt 3) {
    Write-Host "[!] sim died during startup (exit code $ec) - restarting automatically (attempt $a/3)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
  } else {
    Write-Host "[!] sim died during startup 3 times in a row (last exit code $ec)." -ForegroundColor Red
    Write-Host '    Scroll up / open sim-run.log for the traceback.' -ForegroundColor Red
  }
}
'@
  $openerPs1 = @'
# waits for the sim on 127.0.0.1:5000, then opens the browser once and
# drops a marker so run-sim.ps1 knows the sim DID come up.
 $deadline = (Get-Date).AddMinutes(8)
 $flag = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'sim-was-up.flag'
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  $c = '000'
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $c = (& curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' --max-time 3 'http://127.0.0.1:5000/' 2>$null)
    $c = ("$c").Trim()
    if ($c -notmatch '^\d{3}$') { $c = '000' }
  } else {
    try { $t = New-Object System.Net.Sockets.TcpClient; $t.Connect('127.0.0.1', 5000); $c = 'LISTENING'; $t.Close() } catch { $c = '000' }
  }
  if ($c -eq '200' -or $c -eq '503' -or $c -eq 'LISTENING') {
    Set-Content -Path $flag -Value (Get-Date -Format 'HH:mm:ss')
    Start-Process 'http://127.0.0.1:5000'
    break
  }
}
'@
  $runSimBat | Out-File -FilePath (Join-Path $Root 'Run-Sim.bat') -Encoding ascii
  $runSimPs1 | Out-File -FilePath (Join-Path $Root 'run-sim.ps1') -Encoding ascii
  $openerPs1 | Out-File -FilePath (Join-Path $ToolsDir 'open-when-ready.ps1') -Encoding ascii
  Ok 'everyday launcher written: Run-Sim.bat (no env needed, auto-restart, auto-browser)'
}

# ============================== banner =====================================
'' | Out-File -FilePath $LogFile -Encoding utf8
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' LEAP-2 MBD Simulation : one-click setup (v7)' -ForegroundColor Cyan
Write-Host " Root : $Root" -ForegroundColor Gray
Write-Host " Log  : $LogFile" -ForegroundColor Gray
Write-Host ' NOTE: safe to re-run anytime - Setup stops a running sim itself.' -ForegroundColor Gray
Write-Host ' Flags: -ReuseVenv -KeepRunning -ViewerOnly -SkipFrontend -NoSmoke' -ForegroundColor Gray
Write-Host '        -InstallNode -NoAutoRun -NoPatchRunSim -BootTimeoutSec <sec>' -ForegroundColor Gray
Write-Host '        -NodeVersion <ver> -DistUrl <url>' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Cyan

# ====================== Step 1 : pre-flight + shield =======================
Step 'Pre-flight (python / node / orekit-data) + run_simulator self-sufficiency'
 $py312 = Get-Py312
if (-not $py312) { Fail "Python 3.12 not found - the ONLY prerequisite. Install python.org 3.12 64-bit WITH 'py launcher' checked, then re-run: https://www.python.org/downloads/release/python-3127/" }
Ok "Python 3.12 via: $($py312.Exe) $($py312.Args -join ' ')"

 $npmOk = Test-Npm
if ($npmOk) { Ok 'node/npm present on PATH' }
elseif (Test-PortableNode) { Ok 'portable Node already cached (tools\node) - frontend can be built offline' }
else { Say '  [..] Node not found - Step 5 will fetch a portable copy automatically (needs internet)' DarkCyan }
if (Test-Path $DistIndex) { Ok "frontend/dist already present ($DistIndex)" }

 $od = Join-Path $Root 'orekit-data'
if (Test-Path (Join-Path $od 'Potential')) { Ok "orekit-data present ($od)" }
else {
  Say '  orekit-data not in this clone - downloading it ...' DarkCyan
  if (-not (Install-OrekitData)) {
    Fail "orekit-data missing AND download failed. Manual fix: download https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip , unzip, rename orekit-data-main -> orekit-data at repo root, re-run Setup.bat -ReuseVenv"
  }
  if (-not (Test-Path (Join-Path $od 'Potential'))) { Fail 'orekit-data downloaded but looks incomplete (no Potential/ inside).' }
  Ok 'orekit-data downloaded and installed'
}

if ($Root -match '(?i)(Downloads|OneDrive|Dropbox)') {
  Warn "project sits in a Downloads/OneDrive-synced location ($Root) - synced+scanned folders stall imports and slow file deletion. Recommended: move to C:\Projects\ADCS_Sim and re-run Setup.bat."
}
if (Test-PortFree 5000) { Ok 'port 5000 free' } else { Warn 'port 5000 is BUSY (the sim from last time is running) - Setup will stop it automatically in Step 2.' }
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force } catch {}
Ensure-RunSimShield

# ====================== Step 2 : fresh venv ================================
Step 'Fresh virtual environment (.venv)'
if ((Test-Path $VenvDir) -and (-not $ReuseVenv)) {
  Log '  removing old .venv (stopping its processes first) ...'
  Stop-VenvProcesses $VenvDir
  if (Remove-Tree $VenvDir) { Ok 'old .venv deleted cleanly' }
  else {
    Fail ("old .venv could not be fully deleted - OneDrive/antivirus/VS Code are still holding files inside it. Do this, then re-run Setup.bat:`n" +
          "   1) close VS Code COMPLETELY (File > Exit, not just the window) and every sim/console window`n" +
          "   2) open cmd in the project folder and run:   rmdir /s /q .venv`n" +
          "   3) re-run Setup.bat`n" +
          "   (if it still refuses: pause OneDrive sync / reboot once, then rmdir again)")
  }
} elseif (Test-Path $VenvDir) { Ok 'reusing existing .venv (-ReuseVenv)' }
if (-not (Test-Path $VenvPy)) {
  Log "  creating venv: $($py312.Exe) $($py312.Args -join ' ') -m venv .venv ..."
  $null = Run $py312.Exe ($py312.Args + @('-m','venv','.venv'))
  if (-not (Test-Path $VenvPy)) { Fail 'venv creation failed (see setup.log). Usual cause: broken Python install - repair via the python.org installer.' }
}
Ok "venv ready: $VenvPy"
 $null = Run $VenvPy @('--version')

# ====================== Step 3 : python deps ===============================
Step 'Python dependencies (pip install -r requirements.txt)'
 $null = Run $VenvPy @('-m','pip','install','--upgrade','pip')
 $req = Join-Path $Root 'requirements.txt'
 $ec  = Run $VenvPy @('-m','pip','install','-r',$req)
if ($ec -ne 0) {
  Warn 'first pip pass failed - retrying once with --no-cache-dir ...'
  $ec = Run $VenvPy @('-m','pip','install','--no-cache-dir','-r',$req)
  if ($ec -ne 0) { Fail "pip install failed twice. Open setup.log and search for 'ERROR:'." }
}
 $ec = Run $VenvPy @('-c',"import flask,numpy,scipy,yaml,requests,waitress,orekit_jpype,jdk4py; print('py-deps-ok')")
if ($ec -ne 0) { Fail 'dependency import check failed (flask/numpy/scipy/yaml/requests/waitress/orekit_jpype/jdk4py). See setup.log.' }
Ok 'all python deps import cleanly'

# ============ Step 4 : Java 21 via jdk4py (JVM path fix) ===================
Step 'Java 21 via jdk4py (fixes "No JVM shared library file (jvm.dll) found")'
 $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
 $jdkHome = (& $VenvPy -c "import jdk4py; print(jdk4py.JAVA_HOME)" 2>&1 | Out-String).Trim()
 $ErrorActionPreference = $prev
 $jdkHome = ($jdkHome -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
if ($jdkHome) { $jdkHome = $jdkHome.Trim() }
if (-not $jdkHome -or -not (Test-Path $jdkHome)) { Fail "jdk4py did not return a valid JAVA_HOME (got '$jdkHome'). Fix: $VenvPy -m pip install --force-reinstall jdk4py, then re-run." }
if (-not (Test-Path (Join-Path $jdkHome 'bin\server\jvm.dll'))) { Fail "jvm.dll not found under $jdkHome\bin\server - jdk4py install is corrupt. Re-run Setup.bat (fresh venv)." }
 $env:Path = "$jdkHome\bin;$env:Path"
 $env:JAVA_HOME = $jdkHome
Log "  JAVA_HOME=$env:JAVA_HOME"
Ok "jvm.dll present: $jdkHome\bin\server\jvm.dll"

 $actSim = Join-Path $VenvDir 'Scripts\Activate-sim.ps1'
@"
# auto-generated by setup.ps1 - optional; run_simulator.py now sets JAVA_HOME itself
& "$VenvDir\Scripts\Activate.ps1"
`$env:JAVA_HOME = "$jdkHome"
`$env:Path = "`$env:JAVA_HOME\bin;`$env:Path"
`$env:OREKIT_DATA = "$od"
Write-Host "sim env ready | JAVA_HOME=`$env:JAVA_HOME" -ForegroundColor Green
Write-Host 'run:  python run_simulator.py   (full physics + viewer http://127.0.0.1:5000)' -ForegroundColor Cyan
"@ | Out-File -FilePath $actSim -Encoding utf8
Ok "VS Code helper written: $actSim (not strictly needed anymore - the sim is env-independent now)"

 $vsDir = Join-Path $Root '.vscode'; New-Item -ItemType Directory -Force -Path $vsDir | Out-Null
 $settingsPath = Join-Path $vsDir 'settings.json'
 $settings = [ordered]@{}
if (Test-Path $settingsPath) {
  $raw = Get-Content $settingsPath -Raw
  $raw = $raw.TrimStart([char]0xFEFF)
  $parsed = $null
  try { $parsed = $raw | ConvertFrom-Json } catch {}
  if (-not $parsed) {
    $stripped = ($raw -replace '/\*[\s\S]*?\*/','') -replace '(?m)^\s*//.*$',''
    $stripped = $stripped -replace ',\s*([\]}])', '$1'
    try { $parsed = $stripped | ConvertFrom-Json } catch {}
  }
  if ($parsed) { $parsed.PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value } }
  else { Copy-Item $settingsPath "$settingsPath.bak" -Force; Warn 'existing .vscode/settings.json unreadable (JSONC?) - backed up, writing ours' }
}
 $settings['python.defaultInterpreterPath'] = $VenvPy
 $settings['python.terminal.activateEnvironment'] = $true
($settings | ConvertTo-Json -Depth 6) | Out-File -FilePath $settingsPath -Encoding utf8
Ok 'VS Code pinned to .venv (python.defaultInterpreterPath)'

 $gi = Join-Path $Root '.gitignore'
 $want = @('tools/','Run-Sim.bat','run-sim.ps1','setup.log','sim-boot.*.log','sim-run.log','.env','run_simulator.py.orig')
 $cur = if (Test-Path $gi) { Get-Content $gi } else { @() }
 $add = $want | Where-Object { $cur -notcontains $_ }
if ($add) { Add-Content -Path $gi -Value ''; Add-Content -Path $gi -Value '# auto-added by setup.ps1'; $add | ForEach-Object { Add-Content -Path $gi -Value $_ }; Ok ".gitignore updated (added: $($add -join ', '))" }

# ============ Step 5 : frontend (self-provisioning Node) ===================
Step 'Frontend build (auto-gets Node if missing -> frontend/dist/index.html)'
if ($SkipFrontend) { Warn 'skipped via -SkipFrontend (viewer will 503 until you build).' }
elseif (Test-Path $DistIndex) { Ok "dist already present: $DistIndex" }
else {
  $npmCmd = $null
  if (Test-Npm) { $npmCmd = 'npm.cmd'; Ok 'using system npm' }
  elseif (Test-PortableNode) {
    $env:Path = "$PortableNodeDir;$env:Path"
    $npmCmd = Join-Path $PortableNodeDir 'npm.cmd'
    Ok "using cached portable Node: $PortableNodeDir (no download needed)"
  }
  if (-not $npmCmd -and $InstallNode) { if (Install-NodeViaWinget) { $npmCmd = 'npm.cmd' } }
  if (-not $npmCmd) {
    if (-not (Install-PortableNode $NodeVersion)) {
      Warn 'portable Node download failed - trying winget as fallback ...'
      if (Install-NodeViaWinget) { $npmCmd = 'npm.cmd' }
    } else {
      $env:Path = "$PortableNodeDir;$env:Path"
      $npmCmd = Join-Path $PortableNodeDir 'npm.cmd'
    }
  }
  if ($npmCmd) {
    Push-Location (Join-Path $Root 'frontend')
    try {
      Say '  npm install ...' DarkCyan
      $ec = Run $npmCmd @('install')
      if ($ec -ne 0) {
        Warn 'npm install failed - cleaning node_modules + package-lock and retrying once ...'
        Remove-Item -Recurse -Force '.\node_modules' -ErrorAction SilentlyContinue
        Remove-Item -Force '.\package-lock.json' -ErrorAction SilentlyContinue
        $ec = Run $npmCmd @('install')
      }
      Say '  npm run build ...' DarkCyan
      $ec = Run $npmCmd @('run','build')
    } finally { Pop-Location }
    if (Test-Path $DistIndex) { Ok "frontend built: $DistIndex" }
    else { $FrontendMissing = $true; Warn "npm build did not produce frontend/dist/index.html. Open setup.log, search 'npm ERR!'." }
  }
  elseif ($DistUrl) {
    Warn "no Node available - fetching prebuilt frontend from -DistUrl ..."
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $dz = Join-Path $ToolsDir 'frontend-dist.zip'
    try { Invoke-WebRequest -Uri $DistUrl -OutFile $dz -UseBasicParsing }
    catch { $FrontendMissing = $true; Warn "dist download failed: $($_.Exception.Message)" }
    if (-not $FrontendMissing) {
      $tmp = Join-Path $ToolsDir 'dist-extract'
      if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
      Expand-Archive -Path $dz -DestinationPath $tmp -Force
      $src = $null
      if     (Test-Path (Join-Path $tmp 'dist\index.html')) { $src = Join-Path $tmp 'dist' }
      elseif (Test-Path (Join-Path $tmp 'index.html'))      { $src = $tmp }
      if ($src) {
        $dest = Join-Path $Root 'frontend\dist'
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
        Move-Item $src $dest
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        Ok "prebuilt frontend installed: $DistIndex"
      } else { $FrontendMissing = $true; Warn 'the -DistUrl zip did not contain dist/index.html at its root.' }
    }
  }
  else {
    $FrontendMissing = $true
    Warn 'NO Node and NO download path succeeded - frontend cannot be built here (needs internet once, or -DistUrl, or copy frontend\dist).'
  }
}

# ====================== Step 6 : smoke test + warm-up =======================
Step 'Smoke test + timed warm-up (JVM / orekit-data / full physics import)'
if ($NoSmoke) { Warn 'skipped via -NoSmoke (including the warm-up import).' }
else {
  $ec = Run $VenvPy @('-m','py_compile',(Join-Path $Root 'run_simulator.py'))
  if ($ec -ne 0) { Fail 'run_simulator.py failed to compile - if setup patched it, restore run_simulator.py.orig and commit the shielded version by hand. See setup.log.' }
  Ok 'run_simulator.py compiles'

  $env:OREKIT_DATA = $od
  $ec = Run $VenvPy @('-c',"from engine.orekit_runtime import ensure_initialized; print('orekit-smoke-ok')")
  if ($ec -ne 0) {
    $tail = Tail-File $LogFile 25
    if ($tail -match 'jvm\.dll|JVMNotFound|JAVA_HOME') { Fail "JVM still not found (jdk4py path was $jdkHome). Fixes: 1) new terminal 2) $VenvPy -m pip install --force-reinstall jdk4py orekit-jpype 3) re-run Setup.bat. Log tail:`n$tail" }
    elseif ($tail -match 'orekit-data|EGM2008|egm2008') { Fail "orekit-data invalid (EGM2008 check failed). Log tail:`n$tail" }
    else { Fail "Orekit smoke import failed. Tail of setup.log:`n$tail" }
  }
  Ok 'JVM + orekit-data load cleanly'

  $ec = Run $VenvPy @('-c',"import app; print('viewer-import-ok')")
  if ($ec -ne 0) { Fail 'import app failed (viewer-only, no Java needed) - a python dep is broken. See setup.log.' }
  Ok 'viewer imports cleanly (no JVM needed)'

  Say '  warm-up: importing the FULL physics chain once, with timing (silent 1-3 min is NORMAL) ...' DarkCyan
  $t0 = Get-Date
  $ec = Run $VenvPy @('-c',"import time; t=time.time(); import satellite_flight_visualisation; print('physics-import-ok %.1fs' % (time.time()-t))")
  if ($ec -ne 0) {
    $tail = Tail-File $LogFile 20
    Warn "full physics-chain import did not complete:`n$tail"
    Warn 'the live-boot step below will surface the real error and auto-fallback if needed.'
  } else {
    $secs = [int][Math]::Ceiling(((Get-Date) - $t0).TotalSeconds)
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    "$secs" | Out-File -FilePath (Join-Path $ToolsDir 'import-time.txt') -Encoding ascii
    Ok "full physics chain imports cleanly (~$secs s; later boots are faster)"
  }
}

# ============ Step 7 : live boot proof (status-code aware) ==================
Step "Live boot proof (start sim, wait up to ${BootTimeoutSec}s, then stop)"
Write-Launchers
 $targetPath = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
 $mode = if ($ViewerOnly) { 'VIEWER-ONLY (app.py, no physics/Java)' } else { 'FULL SIM (run_simulator.py, physics + viewer)' }
Log "  mode: $mode"
Remove-Item $BootOut, $BootErr -Force -ErrorAction SilentlyContinue
 $simProc = Start-Process -FilePath $VenvPy -ArgumentList @('-u', "`"$targetPath`"") -WorkingDirectory $Root `
               -PassThru -WindowStyle Hidden -RedirectStandardOutput $BootOut -RedirectStandardError $BootErr
Ok "sim process started (pid $($simProc.Id)); output -> sim-boot.out.log / sim-boot.err.log"
 $up = $false; $partial = $false; $sawCode = ''; $bootStart = Get-Date
 $deadline = $bootStart.AddSeconds($BootTimeoutSec)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  $elapsed = [int]((Get-Date) - $bootStart).TotalSeconds
  if ($simProc.HasExited) {
    $code = $simProc.ExitCode
    $tail = Tail-File $BootErr 20; if (-not $tail) { $tail = Tail-File $BootOut 20 }
    if ($ViewerOnly) { Fail "viewer-only process exited early (code $code). Last output:`n$tail" }
    Warn "physics process exited early (code $code) - last output:`n$tail"
    if     ($tail -match 'Address already in use|Only one usage of each socket|10048') { Say '  -> diagnosis: PORT 5000 BUSY. Close the old python.exe (Task Manager) or reboot, then re-run.' Yellow }
    elseif ($tail -match 'jvm\.dll|JVMNotFound|No JVM') { Say '  -> diagnosis: JVM missing. Re-run Setup.bat (reinstalls jdk4py).' Yellow }
    elseif ($tail -match 'ModuleNotFoundError') { Say '  -> diagnosis: missing python module. Re-run Setup.bat without -ReuseVenv.' Yellow }
    Warn 'auto-fallback: retrying in VIEWER-ONLY mode to at least prove the frontend/server ...'
    $targetPath = Join-Path $Root 'app.py'; $mode = 'VIEWER-ONLY fallback'
    Remove-Item $BootOut, $BootErr -Force -ErrorAction SilentlyContinue
    $simProc = Start-Process -FilePath $VenvPy -ArgumentList @('-u', "`"$targetPath`"") -WorkingDirectory $Root `
                   -PassThru -WindowStyle Hidden -RedirectStandardOutput $BootOut -RedirectStandardError $BootErr
    $bootStart = Get-Date; $deadline = $bootStart.AddSeconds($BootTimeoutSec)
    continue
  }
  $code = Get-HttpCode 5000
  $sawCode = $code
  if ($code -eq '200') { $up = $true; break }
  if ($code -eq '503') {
    $body = Get-HttpBody 5000
    if ($FrontendMissing -or ($body -match 'Build the frontend')) { $partial = $true; break }
    $snip = if ($body) { $body.Substring(0, [Math]::Min(100, $body.Length)) } else { '(empty)' }
    Say "  [${elapsed}s] HTTP 503 - server is UP but unhappy. Body: $snip" Yellow
  } elseif ($code -eq 'LISTENING' -and $FrontendMissing) { $partial = $true; break }
  elseif ($code -eq '000') { Say "  [${elapsed}s] no listener yet (JVM/physics warming up) ..." DarkCyan }
  else { Say "  [${elapsed}s] HTTP $code - server up ..." DarkCyan }
}
if ($up) {
  Ok "LIVE - viewer answered HTTP 200 ($mode)"
  $api = Get-ApiCode '/api/latest'
  if ($api -match '^2\d\d$') { Ok "telemetry endpoint /api/latest answers $api" }
  else { Warn "/api/latest not 2xx yet (physics warming up - normal): $api" }
}
elseif ($partial) {
  Warn 'SERVER IS UP but returns 503 - frontend/dist is missing on this machine.'
  $api = Get-ApiCode '/api/latest'
  if ($api -match '^2\d\d$') { Ok "backend + telemetry PROVEN (/api/latest answers $api) - only the web UI files are missing" }
}
else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  $tail = Tail-File $BootErr 20; if (-not $tail) { $tail = Tail-File $BootOut 20 }
  Fail "no HTTP 200 within ${BootTimeoutSec}s (last probe: $sawCode). Boot log tail:`n$tail`nIf physics needs longer on this machine, re-run with:  Setup.bat -BootTimeoutSec 600"
}

# ====================== Step 8 : stop + LAUNCH for the user ================
Step 'Stop proof-process + launch the sim for you'
if ($KeepRunning) {
  Warn "keeping proof sim alive per -KeepRunning (pid $($simProc.Id)) - open http://127.0.0.1:5000 now."
} else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction Stop; Ok "proof-process stopped (pid $($simProc.Id))" }
  catch { Warn "could not kill pid $($simProc.Id) - close it via Task Manager." }
  Start-Sleep -Seconds 2
  if (-not (Test-PortFree 5000)) { Kill-Port 5000; Start-Sleep -Seconds 1 }
  if (Test-PortFree 5000) { Ok 'port 5000 free again' } else { Warn 'port 5000 still busy - kill leftover python.exe via Task Manager.' }
}

 $autoStarted = $false
if ($up -and -not $KeepRunning -and -not $NoAutoRun) {
  $runBat = Join-Path $Root 'Run-Sim.bat'
  if (Test-Path $runBat) {
    Start-Sleep -Seconds 2
    Say 'launching the sim for you in its own window - browser opens automatically. You can close THIS Setup window.' Cyan
    if ($ViewerOnly) { Start-Process -FilePath $runBat -ArgumentList '-ViewerOnly' -WorkingDirectory $Root }
    else             { Start-Process -FilePath $runBat -WorkingDirectory $Root }
    $autoStarted = $true
  }
}

Write-Host ''
if ($up) {
  Write-Host '============================================================' -ForegroundColor Green
  Write-Host ' SETUP COMPLETE - everything proven working end-to-end.' -ForegroundColor Green
  Write-Host '============================================================' -ForegroundColor Green
  if ($autoStarted) {
    Write-Host ' THE SIM IS ALREADY STARTING in its own window.' -ForegroundColor Cyan
    Write-Host ' Browser opens by itself at http://127.0.0.1:5000 .' -ForegroundColor White
  }
} else {
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' SETUP ~90% COMPLETE - backend proven, UI files missing' -ForegroundColor Yellow
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' Re-run WITH internet:  Setup.bat -ReuseVenv   (auto-fetches Node + builds)' -ForegroundColor White
}
Write-Host ''
Write-Host ' FROM NOW ON, to run the sim:  double-click  Run-Sim.bat' -ForegroundColor Cyan
Write-Host ' Re-running Setup.bat later is safe - it stops the sim itself first.' -ForegroundColor Gray
Write-Host ' VS Code also works with ZERO setup:  python run_simulator.py' -ForegroundColor Gray
Write-Host ' Viewer-only:  Run-Sim.bat -ViewerOnly   (or python app.py)' -ForegroundColor Gray
Write-Host " Full log: $LogFile   Boot log: $BootOut / $BootErr" -ForegroundColor Gray