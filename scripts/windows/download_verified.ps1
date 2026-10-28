<# Download one fixed official artifact, retaining trusted hash and signature evidence. #>
param(
    [Parameter(Mandatory=$true)][string]$Url,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][string]$HashSource,
    [string]$ExpectedSigner,
    [switch]$Resume,
    [ValidateSet('curl','http')][string]$Transport='curl'
)
$ErrorActionPreference='Stop'
$uri=[Uri]$Url
if($uri.Scheme -ne 'https' -or $uri.Host -notin @('desktop.docker.com','github.com')){throw 'Expected an approved official HTTPS artifact'}
$path=[IO.Path]::GetFullPath($Destination)
[void][IO.Directory]::CreateDirectory((Split-Path -Parent $path))
$transportUsed='existing_verified_file'
$partial=$path+'.partial'
if($Resume -and (Test-Path -LiteralPath $partial) -and -not(Test-Path -LiteralPath $path)){
    if((Get-FileHash -LiteralPath $partial).Hash.ToLowerInvariant() -eq $ExpectedSha256.ToLowerInvariant()){
        Move-Item -LiteralPath $partial -Destination $path
    }
}
if(-not(Test-Path -LiteralPath $path)){
    $transportUsed=$Transport
    $partial=$path+'.partial'
    if((Test-Path -LiteralPath $partial) -and -not $Resume){throw 'An incomplete download exists; inspect it and use -Resume to continue the same fixed artifact'}
    if($Transport -eq 'curl'){
        $curl=Get-Command (Join-Path $env:SystemRoot 'System32/curl.exe') -CommandType Application -ErrorAction Stop
        $curlArgs=@('--fail','--location','--silent','--show-error','--retry','2','--retry-delay','2','--connect-timeout','20','--max-time','1800','--output',$partial)
        if($Resume){$curlArgs+=@('--continue-at','-')}
        & $curl.Source @curlArgs $Url
        if($LASTEXITCODE -ne 0){throw 'Official download failed; partial file retained for inspection'}
    }else{
        Add-Type -AssemblyName System.Net.Http
        $offset=if(Test-Path -LiteralPath $partial){(Get-Item -LiteralPath $partial).Length}else{0}
        $client=New-Object Net.Http.HttpClient
        $client.Timeout=[TimeSpan]::FromMinutes(30)
        $request=New-Object Net.Http.HttpRequestMessage([Net.Http.HttpMethod]::Get,$Url)
        if($offset -gt 0){$request.Headers.Range=New-Object Net.Http.Headers.RangeHeaderValue($offset,$null)}
        try{
            $response=$client.SendAsync($request,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            [void]$response.EnsureSuccessStatusCode()
            if($offset -gt 0 -and [int]$response.StatusCode -ne 206){throw 'Server did not honor resume range'}
            $inputStream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $outputStream=[IO.File]::Open($partial,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read)
            try{
                $buffer=New-Object byte[] 1048576
                while(($count=$inputStream.Read($buffer,0,$buffer.Length)) -gt 0){$outputStream.Write($buffer,0,$count);$outputStream.Flush()}
            }finally{$outputStream.Dispose();$inputStream.Dispose()}
        }finally{$request.Dispose();$client.Dispose()}
    }
    $actual=(Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if($actual -ne $ExpectedSha256.ToLowerInvariant()){throw 'Downloaded SHA256 does not match official metadata; partial file retained'}
    Move-Item -LiteralPath $partial -Destination $path
}
$actual=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
if($actual -ne $ExpectedSha256.ToLowerInvariant()){throw 'Existing file does not match official SHA256'}
$signature=$null
if($ExpectedSigner){
    $s=Get-AuthenticodeSignature -LiteralPath $path
    $signature=[ordered]@{status=[string]$s.Status;subject=$s.SignerCertificate.Subject;thumbprint=$s.SignerCertificate.Thumbprint}
    if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike ('*'+$ExpectedSigner+'*')){throw 'Official artifact signature was not valid for the expected signer'}
}
$record=[ordered]@{schema_version=1;recorded_at_utc=[DateTimeOffset]::UtcNow.ToString('o');source_url=$Url
    hash_source=$HashSource;expected_sha256=$ExpectedSha256.ToLowerInvariant();actual_sha256=$actual
    path=$path;bytes=(Get-Item -LiteralPath $path).Length;signature=$signature;transport=$transportUsed;verified=$true}
[IO.File]::WriteAllText($path+'.download.json',($record|ConvertTo-Json -Depth 7)+"`r`n",(New-Object Text.UTF8Encoding($false)))
$record|ConvertTo-Json -Depth 7
