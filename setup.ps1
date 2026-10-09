# ============================================================================
#  setup.ps1 - LEAP-2 MBD Simulation - one-click setup (v10)
#  Flow: git clone repo -> double-click Setup.bat -> use VS Code normally.
#
#  v10 fixes the v9 crash "The operation '[System.Char] * [System.Int32]'
#  is not defined": Windows PowerShell 5.1 cannot multiply a char by a
#  number. All box/block glyphs are now stored as STRINGS, so every
#  ($S.d * $w) is legal string repetition.
#  v10 also adds the presentation layer done right:
#   - true-color (24-bit) VT output when the console supports it,
#     with automatic 16-color fallback and -Plain monochrome mode
#   - big shaded "LEAP-2" block-art banner with 3D drop shadow,
#     per-character gradient + horizontal light shading
#   - starfield, comet sweep animation, gradient progress bars
#  All non-ASCII glyphs are built from code points -> the file itself
#  stays pure ASCII and survives any encoding.
#  Logic is identical to v8: install + verify + stop; no launcher files,
#  no auto-launch; running the sim = VS Code terminal as usual.
# ============================================================================
param(
  [switch]$ReuseVenv,
  [switch]$ViewerOnly,
  [switch]$SkipFrontend,
  [switch]$NoSmoke,
  [switch]$InstallNode,
  [switch]$NoPatchRunSim,
  [switch]$Plain,
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
 $StepTotal  = 8; $StepNo = 0; $StepT0 = Get-Date; $T_Start = Get-Date
 $FrontendMissing = $false; $WarmOk = $true
 $script:Report = New-Object System.Collections.ArrayList
 $script:ArtCache = $null
 $script:t_stepName = ''

# ---------- glyph kit: STRINGS, never [char] (PS 5.1 char*int is illegal) --
 $S = @{
  h    = "$([char]0x2500)"   # -
  d    = "$([char]0x2550)"   # =
  v    = "$([char]0x2502)"   # |
  dv   = "$([char]0x2551)"   # ||
  tl   = "$([char]0x2554)"   # top-left corner
  tr   = "$([char]0x2557)"   # top-right corner
  bl   = "$([char]0x255A)"   # bottom-left corner
  br   = "$([char]0x255D)"   # bottom-right corner
  blk  = "$([char]0x2588)"   # full block
  s1   = "$([char]0x2591)"   # light shade
  s2   = "$([char]0x2592)"   # medium shade
  arr  = "$([char]0x25BA)"   # right pointer
  chk  = "$([char]0x221A)"   # check mark
  crs  = "$([char]0x00D7)"   # multiplication sign
}
 $Spin = @('|','/','-','\')
 $E = [char]27

# ---------- enable VT (true color) when the console supports it -----------
 $script:VT = $false
if (-not $Plain) {
  try {
    $k32 = Add-Type -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int h);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr h, out int m);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr h, int m);
'@ -Name 'K32VT' -Namespace 'LEAP' -PassThru -ErrorAction Stop
    $hnd = $k32::GetStdHandle(-11)
    $m = 0; $null = $k32::GetConsoleMode($hnd, [ref]$m)
    $script:VT = $k32::SetConsoleMode($hnd, ($m -bor 4))
  } catch { $script:VT = $false }
}

# ---------------------------- console kit ----------------------------------
function P([string]$t, [string]$c = 'Gray') { if ($Plain) { $c = 'Gray' }; Write-Host $t -ForegroundColor $c }
function Log([string]$m) { Add-Content -Path $LogFile -Value $m -Encoding UTF8 }
function Info([string]$m) { P ("    {0} {1}" -f $S.arr, $m) DarkCyan; Log ("  >> " + $m) }
function Ok([string]$m)   { P ("    {0} {1}" -f $S.chk, $m) Green;    Log ("  OK: " + $m) }
function Warn([string]$m) { P ("    ! {0}" -f $m) Yellow;             Log ("  WARN: " + $m) }
function Fail([string]$m) { P ("    {0} {1}" -f $S.crs, $m) Red;      Log ("  FAIL: " + $m); throw $m }
function Clear-Line() { Write-Host ("`r" + (' ' * 90) + "`r") -NoNewline }
function Wrap54([string]$m) {
  $out = @()
  foreach ($ln in ($m -split "`r?`n")) {
    $cur = ''
    foreach ($word in ($ln -split ' ')) {
      if (($cur + ' ' + $word).Trim().Length -gt 54) { if ($cur) { $out += $cur }; $cur = $word }
      else { if ($cur) { $cur += ' ' + $word } else { $cur = $word } }
    }
    if ($cur) { $out += $cur }
  }
  return $out
}

