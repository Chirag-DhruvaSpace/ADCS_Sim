# ============================================================================
#  setup.ps1 - LEAP-2 MBD Simulation - one-click setup (v8)
#  Flow: git clone repo -> double-click Setup.bat -> use VS Code normally.
#
#  v8 vs v7 - per user request:
#   * NO separate launcher files (no Run-Sim.bat / run-sim.ps1 / opener)
#   * NO auto-launch at the end. Setup downloads, builds, verifies (HTTP 200),
#     then STOPS everything and leaves the machine clean for VS Code.
#   * Setup always stops any running sim first (safe to re-run anytime).
#   * run_simulator.py patched/upgraded to shield v2: friendly "already
#     running" guard (no more WinError 10048 tracebacks on double-runs).
#  Kept from v7: bulletproof .venv teardown (kill only venv processes, cmd
#  rmdir with retries), orekit-data auto-download, portable-Node auto-fetch,
#  proxy-immune 000/503/200 boot probe, boot-log capture + diagnosis.
# ============================================================================
param(
  [switch]$ReuseVenv,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke,
  [switch]$InstallNode,
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

# ---------- stop everything that runs from inside .venv --------------------
# Kills ONLY: processes whose executable lives inside .venv, leftover
# run-sim/Run-Sim wrappers from older setups, and the port-5000 owner.
function Stop-VenvProcesses([string]$venvDir) {
  Say '  stopping any running sim + processes from inside .venv ...' DarkCyan
  try {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($venvDir, [StringComparison]::OrdinalIgnoreCase)) -or
      ($_.CommandLine -and $_.CommandLine -match 'run-sim\.ps1|Run-Sim\.bat|open-when-ready\.ps1')
    }
    foreach ($p in $procs) {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Log "  stopped pid $($p.ProcessId): $(if ($p.ExecutablePath) { $p.ExecutablePath } else { $p.CommandLine })"
    }
  } catch { Log "  process scan failed: $($_.Exception.Message)" }
  try {
    Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Log "  stopped port-5000 owner pid $($_.OwningProcess)" }
  } catch {}
  Start-Sleep -Seconds 2
}
# cmd rmdir /s /q: immune to the PowerShell "directory is not empty" race.
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

