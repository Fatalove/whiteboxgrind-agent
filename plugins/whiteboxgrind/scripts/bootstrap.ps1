<# Fetch one pinned release or use a hash-verified offline archive; no Git/host Python. #>
param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [ValidateSet('Install','Check','Repair','Upgrade')][string]$Action='Check',
    [string]$Archive,
    [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [string]$Descriptor,
    [switch]$AcceptDockerTerms,
    [string]$DockerInstaller,
    [string]$DataRoot,
    [string]$AppsRoot
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try{
    if(-not $Descriptor){$Descriptor=Join-Path $PSScriptRoot 'release-source.json'}
    $target=[IO.Path]::GetFullPath($Destination)
    if(-not(Test-Path -LiteralPath (Join-Path $target 'release-manifest.json'))){
        if($Action -eq 'Check'){
            @{schema_version=1;status='not_ready';reason_code='tool_not_installed';tool_root=$target}|ConvertTo-Json
            exit 2
        }
        if(Test-Path -LiteralPath $target){throw 'An incomplete or unrelated destination exists; preserve it and choose a new destination'}
        $source=$null
        if(Test-Path -LiteralPath $Descriptor){
            $source=Get-Content -LiteralPath $Descriptor -Raw -Encoding UTF8|ConvertFrom-Json
            if($source.schema_version -ne 1 -or $source.bundle.sha256 -notmatch '^[a-f0-9]{64}$'){throw 'Invalid pinned release descriptor'}
        }
        if(-not $ExpectedSha256 -and $source){$ExpectedSha256=$source.bundle.sha256}
        if(-not $ExpectedSha256){throw 'A published fixed release descriptor or explicit expected SHA256 is required; publication is not configured in this candidate'}
        if(-not $Archive){
            if(-not $source){throw 'No published fixed release URL; provide the verified offline archive'}
            $uri=[Uri]$source.bundle.url
            if($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or $uri.AbsolutePath -notmatch '^/[^/]+/[^/]+/releases/download/[^/]+/[^/]+$'){throw 'Expected a fixed GitHub release asset URL'}
            $downloadRoot=Join-Path (Split-Path -Parent $target) 'downloads'
            [void][IO.Directory]::CreateDirectory($downloadRoot)
            $Archive=Join-Path $downloadRoot ([IO.Path]::GetFileName($uri.AbsolutePath))
            if(-not(Test-Path -LiteralPath $Archive)){
                Add-Type -AssemblyName System.Net.Http
                $client=New-Object Net.Http.HttpClient
                $client.Timeout=[TimeSpan]::FromMinutes(30)
                try{
                    $response=$client.GetAsync($uri,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
                    [void]$response.EnsureSuccessStatusCode()
                    $stream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                    $output=[IO.File]::Open($Archive+'.partial',[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read)
                    try{$stream.CopyTo($output)}finally{$output.Dispose();$stream.Dispose()}
                }finally{$client.Dispose()}
                if((Get-FileHash -LiteralPath ($Archive+'.partial')).Hash.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()){throw 'Release download SHA256 mismatch; partial file retained'}
                Move-Item -LiteralPath ($Archive+'.partial') -Destination $Archive
            }
        }
        $archivePath=(Resolve-Path -LiteralPath $Archive).Path
        if((Get-FileHash -LiteralPath $archivePath).Hash.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()){throw 'Offline release SHA256 mismatch'}
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip=[IO.Compression.ZipFile]::OpenRead($archivePath)
        try{
            foreach($entry in $zip.Entries){
                $entryPath=[IO.Path]::GetFullPath((Join-Path $target $entry.FullName))
                if(-not $entryPath.StartsWith($target+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Archive path escaped destination'}
                if((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000){throw 'Symlink archive entry refused'}
            }
        }finally{$zip.Dispose()}
        Expand-Archive -LiteralPath $archivePath -DestinationPath $target
        if(-not(Test-Path -LiteralPath (Join-Path $target 'release-manifest.json'))){throw 'Release archive has no root manifest; extracted files retained for review'}
    }
    $installer=Join-Path $target 'scripts/install.ps1'
    if(-not(Test-Path -LiteralPath $installer)){throw 'Release installer missing'}
    $values=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$installer,'-Action',$Action)
    if($DataRoot){$values+=@('-DataRoot',$DataRoot)}
    if($AppsRoot){$values+=@('-AppsRoot',$AppsRoot)}
    if($AcceptDockerTerms){$values+='-AcceptDockerTerms'}
    if($DockerInstaller){$values+=@('-DockerInstaller',$DockerInstaller)}
    $bootstrap=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    & $bootstrap @values
    exit $LASTEXITCODE
}catch{
    @{schema_version=1;status='error';reason_code='release_bootstrap_failed';detail=$_.Exception.Message;analysis_started=$false}|ConvertTo-Json -Depth 6
    exit 40
}