# ---------------------------- banner kit -----------------------------------
function Get-Art {
  if ($script:ArtCache) { return $script:ArtCache }
  $K = $S.blk; $C = $S.tr; $Q = $S.tl; $Lc = $S.bl; $Rc = $S.br; $D = $S.d; $V = $S.dv
  $Lt = @{}
  $Lt['L'] = @( ($K+$K+$C+'     '), ($K+$K+$V+'     '), ($K+$K+$V+'     '), ($K+$K+$V+'     '), ($K*7+$C), ($Lc+$D*6+$Rc) )
  $Lt['E'] = @( ($K*7+$C), ($K+$K+$Q+$D*4+$Rc), ($K*5+$C+'  '), ($K+$K+$Q+$D*2+$Rc+'  '), ($K*7+$C), ($Lc+$D*6+$Rc) )
  $Lt['A'] = @( (' '+$K*6+$C+' '), ($K+$K+$Q+$D*3+$K+$K+$C), ($K*7+$V+' '), ($K+$K+$Q+$D*2+$K+$K+$V+' '), ($K+$K+$V+'  '+$K+$K+$V+' '), ($Lc+$D+$Rc+'  '+$Lc+$D+$Rc+' ') )
  $Lt['P'] = @( ($K*6+$C+' '), ($K+$K+$Q+$D*2+$K+$K+$C), ($K*6+$Q+$Rc), ($K+$K+$Q+$D*3+$Rc+' '), ($K+$K+$V+'     '), ($Lc+$D+$Rc+'     ') )
  $Lt['-'] = @( (' '*9), (' '*9), (' '+$K*7+$C), (' '+$Lc+$D*6+$Rc), (' '*9), (' '*9) )
  $Lt['2'] = @( ($K*7+$C), ($Lc+$D*2+$K*3+$Q+$Rc), ('  '+$K*3+$Q+$Rc+' '), (' '+$K*3+$Q+$Rc+'  '), ($K*7+$C), ($Lc+$D*6+$Rc) )
  $a = New-Object System.Collections.ArrayList
  for ($r = 0; $r -lt 6; $r++) {
    [void]$a.Add(($Lt['L'][$r] + $Lt['E'][$r] + $Lt['A'][$r] + $Lt['P'][$r] + $Lt['-'][$r] + $Lt['2'][$r]))
  }
  $script:ArtCache = $a.ToArray()
  return $script:ArtCache
}
function Get-BannerCell([string[]]$art, [int]$i, [int]$j, [int]$rows, [int]$dy, [int]$dx) {
  if ($i -lt $rows -and $j -lt $art[$i].Length -and $art[$i][$j] -ne ' ') { return @($art[$i][$j], 0) }
  $si = $i - $dy; $sj = $j - $dx
  if ($si -ge 0 -and $si -lt $rows -and $sj -ge 0 -and $sj -lt $art[$si].Length -and $art[$si][$sj] -ne ' ') { return @($art[$si][$sj], 1) }
  return @(' ', 2)
}
function Show-Starfield([int]$width = 88) {
  $chars = @('.', '.', '.', '*', '+', "$([char]0x00B7)")
  for ($ln = 0; $ln -lt 2; $ln++) {
    $line = ''
    for ($j = 0; $j -lt $width; $j++) {
      if ((Get-Random -Minimum 0 -Maximum 100) -lt 12) {
        $ch = $chars[(Get-Random -Minimum 0 -Maximum $chars.Count)]
        if ($script:VT) {
          $b = Get-Random -Minimum 70 -Maximum 210
          $line += "${E}[38;2;$b;$b;255m$ch"
        } else { $line += $ch }
      } else { $line += ' ' }
    }
    if ($script:VT) { Write-Host ('    ' + $line + "${E}[0m") }
    else { Write-Host ('    ' + $line) -ForegroundColor DarkGray }
  }
}
function Show-Comet([int]$width = 56) {
  if (-not $script:VT -or $Plain) { return }
  $tch = [string][char]0x00BB
  for ($p = 3; $p -lt ($width + 10); $p++) {
    $pre = ' ' * [Math]::Max(0, $p - 8)
    $trail = ''
    for ($k = [Math]::Max(0, $p - 8); $k -lt $p; $k++) {
      $a = ($k - ($p - 8)) / 8.0; if ($a -lt 0) { $a = 0 }
      $r = [int](255 * $a); $g = [int](205 * $a); $b = [int](95 * $a)
      $trail += "${E}[38;2;$r;$g;${b}m" + $tch
    }
    $head = "${E}[38;2;255;255;255m" + $S.arr + "${E}[0m"
    Write-Host ("`r    " + $pre + $trail + $head + "   ") -NoNewline
    Start-Sleep -Milliseconds 26
  }
  Write-Host ("`r" + (' ' * 80) + "`r") -NoNewline
  Write-Host ''
}
function Show-Banner {
  $art = Get-Art
  $dy = 1; $dx = 2
  $rows = $art.Count
  $w = 0; foreach ($l in $art) { if ($l.Length -gt $w) { $w = $l.Length } }
  $H = $rows + $dy; $W = $w + $dx
  $row16 = @('DarkMagenta','Magenta','DarkCyan','DarkCyan','Cyan','Cyan','DarkGray')
  if ($Plain) {
    foreach ($l in $art) { Write-Host ('    ' + $l) -ForegroundColor DarkCyan }
    Write-Host '      A D C S   S I M U L A T O R' -ForegroundColor DarkCyan
    return
  }
  if (-not $Plain) { Show-Starfield }
  for ($i = 0; $i -lt $H; $i++) {
    if ($script:VT) {
      $s = ''
      for ($j = 0; $j -lt $W; $j++) {
        $c = Get-BannerCell $art $i $j $rows $dy $dx
        if ($c[1] -eq 2) { $s += ' ' }
        elseif ($c[1] -eq 0) {
          $f = $i / [Math]::Max(1, ($H - 1))
          $r = [int](120 + (0 - 120) * $f); $g = [int](40 + (235 - 40) * $f); $b = [int](235 + (255 - 235) * $f)
          $hf = 1.06 - 0.20 * ($j / [Math]::Max(1, $W - 1))
          $r = [Math]::Min(255, [int]($r * $hf)); $g = [Math]::Min(255, [int]($g * $hf)); $b = [Math]::Min(255, [int]($b * $hf))
          $s += "${E}[38;2;$r;$g;${b}m" + $c[0]
        } else {
          $r = 40 + 6 * $i; $g = 40 + 6 * $i; $b = 64 + 10 * $i
          $s += "${E}[38;2;$r;$g;${b}m" + $c[0]
        }
      }
      Write-Host ('    ' + $s + "${E}[0m")
    } else {
      Write-Host '    ' -NoNewline
      $runs = @(); $cur = ''; $curT = -1
      for ($j = 0; $j -lt $W; $j++) {
        $c = Get-BannerCell $art $i $j $rows $dy $dx
        if ($c[1] -ne $curT) { if ($cur -ne '') { $runs += ,@($cur, $curT) }; $cur = ''; $curT = $c[1] }
        $cur += $c[0]
      }
      if ($cur -ne '') { $runs += ,@($cur, $curT) }
      foreach ($run in $runs) {
        if ($run[1] -eq 0)      { $col = $row16[[Math]::Min($i, $row16.Count - 1)] }
        elseif ($run[1] -eq 1)  { $col = 'DarkGray' }
        else                     { $col = 'Black' }
        Write-Host $run[0] -NoNewline -ForegroundColor $col
      }
      Write-Host ''
    }
  }
  $sub = 'A D C S   S I M U L A T O R'
  if ($script:VT) {
    $line = ''
    for ($j = 0; $j -lt $sub.Length; $j++) {
      $f = $j / ($sub.Length - 1)
      $r = [int](0 + 190 * $f); $g = [int](170 + 80 * $f); $b = 255
      $line += "${E}[38;2;$r;$g;${b}m" + $sub[$j]
    }
    Write-Host ('      ' + $line + "${E}[0m")
    Write-Host '    ' -NoNewline
    for ($i2 = 0; $i2 -le 56; $i2++) {
      $f = $i2 / 56
      $r = [int](120 * (1 - $f)); $g = [int](120 + 115 * $f); $b = 255
      Write-Host ("${E}[38;2;$r;$g;${b}m" + $S.blk) -NoNewline
      Start-Sleep -Milliseconds 6
    }
    Write-Host "${E}[0m"
  } else {
    Write-Host ('      ' + $sub) -ForegroundColor Cyan
    Write-Host ('    ' + ($S.blk * 57)) -ForegroundColor Cyan
  }
  Show-Comet
}

