<# Per-container physical disk measurements; exits when that container stops, no model calls. #>
param(
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$WorkRoot,
    [Parameter(Mandatory=$true)][string]$ExportRoot,
    [string]$Container,
    [string]$DockerExecutable,
    [string]$DockerContext='desktop-linux'
)
$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $PSScriptRoot 'host.ps1')
$workDrive=New-Object IO.DriveInfo([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($WorkRoot)))
$exportDrive=New-Object IO.DriveInfo([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($ExportRoot)))
$outputPath=[IO.Path]::GetFullPath($Output)
[void][IO.Directory]::CreateDirectory((Split-Path -Parent $outputPath))
$utf8=New-Object Text.UTF8Encoding($false)
do{
    $record=[ordered]@{schema_version=1;recorded_at_utc=[DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'")
        work_drive=$workDrive.Name;export_drive=$exportDrive.Name;work_free_bytes=[long]$workDrive.AvailableFreeSpace
        export_free_bytes=[long]$exportDrive.AvailableFreeSpace;scope='Actual Windows physical volumes, not sparse VHDX capacity'}
    [IO.File]::WriteAllText($outputPath+'.tmp',($record|ConvertTo-Json -Depth 5),$utf8)
    Move-Item -LiteralPath ($outputPath+'.tmp') -Destination $outputPath -Force
    if(-not $Container){$record|ConvertTo-Json;break}
    if($Container -notmatch '^[a-f0-9]{64}$'){throw 'Expected the exact owned container ID'}
    $check=Invoke-WbgProcess $DockerExecutable @('--context',$DockerContext,'inspect','--format','{{json .State.Running}}',$Container) -TimeoutSeconds 15
    if($check.exit_code -ne 0 -or $check.stdout.Trim() -ne 'true'){break}
    Start-Sleep -Seconds 5
}while($true)
