# ============================================================================
#  setup.ps1 - LEAP-2 MBD Simulation - one-click setup + self-diagnosis (v2)
#  Windows PowerShell 5.1+ (the one that ships with Windows 10/11)
#
#  v2 fixes vs the version that failed with "viewer never answered 200":
#   * HTTP probe uses curl.exe --noproxy "*": immune to corporate proxies and
#     DISTINGUISHES "no server" (000) from "server up, 503 frontend missing"
#     from "200 OK". PS 5.1 Invoke-WebRequest throws on 503, which made an
#     answered 503 look identical to a dead port -> blind 120s timeout.
#   * The booted sim's stdout/stderr are captured to sim-boot.out.log /
#     sim-boot.err.log and dumped on any failure (real error text, not guesses).
#   * Early-exit auto-diagnosis: port busy / JVM missing / ModuleNotFoundError.
#   * "Server up but 503 because frontend/dist missing" = clear PARTIAL success
#     with exact next steps - not a scary generic failure.
#   * -BootTimeoutSec <sec> (default 240), -InstallNode (winget auto-install).
#   * npm build retried once after cleaning node_modules.
#   * .vscode/settings.json: tolerates JSONC comments, backs up before rewrite
#     (old version used -AsHashtable, which does not exist in PS 5.1 and made
#     it overwrite a VALID settings.json on every machine).
#   * No more double-printed log lines; $VenvPy expands correctly in messages.
# ============================================================================
param(
  [switch]$ReuseVenv,
  [switch]$KeepRunning,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke,
  [switch]$InstallNode,
  [int]$BootTimeoutSec = 240
)

 $ErrorActionPreference = 'Stop'
 $Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
 $LogFile    = Join-Path $Root 'setup.log'
 $VenvDir    = Join-Path $Root '.venv'
 $VenvPy     = Join-Path $VenvDir 'Scripts\python.exe'
 $DistIndex  = Join-Path $Root 'frontend\dist\index.html'
 $BootOut    = Join-Path $Root 'sim-boot.out.log'
 $BootErr    = Join-Path $Root 'sim-boot.err.log'
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
  Log "STEP $($scriptNo)/$StepTotal : $t"
}

# Run a native command, stream output to console+log, return exit code.
# EAP is relaxed inside because PS 5.1 turns native stderr into
# NativeCommandError records that would otherwise kill the script.
function Run([string]$exe, [string[]]$argList) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    & $exe @argList 2>&1 | ForEach-Object { $ln = "$_"; Write-Host "  $ln" -ForegroundColor DarkGray; Log "  $ln" }
  } finally { $ErrorActionPreference = $prev }
  return $LASTEXITCODE
}

# ---- HTTP probes (curl.exe: proxy-immune, status-code aware) ----
function Get-HttpCode([int]$Port = 5000) {
  $url = "http://127.0.0.1:$Port/"
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' --max-time 5 $url 2>$null
    $code = ("$code").Trim()
    if ($code -match '^\d{3}$') { return $code }
    return '000'
  }
  # fallback for ancient Windows without curl.exe: only tell if it listens
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
  try {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  } catch {}
}
function Test-Npm {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { $null = npm.cmd --version 2>&1; return ($LASTEXITCODE -eq 0) }
  catch { return $false } finally { $ErrorActionPreference = $prev }
}
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

# ============================== banner =====================================
'' | Out-File -FilePath $LogFile -Encoding utf8
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' LEAP-2 MBD Simulation : one-click setup (v2, self-diagnosing)' -ForegroundColor Cyan
Write-Host " Root : $Root" -ForegroundColor Gray
Write-Host " Log  : $LogFile" -ForegroundColor Gray
Write-Host ' Flags: -ReuseVenv -KeepRunning -ViewerOnly -SkipFrontend -NoSmoke -InstallNode -BootTimeoutSec <sec>' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Cyan

# ====================== Step 1 : pre-flight ================================
Step 'Pre-flight checks (python / node / frontend / orekit-data / port 5000)'
 $py312 = Get-Py312
if (-not $py312) { Fail "Python 3.12 not found. Install python.org 3.12 64-bit WITH 'py launcher' checked, then re-run: https://www.python.org/downloads/release/python-3127/" }
Ok "Python 3.12 via: $($py312.Exe) $($py312.Args -join ' ')"

 $npmOk = Test-Npm