# ---------------------------- bar kit --------------------------------------
function Bar-Str([int]$n, [int]$w) {
  if ($script:VT) {
    $s = ''
    for ($x = 0; $x -lt $w; $x++) {
      if ($x -lt $n) {
        $f = $x / [Math]::Max(1, $w - 1)
        $r = [int](30 + 200 * $f); $g = [int](90 + 140 * $f); $b = 255
        $s += "${E}[38;2;$r;$g;${b}m" + $S.blk
      } else { $s += "${E}[38;2;55;65;85m" + $S.s1 }
    }
    return $s + "${E}[0m"
  }
  return ($S.blk * $n) + ($S.s1 * ($w - $n))
}
function Out-Bar([string]$s) {
  if ($script:VT) { Write-Host $s -NoNewline }
  else { Write-Host $s -NoNewline -ForegroundColor Cyan }
}

# ---------------------------- step kit -------------------------------------
function Step2([string]$t) {
  $script:t_stepName = $t
  $script:StepNo++; $script:StepT0 = Get-Date
  try { $host.UI.RawUI.WindowTitle = ("LEAP-2 setup - step {0}/{1}" -f $StepNo, $StepTotal) } catch {}
  $w = 58
  if ($t.Length -gt 45) { $t = $t.Substring(0, 42) + '...' }
  Write-Host ''
  P ("  {0}{1}{2}" -f $S.tl, ($S.d * $w), $S.tr) Cyan
  Write-Host ("  {0} " -f $S.dv) -NoNewline -ForegroundColor Cyan
  Write-Host ("STEP {0}/{1}" -f $StepNo, $StepTotal).PadRight(10) -NoNewline -ForegroundColor Magenta
  Write-Host $t.PadRight(45) -NoNewline -ForegroundColor White
  Write-Host (" {0}" -f $S.dv) -ForegroundColor Cyan
  P ("  {0}{1}{2}" -f $S.bl, ($S.d * $w), $S.br) Cyan
  Log ("STEP $StepNo/$StepTotal : $t")
}
function StepDone([string]$status = 'ok') {
  $el = ((Get-Date) - $script:StepT0).TotalSeconds
  $secs = if ($el -lt 10) { '{0:0.#}' -f $el } else { '{0:0}' -f $el }
  $bw = 22
  $n = [int][Math]::Round($bw * $script:StepNo / $StepTotal)
  $col = if ($status -eq 'ok') { 'Green' } elseif ($status -eq 'partial') { 'Yellow' } else { 'Red' }
  Write-Host ('   ' + ($S.h * 3) + (' done in {0}s  ' -f $secs)) -NoNewline -ForegroundColor $col
  Out-Bar (Bar-Str $n $bw)
  Write-Host ('  {0}/{1}' -f $script:StepNo, $StepTotal) -ForegroundColor $col
  [void]$script:Report.Add([pscustomobject]@{ N = $script:StepNo; T = $script:t_stepName; S = $status; Secs = $secs })
}
function Show-Report {
  $w = 62
  Write-Host ''
  P ("  {0}{1}{2}" -f $S.tl, ($S.d * $w), $S.tr) Cyan
  $hd = ' RESULTS '
  $inner = $hd + ($S.d * (60 - $hd.Length))
  P ("  {0} {1} {2}" -f $S.dv, $inner, $S.dv) Cyan
  foreach ($r in $script:Report) {
    $mark = if ($r.S -eq 'ok') { $S.chk } elseif ($r.S -eq 'partial') { '!' } else { $S.crs }
    $col  = if ($r.S -eq 'ok') { 'Green' } elseif ($r.S -eq 'partial') { 'Yellow' } else { 'Red' }
    $name = [string]$r.T; if ($name.Length -gt 36) { $name = $name.Substring(0, 33) + '...' }
    $row = ('{0,2}  {1,-36} {2}  {3,7}' -f $r.N, $name, $mark, ($r.Secs + 's'))
    P ("  {0} {1} {2}" -f $S.dv, $row.PadRight(60), $S.dv) $col
  }
  P ("  {0}{1}{2}" -f $S.bl, ($S.d * $w), $S.br) Cyan
}

