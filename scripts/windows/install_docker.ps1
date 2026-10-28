<# Install the fixed, signed Docker Desktop per-user package; no resource-limit changes. #>
param(
    [string]$Installer,
    [string]$DataRoot,
    [string]$InstallRoot,
    [switch]$AcceptTerms
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $PSScriptRoot 'paths.ps1')
$paths=Get-WbgPaths $project
$data=$paths.data_root
if(-not $InstallRoot){$InstallRoot=Join-Path $paths.apps_root 'Docker'}
if(-not $Installer){$Installer=Join-Path $data 'cache/downloads/Docker-Desktop-4.97.0-Installer.exe'}
if(-not $DataRoot){$DataRoot=Join-Path $data 'docker-wsl'}
$installerPath=(Resolve-Path -LiteralPath $Installer).Path
$dataPath=[IO.Path]::GetFullPath($DataRoot)
$expected='2668273f82b342a058a28f9ab53ea7bddde10bb6d51307ce2ec54c2d36459744'
if((Get-FileHash -LiteralPath $installerPath).Hash.ToLowerInvariant() -ne $expected){throw 'Installer SHA256 does not match the fixed official release'}
$signature=Get-AuthenticodeSignature -LiteralPath $installerPath
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Docker Inc*'){throw 'Docker installer signature validation failed'}
if(-not $AcceptTerms){throw 'Docker first-use terms require the user choice; pass -AcceptTerms only after explicit agreement'}
. (Join-Path $PSScriptRoot 'host.ps1')
$installArgs=@('install',('--installation-dir='+[IO.Path]::GetFullPath($InstallRoot)),'--quiet','--backend=wsl-2',('--wsl-default-data-root='+$dataPath),'--accept-license')
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
    $result=Invoke-WbgProcess $installerPath $installArgs -TimeoutSeconds 0
}else{
    $native=@($installArgs|ForEach-Object {ConvertTo-WbgNativeArgument $_}) -join ' '
    $child=Start-Process -FilePath $installerPath -ArgumentList $native -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    $result=[pscustomobject]@{exit_code=$child.ExitCode;stdout='';stderr='';windows_elevation_requested=$true}
}
$record=[ordered]@{schema_version=1;recorded_at_utc=[DateTimeOffset]::UtcNow.ToString('o');version='4.97.0'
    installer=$installerPath;sha256=$expected;signature_status=[string]$signature.Status
    arguments=$installArgs;exit_code=$result.exit_code;stdout=$result.stdout;stderr=$result.stderr
    data_root=$dataPath;mode='all_users_custom_directory';backend='wsl-2';terms_explicitly_accepted=$true
    wsl_resource_configuration_changed=$false;existing_native_engine_changed=$false
    reboot_required=($result.exit_code -eq 3010)}
$evidence=Join-Path $data 'state/install-history/docker'
[void][IO.Directory]::CreateDirectory($evidence)
$recordPath=Join-Path $evidence ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')+'.json')
[IO.File]::WriteAllText($recordPath,($record|ConvertTo-Json -Depth 10)+"`r`n",(New-Object Text.UTF8Encoding($false)))
$record|ConvertTo-Json -Depth 10
exit $result.exit_code
