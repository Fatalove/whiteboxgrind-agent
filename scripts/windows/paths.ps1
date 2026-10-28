<# Deployment paths are explicit and independent of the source checkout. #>
function Get-WbgPaths {
    param([string]$ProjectRoot)
    $settings=$null
    $file=Join-Path $ProjectRoot 'config/deployment.json'
    if(Test-Path -LiteralPath $file){
        $settings=Get-Content -LiteralPath $file -Raw -Encoding UTF8|ConvertFrom-Json
        if($settings.schema_version -ne 1){throw 'Invalid deployment configuration'}
    }
    $data=if($env:WBG_DATA_ROOT){$env:WBG_DATA_ROOT}elseif($settings -and $settings.data_root){$settings.data_root}else{Join-Path (Split-Path -Parent $ProjectRoot) 'whiteboxgrind-data'}
    $apps=if($env:WBG_APPS_ROOT){$env:WBG_APPS_ROOT}elseif($settings -and $settings.apps_root){$settings.apps_root}elseif(Test-Path -LiteralPath 'D:\Apps'){'D:\Apps'}else{Join-Path $env:LOCALAPPDATA 'Programs'}
    $data=[IO.Path]::GetFullPath($data);$apps=[IO.Path]::GetFullPath($apps)
    return [pscustomobject]@{data_root=$data;apps_root=$apps;config_root=(Join-Path $data 'state/config');settings=$settings;deployment_file=$file}
}
function Save-WbgDeployment {
    param([string]$ProjectRoot,[string]$DataRoot,[string]$AppsRoot)
    $paths=Get-WbgPaths $ProjectRoot
    if($DataRoot){$paths.data_root=[IO.Path]::GetFullPath($DataRoot)}
    if($AppsRoot){$paths.apps_root=[IO.Path]::GetFullPath($AppsRoot)}
    [void][IO.Directory]::CreateDirectory((Join-Path $ProjectRoot 'config'))
    [void][IO.Directory]::CreateDirectory((Join-Path $paths.data_root 'state/config'))
    $record=[ordered]@{schema_version=1;data_root=$paths.data_root;apps_root=$paths.apps_root}
    [IO.File]::WriteAllText($paths.deployment_file,($record|ConvertTo-Json)+"`n",(New-Object Text.UTF8Encoding($false)))
    return Get-WbgPaths $ProjectRoot
}
function Get-WbgContainerProfilePath {
    param([string]$ProjectRoot)
    $current=Join-Path (Get-WbgPaths $ProjectRoot).config_root 'container-runtime.json'
    if(Test-Path -LiteralPath $current){return $current}
    $legacy=Join-Path $ProjectRoot 'experiments/container-runtime.json'
    if(Test-Path -LiteralPath $legacy){return $legacy}
    return $current
}
function Get-WbgDockerPath {
    param([string]$ProjectRoot,[switch]$Desktop)
    $paths=Get-WbgPaths $ProjectRoot
    $candidates=New-Object 'Collections.Generic.List[string]'
    if($env:WBG_DOCKER -and -not $Desktop){$candidates.Add($env:WBG_DOCKER)}
    if($paths.settings){
        $selected=if($Desktop){$paths.settings.docker_desktop}else{$paths.settings.docker_executable}
        if($selected){$candidates.Add([string]$selected)}
    }
    $leaf=if($Desktop){'Docker Desktop.exe'}else{'resources/bin/docker.exe'}
    foreach($key in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop')){
        $registered=Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        if($registered -and $registered.InstallLocation){$candidates.Add((Join-Path ([string]$registered.InstallLocation) $leaf))}
    }
    $candidates.Add((Join-Path $paths.apps_root ('Docker/'+$leaf)))
    $candidates.Add((Join-Path $env:LOCALAPPDATA ('Programs/DockerDesktop/'+$leaf)))
    $candidates.Add((Join-Path $env:ProgramFiles ('Docker/Docker/'+$leaf)))
    $found=Get-Command docker.exe -CommandType Application -ErrorAction SilentlyContinue|Select-Object -First 1
    if($found){
        if($Desktop){$candidates.Add([IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $found.Source) '../../Docker Desktop.exe')))}else{$candidates.Add($found.Source)}
    }
    foreach($candidate in $candidates){if(Test-Path -LiteralPath $candidate -PathType Leaf){return [IO.Path]::GetFullPath($candidate)}}
    return $null
}


function Get-WbgDockerStorageRoot {
    param([string]$DockerExecutable,[string]$Context='desktop-linux')
    $kernel=Invoke-WbgProcess $DockerExecutable @('--context',$Context,'info','--format','{{.KernelVersion}}')
    if($kernel.exit_code -ne 0 -or $kernel.stdout -notmatch '(?i)microsoft.*wsl2'){
        throw 'The supported Windows release requires the active WSL2 Docker backend'
    }
    $rows=@(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue|
        ForEach-Object {Get-ItemProperty -LiteralPath $_.PSPath}|Where-Object DistributionName -EQ 'docker-desktop')
    if($rows.Count -ne 1){throw 'Actual Docker WSL storage mapping is unavailable; use the authorized local executor'}
    $base=[string]$rows[0].BasePath
    if($base.StartsWith('\\?\')){$base=$base.Substring(4)}
    $candidate=Split-Path -Parent $base
    if(-not(Test-Path -LiteralPath (Join-Path $candidate 'disk/docker_data.vhdx') -PathType Leaf)){
        throw 'Actual Docker WSL data disk was not found; requested install paths are not proof of physical storage'
    }
    return [IO.Path]::GetFullPath($candidate)
}