# --------------------------- core helpers ----------------------------------
function Run([string]$exe, [string[]]$argList) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $exe @argList 2>&1 | ForEach-Object { $ln = "$_"; P ("    $ln") DarkGray; Log ("  " + $ln) } }
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
function Stop-VenvProcesses([string]$venvDir) {
  Info 'stopping any running sim + processes from inside .venv ...'
  try {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
      ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($venvDir, [StringComparison]::OrdinalIgnoreCase)) -or
      ($_.CommandLine -and $_.CommandLine -match 'run-sim\.ps1|Run-Sim\.bat|open-when-ready\.ps1')
    }
    foreach ($p in $procs) {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
      Log ("  stopped pid $($p.ProcessId): " + $(if ($p.ExecutablePath) { $p.ExecutablePath } else { $p.CommandLine }))
    }
  } catch { Log ("  process scan failed: " + $_.Exception.Message) }
  try {
    Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction Stop |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Log ("  stopped port-5000 owner pid " + $_.OwningProcess) }
  } catch {}
  Start-Sleep -Seconds 2
}
function Remove-Tree([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return $true }
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
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
  } finally { $ErrorActionPreference = $prev }
}
function Get-File([string]$url, [string]$dest) {
  if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & curl.exe -L --fail --retry 2 --connect-timeout 20 --progress-bar -o "$dest" "$url" }
    finally { $ErrorActionPreference = $prev }
    return ($LASTEXITCODE -eq 0)
  }
  try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing; return $true } catch { return $false }
}
function Invoke-Animated([string]$exe, [string]$argStr, [string]$label, [int]$timeoutSec = 900) {
  $outF = [IO.Path]::GetTempFileName(); $errF = [IO.Path]::GetTempFileName()
  $p = Start-Process -FilePath $exe -ArgumentList $argStr -WorkingDirectory $Root -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput $outF -RedirectStandardError $errF
  $t0 = Get-Date; $f = 0
  while (-not $p.HasExited) {
    if (((Get-Date) - $t0).TotalSeconds -gt $timeoutSec) {
      try { Stop-Process -Id $p.Id -Force } catch {}
      Clear-Line; Warn "timeout after ${timeoutSec}s: $label"; break
    }
    $el = [int]((Get-Date) - $t0).TotalSeconds
    $ch = $Spin[$f % 4]; $f++
    $last = ''
    try { $t = Get-Content $outF -Tail 1 -ErrorAction SilentlyContinue; if ($t) { $last = ([string]$t).Trim() } } catch {}
    if ($last.Length -gt 34) { $last = $last.Substring(0, 34) }
    if ($Plain) { Start-Sleep -Milliseconds 500; continue }
    $line = ("    {0} {1} {2,4}s  {3}" -f $ch, $label.PadRight(26), $el, $last).PadRight(84)
    Write-Host ("`r" + $line) -NoNewline -ForegroundColor DarkCyan
    Start-Sleep -Milliseconds 180
  }
  Clear-Line
  $code = if ($null -ne $p.ExitCode) { $p.ExitCode } else { -1 }
  $out = ''; $err = ''
  try { $out = [IO.File]::ReadAllText($outF) } catch {}
  try { $err = [IO.File]::ReadAllText($errF) } catch {}
  Log ("  animated-run [$label] exit=$code")
  if ($out) { Log ($out.Trim()) }
  if ($err) { Log ("  stderr: " + $err.Trim()) }
  Remove-Item $outF, $errF -Force -ErrorAction SilentlyContinue
  return @{ Code = $code; Out = $out; Err = $err }
}

