<# PS5.1 bootstrap for the pinned Docker deployment, using the existing host checks. #>
$CliArgs=@($args)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'windows/host.ps1')
try{
    $hostRecord=Get-WbgHost $root
    if(-not $hostRecord.ready){
        @{schema_version=1;status='not_ready';ready=$false;reason_code='windows_host_not_ready';windows_host=$hostRecord}|ConvertTo-Json -Depth 24 -Compress
        exit 2
    }
    if((Get-WbgIdentity).executable -ine $hostRecord.selected_runtime.executable){
        $result=Invoke-WbgProcess $hostRecord.selected_runtime.executable (@('-NoProfile','-File',$PSCommandPath)+$CliArgs) -TimeoutSeconds 0
        $body=$result.stdout|ConvertFrom-Json
        $body|Add-Member -NotePropertyName windows_bootstrap -NotePropertyValue $hostRecord.bootstrap -Force
        $body|ConvertTo-Json -Depth 32 -Compress
        [Console]::Error.Write($result.stderr);exit $result.exit_code
    }
    . (Join-Path $PSScriptRoot 'windows/container.ps1')
    $result=Invoke-WbgContainerCli -ToolRoot $root -CliArgs $CliArgs -WindowsHost $hostRecord
    $result.body|Add-Member -NotePropertyName windows_host -NotePropertyValue $hostRecord -Force
    $result.body|ConvertTo-Json -Depth 32 -Compress
    exit $result.exit_code
}catch{
    @{schema_version=1;status='error';reason_code='container_launcher_error';detail=$_.Exception.Message;execution=@{status='not_started'};recovery=@{status='not_attempted'}}|ConvertTo-Json -Depth 12 -Compress
    exit 40
}
