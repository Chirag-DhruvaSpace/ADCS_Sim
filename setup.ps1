# ============================================================================
#  setup.ps1 - ADCS Simulator - one-click setup (v8)
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

# Presentation only: native commands still run synchronously in this shell.
function Initialize-MissionConsole {
  if ('AdcsSetupConsole' -as [type]) { return }
  Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Runtime.InteropServices;
public static class AdcsSetupConsole {
  static readonly object Gate=new object();
  static Thread worker; static volatile bool stopping;
  static bool active,visible; static int tick; static ConsoleColor originalColor;
  static string label; static Stopwatch clock;
  static readonly string[] Orbit={"o . . .",". o . .",". . o .",". . . o",". . o .",". o . ."};
  public static string[] Planet(double phase) {
    string[] rows=new string[15]; string ramp=".,:;irsXA253hMHGS#9B&@";
    double ca=Math.Cos(-0.32),sa=Math.Sin(-0.32);
    for(int row=0;row<15;row++) {
      StringBuilder line=new StringBuilder();
      for(int col=0;col<64;col++) {
        double x=(col-31.5)/2,y=7-row,sphere=35-x*x-y*y;
        double z=sphere>=0?Math.Sqrt(sphere):-100;
        double u=ca*x+sa*y,v=(-sa*x+ca*y)/0.34,r=Math.Sqrt(u*u+v*v);
        bool ring=r>7.8 && r<15.3 && !(r>11.6 && r<12.1);
        char pixel=' ';
        if(ring && (sphere<0 || -v*Math.Sqrt(1-0.34*0.34)>z)) {
          double bands=0.5+0.5*Math.Sin(r*4.5);
          double glint=Math.Pow(0.5+0.5*Math.Cos(Math.Atan2(v,u)-phase),10);
          double shade=Math.Min(1,0.38+0.12*bands+0.32*glint);
          if(r<8.05 || r>15.05 || (r>11.35 && r<12.35)) shade=Math.Min(1,shade+0.18);
          pixel=" .:-=+*#%@"[(int)(shade*9)];
        } else if(sphere>=0) {
          double light=Math.Max(0,(-0.55*x+0.4*y+0.73*z)/Math.Sqrt(35));
          double bands=0.91+0.09*Math.Sin(y*3.2+0.35*Math.Sin(Math.Atan2(x,z)*4-phase*0.45));
          pixel=ramp[(int)(Math.Min(1,(0.08+0.92*light)*bands)*(ramp.Length-1))];
        } else if((row==1 && col==7)||(row==12 && col==57)) pixel='.';
        else if((row==3 && col==58)||(row==11 && col==4)) pixel='+';
        line.Append(pixel);
      } rows[row]=line.ToString();
    } return rows;
  }
  static ConsoleColor Shade(char c) {
    if("@&B9#%".IndexOf(c)>=0) return ConsoleColor.White;
    if("GSHMh3*+".IndexOf(c)>=0) return ConsoleColor.Yellow;
    if("52AXsr=-".IndexOf(c)>=0) return ConsoleColor.DarkYellow;
    return ConsoleColor.DarkGray;
  }
  sealed class Span {
    public string Text; public ConsoleColor Color;
    public Span(string text,ConsoleColor color) { Text=text; Color=color; }
  }
  static readonly System.Collections.Generic.List<System.Collections.Generic.List<Span>> History = new System.Collections.Generic.List<System.Collections.Generic.List<Span>>();
  static System.Collections.Generic.List<Span> pending=new System.Collections.Generic.List<Span>();
  static bool busy; static string phase="PREPARING",detail="Initializing setup";
  static int phaseNo,total=8,completed,scrollOffset,maxScroll,lastRowCount;
  static IntPtr inputHandle;
  static uint originalInputMode;
  static bool inputModeChanged;
  [StructLayout(LayoutKind.Explicit,Size=20)]
  struct InputRecord {
    [FieldOffset(0)] public ushort Type;
    [FieldOffset(4)] public int KeyDown;
    [FieldOffset(8)] public ushort Repeat;
    [FieldOffset(10)] public ushort Key;
    [FieldOffset(6)] public short MouseY;
    [FieldOffset(8)] public uint Buttons;
    [FieldOffset(16)] public uint Flags;
  }
  [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int value);
  [DllImport("kernel32.dll")] static extern bool GetConsoleMode(IntPtr handle,out uint mode);
  [DllImport("kernel32.dll")] static extern bool SetConsoleMode(IntPtr handle,uint mode);
  [DllImport("kernel32.dll",EntryPoint="PeekConsoleInputW")] static extern bool PeekInput(IntPtr handle,out InputRecord record,uint length,out uint read);
  [DllImport("kernel32.dll",EntryPoint="ReadConsoleInputW")] static extern bool ReadInput(IntPtr handle,out InputRecord record,uint length,out uint read);
  static void EnablePaneInput() {
    inputHandle=GetStdHandle(-10);
    if(GetConsoleMode(inputHandle,out originalInputMode)) {
      // Preserve processed input (including Ctrl+C); disable selection freeze
      // and request mouse events for the output pane. Restore on exit.
      inputModeChanged=SetConsoleMode(inputHandle,(originalInputMode|0x0010u|0x0080u)&~0x0040u);
    }
  }
  static void RestorePaneInput() {
    if(inputModeChanged) { SetConsoleMode(inputHandle,originalInputMode); inputModeChanged=false; }
  }
  static void PollPaneInput() {
    if(!inputModeChanged) return;
    for(int i=0;i<32;i++) {
      InputRecord record; uint count;
      if(!PeekInput(inputHandle,out record,1,out count) || count==0) break;
      bool nav=record.Type==1 && (record.Key==33 || record.Key==34 || record.Key==35 || record.Key==36 || record.Key==38 || record.Key==40);
      bool mouse=record.Type==2,other=record.Type==4 || record.Type==16;
      if(!nav && !mouse && !other) break; // Leave ordinary keys for the native command.
      if(!ReadInput(inputHandle,out record,1,out count) || count==0) break;
      if(nav && record.KeyDown!=0) {
        int page=Math.Max(1,Console.WindowHeight-HeaderHeight-2);
        int repeat=Math.Max(1,(int)record.Repeat);
        if(record.Key==33) MoveScroll(page*repeat);
        else if(record.Key==34) MoveScroll(-page*repeat);
        else if(record.Key==38) MoveScroll(repeat);
        else if(record.Key==40) MoveScroll(-repeat);
        else if(record.Key==36) MoveScroll(Int32.MaxValue);
        else if(record.Key==35) MoveScroll(-Int32.MaxValue);
      } else if(mouse && (record.Flags&4)!=0 && record.MouseY>=Console.WindowTop+HeaderHeight) {
        short delta=(short)(record.Buttons>>16);
        MoveScroll(delta>0?3:-3);
      }
    }
  }
  static void MoveScroll(int lines) {
    scrollOffset=(int)Math.Max(0,Math.Min((long)maxScroll,(long)scrollOffset+lines));
  }
  public static int ScrollOffset { get { return scrollOffset; } }
  public static int MaxScroll { get { return maxScroll; } }
  public static void Scroll(int lines) {
    lock(Gate) { if(!active) return; Logs(); MoveScroll(lines); Logs(); }
  }

  public static bool IsPinned { get { return active; } }
  public static int FrameCount { get { return tick; } }
  public static void BannerPlanet() {
    ConsoleColor old=Console.ForegroundColor;
    foreach(string row in Planet(0)) {
      Console.Write("    ");
      foreach(char c in row) { Console.ForegroundColor=Shade(c); Console.Write(c); }
      Console.WriteLine();
    } Console.ForegroundColor=old;
  }
  static int PlanetHeight { get { return Math.Min(13,Math.Min(Math.Max(3,Console.WindowHeight-11),Math.Max(3,(Console.WindowWidth-5)*13/64))); } }
  static int HeaderHeight { get { return PlanetHeight+5; } }
  static void Row(int row,string text,ConsoleColor color) {
    int width=Console.WindowWidth-1;
    if(text.Length>width) text=text.Substring(0,width);
    Console.SetCursorPosition(Console.WindowLeft,Console.WindowTop+row);
    Console.ForegroundColor=color; Console.Write(text.PadRight(width));
  }
  static void ColoredRow(int row,System.Collections.Generic.List<Span> spans) {
    int width=Console.WindowWidth-1,count=0;
    Console.SetCursorPosition(Console.WindowLeft,Console.WindowTop+row);
    foreach(Span span in spans) {
      int size=Math.Min(span.Text.Length,width-count);
      if(size<=0) break;
      Console.ForegroundColor=span.Color; Console.Write(span.Text.Substring(0,size)); count+=size;
    }
    Console.Write(new string(' ',Math.Max(0,width-count)));
  }
  static void Header() {
    int h=HeaderHeight,seconds=(int)clock.Elapsed.TotalSeconds;
    string elapsed=String.Format("{0:00}:{1:00}",seconds/60,seconds%60);
    Row(0,"  A D C S   S I M U L A T O R",ConsoleColor.White);
    Row(1,String.Format("  MISSION CONTROL   /   PHASE {0:00} OF {1:00}   /   {2}",phaseNo,total,phase),ConsoleColor.Magenta);
    int barWidth=Console.WindowWidth>=60?28:14;
    int filled=completed*barWidth/Math.Max(1,total);
    Row(2,"  ["+new string('=',filled)+new string('-',barWidth-filled)+"]  "+completed+"/"+total+" phases complete",ConsoleColor.Cyan);
    {
      string[] planet=Planet(tick*0.08);
      int planetHeight=PlanetHeight,planetWidth=Math.Min(Console.WindowWidth-5,64*planetHeight/13);
      for(int i=0;i<planetHeight;i++) {
        StringBuilder sampled=new StringBuilder("    ");
        string source=planet[1+i*13/planetHeight];
        for(int x=0;x<planetWidth;x++) sampled.Append(source[x*64/planetWidth]);
        string line=sampled.ToString();
        var spans=new System.Collections.Generic.List<Span>();
        int begin=0;
        while(begin<line.Length) {
          ConsoleColor color=Shade(line[begin]); int end=begin+1;
          while(end<line.Length && Shade(line[end])==color) end++;
          spans.Add(new Span(line.Substring(begin,end-begin),color)); begin=end;
        }
        ColoredRow(i+3,spans);
      }
    }
    string state=busy?"ACTIVE":"SETUP";
    Row(h-2,"  [ "+Orbit[tick%6]+" ]  "+state+" / "+elapsed+" / "+(busy?label:detail),ConsoleColor.Cyan);
    Row(h-1,"  "+new string('=',Math.Max(0,Console.WindowWidth-5)),ConsoleColor.Blue);
    Console.Title="ADCS Simulator | "+phase+" | "+elapsed;
  }
  static void Logs() {
    int width=Console.WindowWidth-1,start=HeaderHeight,room=Console.WindowHeight-start-1;
    var rows=new System.Collections.Generic.List<System.Collections.Generic.List<Span>>();
    int first=0;
    for(int n=first;n<=History.Count;n++) {
      var logical=n==History.Count?pending:History[n];
      if(n==History.Count && logical.Count==0) break;
      var current=new System.Collections.Generic.List<Span>(); int used=0;
      foreach(Span span in logical) {
        int offset=0;
        while(offset<span.Text.Length) {
          int size=Math.Min(width-used,span.Text.Length-offset);
          current.Add(new Span(span.Text.Substring(offset,size),span.Color)); used+=size; offset+=size;
          if(used==width) { rows.Add(current); current=new System.Collections.Generic.List<Span>(); used=0; }
        }
      }
      if(used>0 || logical.Count==0) rows.Add(current);
    }
    maxScroll=Math.Max(0,rows.Count-room);
    if(scrollOffset>0 && rows.Count>lastRowCount) scrollOffset+=rows.Count-lastRowCount;
    scrollOffset=Math.Min(scrollOffset,maxScroll); lastRowCount=rows.Count;
    int skip=Math.Max(0,rows.Count-room-scrollOffset);
    for(int i=0;i<room;i++) {
      if(skip+i<rows.Count) ColoredRow(start+i,rows[skip+i]); else Row(start+i,"",ConsoleColor.Gray);
    }
    string view=scrollOffset==0?"LIVE":"HISTORY +"+scrollOffset;
    Row(Console.WindowHeight-1,"  - PgUp/PgDn | Wheel | End: live | "+view+" | setup.log",ConsoleColor.DarkCyan);
  }
  static void Draw() {
    ConsoleColor old=Console.ForegroundColor;
    try { Header(); Logs(); } finally { Console.ForegroundColor=old; }
  }
  public static bool Open() {
    if(Console.IsOutputRedirected) return false;
    lock(Gate) { try {
      if(active) return true;
      if(Console.WindowWidth<40 || Console.WindowHeight<10) return false;
      visible=Console.CursorVisible; originalColor=Console.ForegroundColor; Console.CursorVisible=false;
      Console.Clear(); History.Clear(); pending.Clear(); scrollOffset=0; maxScroll=0; lastRowCount=0;
      EnablePaneInput();
      clock=Stopwatch.StartNew(); tick=0; stopping=false; active=true; Draw();
      worker=new Thread(Animate); worker.IsBackground=true; worker.Start(); return true;
    } catch { active=false; RestorePaneInput(); try { Console.CursorVisible=visible; } catch {} return false; } }
  }
  public static void Phase(int number,int count,string name,string description) {
    lock(Gate) { phaseNo=number; total=count; completed=Math.Max(0,number-1); phase=name; detail=description;
      if(active) { try { Header(); } catch {} } }
  }
  public static bool Start(string task) {
    lock(Gate) { label=task; busy=true; return active; }
  }
  static void Animate() {
    while(!stopping) {
      lock(Gate) { if(!active) return; try { PollPaneInput(); tick++; Draw(); }
        catch {} }
      Thread.Sleep(140);
    }
  }
  public static bool Write(string text,ConsoleColor color,bool newline) {
    lock(Gate) {
      if(!active) return false;
      try {
        string[] parts=text.Replace("\r\n","\n").Replace("\r","\n").Replace("\t","    ").Split('\n');
        for(int i=0;i<parts.Length;i++) {
          if(parts[i].Length>0) pending.Add(new Span(parts[i],color));
          if(i<parts.Length-1 || newline) {
            History.Add(pending); pending=new System.Collections.Generic.List<Span>();
          }
        }
        if(History.Count>2000) History.RemoveRange(0,History.Count-2000);
        Logs(); return true;
      } catch { return true; } // A resize can interrupt a frame; retry on the next animation tick.
    }
  }
  public static bool Output(string text) {
    ConsoleColor color=ConsoleColor.Gray;
    string lower=text.ToLowerInvariant();
    if(lower.Contains("error") || lower.Contains("failed")) color=ConsoleColor.Red;
    else if(lower.Contains("warning")) color=ConsoleColor.Yellow;
    else if(lower.Contains("successfully") || lower.Contains("requirement already satisfied")) color=ConsoleColor.Green;
    else if(lower.Contains("downloading") || lower.Contains("fetch")) color=ConsoleColor.Blue;
    else if(lower.Contains("collecting") || lower.Contains("installing") || lower.Contains("building")) color=ConsoleColor.Cyan;
    return Write("  "+text,color,true);
  }
  // Finishing one command leaves the shared Saturn running between phases.
  public static void Stop() { lock(Gate) { busy=false; } }
  public static void Complete(bool success) {
    lock(Gate) {
      phase=success?"READY FOR FLIGHT":"ACTION REQUIRED"; detail=success?"Setup verified / simulator stopped":"Backend ready / frontend needs attention";
      busy=false; completed=total; scrollOffset=0;
    }
    if(!active) return;
    Write(success?"  [+] Setup complete. Start your simulation in VS Code.":"  [!] UI missing: re-run Setup.bat -ReuseVenv with internet.",success?ConsoleColor.Green:ConsoleColor.Yellow,true);
    Write("  1. Open this folder in VS Code.",ConsoleColor.White,true);
    Write("  2. Open a new terminal (the .venv activates).",ConsoleColor.Gray,true);
    Write("  3. python run_simulator.py",ConsoleColor.Cyan,true);
    Write("  4. http://127.0.0.1:5000 / Ctrl+C to stop",ConsoleColor.Magenta,true);
  }
  public static void Shutdown() {
    stopping=true; if(worker!=null) { worker.Join(1500); worker=null; }
    lock(Gate) { try {
      if(active) { Draw(); Console.SetCursorPosition(Console.WindowLeft,Console.WindowTop+Console.WindowHeight-1); }
    } catch {} finally {
      active=false; RestorePaneInput(); try { Console.CursorVisible=visible; Console.ForegroundColor=originalColor; } catch {}
    } }
  }

}
"@
}
function Write-MissionText {
  param([Parameter(Position=0)][AllowEmptyString()][string]$Object = '',
        [ConsoleColor]$ForegroundColor = 'Gray', [switch]$NoNewline)
  if (('AdcsSetupConsole' -as [type]) -and [AdcsSetupConsole]::Write($Object, $ForegroundColor, (-not $NoNewline))) { return }
  Write-Host $Object -ForegroundColor $ForegroundColor -NoNewline:$NoNewline
}
function Log([string]$m) { Add-Content -Path $LogFile -Value $m -Encoding UTF8 }
function Say([string]$m, [string]$c = 'Gray') { Write-MissionText $m -ForegroundColor $c; Log $m }
function Ok([string]$m) { Say "  [+] $m" Green }
function Warn([string]$m) { Say "  [!] $m" Yellow }
function Fail([string]$m) { Say "  [X] $m" Red; throw $m }
function MissionRule([string]$color = 'Blue', [switch]$Thin) {
  $line = if ($Thin) { '-' } else { '=' }
  Write-MissionText ('  ' + ($line * 68)) -ForegroundColor $color
}
function MissionBanner {
  try { Initialize-MissionConsole } catch { $script:ConsoleUiUnavailable = $true }
  try { $Host.UI.RawUI.WindowTitle = 'ADCS Simulator | Setup' } catch {}
  $pinned = $false
  if (-not $script:ConsoleUiUnavailable) { $pinned = [AdcsSetupConsole]::Open() }
  Write-MissionText ''
  Write-MissionText '  A D C S   S I M U L A T O R' -ForegroundColor White
  Write-MissionText '  ATTITUDE DETERMINATION & CONTROL SYSTEM' -ForegroundColor Magenta
  Write-MissionText ''
  if (-not $script:ConsoleUiUnavailable -and -not $pinned) { [AdcsSetupConsole]::BannerPlanet() }
  MissionRule
  Write-MissionText '  M I S S I O N   P R E P A R A T I O N' -ForegroundColor Cyan
  Write-MissionText '  01 PREFLIGHT   02 ENVIRONMENT   03 PACKAGES   04 JAVA' -ForegroundColor Cyan
  Write-MissionText '  05 FRONTEND    06 VALIDATION    07 BOOT       08 HANDOVER' -ForegroundColor Magenta
  MissionRule
  Write-MissionText '  Install, verify, then stop. Ready for your next simulation.' -ForegroundColor White
  Write-MissionText "  Workspace  $Root" -ForegroundColor DarkGray
  Write-MissionText "  Full log   $LogFile" -ForegroundColor DarkGray
}
function Step([string]$t) {
  $script:StepNo++
  $names = @('PREFLIGHT', 'ENVIRONMENT', 'PACKAGES', 'JAVA RUNTIME', 'FRONTEND', 'VALIDATION', 'LIVE BOOT', 'HANDOVER')
  Write-MissionText ''
  if ('AdcsSetupConsole' -as [type]) { [AdcsSetupConsole]::Phase($script:StepNo, $StepTotal, $names[$script:StepNo - 1], $t) }
  MissionRule
  Write-MissionText ("  {0:00} / {1:00}   {2}" -f $script:StepNo, $StepTotal, $names[$script:StepNo - 1]) -ForegroundColor Cyan
  Write-MissionText "  $t" -ForegroundColor White
  $done = ($script:StepNo - 1) * 3
  Write-MissionText '  [' -NoNewline -ForegroundColor DarkGray
  Write-MissionText ('=' * $done) -NoNewline -ForegroundColor Cyan
  Write-MissionText (' ' * (24 - $done)) -NoNewline -ForegroundColor DarkGray
  Write-MissionText "]  $($script:StepNo - 1) / $StepTotal complete" -ForegroundColor Gray
  MissionRule -Thin
  Log "STEP $($script:StepNo)/$StepTotal : $t"
}
function Run([string]$exe, [string[]]$argList) {
  $label = Split-Path -Leaf $exe
  if ($argList -contains 'pip') { $label = 'Installing Python packages' }
  elseif ($label -eq 'npm.cmd') { $label = "Frontend / npm $($argList -join ' ')" }
  elseif ($argList -contains 'venv') { $label = 'Preparing Python environment' }
  else { $label = "Validating / $label" }
  Write-MissionText "  [>] $label" -ForegroundColor Cyan
  $animated = $false
  if (-not $script:ConsoleUiUnavailable -and ('AdcsSetupConsole' -as [type])) {
    $animated = [AdcsSetupConsole]::Start($label)
  }
  $clock = [Diagnostics.Stopwatch]::StartNew()
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    & $exe @argList 2>&1 | ForEach-Object {
      $ln = "$_"
      if (-not $animated -or -not [AdcsSetupConsole]::Output($ln)) { Write-MissionText "  $ln" -ForegroundColor DarkGray }
      Log "  $ln"
    }
    $exitCode = $LASTEXITCODE
  } finally {
    if ($animated) { [AdcsSetupConsole]::Stop() }
    $ErrorActionPreference = $prev
  }
  $clock.Stop()
  $color = if ($exitCode -eq 0) { 'Green' } else { 'Yellow' }
  Write-MissionText ("  [<] Command finished in {0:0.0}s / exit {1}" -f $clock.Elapsed.TotalSeconds, $exitCode) -ForegroundColor $color
  return $exitCode
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
MissionBanner
try {

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

Write-MissionText ''
if ($up) {
  MissionRule Green
  Write-MissionText '  ADCS SIMULATOR / READY FOR FLIGHT' -ForegroundColor Green
  Write-MissionText '  Everything installed AND proven working.' -ForegroundColor White
  Write-MissionText '  [========================]  8 / 8 complete' -ForegroundColor Cyan
  MissionRule Green
} else {
  MissionRule Yellow
  Write-MissionText '  ADCS SIMULATOR / ACTION REQUIRED' -ForegroundColor Yellow
  Write-MissionText '  Backend proven; UI files missing.' -ForegroundColor White
  MissionRule Yellow
  Write-MissionText ' Re-run WITH internet:  Setup.bat -ReuseVenv   (auto-fetches Node + builds)' -ForegroundColor White
}
Write-MissionText ''
Write-MissionText ' HOW EVERYONE RUNS THE SIM FROM NOW ON (VS Code, as usual):' -ForegroundColor Cyan
Write-MissionText '   1. Open VS Code > File > Open Folder > this folder' -ForegroundColor White
Write-MissionText '      (if it asks to use the existing virtual environment -> Yes)' -ForegroundColor Gray
Write-MissionText '   2. Open a NEW terminal (Ctrl+`)  - the .venv activates itself' -ForegroundColor White
Write-MissionText '   3. python run_simulator.py' -ForegroundColor White
Write-MissionText '   4. open http://127.0.0.1:5000   (Ctrl+C in the terminal stops it)' -ForegroundColor White
Write-MissionText ' ONE instance at a time - starting a second prints a friendly' -ForegroundColor Gray
Write-MissionText ' message instead of a port error (shield v2 handles it).' -ForegroundColor Gray
Write-MissionText ' Viewer-only, no Java:  python app.py' -ForegroundColor Gray
Write-MissionText " Full log: $LogFile   Boot log: $BootOut / $BootErr" -ForegroundColor Gray
if ('AdcsSetupConsole' -as [type]) { [AdcsSetupConsole]::Complete([bool]$up) }
} finally {
  if ('AdcsSetupConsole' -as [type]) { [AdcsSetupConsole]::Shutdown() }
}