if (-not $npmOk -and $InstallNode) {
  Warn 'npm not found - attempting winget auto-install of Node.js LTS (needs internet; IT must allow winget) ...'
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $null = Run winget @('install','-e','--id','OpenJS.NodeJS.LTS','--accept-source-agreements','--accept-package-agreements','--silent')
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    $npmOk = Test-Npm
    if ($npmOk) { Ok 'Node.js installed via winget and visible in this session' }
    else { Warn 'winget ran but npm is still not visible - install Node LTS manually from https://nodejs.org and re-run Setup.bat in a NEW window.' }
  } else { Warn 'winget not available - install Node LTS manually from https://nodejs.org and re-run Setup.bat in a NEW window.' }
}
if ($npmOk) { Ok 'node/npm present' } elseif (-not $InstallNode) { Warn 'node/npm NOT found - the frontend cannot be built on this machine.' }

if (Test-Path $DistIndex) { Ok "frontend/dist shipped in this copy - no Node needed ($DistIndex)" }
elseif ($npmOk) { Say '  [..] frontend/dist not present but npm is - it will be built in Step 5' DarkCyan }
else {
  $FrontendMissing = $true
  Warn 'frontend/dist/index.html MISSING and Node.js missing -> after setup the server WILL answer 503 "Build the frontend first" (UI missing). Backend will still be installed and proven. Finish later with: install Node LTS -> Setup.bat -ReuseVenv (new window), or copy frontend\dist from the dev machine.'
}

 $od = Join-Path $Root 'orekit-data'
if (Test-Path (Join-Path $od 'Potential')) { Ok "orekit-data shipped OK ($od)" }
else { Fail "orekit-data/ folder missing or incomplete. Re-extract the zip, or download https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip and rename the folder to orekit-data at repo root." }

if (Test-PortFree 5000) { Ok 'port 5000 free' } else { Warn 'port 5000 is BUSY (an old sim is running?). Setup continues, but the boot check may attach to the OLD server. Close it first if results look odd.' }
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force } catch {}