function Install-NodeViaWinget {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Warn 'winget not available on this machine.'; return $false }
  Info 'winget install OpenJS.NodeJS.LTS (system-wide, may ask for elevation) ...'
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
  Info "downloading portable Node $Version (~30 MB, one-time; cached in tools\node) ..."
  Log ("  url: " + $zipUrl)
  if (-not (Get-File $zipUrl $zipPath)) { Warn 'download failed (no internet, or nodejs.org blocked by proxy/IT)'; return $false }
  Info 'extracting ...'
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
  Ok "portable Node ready: tools\node ($($nv.Trim())) - nothing installed system-wide"
  return $true
}
function Install-OrekitData {
  $url = 'https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip'
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
  New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
  $zip = Join-Path $ToolsDir 'orekit-data.zip'
  Info 'downloading orekit-data from Orekit GitLab (one-time, ~100 MB) ...'
  Log ("  url: " + $url)
  if (-not (Get-File $url $zip)) { Warn 'download failed.'; return $false }
  Info 'extracting ...'
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

# --- upgrades run_simulator.py to shield v2 if the clone has the old one ---
function Ensure-RunSimShield {
  $rs = Join-Path $Root 'run_simulator.py'
  if (-not (Test-Path $rs)) { Warn 'run_simulator.py not found - skipping patch step.'; return }
  $raw = Get-Content $rs -Raw
  if ($raw -match 'LEAP2_BOOT_SHIELD v2') { Ok 'run_simulator.py is the shielded v2 (self-set JAVA_HOME, boot immunity, double-run guard)'; return }
  $known = ($raw -match 'Run physics and the viewer with shared command state') -and
           ($raw -match 'from satellite_flight_visualisation import run_simulation, _telemetry_publisher') -and
           ($raw -match 'run_simulation\(\)')
  if (-not $known) { Warn 'run_simulator.py not recognized - NOT patching. Commit the shielded v2 file.'; return }
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
        print(f'  -> open http://127.0.0.1:{VIEWER_PORT} in your browser, or', flush=True)
        print('     close the other sim window/terminal and run this again.', flush=True)
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
        if getattr(e, 'winerror', None) == 10048 or e.errno in (48, 98, 10048):
            print('\nAnother LEAP-2 sim instance is already running (its port '
                  'is already bound).', flush=True)
            print('Close the other sim window/terminal and run this again.', flush=True)
            raise SystemExit(1)
        raise


if __name__ == '__main__':
    main()
'@
  $new | Out-File -FilePath $rs -Encoding utf8
  Ok 'run_simulator.py upgraded to shield v2 (backup: run_simulator.py.orig). COMMIT the v2 file once.'
}

# ================================ banner =====================================
try { Clear-Host } catch {}
try { $host.UI.RawUI.WindowTitle = 'LEAP-2 MBD Simulation - Setup' } catch {}
'' | Out-File -FilePath $LogFile -Encoding utf8
Show-Banner
Write-Host ''
Info ("project : " + $Root)
Info ("log     : " + $LogFile)
Info ('mode    : ' + $(if ($ViewerOnly) { 'VIEWER-ONLY verification' } else { 'FULL SIM setup + verification' }))
Info ('setup only installs + verifies, then stops - you run the sim from VS Code')
Write-Host ''

# ================================ main flow ==================================
try {

# ---- Step 1 ------------------------------------------------------------------
Step2 'Pre-flight (python / node / orekit-data) + run_simulator self-sufficiency'
 $py312 = Get-Py312
if (-not $py312) { Fail "Python 3.12 not found - the ONLY prerequisite. Install python.org 3.12 64-bit WITH 'py launcher' checked, then re-run: https://www.python.org/downloads/release/python-3127/" }
Ok ("Python 3.12 via: " + $py312.Exe + ' ' + ($py312.Args -join ' '))

 $npmOk = Test-Npm
if ($npmOk) { Ok 'node/npm present on PATH' }
elseif (Test-PortableNode) { Ok 'portable Node already cached (tools\node) - frontend can be built offline' }
else { Info 'Node not found - Step 5 will fetch a portable copy automatically (needs internet)' }
if (Test-Path $DistIndex) { Ok ("frontend/dist already present (" + $DistIndex + ")") }

 $od = Join-Path $Root 'orekit-data'
if (Test-Path (Join-Path $od 'Potential')) { Ok ("orekit-data present (" + $od + ")") }
else {
  Info 'orekit-data not in this clone - downloading it ...'
  if (-not (Install-OrekitData)) {
    Fail "orekit-data missing AND download failed. Manual fix: download https://gitlab.orekit.org/orekit/orekit-data/-/archive/main/orekit-data-main.zip , unzip, rename orekit-data-main -> orekit-data at repo root, re-run Setup.bat -ReuseVenv"
  }
  if (-not (Test-Path (Join-Path $od 'Potential'))) { Fail 'orekit-data downloaded but looks incomplete (no Potential/ inside).' }
  Ok 'orekit-data downloaded and installed'
}

if ($Root -match '(?i)(Downloads|OneDrive|Dropbox)') {
  Warn ("project sits in a Downloads/OneDrive-synced location (" + $Root + ") - synced+scanned folders stall imports and slow file deletion. Recommended: move to C:\Projects\ADCS_Sim and re-run Setup.bat.")
}
if (Test-PortFree 5000) { Ok 'port 5000 free' } else { Warn 'port 5000 busy (a sim is running) - Setup stops it automatically in Step 2.' }
try { Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force } catch {}
Ensure-RunSimShield
StepDone 'ok'

# ---- Step 2 ------------------------------------------------------------------
Step2 'Fresh virtual environment (.venv)'
Stop-VenvProcesses $VenvDir
if ((Test-Path $VenvDir) -and (-not $ReuseVenv)) {
  Info 'removing old .venv ...'
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
  Info ("creating venv: " + $py312.Exe + ' ' + ($py312.Args -join ' ') + ' -m venv .venv ...')
  $null = Run $py312.Exe ($py312.Args + @('-m','venv','.venv'))
  if (-not (Test-Path $VenvPy)) { Fail 'venv creation failed (see setup.log). Usual cause: broken Python install - repair via the python.org installer.' }
}
Ok ("venv ready: " + $VenvPy)
 $null = Run $VenvPy @('--version')
StepDone 'ok'

# ---- Step 3 ------------------------------------------------------------------
Step2 'Python dependencies (pip install -r requirements.txt)'
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
StepDone 'ok'

# ---- Step 4 ------------------------------------------------------------------
Step2 'Java 21 via jdk4py (fixes "No JVM shared library file (jvm.dll) found")'
 $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
 $jdkHome = (& $VenvPy -c "import jdk4py; print(jdk4py.JAVA_HOME)" 2>&1 | Out-String).Trim()
 $ErrorActionPreference = $prev
 $jdkHome = ($jdkHome -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
if ($jdkHome) { $jdkHome = $jdkHome.Trim() }
if (-not $jdkHome -or -not (Test-Path $jdkHome)) { Fail "jdk4py did not return a valid JAVA_HOME (got '$jdkHome'). Fix: $VenvPy -m pip install --force-reinstall jdk4py, then re-run." }
if (-not (Test-Path (Join-Path $jdkHome 'bin\server\jvm.dll'))) { Fail "jvm.dll not found under $jdkHome\bin\server - jdk4py install is corrupt. Re-run Setup.bat (fresh venv)." }
 $env:Path = "$jdkHome\bin;$env:Path"
 $env:JAVA_HOME = $jdkHome
Log ("  JAVA_HOME=" + $env:JAVA_HOME)
Ok ("jvm.dll present: " + $jdkHome + "\bin\server\jvm.dll (run_simulator.py sets this itself too - no terminal setup needed)")

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
if ($add) { Add-Content -Path $gi -Value ''; Add-Content -Path $gi -Value '# auto-added by setup.ps1'; $add | ForEach-Object { Add-Content -Path $gi -Value $_ }; Ok (".gitignore updated (added: " + ($add -join ', ') + ")") }
StepDone 'ok'

# ---- Step 5 ------------------------------------------------------------------
Step2 'Frontend build (auto-gets Node if missing -> frontend/dist/index.html)'
 $step5status = 'ok'
if ($SkipFrontend) { Warn 'skipped via -SkipFrontend (viewer will 503 until you build).'; $step5status = 'partial' }
elseif (Test-Path $DistIndex) { Ok ("dist already present: " + $DistIndex) }
else {
  $npmCmd = $null
  if (Test-Npm) { $npmCmd = 'npm.cmd'; Ok 'using system npm' }
  elseif (Test-PortableNode) {
    $env:Path = "$PortableNodeDir;$env:Path"
    $npmCmd = Join-Path $PortableNodeDir 'npm.cmd'
    Ok ("using cached portable Node: " + $PortableNodeDir + " (no download needed)")
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
      Info 'npm install ...'
      $ec = Run $npmCmd @('install')
      if ($ec -ne 0) {
        Warn 'npm install failed - cleaning node_modules + package-lock and retrying once ...'
        Remove-Item -Recurse -Force '.\node_modules' -ErrorAction SilentlyContinue
        Remove-Item -Force '.\package-lock.json' -ErrorAction SilentlyContinue
        $ec = Run $npmCmd @('install')
      }
      Info 'npm run build ...'
      $ec = Run $npmCmd @('run','build')
    } finally { Pop-Location }
    if (Test-Path $DistIndex) { Ok ("frontend built: " + $DistIndex) }
    else { $FrontendMissing = $true; $step5status = 'partial'; Warn "npm build did not produce frontend/dist/index.html. Open setup.log, search 'npm ERR!'." }
  }
  elseif ($DistUrl) {
    Warn 'no Node available - fetching prebuilt frontend from -DistUrl ...'
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $dz = Join-Path $ToolsDir 'frontend-dist.zip'
    if (-not (Get-File $DistUrl $dz)) { $FrontendMissing = $true; $step5status = 'partial'; Warn 'dist download failed.' }
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
        Ok ("prebuilt frontend installed: " + $DistIndex)
      } else { $FrontendMissing = $true; $step5status = 'partial'; Warn 'the -DistUrl zip did not contain dist/index.html at its root.' }
    }
  }
  else {
    $FrontendMissing = $true; $step5status = 'partial'
    Warn 'NO Node and NO download path succeeded - frontend cannot be built here (needs internet once, or -DistUrl, or copy frontend\dist).'
  }
}
StepDone $step5status

