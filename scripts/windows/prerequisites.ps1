param([switch]$Install,[switch]$Library)
function Get-WbgPrerequisites {
    param([switch]$Install)
    $wsl=Join-Path $env:SystemRoot 'System32/wsl.exe'
    $record=[ordered]@{schema_version=1;status='not_ready';reason_code=$null;restart_performed=$false;analysis_started=$false;install_attempted=$false}
    if(-not [Environment]::Is64BitOperatingSystem){$record.reason_code='windows_x64_required';return $record}
    if(-not(Test-Path -LiteralPath $wsl)){$record.reason_code='wsl_executable_missing';$record['resolution']='Enable Windows Subsystem for Linux with Windows optional features; administrator privileges required.';return $record}
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$wsl;$info.Arguments='--status';$info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.Encoding]::Unicode;$info.StandardErrorEncoding=[Text.Encoding]::Unicode
    $process=[Diagnostics.Process]::Start($info)
    $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
    if(-not $process.WaitForExit(20000)){$process.Kill();throw 'WSL prerequisite status timed out'}
    $stdout.Wait();$stderr.Wait()
    $record['wsl_status']=@{exit_code=$process.ExitCode;stdout=$stdout.Result;stderr=$stderr.Result}
    $code=$process.ExitCode;$process.Dispose()
    if($code -eq 0){$record.status='ready';return $record}
    $record.reason_code='wsl_configuration_required'
    $record['resolution']='Use an elevated local executor to run wsl.exe --install --no-distribution; enable firmware virtualization if WSL reports it is unavailable. Restart only after the user saves work.'
    if($Install){
        $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        $record.install_attempted=$true
        . (Join-Path $PSScriptRoot 'host.ps1')
        if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            $result=Invoke-WbgProcess $wsl @('--install','--no-distribution') -TimeoutSeconds 0
        }else{
            $child=Start-Process -FilePath $wsl -ArgumentList @('--install','--no-distribution') -Verb RunAs -WindowStyle Hidden -Wait -PassThru
            $result=[pscustomobject]@{exit_code=$child.ExitCode;stdout='';stderr='';windows_elevation_requested=$true}
        }
        $record['installation']=$result
        if($result.exit_code -eq 0){
            $after=Get-WbgPrerequisites
            $record['post_installation_check']=$after
            if($after.status -eq 'ready'){$record.status='ready';$record.reason_code=$null}
            else{$record.status='restart_required';$record.reason_code='restart_and_recheck'}
        }elseif($result.exit_code -eq 3010){$record.status='restart_required';$record.reason_code='restart_and_recheck'}
        else{$record.reason_code='wsl_installation_failed'}
    }
    return $record
}
if(-not $Library){Get-WbgPrerequisites -Install:$Install|ConvertTo-Json -Depth 8}
