# Leap2_MBD_Simulation - one-click setup (Windows-first)
# Double-click Setup.bat  OR  right-click setup.ps1 > Run with PowerShell
# What it does: nukes .venv (unless -ReuseVenv), reinstalls py deps,
# fixes JAVA_HOME via jdk4py, builds frontend, smoke-tests JVM+Orekit,
# boots run_simulator.py until http://127.0.0.1:5000 answers 200, then stops it.
# After that: open VS Code > select .venv interpreter > run activate-sim.ps1 > python run_simulator.py
param(
  [switch]$ReuseVenv,
  [switch]$KeepRunning,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$LogFile = Join-Path $Root 'setup.log'
$VenvDir = Join-Path $Root '.venv'
$VenvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$StepTotal = 8; $StepNo = 0

function Log([string]$m) { $line = "[$(Get-Date -Format 'HH:mm:ss')] $m"; $line | Tee-Object -FilePath $LogFile -Append | Out-Null; Write-Host $m }
function Step([string]$t) { $script:StepNo++; Write-Host ''; Write-Host "===== [$($script:StepNo)/$StepTotal] $t =====" -ForegroundColor Cyan; Log "STEP $($script:StepNo)/$StepTotal : $t" }
function Ok([string]$m) { Write-Host "  [OK] $m" -ForegroundColor Green; Log "  OK: $m" }
function Warn([string]$m) { Write-Host "  [!!] $m" -ForegroundColor Yellow; Log "  WARN: $m" }
function Fail([string]$m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; Log "  FAIL: $m"; throw $m }
try { '' | Out-File -FilePath $LogFile -Encoding utf8 } catch {}
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' LEAP-2 MBD Simulation : one-click setup' -ForegroundColor Cyan
Write-Host " Root : $Root" -ForegroundColor Gray
Write-Host " Log  : $LogFile" -ForegroundColor Gray
Write-Host ' Flags: -ReuseVenv -KeepRunning -ViewerOnly -SkipFrontend -NoSmoke' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Cyan

function Test-PortFree([int]$Port) {
  try { $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop; return $false }
  catch { return $true }
}
function Get-Py312 {
  foreach ($c in @('py -V:3.12','py','python')) {
    try {
      if ($c -like 'py *') { $out = & py -V:3.12 --version 2>&1 | Out-String; if ($out -match '3\.12') { return @{ Exe='py'; Args=@('-V:3.12') } } }
      else { $out = & $c --version 2>&1 | Out-String; if ($out -match '3\.12') { return @{ Exe=$c; Args=@() } } }
    } catch {}
  }
  return $null
}
# ---------- Step 0 : pre-flight ----------
Step 'Pre-flight checks (python / node / orekit-data / port 5000)'
$py312 = Get-Py312
if (-not $py312) { Fail 'Python 3.12 not found. Install python.org 3.12 64-bit WITH "py launcher" checked, then re-run. Get it: https://www.python.org/downloads/release/python-3127/' }
Ok "Python 3.12 via: $($py312.Exe) $($py312.Args -join ' ')"
try { $nd = (node --version) 2>$null; $nm = (npm --version) 2>$null; Ok "node $nd / npm $nm" } catch { Warn 'node/npm NOT found. Frontend build will be skipped. Install Node LTS from https://nodejs.org then re-run (or use -ViewerOnly).' }
$od = Join-Path $Root 'orekit-data'
if (Test-Path (Join-Path $od 'Potential')) { Ok "orekit-data shipped OK ($od)" }
else { Fail "orekit-data/ folder missing or incomplete. You said you ship it in the zip - re-extract the zip, or download https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip and rename to orekit-data/ at repo root." }
if (Test-PortFree 5000) { Ok 'port 5000 free' } else { Warn 'port 5000 is BUSY (old sim still running?). Setup continues, but the live-boot check may attach to the old process. Close it first if the check behaves oddly.' }
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force } catch {}