# --- upgrades run_simulator.py to shield v2 (double-run guard) -------------
function Ensure-RunSimShield {
  $rs = Join-Path $Root 'run_simulator.py'
  if (-not (Test-Path $rs)) { Warn 'run_simulator.py not found - skipping patch step.'; return }
  $raw = Get-Content $rs -Raw
  if ($raw -match 'LEAP2_BOOT_SHIELD v2') { Ok 'run_simulator.py is the shielded v2 (self-set JAVA_HOME, boot immunity, double-run guard)'; return }
  $known = ($raw -match 'Run physics and the viewer with shared command state') -and
           ($raw -match 'from satellite_flight_visualisation import run_simulation, _telemetry_publisher') -and
           ($raw -match 'run_simulation\(\)')
  if (-not $known) { Warn 'run_simulator.py not recognized - NOT patching. Commit the shielded v2 file from the README/setup source.'; return }
  if ($NoPatchRunSim) { Warn 'run_simulator.py patch skipped via -NoPatchRunSim.'; return }
  if (-not (Test-Path "$rs.orig")) { Copy-Item $rs "$rs.orig" -Force }
  $new = @'
"""Run physics and the viewer with shared command state; no Flask reloader."""
# LEAP2_BOOT_SHIELD v2 -- marker checked by setup.ps1; do not remove.
import os
import signal
import socket
import threading
from threading import Thread

VIEWER_PORT = 5000


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


def _already_running():
    """True if another sim instance is already serving the viewer port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', VIEWER_PORT)) == 0


_stop_heartbeat = threading.Event()


def _heartbeat():
    n = 0
    while not _stop_heartbeat.wait(10):
        n += 10
        print(f'  ... still starting up ({n}s) - normal, wait for the '
              f'"Viewer:" line', flush=True)


def main():
    if _already_running():
        print(f'LEAP-2 sim: ALREADY RUNNING in another window '
              f'(port {VIEWER_PORT} answers).', flush=True)
        print(f'  -> open http://127.0.0.1:{VIEWER_PORT} in your browser, or',
              flush=True)
        print('     close the other sim window/terminal and run this again.',
              flush=True)
        raise SystemExit(0)
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
        server = lambda: serve(app, host='127.0.0.1', port=VIEWER_PORT,
                               threads=4)
    except ImportError:
        server = lambda: app.run(host='127.0.0.1', port=VIEWER_PORT,
                                 threaded=True, debug=False, use_reloader=False)
    Thread(target=server, name='viewer-http', daemon=True).start()
    print(f'Viewer: http://127.0.0.1:{VIEWER_PORT}', flush=True)
    try:
        run_simulation()
    except OSError as e:
        # WinError 10048: another instance already bound the firmware/SITL port
        if getattr(e, 'winerror', None) == 10048 or e.errno in (48, 98, 10048):
            print('\nAnother LEAP-2 sim instance is already running (its port '
                  'is already bound).', flush=True)
            print('Close the other sim window/terminal and run this again.',
                  flush=True)
            raise SystemExit(1)
        raise


if __name__ == '__main__':
    main()
'@
  $new | Out-File -FilePath $rs -Encoding utf8
  Ok 'run_simulator.py upgraded to shield v2 (backup: run_simulator.py.orig). COMMIT the v2 file once - then this step is a no-op.'
}

# ============================== banner =====================================
'' | Out-File -FilePath $LogFile -Encoding utf8
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' LEAP-2 MBD Simulation : one-click setup (v8)' -ForegroundColor Cyan
Write-Host " Root : $Root" -ForegroundColor Gray
Write-Host " Log  : $LogFile" -ForegroundColor Gray
Write-Host ' Setup ONLY installs + verifies, then stops everything.' -ForegroundColor Gray
Write-Host ' Running the sim afterwards = VS Code, as usual (see end).' -ForegroundColor Gray
Write-Host ' Safe to re-run anytime - Setup stops a running sim itself.' -ForegroundColor Gray
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
if (Test-PortFree 5000) { Ok 'port 5000 free' } else { Warn 'port 5000 busy (a sim is running) - Setup stops it automatically in Step 2.' }
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force } catch {}
Ensure-RunSimShield

# ====================== Step 2 : fresh venv ================================
Step 'Fresh virtual environment (.venv)'
Stop-VenvProcesses $VenvDir      # always - makes re-runs safe
if ((Test-Path $VenvDir) -and (-not $ReuseVenv)) {
  Log '  removing old .venv ...'
  if (Remove-Tree $VenvDir) { Ok 'old .venv deleted cleanly' }
  else {
    Fail ("old .venv could not be fully deleted - OneDrive/antivirus/VS Code are holding files inside it. Do this, then re-run Setup.bat:`n" +
          "   1) close VS Code COMPLETELY (File > Exit) and every sim/console window`n" +
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
Ok "jvm.dll present: $jdkHome\bin\server\jvm.dll (run_simulator.py sets this itself too - no terminal setup needed)"

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
Ok 'VS Code pinned: opening a terminal there auto-activates this .venv'

 $gi = Join-Path $Root '.gitignore'
 $want = @('tools/','setup.log','sim-boot.*.log','sim-run.log','.env','run_simulator.py.orig')
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
  if ($ec -ne 0) { Fail 'run_simulator.py failed to compile - if setup patched it, restore run_simulator.py.orig and commit the v2 file by hand. See setup.log.' }
  Ok 'run_simulator.py compiles'

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

  Say '  warm-up: importing the FULL physics chain once, with timing ...' DarkCyan
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

# ============ Step 7 : live boot proof (then STOP) ==========================
Step "Live boot proof (start sim hidden, wait up to ${BootTimeoutSec}s for 200, then stop)"
 $targetPath = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
 $mode = if ($ViewerOnly) { 'VIEWER-ONLY (app.py, no physics/Java)' } else { 'FULL SIM (run_simulator.py, physics + viewer)' }
Log "  mode: $mode"
Remove-Item $BootOut, $BootErr -Force -ErrorAction SilentlyContinue
 $simProc = Start-Process -FilePath $VenvPy -ArgumentList @('-u', "`"$targetPath`"") -WorkingDirectory $Root `
               -PassThru -WindowStyle Hidden -RedirectStandardOutput $BootOut -RedirectStandardError $BootErr
Ok "sim process started hidden (pid $($simProc.Id)); output -> sim-boot.out.log / sim-boot.err.log"
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
    if     ($tail -match 'Address already in use|Only one usage of each socket|10048') { Say '  -> diagnosis: PORT already bound - another sim was running. Setup stops those automatically; re-run Setup.bat.' Yellow }
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

# ====================== Step 8 : stop + clean handover ======================
Step 'Stop everything + clean handover to VS Code'
try { Stop-Process -Id $simProc.Id -Force -ErrorAction Stop; Ok "proof-process stopped (pid $($simProc.Id))" }
catch { Warn "could not kill pid $($simProc.Id) - closing via port owner instead." }
Start-Sleep -Seconds 2
if (-not (Test-PortFree 5000)) { Kill-Port 5000; Start-Sleep -Seconds 1 }
if (Test-PortFree 5000) { Ok 'port 5000 free - machine is clean for VS Code' } else { Warn 'port 5000 still busy - kill leftover python.exe via Task Manager before starting the sim.' }

Write-Host ''
if ($up) {
  Write-Host '============================================================' -ForegroundColor Green
  Write-Host ' SETUP COMPLETE - everything installed AND proven working.' -ForegroundColor Green
  Write-Host '============================================================' -ForegroundColor Green
} else {
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' SETUP ~90% COMPLETE - backend proven, UI files missing' -ForegroundColor Yellow
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' Re-run WITH internet:  Setup.bat -ReuseVenv   (auto-fetches Node + builds)' -ForegroundColor White
}
Write-Host ''
Write-Host ' HOW EVERYONE RUNS THE SIM FROM NOW ON (VS Code, as usual):' -ForegroundColor Cyan
Write-Host '   1. Open VS Code > File > Open Folder > this folder' -ForegroundColor White
Write-Host '      (if it asks to use the existing virtual environment -> Yes)' -ForegroundColor Gray
Write-Host '   2. Open a NEW terminal (Ctrl+`)  - the .venv activates itself' -ForegroundColor White
Write-Host '   3. python run_simulator.py' -ForegroundColor White
Write-Host '   4. open http://127.0.0.1:5000   (Ctrl+C in the terminal stops it)' -ForegroundColor White
Write-Host ' ONE instance at a time - starting a second prints a friendly' -ForegroundColor Gray
Write-Host ' message instead of a port error (shield v2 handles it).' -ForegroundColor Gray
Write-Host ' Viewer-only, no Java:  python app.py' -ForegroundColor Gray
Write-Host " Full log: $LogFile   Boot log: $BootOut / $BootErr" -ForegroundColor Gray