<# Local release allowlist. No remote publication. #>
param([Parameter(Mandatory=$true)][string]$ImageId,[Parameter(Mandatory=$true)][string]$BuildContext,
 [Parameter(Mandatory=$true)][string]$LicenseDirectory,[Parameter(Mandatory=$true)][string]$Destination,
 [Parameter(Mandatory=$true)][string]$PowerShellArchive)
$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $project 'scripts/windows/host.ps1')
$version=(Get-Content -LiteralPath (Join-Path $project 'VERSION') -Raw).Trim()
if($ImageId -notmatch '^sha256:[0-9a-f]{64}$'){throw 'Fixed image digest required'}
$target=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $target){throw 'Candidate directory must be new'}
$docker=Get-WbgDockerPath $project
$check=Invoke-WbgProcess $docker @('--context','desktop-linux','image','inspect','--format','{{json .}}',$ImageId)
if($check.exit_code -ne 0){throw 'Image unavailable'}
$identity=$check.stdout|ConvertFrom-Json
if($identity.Id -ne $ImageId -or $identity.Config.Labels.'io.whiteboxgrind.engine.commit' -ne 'b4f5b78a415aaf4a864f31b9d85c3305a4970b4f'){throw 'Image identity mismatch'}
if($identity.Config.Labels.'org.opencontainers.image.version' -ne $version){throw 'Image version differs from source VERSION'}
if((Get-FileHash -LiteralPath $PowerShellArchive).Hash.ToLowerInvariant() -ne '02fe458be20493fbdf43f61ea20610b811ee6c738ab1676c61b9cfcd1a33c860'){throw 'PowerShell archive differs'}
[void][IO.Directory]::CreateDirectory($target)
foreach($directory in @('src','fixtures','patches','plugins','docs','scripts/windows')){
 $destinationPath=Join-Path $target $directory
 [void][IO.Directory]::CreateDirectory($destinationPath)
 Get-ChildItem -LiteralPath (Join-Path $project $directory) -Recurse -File -Force | Where-Object {$_.Extension -ne '.pyc' -and $_.FullName -notmatch '[\\/]__pycache__[\\/]'} | ForEach-Object {
  $relative=$_.FullName.Substring((Join-Path $project $directory).Length+1)
  $file=Join-Path $destinationPath $relative
  [void][IO.Directory]::CreateDirectory((Split-Path -Parent $file))
  Copy-Item -LiteralPath $_.FullName -Destination $file
 }
}
foreach($file in @('scripts/install.ps1','scripts/wbg.ps1','scripts/wbg-container.ps1','scripts/wbg','scripts/request_cancel_linux.py','README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','VERSION')){
 Copy-Item -LiteralPath (Join-Path $project $file) -Destination (Join-Path $target $file)
}
[void][IO.Directory]::CreateDirectory((Join-Path $target 'config'))
Copy-Item -LiteralPath (Join-Path $project 'config/runtime.json') -Destination (Join-Path $target 'config/runtime.json')
foreach($name in @('artifacts','sources','licenses')){[void][IO.Directory]::CreateDirectory((Join-Path $target $name))}
Copy-Item -LiteralPath $BuildContext -Destination (Join-Path $target 'sources/build-context') -Recurse
Copy-Item -LiteralPath $LicenseDirectory -Destination (Join-Path $target 'licenses/upstream') -Recurse
Copy-Item -LiteralPath $PowerShellArchive -Destination (Join-Path $target 'artifacts/PowerShell-7.6.6-win-x64.zip')
$saved=Invoke-WbgProcess $docker @('--context','desktop-linux','image','save','--output',(Join-Path $target 'artifacts/whiteboxgrind-image.tar'),$ImageId) -TimeoutSeconds 0
if($saved.exit_code -ne 0){throw ('Image save failed: '+$saved.stderr)}
$files=@(Get-ChildItem -LiteralPath $target -Recurse -File |ForEach-Object {@{path=$_.FullName.Substring($target.Length+1).Replace('\','/');bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant()}})
$manifest=@{schema_version=1;version=$version;distribution='local_candidate';
 image=@{id=$ImageId;archive='artifacts/whiteboxgrind-image.tar'};
 powershell=@{version='7.6.6';archive='artifacts/PowerShell-7.6.6-win-x64.zip'};
 docker=@{version='4.97.0';url='https://desktop.docker.com/win/main/amd64/244584/Docker%20Desktop%20Installer.exe';sha256='2668273f82b342a058a28f9ab53ea7bddde10bb6d51307ce2ec54c2d36459744';hash_source='https://desktop.docker.com/win/main/amd64/244584/checksums.txt'};
 acceptance=@{clean_machine=$false;public_distribution=$false;new_chat=$false};files=$files}
[IO.File]::WriteAllText((Join-Path $target 'release-manifest.json'),($manifest|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
@{status='prepared';version=$version;files=$files.Count;public_distribution=$false}|ConvertTo-Json