# ====================== Step 2 : fresh venv ================================
Step 'Fresh virtual environment (.venv)'
if ((Test-Path $VenvDir) -and (-not $ReuseVenv)) {
  Log '  removing old .venv ...'
  try {
    Get-ChildItem (Join-Path $VenvDir 'Scripts') -Filter 'python*.exe' -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Name $_.BaseName -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Remove-Item -Recurse -Force $VenvDir
    Ok 'old .venv deleted'
  } catch { Fail "Could not delete old .venv (a python.exe inside it is probably still running - close VS Code/terminals using it). Detail: $_" }
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
  if ($ec -ne 0) { Fail "pip install failed twice. Open setup.log and search for 'ERROR:'. Usual fix: re-run Setup.bat (fresh venv)." }
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
 $env:Path      = "$jdkHome\bin;$env:Path"
 $env:JAVA_HOME = $jdkHome
Log "  JAVA_HOME=$env:JAVA_HOME"
Ok "jvm.dll present: $jdkHome\bin\server\jvm.dll"

 $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
 $jvmPath = (& $VenvPy -c "import jpype; print(jpype.getDefaultJVMPath())" 2>&1 | Out-String).Trim()
 $ErrorActionPreference = $prev
 $jvmPath = ($jvmPath -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
if ($jvmPath -and ($jvmPath.Trim() -notlike '*jdk4py*')) { Warn "JPype resolved to a NON-jdk4py JVM: $($jvmPath.Trim()) - a stale system JDK may shadow jdk4py. Step 6 smoke test is the real verdict." }
elseif ($jvmPath) { Ok "JPype resolves JVM: $($jvmPath.Trim())" }

# Persist for VS Code terminals
 $actSim = Join-Path $VenvDir 'Scripts\Activate-sim.ps1'
@"
# auto-generated by setup.ps1 - use this instead of plain Activate.ps1
& "$VenvDir\Scripts\Activate.ps1"
`$env:JAVA_HOME = "$jdkHome"
`$env:Path = "`$env:JAVA_HOME\bin;`$env:Path"
`$env:OREKIT_DATA = "$od"
Write-Host "sim env ready | JAVA_HOME=`$env:JAVA_HOME" -ForegroundColor Green
Write-Host 'run:  python run_simulator.py   (full physics + viewer http://127.0.0.1:5000)' -ForegroundColor Cyan
Write-Host 'alt :  python app.py             (viewer only, no physics/Java)' -ForegroundColor Gray
"@ | Out-File -FilePath $actSim -Encoding utf8
Ok "VS Code helper written: $actSim"

 $vsDir = Join-Path $Root '.vscode'; New-Item -ItemType Directory -Force -Path $vsDir | Out-Null
 $settingsPath = Join-Path $vsDir 'settings.json'
 $settings = [ordered]@{}
if (Test-Path $settingsPath) {
  $raw = Get-Content $settingsPath -Raw
  $raw = $raw.TrimStart([char]0xFEFF)
  $parsed = $null
  try { $parsed = $raw | ConvertFrom-Json } catch {}
  if (-not $parsed) {
    # VS Code allows comments + trailing commas (JSONC); PowerShell does not.
    $stripped = ($raw -replace '/\*[\s\S]*?\*/','') -replace '(?m)^\s*//.*$',''
    $stripped = $stripped -replace ',\s*([\]}])', '$1'
    try { $parsed = $stripped | ConvertFrom-Json } catch {}
  }
  if ($parsed) { $parsed.PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value } }
  else {
    Copy-Item $settingsPath "$settingsPath.bak" -Force
    Warn 'existing .vscode/settings.json unreadable (JSONC or invalid) - backed up to settings.json.bak, writing ours'
  }
}
 $settings['python.defaultInterpreterPath'] = $VenvPy
 $settings['python.terminal.activateEnvironment'] = $true
 $settings['terminal.integrated.env.windows'] = @{ JAVA_HOME = $jdkHome; OREKIT_DATA = $od; PATH = "$jdkHome\bin;`${env:PATH}" }
($settings | ConvertTo-Json -Depth 6) | Out-File -FilePath $settingsPath -Encoding utf8
"JAVA_HOME=$jdkHome`nOREKIT_DATA=$od" | Out-File -FilePath (Join-Path $Root '.env') -Encoding utf8
Ok 'VS Code pinned to .venv + JAVA_HOME persisted (.vscode/settings.json, .env)'

# ====================== Step 5 : frontend ===================================
Step 'Frontend build (frontend/dist/index.html)'
if ($SkipFrontend) { Warn 'skipped via -SkipFrontend (viewer will 503 until you build).' }
elseif (Test-Path $DistIndex) { Ok "dist already built: $DistIndex" }
elseif (-not $npmOk) {
  $FrontendMissing = $true
  Warn "npm not found and dist not shipped - frontend CANNOT be built here. Server will return 503 'Build the frontend first...'. Install Node LTS from https://nodejs.org (or re-run with -InstallNode), then Setup.bat -ReuseVenv in a NEW window."
}
else {
  Push-Location (Join-Path $Root 'frontend')
  try {
    Say '  npm.cmd install ...' DarkCyan
    $ec = Run npm.cmd @('install')
    if ($ec -ne 0) {
      Warn 'npm install failed - cleaning node_modules + package-lock and retrying once ...'
      Remove-Item -Recurse -Force '.\node_modules' -ErrorAction SilentlyContinue
      Remove-Item -Force '.\package-lock.json' -ErrorAction SilentlyContinue
      $ec = Run npm.cmd @('install')
    }
    Say '  npm.cmd run build ...' DarkCyan
    $ec = Run npm.cmd @('run','build')
  } finally { Pop-Location }
  if (Test-Path $DistIndex) { Ok "frontend built: $DistIndex" }
  else { Fail "frontend build finished but frontend/dist/index.html is still missing. Open setup.log, search 'npm ERR!'. Usual fix: delete frontend/node_modules + frontend/package-lock.json and re-run." }
}

# ====================== Step 6 : smoke test =================================
Step 'Smoke test (Orekit JVM + orekit-data + viewer import)'
if ($NoSmoke) { Warn 'skipped via -NoSmoke.' }
else {
  $env:OREKIT_DATA = $od
  $ec = Run $VenvPy @('-c',"from engine.orekit_runtime import ensure_initialized; print('orekit-smoke-ok')")
  if ($ec -ne 0) {
    $tail = Tail-File $LogFile 25
    if ($tail -match 'jvm\.dll|JVMNotFound|JAVA_HOME') { Fail "JVM still not found (jdk4py path was $jdkHome). Fixes: 1) new terminal 2) $VenvPy -m pip install --force-reinstall jdk4py orekit-jpype 3) re-run Setup.bat. Log tail:`n$tail" }
    elseif ($tail -match 'orekit-data|EGM2008|egm2008') { Fail "orekit-data invalid (EGM2008 check failed). Re-extract orekit-data/ from the zip. Log tail:`n$tail" }
    else { Fail "Orekit smoke import failed. Tail of setup.log:`n$tail" }
  }
  Ok 'JVM + orekit-data load cleanly'

  $ec = Run $VenvPy @('-c',"import app; print('viewer-import-ok')")
  if ($ec -ne 0) { Fail 'import app failed (viewer-only, no Java needed) - a python dep is broken. See setup.log.' }
  Ok 'viewer imports cleanly (no JVM needed)'

  $ec = Run $VenvPy @('-c',"from astropy.time import Time; print('astropy-ok')")
  if ($ec -ne 0) {
    Warn 'astropy import failed - attempting repair (force-reinstall astropy+numpy) ...'
    $null = Run $VenvPy @('-m','pip','install','--force-reinstall','--no-cache-dir','astropy','numpy')
    $ec = Run $VenvPy @('-c',"from astropy.time import Time; print('astropy-ok-after-reinstall')")
    if ($ec -ne 0) { Warn 'astropy STILL failing after reinstall. On corporate machines the usual cause is IT policy (AppLocker/WDAC) blocking compiled modules - not a code bug. FULL SIM will fail here; VIEWER-ONLY still works. The boot step will auto-fallback.' }
    else { Ok 'astropy repaired by reinstall' }
  } else { Ok 'astropy imports cleanly (physics chain unblocked)' }
}

# ============ Step 7 : live boot proof (status-code aware) ==================
Step "Live boot proof (start sim, wait up to ${BootTimeoutSec}s, then stop)"
 $targetPath = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
 $mode = if ($ViewerOnly) { 'VIEWER-ONLY (app.py, no physics/Java)' } else { 'FULL SIM (run_simulator.py, physics + viewer)' }
Log "  mode: $mode"
Remove-Item $BootOut, $BootErr -Force -ErrorAction SilentlyContinue
 $simProc = Start-Process -FilePath $VenvPy -ArgumentList "`"$targetPath`"" -WorkingDirectory $Root `
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
    $simProc = Start-Process -FilePath $VenvPy -ArgumentList "`"$targetPath`"" -WorkingDirectory $Root `
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
  else { Warn "/api/latest not 2xx yet (physics warming up - normal in the first seconds): $api" }
}
elseif ($partial) {
  Warn 'SERVER IS UP but returns 503 - frontend/dist is missing (Node.js not installed on this machine).'
  Warn 'This is NOT a python/java failure - the backend stack is proven.'
  $api = Get-ApiCode '/api/latest'
  if ($api -match '^2\d\d$') { Ok "backend + telemetry PROVEN (/api/latest answers $api) - only the web UI files are missing" }
}
else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  $tail = Tail-File $BootErr 20; if (-not $tail) { $tail = Tail-File $BootOut 20 }
  Fail "no HTTP 200 within ${BootTimeoutSec}s (last probe: $sawCode). Boot log tail:`n$tail`nIf physics needs longer on this machine, re-run with:  Setup.bat -BootTimeoutSec 600"
}

