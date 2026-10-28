<# Pack only immutable manifest entries; never include installed state, history or QA outputs. #>
param([Parameter(Mandatory=$true)][string]$BundleRoot,[Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath $BundleRoot).Path
$target=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $target){throw 'Archive must be new'}
[void][IO.Directory]::CreateDirectory((Split-Path -Parent $target))
$manifest=Get-Content -LiteralPath (Join-Path $root 'release-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stream=[IO.File]::Open($target+'.partial',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
$zip=New-Object IO.Compression.ZipArchive($stream,[IO.Compression.ZipArchiveMode]::Create)
try{
    foreach($row in @($manifest.files|Sort-Object path)+@(@{path='release-manifest.json';sha256=(Get-FileHash -LiteralPath (Join-Path $root 'release-manifest.json')).Hash.ToLowerInvariant()})){
        $path=[IO.Path]::GetFullPath((Join-Path $root $row.path))
        if(-not $path.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Manifest path escaped bundle'}
        if((Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $row.sha256){throw ('Immutable bundle file changed: '+$row.path)}
        $level=if($row.path -match '\.(zip|tar|gz)$'){[IO.Compression.CompressionLevel]::NoCompression}else{[IO.Compression.CompressionLevel]::Optimal}
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,$path,$row.path,$level)
    }
}finally{$zip.Dispose();$stream.Dispose()}
Move-Item -LiteralPath ($target+'.partial') -Destination $target
$record=[ordered]@{schema_version=1;version=$manifest.version;archive=$target;bytes=(Get-Item -LiteralPath $target).Length
    sha256=(Get-FileHash -LiteralPath $target).Hash.ToLowerInvariant();files=$manifest.files.Count+1;image=$manifest.image.id
    scope='Only manifest-listed files and manifest; installed profiles, history, local experiments and QA state excluded';public_distribution=$false}
[IO.File]::WriteAllText($target+'.json',($record|ConvertTo-Json -Depth 8)+"`n",(New-Object Text.UTF8Encoding($false)))
$record|ConvertTo-Json -Depth 8
exit 0
