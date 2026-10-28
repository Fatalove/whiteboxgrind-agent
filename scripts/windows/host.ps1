<# PS5.1-compatible bootstrap helpers. No installation or global changes. #>
. (Join-Path $PSScriptRoot 'paths.ps1')
function Get-WbgIdentity {
    $framework = 'unknown'
    try { $framework = [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription } catch {}
    return [ordered]@{executable=(Get-Process -Id $PID).Path; powershell_version=$PSVersionTable.PSVersion.ToString()
        edition=[string]$PSVersionTable.PSEdition; dotnet=$framework; process_bits=[IntPtr]::Size*8
        os_version=[Environment]::OSVersion.Version.ToString()}
}

function ConvertTo-WbgNativeArgument {
    param([AllowEmptyString()][string] $Value)
    # WSL's option scanner also needs simple switches left unquoted.
    if($Value -and $Value -notmatch '[\s"]'){return $Value}
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function New-WbgStartInfo {
    param([string] $Executable, [string[]] $Arguments, [switch] $LegacyArguments)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Executable; $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=New-Object Text.UTF8Encoding($false)
    $info.StandardErrorEncoding=New-Object Text.UTF8Encoding($false)
    if([IO.Path]::GetFileName($Executable) -in @('powershell.exe','pwsh.exe')){
        # Each interpreter must find its own built-ins before cross-version inherited modules.
        $builtInModules=Join-Path (Split-Path -Parent $Executable) 'Modules'
        if(Test-Path -LiteralPath $builtInModules){
            $info.EnvironmentVariables['PSModulePath']=$builtInModules+';'+[Environment]::GetEnvironmentVariable('PSModulePath')
        }
    }
    if([IO.Path]::GetFileName($Executable) -ieq 'docker.exe'){
        $info.EnvironmentVariables['PATH']=(Split-Path -Parent $Executable)+';'+[Environment]::GetEnvironmentVariable('PATH')
    }
    if (-not $LegacyArguments -and $null -ne $info.PSObject.Properties['ArgumentList']) {
        foreach ($value in $Arguments) { [void]$info.ArgumentList.Add($value) }
    } else { $info.Arguments=@($Arguments | ForEach-Object { ConvertTo-WbgNativeArgument $_ }) -join ' ' }
    return $info
}

function Invoke-WbgProcess {
    param([string] $Executable, [string[]] $Arguments, [int] $TimeoutSeconds=20,
          [scriptblock] $OnCancel, [switch] $LegacyArguments)
    $process=New-Object Diagnostics.Process
    $process.StartInfo=New-WbgStartInfo $Executable $Arguments -LegacyArguments:$LegacyArguments
    $hook=$null -ne $OnCancel
    try {
        if ($hook) { Initialize-WbgCancelHook; [WbgCancelHook]::Install() }
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadToEndAsync(); $stderr=$process.StandardError.ReadToEndAsync()
        $watch=[Diagnostics.Stopwatch]::StartNew(); $cancelSent=$false; $cancelObserved=$false; $cancelAttempts=0
        while (-not $process.WaitForExit(100)) {
            if ($hook -and [WbgCancelHook]::Requested -and -not $cancelSent) {
                $cancelObserved=$true; $cancelAttempts++; $cancelSent=[bool](& $OnCancel)
            }
            if ($TimeoutSeconds -gt 0 -and $watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                $process.Kill(); $process.WaitForExit(); throw "host_process_timeout: $Executable"
            }
        }
        $stdout.Wait(); $stderr.Wait()
        return [pscustomobject]@{stdout=$stdout.Result;stderr=$stderr.Result;exit_code=$process.ExitCode
            cancel_signal_observed=$cancelObserved;cancel_attempts=$cancelAttempts;cancel_marker_accepted=$cancelSent
            cancel_last_request=if($cancelObserved){$script:WbgLastCancelRequest}else{$null}}
    } finally { if($hook){[WbgCancelHook]::Remove()}; $process.Dispose() }
}

function Initialize-WbgCancelHook {
    if ('WbgCancelHook' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WbgCancelHook {
    private static ConsoleCancelEventHandler handler;
    public static volatile bool Requested;
    [DllImport("kernel32.dll")] private static extern bool SetConsoleCtrlHandler(IntPtr handler, bool add);
    public static void Install() {
        Requested = false;
        SetConsoleCtrlHandler(IntPtr.Zero, false);
        handler = (sender, args) => { args.Cancel = true; Requested = true; };
        Console.CancelKeyPress += handler;
    }
    public static void Remove() {
        if (handler != null) Console.CancelKeyPress -= handler;
        handler = null;
    }
}
'@
}

function Test-WbgRuntime {
    param([string] $Executable)
    if (-not [IO.Path]::IsPathRooted($Executable) -or -not (Test-Path -LiteralPath $Executable -PathType Leaf) -or
        [IO.Path]::GetFileName($Executable) -ine 'pwsh.exe') { throw 'runtime_path_invalid: expected an absolute existing pwsh.exe' }
    $probe=@'
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$identity=[ordered]@{executable=(Get-Process -Id $PID).Path;powershell_version=$PSVersionTable.PSVersion.ToString();edition=$PSVersionTable.PSEdition;dotnet=[Runtime.InteropServices.RuntimeInformation]::FrameworkDescription;process_bits=[IntPtr]::Size*8;argument_list=$false;argv_smoke=$false}
$info=[Diagnostics.ProcessStartInfo]::new((Join-Path $PSHOME 'pwsh.exe'))
$identity.argument_list=$null -ne $info.PSObject.Properties['ArgumentList']
if($identity.argument_list){
  $info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true
  $info.ArgumentList.Add('-NoProfile');$info.ArgumentList.Add('-NonInteractive');$info.ArgumentList.Add('-Command')
  $info.ArgumentList.Add('[Console]::Write("wbg-host-probe")')
  $p=[Diagnostics.Process]::Start($info);$s=$p.StandardOutput.ReadToEnd()
  if(-not $p.WaitForExit(10000)){$p.Kill();throw 'runtime smoke timeout'}
  $identity.argv_smoke=$p.ExitCode -eq 0 -and $s -eq 'wbg-host-probe';$p.Dispose()
}
$identity|ConvertTo-Json -Compress
'@
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probe))
    $record=Invoke-WbgProcess $Executable @('-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',$encoded)
    if ($record.exit_code -ne 0) { throw ('runtime_probe_failed: '+$record.stderr) }
    return $record.stdout | ConvertFrom-Json
}

function Get-WbgResources {
    param([string] $ProjectRoot)
    $result=[ordered]@{memory_available_bytes=$null;memory_total_bytes=$null;wsl_storage_drive=$null;export_drive=$null;volumes=@{}}
    try {
        if(-not ('WbgResourceMemory' -as [type])) {
            Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public class WbgResourceMemory {
 [StructLayout(LayoutKind.Sequential)] public struct Info {
  public uint length,load; public ulong total,available,totalPage,availablePage,totalVirtual,availableVirtual,extended;
 }
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool GlobalMemoryStatusEx(ref Info value);
 public static Info Read(){var x=new Info();x.length=(uint)Marshal.SizeOf(typeof(Info));if(!GlobalMemoryStatusEx(ref x))throw new Exception("memory_query_failed");return x;}
}
'@
        }
        $mem=[WbgResourceMemory]::Read();$result.memory_available_bytes=$mem.available;$result.memory_total_bytes=$mem.total
        $distro=Get-ChildItem -ErrorAction SilentlyContinue 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'|ForEach-Object{Get-ItemProperty -LiteralPath $_.PSPath}|Where-Object{$_.DistributionName -eq 'Ubuntu-22.04'}|Select-Object -First 1
        if($distro){$result.wsl_storage_drive=[IO.Path]::GetPathRoot($distro.BasePath).Substring(0,1).ToUpperInvariant()}
        $result.export_drive=[IO.Path]::GetPathRoot($ProjectRoot).Substring(0,1).ToUpperInvariant()
        foreach($drive in @($result.wsl_storage_drive,$result.export_drive)|Select-Object -Unique){
            if($drive){$volume=New-Object IO.DriveInfo($drive+':\');$result.volumes[$drive]=@{free_bytes=$volume.AvailableFreeSpace;total_bytes=$volume.TotalSize}}
        }
    } catch {$result['query_error']=$_.Exception.Message}
    return $result
}

function Get-WbgHost {
    param([string] $ProjectRoot)
    $bootstrap=Get-WbgIdentity; $checks=New-Object 'Collections.Generic.List[object]'
    $selected=$null; $selection=$null; $identity=$null; $problem=$null
    $configPath=Join-Path (Get-WbgPaths $ProjectRoot).config_root 'windows-runtime.json'
    $explicitEnvironment=[Environment]::GetEnvironmentVariable('WBG_POWERSHELL')
    try {
        if($explicitEnvironment){$selected=$explicitEnvironment;$selection='explicit_environment'}
        elseif(Test-Path -LiteralPath $configPath){
            $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json
            if($config.schema_version -ne 1 -or -not $config.powershell_path){throw 'runtime_config_invalid'}
            $selected=[string]$config.powershell_path;$selection='saved_configuration'
        } elseif($PSVersionTable.PSVersion.Major -ge 7){$selected=$bootstrap.executable;$selection='current_runtime'}
        else{
            $found=Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue|Select-Object -First 1
            if($found){$selected=$found.Source;$selection='discovered_path'}
        }
        if($selected){$identity=Test-WbgRuntime $selected}else{$problem='compatible_runtime_missing'}
    } catch {$problem=$_.Exception.Message}
    $version=$null; if($identity){$version=[version]$identity.powershell_version}
    $checks.Add([ordered]@{name='windows.bootstrap';passed=$env:OS -eq 'Windows_NT' -and $PSVersionTable.PSVersion -ge [version]'5.1';actual=$bootstrap})
    $checks.Add([ordered]@{name='windows.runtime_probe';passed=$null -ne $identity;actual=$identity;error=$problem;selected_path=$selected;selection=$selection})
    $checks.Add([ordered]@{name='windows.runtime_version';passed=$null -ne $version -and $version -ge [version]'7.6' -and $version -lt [version]'7.7';actual=if($identity){$identity.powershell_version}else{$null};expected='7.6.x; Stage B supported LTS family'})
    $checks.Add([ordered]@{name='windows.runtime_capabilities';passed=[bool]($identity -and $identity.argument_list -and $identity.argv_smoke -and $identity.process_bits -eq 64);actual=$identity})
    $wsl=Join-Path $env:SystemRoot 'System32\wsl.exe'
    $checks.Add([ordered]@{name='windows.wsl_executable';passed=Test-Path -LiteralPath $wsl -PathType Leaf;actual=$wsl})
    return [ordered]@{schema_version=1;ready=@($checks|Where-Object{-not $_.passed}).Count -eq 0
        bootstrap=$bootstrap;selected_runtime=$identity;selection=$selection;runtime_configuration=$configPath
        checks=@($checks.ToArray());wsl_executable=$wsl;launch_token=[guid]::NewGuid().ToString('N');resources=(Get-WbgResources $ProjectRoot)
        resolutions=@(
          @{action='configure_private_runtime';recommended=$true;installation_implemented=(Test-Path -LiteralPath (Join-Path $ProjectRoot 'scripts/windows/install_runtime.ps1'));description='Official fixed PowerShell ZIP in a user directory; use scripts/windows/install_runtime.ps1 and preserve prior selection.'},
          @{action='select_existing_runtime';description='Set WBG_POWERSHELL to an absolute compatible pwsh.exe, or save schema_version=1 and powershell_path in runtime configuration.'},
          @{action='system_install';description='User-selected side-by-side PowerShell 7; no automatic global changes.'})
        scope='Windows host readiness only; no installation and no recovery experiment'}
}

function ConvertTo-WbgWslPath {
    param([string] $WindowsPath)
    if([IO.Path]::IsPathRooted($WindowsPath)){$full=[IO.Path]::GetFullPath($WindowsPath)}
    else{$full=[IO.Path]::GetFullPath((Join-Path (Get-Location).Path $WindowsPath))}
    if($full -notmatch '^([A-Za-z]):[\\/](.*)$'){throw "unsupported_windows_path: $full"}
    return '/mnt/'+$Matches[1].ToLowerInvariant()+'/'+$Matches[2].Replace('\','/')
}

function Request-WbgCancellation {
    param($HostRecord,[string]$ProjectRoot)
    $cancelScript=(ConvertTo-WbgWslPath $ProjectRoot)+'/scripts/request_cancel_linux.py'
    $cancelArguments=@('-d','Ubuntu-22.04','-u','wbg','--','/home/wbg/whiteboxgrind-work/venv/bin/python',$cancelScript,'--token',$HostRecord.launch_token)
    $result=Invoke-WbgProcess -Executable $HostRecord.wsl_executable -Arguments $cancelArguments
    $script:WbgLastCancelRequest=@{exit_code=$result.exit_code;stdout=$result.stdout;stderr=$result.stderr;token=$HostRecord.launch_token;argv=$cancelArguments}
    return $result.exit_code -eq 0
}
