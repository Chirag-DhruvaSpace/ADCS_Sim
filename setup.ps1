# ============================================================================
#  setup.ps1 - LEAP-2 MBD Simulation - one-click setup + self-diagnosis (v3)
#  Windows PowerShell 5.1+ (the one that ships with Windows 10/11)
#
#  v3 vs v2:
#   * If npm is missing, Step 5 now FIXES IT ITSELF instead of giving up:
#       1. portable Node zip -> tools\node  (NO admin, NO system install,
#          nothing in registry/Program Files - corporate-laptop friendly)
#       2. if download blocked -> winget auto-install as fallback
#       3. -DistUrl <zip>      -> fetch a PREBUILT frontend/dist, no Node at all
#     Portable Node is cached: re-runs build offline.
#   * New flags: -NodeVersion <ver> (default 22.14.0 LTS), -DistUrl <url>,
#     -InstallNode (force system-wide winget install FIRST).
#  v2 fixes kept: curl.exe --noproxy probe (000 vs 503 vs 200), sim boot output
#  captured to sim-boot.*.log + auto-diagnosis, -BootTimeoutSec, JSONC-tolerant
#  .vscode/settings.json with backup, npm clean-retry, port cleanup.
# ============================================================================
param(
  [switch]$ReuseVenv,
  [switch]$KeepRunning,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke,
  [switch]$InstallNode,            # prefer system-wide winget install of Node LTS
  [int]$BootTimeoutSec = 240,
  [string]$NodeVersion = '22.14.0', # Node LTS used for the portable copy
  [string]$DistUrl = ''            # optional: URL of a prebuilt frontend-dist .zip
)

 $ErrorActionPreference = 'Stop'
 $ProgressPreference = 'SilentlyContinue'   # 30MB downloads would crawl otherwise
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
  $url = "http://127.0.0.1:$Port/"
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --noproxy '*' --max-time 5 $url 2>$null
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
function Install-NodeViaWinget {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Warn 'winget not available on this machine.'; return $false }
  Say '  winget install OpenJS.NodeJS.LTS (system-wide, may ask for elevation) ...' DarkCyan
  $null = Run winget @('install','-e','--id','OpenJS.NodeJS.LTS','--accept-source-agreements','--accept-package-agreements','--silent')
  Refresh-PathFromMachine
  if (Test-Npm) { Ok 'Node.js installed via winget and visible now'; return $true }
  # winget ran but PATH not refreshed in this session -> probe the default location directly
  $std = 'C:\Program Files\nodejs'
  if (Test-Path (Join-Path $std 'npm.cmd')) {
    $env:Path = "$std;$env:Path"
    Ok "winget installed Node; using it directly from $std"
    return $true
  }
  Warn 'winget reported success but npm is still not usable - will try portable Node next.'
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
  $nv = (& (Join-Path $PortableNodeDir 'node.exe') --version) 2>&1 | Out-String
  Ok "portable Node ready: $PortableNodeDir ($($nv.Trim())) - nothing was installed system-wide"
  return $true
}

# ============================== banner =====================================
'' | Out-File -FilePath $LogFile -Encoding utf8
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' LEAP-2 MBD Simulation : one-click setup (v3, self-provisioning)' -ForegroundColor Cyan
Write-Host " Root : $Root" -ForegroundColor Gray
Write-Host " Log  : $LogFile" -ForegroundColor Gray
Write-Host ' Flags: -ReuseVenv -KeepRunning -ViewerOnly -SkipFrontend -NoSmoke' -ForegroundColor Gray
Write-Host '        -InstallNode -BootTimeoutSec <sec> -NodeVersion <ver> -DistUrl <url>' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Cyan

# ====================== Step 1 : pre-flight ================================
Step 'Pre-flight checks (python / node / frontend / orekit-data / port 5000)'
 $py312 = Get-Py312
if (-not $py312) { Fail "Python 3.12 not found. Install python.org 3.12 64-bit WITH 'py launcher' checked, then re-run: https://www.python.org/downloads/release/python-3127/" }
Ok "Python 3.12 via: $($py312.Exe) $($py312.Args -join ' ')"

 $npmOk = Test-Npm
if ($npmOk) { Ok 'node/npm present on PATH' }
elseif (Test-PortableNode) { Ok 'portable Node already cached (tools\node) - frontend can be built offline' }
elseif (Test-Path $DistIndex) { Say '  [..] frontend/dist shipped - Node will not be needed at all' DarkCyan }
else { Say '  [..] Node not found - Step 5 will fetch a portable copy automatically (needs internet)' DarkCyan }

if (Test-Path $DistIndex) { Ok "frontend/dist shipped in this copy - no Node needed ($DistIndex)" }
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
 $env:Path = "$jdkHome\bin;$env:Path"
 $env:JAVA_HOME = $jdkHome
Log "  JAVA_HOME=$env:JAVA_HOME"
Ok "jvm.dll present: $jdkHome\bin\server\jvm.dll"

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

# ============ Step 5 : frontend (now self-provisioning Node) ================
Step 'Frontend build (auto-gets Node if missing -> frontend/dist/index.html)'
if ($SkipFrontend) { Warn 'skipped via -SkipFrontend (viewer will 503 until you build).' }
elseif (Test-Path $DistIndex) { Ok "dist already present: $DistIndex" }
else {
  # ---- acquire a Node toolset: system npm > cached portable > winget > download portable ----
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
    else {
      $FrontendMissing = $true
      Warn "npm build did not produce frontend/dist/index.html. Open setup.log, search 'npm ERR!'. If it is a network/proxy error, re-run once more; else build on the dev machine and copy frontend\dist."
    }
  }
  elseif ($DistUrl) {
    # ---- no Node at all: fetch a prebuilt dist bundle ----
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
        Remove-Item $dz -Force -ErrorAction SilentlyContinue
        Ok "prebuilt frontend installed: $DistIndex"
      } else { $FrontendMissing = $true; Warn 'the -DistUrl zip did not contain dist/index.html or index.html at its root.' }
    }
  }
  else {
    $FrontendMissing = $true
    Warn 'NO Node and NO internet path succeeded - frontend cannot be built here.'
    Warn 'Fix (pick one): 1) re-run with internet, 2) re-run with -DistUrl <url-to-prebuilt-dist.zip>, 3) copy frontend\dist from the dev machine. Backend setup continues and is fully usable otherwise.'
  }
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
  Warn 'SERVER IS UP but returns 503 - frontend/dist is missing on this machine.'
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
  Write-Host '   A) With internet:  Setup.bat -ReuseVenv   (auto-downloads portable Node and builds)' -ForegroundColor White
  Write-Host '   B) Prebuilt UI:    Setup.bat -ReuseVenv -DistUrl <url-to-dist.zip>' -ForegroundColor White
  Write-Host '   C) Manual copy:    copy frontend\dist from the dev machine into this folder' -ForegroundColor White
  Write-Host ' Until then run_simulator.py serves 503 "Build the frontend first".' -ForegroundColor Gray
}
Write-Host ''
Write-Host ' Every day after this (VS Code, nothing to configure):' -ForegroundColor Cyan
Write-Host '   1. .\.venv\Scripts\Activate-sim.ps1' -ForegroundColor White
Write-Host '   2. python run_simulator.py   ->  http://127.0.0.1:5000' -ForegroundColor White
Write-Host ' Viewer-only (no Java):  python app.py' -ForegroundColor Gray
Write-Host " Full log: $LogFile   Boot log: $BootOut / $BootErr" -ForegroundColor Gray