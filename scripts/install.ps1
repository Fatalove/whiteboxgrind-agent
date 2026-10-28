<# Unpacked Windows release entry. Requires no Git or host Python; never runs analysis. #>
param(
    [ValidateSet('Check','Install','Repair','Rollback','Upgrade')][string]$Action='Check',
    [switch]$AcceptDockerTerms,
    [string]$DockerInstaller,
    [string]$SelectionRecord,
    [string]$DataRoot,
    [string]$AppsRoot
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'windows/host.ps1')
if(-not $DataRoot -and $Action -in @('Install','Upgrade','Repair')){
    $initial=Get-WbgPaths $root
    $appBase=if($AppsRoot){[IO.Path]::GetFullPath($AppsRoot)}else{$initial.apps_root}
    $pointer=Join-Path $appBase 'Whiteboxgrind/current.json'
    if(Test-Path -LiteralPath $pointer){
        $current=Get-Content -LiteralPath $pointer -Raw -Encoding UTF8|ConvertFrom-Json
        if($current.schema_version -ne 1 -or -not $current.data_root){throw 'Invalid current installation pointer'}
        $DataRoot=[string]$current.data_root
    }elseif($Action -eq 'Upgrade'){
        throw 'Upgrade requires the existing -DataRoot; no new empty accounting will be selected'
    }
}
$paths=if($Action -eq 'Check'){Get-WbgPaths $root}else{Save-WbgDeployment $root $DataRoot $AppsRoot}
if($DataRoot){$env:WBG_DATA_ROOT=[IO.Path]::GetFullPath($DataRoot);$paths=Get-WbgPaths $root}
if($AppsRoot){$env:WBG_APPS_ROOT=[IO.Path]::GetFullPath($AppsRoot);$paths=Get-WbgPaths $root}
$data=$paths.data_root
$recordRoot=Join-Path $data ('state/install-history/'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
[void][IO.Directory]::CreateDirectory($recordRoot)
$utf8=New-Object Text.UTF8Encoding($false)
function Save-InstallJson([string]$Name,$Value){
    [IO.File]::WriteAllText((Join-Path $recordRoot ($Name+'.json')),($Value|ConvertTo-Json -Depth 24)+"`n",$utf8)
}
function Get-ReleaseFile([string]$Relative){
    $path=[IO.Path]::GetFullPath((Join-Path $root $Relative))
    if(-not $path.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Release path escaped bundle root'}
    return $path
}
function Invoke-InstallChild([string]$Name,[string]$Exe,[string[]]$Values){
    $result=Invoke-WbgProcess $Exe $Values -TimeoutSeconds 0
    Save-InstallJson $Name @{executable=$Exe;arguments=$Values;result=$result}
    if($result.exit_code -eq 3010){
        $pending=@{schema_version=1;status='restart_required';reason_code='restart_and_recheck';step=$Name;evidence=$recordRoot;analysis_started=$false;restart_performed=$false}
        Save-InstallJson 'restart-required' $pending
        $pending|ConvertTo-Json -Depth 7
        exit 3010
    }
    if($result.exit_code -ne 0){throw ($Name+' failed with caller exit '+$result.exit_code+': '+$result.stderr+$result.stdout)}
    return $result
}
try{
    if($env:OS -ne 'Windows_NT'){throw 'This entry is for the Windows release'}
    $manifest=Get-Content -LiteralPath (Join-Path $root 'release-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if($manifest.schema_version -ne 1 -or $manifest.image.id -notmatch '^sha256:[0-9a-f]{64}$'){throw 'Invalid fixed release identity'}
    $checked=0
    foreach($row in $manifest.files){
        $path=Get-ReleaseFile $row.path
        if(-not(Test-Path -LiteralPath $path -PathType Leaf) -or (Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $row.sha256){throw ('Release file integrity mismatch: '+$row.path)}
        $checked++
    }
    Save-InstallJson 'release-integrity' @{version=$manifest.version;image=$manifest.image;verified_files=$checked}
    $runtimeScript=Join-Path $root 'scripts/windows/install_runtime.ps1'
    $bootstrap=(Get-WbgIdentity).executable
    if($Action -eq 'Rollback'){
        if(-not $SelectionRecord){throw 'Rollback requires the explicit runtime selection record'}
        $null=Invoke-InstallChild 'runtime-rollback' $bootstrap @('-NoProfile','-ExecutionPolicy','Bypass','-File',$runtimeScript,'-Action','Rollback','-SelectionRecord',$SelectionRecord)
    }elseif($Action -in @('Install','Repair','Upgrade')){
        $runtimeArchive=Get-ReleaseFile $manifest.powershell.archive
        $runtimeAction=if($Action -eq 'Repair'){'Repair'}else{'Install'}
        $null=Invoke-InstallChild 'private-runtime' $bootstrap @('-NoProfile','-ExecutionPolicy','Bypass','-File',$runtimeScript,'-Action',$runtimeAction,'-Archive',$runtimeArchive)
    }
    . (Join-Path $root 'scripts/windows/prerequisites.ps1') -Library
    $prerequisites=Get-WbgPrerequisites -Install:($Action -in @('Install','Repair','Upgrade'))
    Save-InstallJson 'prerequisites' $prerequisites
    if($prerequisites.status -ne 'ready'){
        @{schema_version=1;status=$prerequisites.status;reason_code=$prerequisites.reason_code;prerequisites=$prerequisites;evidence=$recordRoot;analysis_started=$false}|ConvertTo-Json -Depth 8
        if($prerequisites.status -eq 'restart_required'){exit 3010}else{exit 2}
    }
    $hostRecord=Get-WbgHost $root
    if(-not $hostRecord.ready){throw ('Windows host requires configuration: '+($hostRecord|ConvertTo-Json -Depth 12 -Compress))}
    $runtime=$hostRecord.selected_runtime.executable
    $docker=Get-WbgDockerPath $root
    if(-not $docker){
        if($Action -notin @('Install','Repair','Upgrade')){throw 'Docker Desktop is missing'}
        if(-not $AcceptDockerTerms){throw 'Docker first-use agreement requires the user choice; use -AcceptDockerTerms only after agreement'}
        $download=$DockerInstaller
        if(-not $download){
            $download=Join-Path $data 'cache/downloads/Docker-Desktop-4.97.0-Installer.exe'
            $null=Invoke-InstallChild 'download-docker' $runtime @('-NoProfile','-File',(Join-Path $root 'scripts/windows/download_verified.ps1'),
                '-Url',$manifest.docker.url,'-Destination',$download,'-ExpectedSha256',$manifest.docker.sha256,'-HashSource',$manifest.docker.hash_source,
                '-ExpectedSigner','Docker Inc','-Resume','-Transport','http')
        }
        $null=Invoke-InstallChild 'install-docker' $runtime @('-NoProfile','-File',(Join-Path $root 'scripts/windows/install_docker.ps1'),'-Installer',$download,'-DataRoot',(Join-Path $data 'docker-wsl'),'-InstallRoot',(Join-Path $paths.apps_root 'Docker'),'-AcceptTerms')
        $docker=Get-WbgDockerPath $root
    }
    $server=Invoke-WbgProcess $docker @('--context','desktop-linux','version','--format','{{json .Server}}') -TimeoutSeconds 20
    if($server.exit_code -ne 0 -and $Action -in @('Install','Repair','Upgrade')){
        $desktop=Get-WbgDockerPath $root -Desktop
        if($desktop -and (Test-Path -LiteralPath $desktop)){Start-Process -FilePath $desktop -WindowStyle Hidden}
        for($attempt=0;$attempt -lt 36;$attempt++){
            Start-Sleep -Seconds 5
            $server=Invoke-WbgProcess $docker @('--context','desktop-linux','version','--format','{{json .Server}}') -TimeoutSeconds 10
            if($server.exit_code -eq 0){break}
        }
    }
    Save-InstallJson 'docker-server' $server
    if($server.exit_code -ne 0){throw 'Docker backend is not ready; preserved installation records identify the failing step'}
    if($Action -in @('Install','Repair','Upgrade')){
        $image=Invoke-WbgProcess $docker @('--context','desktop-linux','image','inspect',$manifest.image.id) -TimeoutSeconds 20
        if($image.exit_code -ne 0){$null=Invoke-InstallChild 'offline-image-load' $docker @('--context','desktop-linux','load','--input',(Get-ReleaseFile $manifest.image.archive))}
        $state=Join-Path $data 'state/container'
        $profilePath=Get-WbgContainerProfilePath $root
        if(-not(Test-Path -LiteralPath $profilePath)){
            foreach($legacy in @('config/windows-runtime.json','container-state/session.json','tools/stage-d-provenance/prior-accounting.json')){
                if(Test-Path -LiteralPath (Join-Path $data $legacy)){
                    throw 'legacy_state_requires_migration: preserve old history and accounting before selecting a new runtime; no fresh volume will be created'
                }
            }
        }
        if(Test-Path -LiteralPath $profilePath){
            $priorProfile=Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8|ConvertFrom-Json
            if($priorProfile.image -ne $manifest.image.id -and $Action -ne 'Upgrade'){throw 'Existing image selection differs; explicitly select Upgrade to preserve and replace it'}
            Save-InstallJson 'previous-container-selection' $priorProfile
            $state=$priorProfile.state_root
            $deploymentProfile=$priorProfile
            $deploymentProfile.image=$manifest.image.id
        }else{
            $digest=[Security.Cryptography.SHA256]::Create()
            try{$suffix=([BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($state.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,16)}finally{$digest.Dispose()}
            $deploymentProfile=[ordered]@{schema_version=1;image=$manifest.image.id;volume=('whiteboxgrind-'+$suffix);docker_context='desktop-linux'
                state_root=$state;export_root=(Join-Path $data 'cases');data_root=(Join-Path $data 'docker-wsl')}
        }
        $deploymentProfile.data_root=Get-WbgDockerStorageRoot $docker 'desktop-linux'
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $profilePath))
        [IO.File]::WriteAllText($profilePath,($deploymentProfile|ConvertTo-Json -Depth 12)+"`n",$utf8)
    }
    $doctor=Invoke-WbgProcess $runtime @('-NoProfile','-File',(Join-Path $root 'scripts/wbg.ps1'),'--backend','docker','doctor','--json') -TimeoutSeconds 0
    Save-InstallJson 'doctor' $doctor
    $body=$doctor.stdout|ConvertFrom-Json
    if($doctor.exit_code -ne 0 -or -not $body.ready){throw ('Installed environment is not ready: '+$doctor.stdout+$doctor.stderr)}
    if($Action -in @('Install','Upgrade','Repair')){
        $pointer=Join-Path $paths.apps_root 'Whiteboxgrind/current.json'
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $pointer))
        [IO.File]::WriteAllText($pointer,(@{schema_version=1;version=$manifest.version;tool_root=$root;data_root=$data}|ConvertTo-Json),$utf8)
    }
    Save-InstallJson 'summary' @{status='ready';action=$Action;version=$manifest.version;image=$manifest.image.id;evidence=$recordRoot;analysis_started=$false}
    @{schema_version=1;status='ready';action=$Action;version=$manifest.version;image=$manifest.image.id;tool_root=$root;evidence=$recordRoot;analysis_started=$false}|ConvertTo-Json -Depth 8
    exit 0
}catch{
    $failure=@{schema_version=1;status='error';action=$Action;reason_code='installation_step_failed';detail=$_.Exception.Message;evidence=$recordRoot;analysis_started=$false}
    Save-InstallJson 'failure' $failure
    $failure|ConvertTo-Json -Depth 8
    exit 40
}