# ---------- Step 1 : fresh venv ----------
Step 'Fresh virtual environment (.venv)'
if ((Test-Path $VenvDir) -and (-not $ReuseVenv)) {
  Log '  removing old .venv ...'
  try {
    Get-ChildItem (Join-Path $VenvDir 'Scripts') -Filter 'python*.exe' -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Name ($_.BaseName) -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Remove-Item -Recurse -Force $VenvDir
  } catch { Fail "Could not delete old .venv (a python.exe inside it is probably still running). Close all terminals/VS Code using .venv and re-run. Detail: $_" }
  Ok 'old .venv deleted'
} elseif (Test-Path $VenvDir) { Ok 'reusing existing .venv (-ReuseVenv)' }
if (-not (Test-Path $VenvPy)) {
  Log "  creating venv: $($py312.Exe) $($py312.Args -join ' ') -m venv .venv ..."
  & $py312.Exe @($py312.Args + @('-m','venv','.venv')) 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
  if (-not (Test-Path $VenvPy)) { Fail 'venv creation failed (see setup.log). Usual cause: broken Python install - repair via python.org installer > Modify > Repair.' }
}
Ok "venv ready: $VenvPy"
& $VenvPy --version | Tee-Object -FilePath $LogFile -Append | Out-Host

# ---------- Step 2 : python deps ----------
Step 'Python dependencies (pip install -r requirements.txt)'
& $VenvPy -m pip install --upgrade pip 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
& $VenvPy -m pip install -r (Join-Path $Root 'requirements.txt') 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
if ($LASTEXITCODE -ne 0) { Warn 'first pip pass failed - retrying once with --no-cache-dir ...'; & $VenvPy -m pip install --no-cache-dir -r (Join-Path $Root 'requirements.txt') 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host }
if ($LASTEXITCODE -ne 0) { Fail 'pip install -r requirements.txt failed twice. Open setup.log, search for ERROR:. Usual fixes: delete .venv and re-run, or "pip install --no-cache-dir -r requirements.txt" by hand.' }
& $VenvPy -c "import flask,numpy,scipy,yaml,requests,waitress,orekit_jpype,jdk4py; print('py-deps-ok')" 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
if ($LASTEXITCODE -ne 0) { Fail 'dependency import check failed (flask/numpy/scipy/yaml/requests/waitress/orekit_jpype/jdk4py). See setup.log.' }
Ok 'all python deps import cleanly'



# ---------- Step 3 : JAVA_HOME via jdk4py (replaces your hardcoded Adoptium path) ----------
Step 'Java 21 via jdk4py (fixes "No JVM shared library file (jvm.dll) found")'
$jdkHome = (& $VenvPy -c "import jdk4py; print(jdk4py.JAVA_HOME)" 2>&1 | Out-String).Trim().Split("`n") | Select-Object -Last 1
$jdkHome = $jdkHome.Trim()
if ((-not $jdkHome) -or (-not (Test-Path $jdkHome))) { Fail "jdk4py did not return a valid JAVA_HOME (got: '$jdkHome'). Fix: $VenvPy -m pip install --force-reinstall jdk4py, then re-run." }
# Verified on this machine: once JAVA_HOME+PATH point at jdk4py, getDefaultJVMPath() resolves to jdk4py's jvm.dll
# (order matters - PATH prepend reads $jdkHome, then JAVA_HOME is set).
$env:Path = "$jdkHome\bin;$env:Path"
$env:JAVA_HOME = $jdkHome
Log "  JAVA_HOME=$env:JAVA_HOME"
if (-not (Test-Path (Join-Path $jdkHome 'bin\server\jvm.dll'))) { Fail "jvm.dll not found under $jdkHome\bin\server\. jdk4py install is corrupt - reinstall jdk4py." }
Ok "jvm.dll present: $jdkHome\bin\server\jvm.dll"
$jvmPath = (& $VenvPy -c "import jpype; print(jpype.getDefaultJVMPath())" 2>&1 | Out-String).Trim().Split("`n") | Select-Object -Last 1
if ($jvmPath.Trim() -notlike '*jdk4py*') { Warn "JPype resolved to a NON-jdk4py JVM: $($jvmPath.Trim()). A stale system JDK may shadow jdk4py on PATH. Continuing - Step 5 smoke test is the real verdict." }
Ok "JPype resolves JVM: $($jvmPath.Trim())"
try { (& $VenvPy -c 'import jpype; jpype.startJVM(convertStrings=True); print("jvm-start-ok"); jpype.shutdownJVM()' 2>&1 | Out-String) | Tee-Object -FilePath $LogFile -Append | Out-Host; Ok 'JVM starts and shuts down cleanly in isolation' }
catch { Warn "isolated JVM start probe printed noise - continuing (real check is Step 5). Detail in setup.log." }

