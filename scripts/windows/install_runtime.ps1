<# Fixed private PowerShell installation/check/rollback; never modifies global PATH or PS5.1. #>
param(
    [ValidateSet('Install','Check','Repair','Rollback')][string]$Action='Check',
    [string]$Archive,
    [string]$InstallRoot,
    [string]$SelectionRecord
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $PSScriptRoot 'paths.ps1')
$paths=Get-WbgPaths $project
$data=$paths.data_root
$configuration=Join-Path $paths.config_root 'windows-runtime.json'
$history=Join-Path $paths.config_root 'runtime-selection-history'
$expected='02fe458be20493fbdf43f61ea20610b811ee6c738ab1676c61b9cfcd1a33c860'
$version='7.6.6'
$utf8=New-Object Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'host.ps1')
function Write-Json([string]$Path,$Object){
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    [IO.File]::WriteAllText($Path,($Object|ConvertTo-Json -Depth 12)+"`r`n",$utf8)
}
if($Action -eq 'Check'){
    if(-not(Test-Path -LiteralPath $configuration)){throw 'No saved private runtime selection'}
    $selection=Get-Content -LiteralPath $configuration -Raw -Encoding UTF8|ConvertFrom-Json
    $installation=Join-Path (Split-Path -Parent $selection.powershell_path) 'runtime-install.json'
    $verifiedFiles=0
    if(Test-Path -LiteralPath $installation){
        $manifest=Get-Content -LiteralPath $installation -Raw -Encoding UTF8|ConvertFrom-Json
        foreach($row in $manifest.files){
            $file=Join-Path (Split-Path -Parent $selection.powershell_path) $row.path
            if(-not(Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file).Hash.ToLowerInvariant() -ne $row.sha256){throw 'Installed runtime integrity check failed; use Repair'}
            $verifiedFiles++
        }
    }
    $identity=Test-WbgRuntime $selection.powershell_path
    [ordered]@{status='ready';runtime=$identity;configuration=$configuration;verified_files=$verifiedFiles;scope='Saved runtime identity, known installation hashes and argument smoke'}|ConvertTo-Json -Depth 7
    exit 0
}
if($Action -eq 'Rollback'){
    if(-not $SelectionRecord){throw 'Rollback requires an explicit selection history record'}
    $record=Get-Content -LiteralPath $SelectionRecord -Raw -Encoding UTF8|ConvertFrom-Json
    if(-not $record.previous_effective.powershell_path){throw 'No prior effective runtime in the selected record'}
    $identity=Test-WbgRuntime $record.previous_effective.powershell_path
    Write-Json $configuration ([ordered]@{schema_version=1;powershell_path=$identity.executable})
    [ordered]@{status='rolled_back';runtime=$identity;configuration=$configuration;private_installation_retained=$true}|ConvertTo-Json -Depth 7
    exit 0
}
if(-not $Archive){$Archive=Join-Path $data 'cache/downloads/PowerShell-7.6.6-win-x64.zip'}
$archivePath=(Resolve-Path -LiteralPath $Archive).Path
if((Get-FileHash -LiteralPath $archivePath).Hash.ToLowerInvariant() -ne $expected){throw 'Archive does not match the fixed official SHA256'}
if(-not $InstallRoot){$InstallRoot=Join-Path $paths.apps_root ('Whiteboxgrind/powershell/'+$version)}
$target=[IO.Path]::GetFullPath($InstallRoot)
if($Action -eq 'Repair'){$target+='-repair-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')}
$previous=$null
if(Test-Path -LiteralPath $configuration){$previous=Get-Content -LiteralPath $configuration -Raw -Encoding UTF8|ConvertFrom-Json}
else{
    $found=Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue|Select-Object -First 1
    if($found){$prior=Test-WbgRuntime $found.Source;$previous=[ordered]@{schema_version=1;powershell_path=$prior.executable}}
}
if(-not(Test-Path -LiteralPath $target)){Expand-Archive -LiteralPath $archivePath -DestinationPath $target}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archivePath)
$files=@()
try{
    foreach($entry in $zip.Entries){
        if(-not $entry.Name){continue}
        $path=[IO.Path]::GetFullPath((Join-Path $target $entry.FullName))
        if(-not $path.StartsWith($target+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'ZIP path escaped installation root'}
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw 'Private runtime is incomplete; use Repair for a new independent copy'}
        $stream=$entry.Open();$sha=[Security.Cryptography.SHA256]::Create()
        try{$digest=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose();$stream.Dispose()}
        if((Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $digest){throw 'Private runtime differs from the official archive; use Repair'}
        $files+=[ordered]@{path=$entry.FullName;sha256=$digest}
    }
}finally{$zip.Dispose()}
$executable=Join-Path $target 'pwsh.exe'
$signature=Get-AuthenticodeSignature -LiteralPath $executable
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Microsoft Corporation*'){throw 'Private pwsh.exe signature is invalid'}
$identity=Test-WbgRuntime $executable
if($identity.powershell_version -ne $version){throw 'Private runtime version mismatch'}
$selection=[ordered]@{schema_version=1;powershell_path=$executable}
$record=[ordered]@{schema_version=1;date_utc=[DateTimeOffset]::UtcNow.ToString('o');action=$Action
    source='https://github.com/PowerShell/PowerShell/releases/tag/v7.6.6';archive=$archivePath;archive_sha256=$expected
    runtime=$identity;signer=$signature.SignerCertificate.Subject;previous_effective=$previous;selection=$selection;files=$files}
Write-Json (Join-Path $target 'runtime-install.json') $record
$historyPath=Join-Path $history ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')+'.json')
Write-Json $historyPath $record
Write-Json $configuration $selection
[ordered]@{status='installed';runtime=$identity;configuration=$configuration;selection_record=$historyPath
    official_files_verified=$files.Count;global_path_changed=$false;default_terminal_changed=$false}|ConvertTo-Json -Depth 7
