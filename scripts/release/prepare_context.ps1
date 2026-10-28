<# Exact, source-only build context. Source archives are external to Git. #>
param([Parameter(Mandatory=$true)][string]$Destination,[string]$SourceDirectory)
$ErrorActionPreference='Stop'
$project=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
. (Join-Path $project 'scripts/windows/paths.ps1')
if(-not $SourceDirectory){$SourceDirectory=Join-Path (Get-WbgPaths $project).data_root 'cache/sources'}
$target=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $target){throw 'Build context must be new'}
[void][IO.Directory]::CreateDirectory($target)
foreach($name in @('Dockerfile','build_engine.sh','make_baseline.py','engine-inputs.json','system-packages.lock','requirements.lock','bootstrap-ca-certificates.crt')){
 Copy-Item -LiteralPath (Join-Path $project ('container/'+$name)) -Destination (Join-Path $target $name)
}
Copy-Item -LiteralPath (Join-Path $project 'patches/0001-tracer-close-input-pipe.patch') -Destination (Join-Path $target 'patch.patch')
$hashes=[ordered]@{
 'whiteboxgrind-b4f5b78a415aaf4a864f31b9d85c3305a4970b4f.tar.gz'='80c3866535447dea51feabdcfd334bbb00bd6723ec42ed529f87c023dece237a'
 'asynchronous-2584d9c314451d7afb318d36bd8c86bf57aa945a.tar.gz'='2294d73ad32c7170815ac18911a381e2e521e1a0db9de9e37aa529ff95872a5d'
 'tiny-AES-c-23856752fbd139da0b8ca6e471a13d5bcc99a08d.tar.gz'='b91c219c4ff2dd4f24750130c27045e264b52d763d3b5b2cd24230334176f820'
}
$vendor=Join-Path $target 'vendor';[void][IO.Directory]::CreateDirectory($vendor)
$lines=@()
foreach($name in $hashes.Keys){
 $source=Join-Path $SourceDirectory $name
 if((Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -ne $hashes[$name]){throw 'Source archive digest differs'}
 Copy-Item -LiteralPath $source -Destination (Join-Path $vendor $name)
 $lines+=($hashes[$name]+'  '+$name)
}
[IO.File]::WriteAllText((Join-Path $vendor 'archives.sha256'),($lines -join "`n")+"`n",[Text.UTF8Encoding]::new($false))
$app=Join-Path $target 'app';[void][IO.Directory]::CreateDirectory($app)
foreach($directory in @('src/wbg','fixtures','scripts/windows','patches')){
 $destinationPath=Join-Path $app $directory
 [void][IO.Directory]::CreateDirectory($destinationPath)
 Get-ChildItem -LiteralPath (Join-Path $project $directory) -File -Recurse | Where-Object {$_.Extension -ne '.pyc' -and $_.FullName -notmatch '[\\/]__pycache__[\\/]'} | ForEach-Object {
  $relative=$_.FullName.Substring((Join-Path $project $directory).Length+1)
  $file=Join-Path $destinationPath $relative
  [void][IO.Directory]::CreateDirectory((Split-Path -Parent $file))
  Copy-Item -LiteralPath $_.FullName -Destination $file
 }
}
foreach($name in @('wbg','wbg.ps1','wbg-container.ps1','request_cancel_linux.py')){
 Copy-Item -LiteralPath (Join-Path $project ('scripts/'+$name)) -Destination (Join-Path $app ('scripts/'+$name))
}
$files=@(Get-ChildItem -LiteralPath $target -File -Recurse|ForEach-Object {@{path=$_.FullName.Substring($target.Length+1).Replace('\','/');bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName).Hash.ToLowerInvariant()}})
$record=@{schema_version=1;scope='Whitelisted build inputs; no contest source, candidate, grants or personal paths';files=$files}
[IO.File]::WriteAllText((Join-Path $target 'context-lock.json'),($record|ConvertTo-Json -Depth 7),[Text.UTF8Encoding]::new($false))
@{status='prepared';context=$target;files=$files.Count}|ConvertTo-Json