# ---- Step 6 ------------------------------------------------------------------
Step2 'Smoke test + timed warm-up (JVM / orekit-data / full physics import)'
if ($NoSmoke) { Warn 'skipped via -NoSmoke (including the warm-up import).' }
else {
  $ec = Run $VenvPy @('-m','py_compile',(Join-Path $Root 'run_simulator.py'))
  if ($ec -ne 0) { Fail 'run_simulator.py failed to compile - if setup patched it, restore run_simulator.py.orig and commit the v2 file by hand. See setup.log.' }
  Ok 'run_simulator.py compiles'

  $r = Invoke-Animated $VenvPy '-c "from engine.orekit_runtime import ensure_initialized; print(''orekit-smoke-ok'')"' 'JVM + orekit-data' 300
  if ($r.Code -ne 0) {
    $tail = Tail-File $LogFile 25
    if ($tail -match 'jvm\.dll|JVMNotFound|JAVA_HOME') { Fail "JVM still not found (jdk4py path was $jdkHome). Fixes: 1) new terminal 2) $VenvPy -m pip install --force-reinstall jdk4py orekit-jpype 3) re-run Setup.bat. Log tail:`n$tail" }
    elseif ($tail -match 'orekit-data|EGM2008|egm2008') { Fail "orekit-data invalid (EGM2008 check failed). Log tail:`n$tail" }
    else { Fail ("Orekit smoke import failed. Tail of setup.log:`n" + $tail) }
  }
  Ok 'JVM + orekit-data load cleanly'

  $ec = Run $VenvPy @('-c',"import app; print('viewer-import-ok')")
  if ($ec -ne 0) { Fail 'import app failed (viewer-only, no Java needed) - a python dep is broken. See setup.log.' }
  Ok 'viewer imports cleanly (no JVM needed)'

  Info 'warm-up: importing the FULL physics chain once (this also speeds up later boots) ...'
  $r = Invoke-Animated $VenvPy ('-c "import time; t=time.time(); import satellite_flight_visualisation; print(''physics-import-ok %.1fs'' % (time.time()-t))"') 'importing physics stack' 900
  if ($r.Code -ne 0) {
    $WarmOk = $false
    $tail = Tail-File $LogFile 20
    Warn ("full physics-chain import did not complete:`n" + $tail)
    Warn 'the live-boot step below will surface the real error and auto-fallback if needed.'
  } else {
    $m = ''
    try { $m = ([regex]::Match($r.Out, 'physics-import-ok ([0-9.]+)s')).Groups[1].Value } catch {}
    $secs = if ($m) { [double]$m } else { 0 }
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    "$([int][Math]::Ceiling($secs))" | Out-File -FilePath (Join-Path $ToolsDir 'import-time.txt') -Encoding ascii
    Ok ("full physics chain imports cleanly (~{0:0}s; later boots are faster)" -f $secs)
  }
}
StepDone $(if ($WarmOk) { 'ok' } else { 'partial' })