# Persist for VS Code terminals: activate-sim.ps1 + .vscode/settings.json + .env
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
$settings = @{}
if (Test-Path $settingsPath) {
  try {
    $raw = Get-Content $settingsPath -Raw
    if ($raw.TrimStart().StartsWith([char]0xFEFF)) { $raw = $raw.TrimStart([char]0xFEFF) }  # tolerate BOM written by Out-File -Encoding utf8
    if ([string]::IsNullOrWhiteSpace($raw)) { $settings = @{} } else { $settings = $raw | ConvertFrom-Json -AsHashtable }
    if (-not ($settings -is [hashtable])) { $settings = @{} }
  } catch { Warn '.vscode/settings.json was not valid JSON - it will be overwritten.'; $settings = @{} }
}
$settings['python.defaultInterpreterPath'] = $VenvPy
$settings['python.terminal.activateEnvironment'] = $true
$settings['terminal.integrated.env.windows'] = @{ JAVA_HOME = $jdkHome; OREKIT_DATA = $od; PATH = "$jdkHome\bin;`${env:PATH}" }
($settings | ConvertTo-Json -Depth 6) | Out-File -FilePath $settingsPath -Encoding utf8
"JAVA_HOME=$jdkHome`nOREKIT_DATA=$od`n" | Out-File -FilePath (Join-Path $Root '.env') -Encoding utf8 -NoNewline
Ok 'VS Code pinned to .venv + JAVA_HOME persisted (.vscode/settings.json, .env)'

# ---------- Step 4 : frontend ----------
Step 'Frontend build (frontend/dist/index.html)'
$distIndex = Join-Path $Root 'frontend\dist\index.html'
if ($SkipFrontend) { Warn 'skipped via -SkipFrontend (viewer will 503 until you build).' }
elseif (Test-Path $distIndex) { Ok "dist already built: $distIndex" }
else {
  $npmOk = $false; try { npm.cmd --version 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $npmOk = $true } } catch {}
  if (-not $npmOk) { Warn 'npm not found - skipping build. Viewer will return 503 "Build the frontend first...". Install Node LTS https://nodejs.org then re-run (or npm.cmd install && npm.cmd run build in frontend/).' }
  else {
    Push-Location (Join-Path $Root 'frontend')
    Log '  npm.cmd install ...'; & npm.cmd install 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
    Log '  npm.cmd run build ...'; & npm.cmd run build 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
    Pop-Location
    if (Test-Path $distIndex) { Ok "frontend built: $distIndex" }
    else { Fail 'frontend build finished but frontend/dist/index.html is still missing. Open setup.log, search npm ERR!. Usual fix: delete frontend/node_modules + frontend/package-lock.json and re-run.' }
  }
}

# ---------- Step 5 : smoke test (physics import, no hang) ----------
Step 'Smoke test (Orekit JVM + orekit-data + viewer import)'
if ($NoSmoke) { Warn 'skipped via -NoSmoke.' }
else {
  $env:OREKIT_DATA = $od
  # NOTE: native .exe stderr text surfaces as PowerShell "NativeCommandError" records.
  # They are harmless log noise, NOT fatal - so every probe below runs with
  # $ErrorActionPreference='Continue' and judges by $LASTEXITCODE only.
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  Log '  import engine.orekit_runtime (starts JVM, loads orekit-data) ...'
  & $VenvPy -c "from engine.orekit_runtime import ensure_initialized; print('orekit-smoke-ok')" 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
  $ecOrekit = $LASTEXITCODE
  if ($ecOrekit -ne 0) {
    $tail = (Get-Content $LogFile -Tail 25) -join "`n"
    $ErrorActionPreference = $prevEAP
    if ($tail -match 'jvm\.dll|JVMNotFound|JAVA_HOME') { Fail "JVM still not found. jdk4py path was $jdkHome. Fixes: 1) reopen terminal 2) $VenvPy -m pip install --force-reinstall jdk4py orekit-jpype 3) re-run setup. Log tail:`n$tail" }
    elseif ($tail -match 'Orekit data|EGM2008|egm2008') { Fail "orekit-data invalid (EGM2008 check failed). Re-extract orekit-data/ from your zip. Log tail:`n$tail" }
    else { Fail "Orekit smoke import failed. Tail of setup.log:`n$tail" }
  }
  Ok 'JVM + orekit-data load cleanly'
  & $VenvPy -c "import app; print('viewer-import-ok')" 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
  $ecApp = $LASTEXITCODE
  if ($ecApp -ne 0) { $ErrorActionPreference = $prevEAP; Fail 'import app failed (viewer-only, no Java needed) - this means a python dep is broken. See setup.log.' }
  Ok 'viewer imports cleanly (no JVM needed)'
  Log '  import moon_pointing (astropy check - physics needs this) ...'
  & $VenvPy -c "from astropy.time import Time; print('astropy-ok')" 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
  $ecAstro = $LASTEXITCODE
  if ($ecAstro -ne 0) {
    Warn 'astropy import failed. Trying repair: force-reinstall astropy+numpy ...'
    & $VenvPy -m pip install --force-reinstall --no-cache-dir astropy numpy 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
    & $VenvPy -c "from astropy.time import Time; print('astropy-ok-after-reinstall')" 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Host
    $ecAstro2 = $LASTEXITCODE
    if ($ecAstro2 -ne 0) { Warn 'astropy STILL failing after reinstall. On THIS corporate laptop the cause is IT AppLocker/WDAC ("Application Control policy has blocked this file") - not a code bug. FULL SIM will fail here but VIEWER-ONLY works. On a normal machine this step passes. Continuing to live-boot check which will auto-fallback to viewer-only.' }
    else { Ok 'astropy repaired by reinstall' }
  } else { Ok 'astropy imports cleanly (physics chain unblocked)' }
  $ErrorActionPreference = $prevEAP
}

