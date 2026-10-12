# Safe display preview: loads only named presentation helpers, never setup steps.
param([switch]$Check, [ValidateRange(12,120)][int]$DurationSec = 12)
$ErrorActionPreference = 'Stop'
$setup = Join-Path (Split-Path -Parent $PSScriptRoot) 'setup.ps1'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($setup, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$names = @('Initialize-MissionConsole','Write-MissionText','MissionRule','MissionBanner','Step','Run')
$ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $names }, $false) |
  ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
function Log([string]$m) {} # Preview never writes setup.log.
$Root = Split-Path -Parent $PSScriptRoot
$LogFile = '(preview only / no log written)'
$StepNo = 0; $StepTotal = 8
Initialize-MissionConsole
try {
if ($Check) {
  if (([AdcsSetupConsole]::Planet(0) -join '') -eq ([AdcsSetupConsole]::Planet(1) -join '')) { throw 'Planet does not animate' }
  $pinned = [AdcsSetupConsole]::Open()
  $initialTop = if ($pinned) { [Console]::WindowTop } else { 0 }
  $code = Run $env:ComSpec @('/d','/c','echo stdout-check & ping -n 2 127.0.0.1 >nul & echo stderr-check 1>&2 & exit /b 7')
  if ($code -ne 7) { throw "Exit code was changed: $code" }
  if (-not [Console]::IsOutputRedirected -and [Console]::BufferWidth -ge 40 -and [Console]::WindowHeight -ge 8) {
    $ticks = [AdcsSetupConsole]::FrameCount
    if ($ticks -lt 2) { throw 'Animation did not advance during the quiet command' }
  }
  if ($pinned) {
    if (-not [AdcsSetupConsole]::IsPinned) { throw 'Header disappeared after command' }
    $before = [AdcsSetupConsole]::FrameCount
    1..35 | ForEach-Object { [void][AdcsSetupConsole]::Output("Live output check / line $_") }
    Start-Sleep -Milliseconds 350
    if ([AdcsSetupConsole]::FrameCount -le $before) { throw 'Animation stopped between commands' }
    Step 'Second phase / persistent header check'
    if ([Console]::WindowTop -ne $initialTop) { throw 'Header moved when output scrolled' }
    if (-not [AdcsSetupConsole]::IsPinned) { throw 'Header disappeared at phase transition' }
  }
  Write-MissionText 'PASS: syntax, renderer compilation, pinned header, live output, idle animation, stdout/stderr and exit code.' -ForegroundColor Green
} else {
  MissionBanner
  Step 'DISPLAY PREVIEW / no packages installed / no setup operations run'
  $activity = [AdcsSetupConsole]::Start('Preview / installing Python packages')
  try {
    for ($i = 0; $i -lt $DurationSec; $i++) {
      if ($i -in @(0,3,6,10)) {
        $line = @('Collecting dependencies (sample output)', 'Downloading package (sample output)', 'Installing collected packages (sample output)', 'Finishing installation (sample output)')[@(0,3,6,10).IndexOf($i)]
        if (-not $activity -or -not [AdcsSetupConsole]::Output($line)) { Write-MissionText "  $line" -ForegroundColor Gray }
      }
      Start-Sleep -Seconds 1
    }
  } finally { if ($activity) { [AdcsSetupConsole]::Stop() } }
  Write-MissionText '  Preview complete. No setup changes made.' -ForegroundColor Green
}

} finally { [AdcsSetupConsole]::Shutdown() }