# ---- Step 7 ------------------------------------------------------------------
Step2 ("Live boot proof (start sim hidden, wait up to ${BootTimeoutSec}s for 200, then stop)")
 $targetPath = if ($ViewerOnly) { Join-Path $Root 'app.py' } else { Join-Path $Root 'run_simulator.py' }
 $mode = if ($ViewerOnly) { 'VIEWER-ONLY (app.py, no physics/Java)' } else { 'FULL SIM (run_simulator.py, physics + viewer)' }
Info ("mode: " + $mode)
Remove-Item $BootOut, $BootErr -Force -ErrorAction SilentlyContinue
 $simProc = Start-Process -FilePath $VenvPy -ArgumentList @('-u', "`"$targetPath`"") -WorkingDirectory $Root `
               -PassThru -WindowStyle Hidden -RedirectStandardOutput $BootOut -RedirectStandardError $BootErr
Ok ("sim process started hidden (pid " + $simProc.Id + "); output -> sim-boot.out.log / sim-boot.err.log")
 $up = $false; $partial = $false; $sawCode = ''; $bootStart = Get-Date; $f = 0
 $deadline = $bootStart.AddSeconds($BootTimeoutSec)
 $barW = 24
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 400
  if ($simProc.HasExited) {
    Clear-Line
    $code = $simProc.ExitCode
    $tail = Tail-File $BootErr 20; if (-not $tail) { $tail = Tail-File $BootOut 20 }
    if ($ViewerOnly) { Fail ("viewer-only process exited early (code $code). Last output:`n$tail") }
    Warn ("physics process exited early (code " + $code + ") - last output:`n" + $tail)
    if     ($tail -match 'Address already in use|Only one usage of each socket|10048') { Info 'diagnosis: PORT already bound - another sim was running. Setup stops those automatically; re-run Setup.bat.' }
    elseif ($tail -match 'jvm\.dll|JVMNotFound|No JVM') { Info 'diagnosis: JVM missing. Re-run Setup.bat (reinstalls jdk4py).' }
    elseif ($tail -match 'ModuleNotFoundError') { Info 'diagnosis: missing python module. Re-run Setup.bat without -ReuseVenv.' }
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
  if ($code -eq '200') { $up = $true; Clear-Line; break }
  if ($code -eq '503') {
    $body = Get-HttpBody 5000
    if ($FrontendMissing -or ($body -match 'Build the frontend')) { $partial = $true; Clear-Line; break }
  }
  elseif ($code -eq 'LISTENING' -and $FrontendMissing) { $partial = $true; Clear-Line; break }
  $animEnd = (Get-Date).AddSeconds(3)
  while ((Get-Date) -lt $animEnd -and (Get-Date) -lt $deadline -and -not $simProc.HasExited) {
    $el = [int]((Get-Date) - $bootStart).TotalSeconds
    $n = [int][Math]::Round($barW * [Math]::Min(1.0, $el / $BootTimeoutSec))
    $sp = $Spin[$f % 4]; $f++
    $st = switch ($code) {
      '000'       { 'booting JVM + physics stack ...' }
      '503'       { 'server up - UI missing (503) ...' }
      'LISTENING' { 'server listening ...' }
      default     { ("server up (HTTP " + $code + ") ...") }
    }
    if ($Plain) { Start-Sleep -Milliseconds 500; continue }
    if ($script:VT) { Write-Host ("`r    {0} " -f $sp) -NoNewline -ForegroundColor DarkCyan }
    else { Write-Host ("`r    {0} " -f $sp) -NoNewline -ForegroundColor DarkCyan }
    Out-Bar (Bar-Str $n $barW)
    Write-Host (" {0,3}s/{1}s  {2}" -f $el, $BootTimeoutSec, $st.PadRight(28)) -NoNewline -ForegroundColor DarkCyan
    Start-Sleep -Milliseconds 250
  }
}
Clear-Line
if ($up) {
  Write-Host ("    LIVE  -  viewer answered HTTP 200  (" + $mode + ")  ") -ForegroundColor White -BackgroundColor DarkGreen
  Log ("  LIVE - HTTP 200 (" + $mode + ")")
  $api = Get-ApiCode '/api/latest'
  if ($api -match '^2\d\d$') { Ok ("telemetry endpoint /api/latest answers " + $api) }
  else { Warn ("/api/latest not 2xx yet (physics warming up - normal): " + $api) }
}
elseif ($partial) {
  Warn 'SERVER IS UP but returns 503 - frontend/dist is missing on this machine.'
  $api = Get-ApiCode '/api/latest'
  if ($api -match '^2\d\d$') { Ok ("backend + telemetry PROVEN (/api/latest answers " + $api + ") - only the web UI files are missing") }
}
else {
  try { Stop-Process -Id $simProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  $tail = Tail-File $BootErr 20; if (-not $tail) { $tail = Tail-File $BootOut 20 }
  Fail ("no HTTP 200 within ${BootTimeoutSec}s (last probe: $sawCode). Boot log tail:`n$tail`nIf physics needs longer on this machine, re-run with:  Setup.bat -BootTimeoutSec 600")
}
StepDone $(if ($up) { 'ok' } else { 'partial' })

# ---- Step 8 ------------------------------------------------------------------
Step2 'Stop everything + clean handover to VS Code'
try { Stop-Process -Id $simProc.Id -Force -ErrorAction Stop; Ok ("proof-process stopped (pid " + $simProc.Id + ")") }
catch { Warn ("could not kill pid " + $simProc.Id + " - closing via port owner instead.") }
Start-Sleep -Seconds 2
if (-not (Test-PortFree 5000)) { Kill-Port 5000; Start-Sleep -Seconds 1 }
if (Test-PortFree 5000) { Ok 'port 5000 free - machine is clean for VS Code' } else { Warn 'port 5000 still busy - kill leftover python.exe via Task Manager before starting the sim.' }
StepDone 'ok'

# ---- finale -------------------------------------------------------------------
 $tot = ((Get-Date) - $T_Start).TotalSeconds
 $totStr = ('{0}m {1:0}s' -f [int][Math]::Floor($tot / 60), ($tot % 60))
Show-Report
Write-Host ''
if ($up) {
  Write-Host ("    SETUP COMPLETE  -  everything installed AND proven working  -  total " + $totStr + "  ") -ForegroundColor White -BackgroundColor DarkGreen
} else {
  Write-Host ("    SETUP ~90% COMPLETE  -  backend proven, UI files missing  -  total " + $totStr + "  ") -ForegroundColor Black -BackgroundColor Yellow
  Info 're-run WITH internet:  Setup.bat -ReuseVenv   (auto-fetches Node + builds)'
}
Write-Host ''
 $HW = 58
P ("  {0}{1}{2}" -f $S.tl, ($S.d * $HW), $S.tr) Cyan
 $hdr = ' HOW EVERYONE RUNS THE SIM (VS Code) '
P ("  {0} {1}{2}{3} {4}" -f $S.v, $S.d, $hdr, ($S.d * ($HW - 2 - $hdr.Length)), $S.v) Cyan
 $how = @(
  @('1.', 'VS Code  >  File  >  Open Folder  >  this folder', 'White'),
  @('2.', 'open a NEW terminal (Ctrl+`) - the .venv activates itself', 'White'),
  @('3.', 'python run_simulator.py', 'Yellow'),
  @('4.', 'open http://127.0.0.1:5000     (Ctrl+C in the terminal stops it)', 'Gray')
)
foreach ($l in $how) { P ("  {0} {1} {2,-54} {3}" -f $S.v, $l[0], $l[1], $S.v) $l[2] }
P ("  {0} {1,-56} {2}" -f $S.v, 'one instance at a time - a 2nd start prints a friendly message', $S.v) DarkCyan
P ("  {0} {1,-56} {2}" -f $S.v, 'viewer-only, no Java:  python app.py', $S.v) DarkCyan
P ("  {0}{1}{2}" -f $S.bl, ($S.d * $HW), $S.br) Cyan
Write-Host ''
Info ("full log: " + $LogFile + "   boot log: " + $BootOut + " / " + $BootErr)

} catch {
  # ---------------------------- failure screen -------------------------------
  Clear-Line
  if ($script:StepNo -gt 0 -and (@($script:Report | Where-Object { $_.N -eq $script:StepNo })).Count -eq 0) {
    $el = ((Get-Date) - $script:StepT0).TotalSeconds
    [void]$script:Report.Add([pscustomobject]@{ N = $script:StepNo; T = $script:t_stepName; S = 'fail'; Secs = ('{0:0}' -f $el) })
  }
  Show-Report
  Write-Host ''
  Write-Host ('    SETUP FAILED  -  read the [FAIL] line above for the exact fix  ') -ForegroundColor White -BackgroundColor DarkRed
  Log ("SETUP FAILED: " + $_.Exception.Message)
  $w = 62
  P ("  {0}{1}{2}" -f $S.tl, ($S.d * $w), $S.tr) Red
  foreach ($l in (Wrap54 $_.Exception.Message)) { P ("  {0} {1,-58} {2}" -f $S.v, $l, $S.v) Yellow }
  P ("  {0} {1,-58} {2}" -f $S.v, ('details in: ' + $LogFile), $S.v) Gray
  P ("  {0}{1}{2}" -f $S.bl, ($S.d * $w), $S.br) Red
  Write-Host ''
  exit 1
}