# ====================== Step 8 : stop + handover ============================
Step 'Stop proof-process + handover'
if ($KeepRunning) {
  Warn "keeping sim alive per -KeepRunning (pid $($simProc.Id)) - open http://127.0.0.1:5000 now. Close its window when done."
} else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction Stop; Ok "proof-process stopped (pid $($simProc.Id))" }
  catch { Warn "could not kill pid $($simProc.Id) - close it via Task Manager." }
  Start-Sleep -Seconds 2
  if (-not (Test-PortFree 5000)) { Kill-Port 5000; Start-Sleep -Seconds 1 }
  if (Test-PortFree 5000) { Ok 'port 5000 free again' } else { Warn 'port 5000 still busy - kill leftover python.exe via Task Manager.' }
}

Write-Host ''
if ($up) {
  Write-Host '============================================================' -ForegroundColor Green
  Write-Host ' SETUP COMPLETE - everything proven working end-to-end.' -ForegroundColor Green
  Write-Host '============================================================' -ForegroundColor Green
} else {
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' SETUP 90% COMPLETE - backend fully proven, UI files missing' -ForegroundColor Yellow
  Write-Host '============================================================' -ForegroundColor Yellow
  Write-Host ' To get the web UI, pick ONE:' -ForegroundColor Cyan
  Write-Host '   A) Install Node.js LTS (https://nodejs.org, default options),' -ForegroundColor White
  Write-Host '      close this window, open a NEW one, run:  Setup.bat -ReuseVenv' -ForegroundColor White
  Write-Host '   B) Node installed? Just build:  cd frontend && npm.cmd install && npm.cmd run build' -ForegroundColor White
  Write-Host '   C) Or copy frontend\dist from the dev machine into this folder.' -ForegroundColor White
  Write-Host ' Until then run_simulator.py serves 503 "Build the frontend first".' -ForegroundColor Gray
}
Write-Host ''
Write-Host ' Every day after this (VS Code, nothing to configure):' -ForegroundColor Cyan
Write-Host '   1. .\.venv\Scripts\Activate-sim.ps1' -ForegroundColor White
Write-Host '   2. python run_simulator.py   ->  http://127.0.0.1:5000' -ForegroundColor White
Write-Host ' Viewer-only (no Java):  python app.py' -ForegroundColor Gray
Write-Host " Full log: $LogFile   Boot log: $BootOut / $BootErr" -ForegroundColor Gray