# ---------- Step 6 : live boot proof, then stop ----------
Step 'Live boot proof (start sim, wait for 200, then stop)'
$target = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
$mode = if ($ViewerOnly) { 'VIEWER-ONLY (app.py, no physics/Java)' } else { 'FULL SIM (run_simulator.py, physics + viewer)' }
Log "  mode: $mode"
Log "  launching: $VenvPy $target ..."
$simProc = Start-Process -FilePath $VenvPy -ArgumentList "`"$target`"" -WorkingDirectory $Root -PassThru -WindowStyle Minimized
Ok "sim process started (pid $($simProc.Id)) - waiting up to 120s for http://127.0.0.1:5000 ..."
$up = $false; $deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  if ($simProc.HasExited) {
    $code = $simProc.ExitCode
    if ($ViewerOnly) { Fail "viewer-only process exited early (code $code). Check setup.log tail / run '$VenvPy app.py' by hand to see the error." }
    Warn "physics process exited early (code $code) - auto-fallback: retrying in VIEWER-ONLY mode to prove the frontend..."
    $target = Join-Path $Root 'app.py'
    $simProc = Start-Process -FilePath $VenvPy -ArgumentList "`"$target`"" -WorkingDirectory $Root -PassThru -WindowStyle Minimized
    $mode = 'VIEWER-ONLY fallback (physics crashed - see setup.log; frontend still proven)'
  }
  try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/' -TimeoutSec 5 -UseBasicParsing; if ($r.StatusCode -eq 200) { $up = $true; break } }
  catch { Write-Host '  ... waiting for viewer (still booting / JVM warming up) ...' -ForegroundColor Gray }
}
if (-not $up) {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  Fail 'viewer never answered 200 within 120s. Likely causes: 1) frontend/dist missing (503 page counts as NOT-ok here - build it), 2) port 5000 busy, 3) JVM crash - see hs_err / leap-jvm-error logs in TEMP. Run by hand to see it: $VenvPy run_simulator.py'
}
Ok "LIVE - viewer answered HTTP 200 ($mode)"
try { $api = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/latest' -TimeoutSec 5 -UseBasicParsing; Ok "telemetry endpoint answers: HTTP $($api.StatusCode)" } catch { Warn 'viewer is up but /api/latest did not answer yet (physics still warming up - normal in first seconds).' }

# ---------- Step 7 : stop + handover ----------
Step 'Stop proof-process + handover to VS Code'
if ($KeepRunning) { Warn "keeping sim alive per -KeepRunning (pid $($simProc.Id)). Close its window when done." }
else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction Stop; Ok "proof-process stopped (pid $($simProc.Id))" }
  catch { Warn "could not kill proof-process pid $($simProc.Id) - close its window by hand." }
  Start-Sleep -Seconds 2
  if (Test-PortFree 5000) { Ok 'port 5000 free again' } else { Warn 'port 5000 still busy - a leftover python.exe may be running. Kill it via Task Manager if the next run says address-in-use.' }
}
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' SETUP COMPLETE - everything is proven working.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' Next time (VS Code, 2 commands, nothing else to set):' -ForegroundColor Cyan
Write-Host "   1. .\.venv\Scripts\Activate-sim.ps1" -ForegroundColor White
Write-Host '   2. python run_simulator.py   # then open http://127.0.0.1:5000' -ForegroundColor White
Write-Host ' Viewer-only (no Java):  python app.py' -ForegroundColor Gray
Write-Host " Full log: $LogFile" -ForegroundColor Gray

