<# Windows adapter for the existing Linux CLI in one pinned local Docker image. #>
function Invoke-WbgContainerCli {
    param([string]$ToolRoot,[string[]]$CliArgs,$WindowsHost)
    $containerProfilePath=Get-WbgContainerProfilePath $ToolRoot
    if(-not(Test-Path -LiteralPath $containerProfilePath)){
        return @{exit_code=2;body=@{schema_version=1;command='doctor';status='not_ready';ready=$false;reason_code='container_configuration_missing'}}
    }
    $containerProfile=Get-Content -LiteralPath $containerProfilePath -Raw -Encoding UTF8|ConvertFrom-Json
    if($containerProfile.schema_version -ne 1 -or $containerProfile.image -notmatch '^sha256:[0-9a-f]{64}$' -or
       $containerProfile.volume -notmatch '^whiteboxgrind-[a-z0-9-]+$' -or $containerProfile.docker_context -ne 'desktop-linux'){
        throw 'Invalid pinned local container profile'
    }
    $docker=Get-WbgDockerPath $ToolRoot
    if(-not $docker){throw 'Docker CLI not installed'}
    function Invoke-WbgDockerLocal([string[]]$Values,[int]$Timeout=30){
        return Invoke-WbgProcess $docker (@('--context',$containerProfile.docker_context)+$Values) -TimeoutSeconds $Timeout
    }
    function New-WbgDockerMount([string]$Kind,[string]$Source,[string]$Target,[bool]$ReadOnly=$false){
        $field='source='+$Source
        if($field.Contains(',')){$field='"'+$field.Replace('"','""')+'"'}
        return 'type='+$Kind+','+$field+',target='+$Target+$(if($ReadOnly){',readonly'}else{''})
    }
    function Write-WbgContainerJson([string]$Path,$Value){
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
        [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 24)+"`n",(New-Object Text.UTF8Encoding($false)))
    }
    $command=if($CliArgs.Count){$CliArgs[0]}else{''}
    if($command -notin @('doctor','history','analyze','demo','probe','status','decide','cancel','case','cleanup')){throw 'Expected a supported CLI command'}
    $serverCheck=Invoke-WbgDockerLocal @('version','--format','{{json .Server}}')
    if($serverCheck.exit_code -ne 0){
        return @{exit_code=2;body=@{schema_version=1;command=$command;status='not_ready';ready=$false;reason_code='container_backend_unavailable';detail=$serverCheck.stderr}}
    }
    $imageCheck=Invoke-WbgDockerLocal @('image','inspect','--format','{{json .}}',$containerProfile.image)
    if($imageCheck.exit_code -ne 0){
        return @{exit_code=2;body=@{schema_version=1;command=$command;status='not_ready';ready=$false;reason_code='container_image_missing';detail=$imageCheck.stderr}}
    }
    $image=$imageCheck.stdout|ConvertFrom-Json
    if($image.Config.Labels.'io.whiteboxgrind.engine.commit' -ne 'b4f5b78a415aaf4a864f31b9d85c3305a4970b4f'){
        throw 'Pinned image engine identity mismatch'
    }
    $containerProfile.data_root=Get-WbgDockerStorageRoot $docker $containerProfile.docker_context
    $stateRoot=[IO.Path]::GetFullPath($containerProfile.state_root)
    [void][IO.Directory]::CreateDirectory($stateRoot)
    $identityHash=[Security.Cryptography.SHA256]::Create()
    try{$owner=([BitConverter]::ToString($identityHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($stateRoot.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,16)}finally{$identityHash.Dispose()}
    if($containerProfile.owner){
        if($containerProfile.owner -notmatch '^[a-f0-9]{16}$'){throw 'Invalid stable volume owner'}
        $owner=$containerProfile.owner
    }
    $volumeCheck=Invoke-WbgDockerLocal @('volume','inspect','--format','{{json .}}',$containerProfile.volume)
    if($volumeCheck.exit_code -eq 0){
        $volume=$volumeCheck.stdout|ConvertFrom-Json
        if($volume.Labels.'io.whiteboxgrind.owner' -ne $owner){throw 'Volume belongs to another installation'}
    }else{
        $created=Invoke-WbgDockerLocal @('volume','create','--label',('io.whiteboxgrind.owner='+$owner),$containerProfile.volume)
        if($created.exit_code -ne 0){throw ('Volume creation failed: '+$created.stderr)}
    }
    $sessionPath=Join-Path $stateRoot 'session.json'
    $base=@('--init','--user','1000:1000','--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--pids-limit','256','--memory','4g','--memory-swap','5g','--cpus','2',
            '--tmpfs','/tmp:rw,nosuid,size=268435456,mode=1777','--mount',(New-WbgDockerMount 'volume' $containerProfile.volume '/work'))
    if($command -in @('status','decide','cancel')){
        if(-not(Test-Path -LiteralPath $sessionPath)){
            if($command -eq 'status'){return @{exit_code=0;body=@{schema_version=1;status='idle';run_id=$null;decision=$null}}}
            throw 'No owned container session'
        }
        $session=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json
        $inspected=Invoke-WbgDockerLocal @('inspect','--format','{{json .}}',$session.container_id)
        if($inspected.exit_code -ne 0){throw 'Owned container is unavailable; preserved run data require review'}
        $container=$inspected.stdout|ConvertFrom-Json
        if($container.Id -ne $session.container_id -or $container.Config.Labels.'io.whiteboxgrind.owner' -ne $owner){throw 'Container ownership mismatch'}
        if($container.State.Running){
            $result=Invoke-WbgDockerLocal (@('exec',$container.Id,'/opt/wbg-engine/venv/bin/python','-m','wbg')+$CliArgs) 0
            $body=$result.stdout|ConvertFrom-Json
        }else{
            if($command -ne 'status'){throw 'Run has already terminated'}
            # Read the requested run from the durable volume, including older runs.
            # Read completed records with the selected compatible CLI, retaining original execution identity.
            $readerBase=@($base|ForEach-Object {if($_ -like 'type=volume,*target=/work'){$_+',readonly'}else{$_}})
            $view=Invoke-WbgDockerLocal (@('run','--rm')+$readerBase+@($containerProfile.image)+$CliArgs) 0
            if($view.exit_code -eq 0 -and $view.stdout.Trim()){$body=$view.stdout|ConvertFrom-Json}
            elseif($view.stdout.Trim() -and -not $container.State.OOMKilled){$body=$view.stdout|ConvertFrom-Json}
            else{$body=[pscustomobject]@{schema_version=1;status=if($container.State.OOMKilled){'resource_limit'}else{'error'};
                reason_code=if($container.State.OOMKilled){'container_oom'}else{'container_exit_without_result'};
                execution=@{status='incomplete'};recovery=@{status='undetermined'};detail=$view.stderr}}
            $result=[pscustomobject]@{exit_code=$view.exit_code}
        }
        if(-not $session.run_id -or $body.run_id -eq $session.run_id){
            $body|Add-Member -NotePropertyName container -NotePropertyValue @{id=$container.Id;image=$session.image;reader_image=$(if($container.State.Running){$session.image}else{$containerProfile.image});running=$container.State.Running;exit_code=$container.State.ExitCode;oom_killed=$container.State.OOMKilled} -Force
        }
        return @{exit_code=$result.exit_code;body=$body}
    }
    if($command -in @('analyze','demo','probe') -and (Test-Path -LiteralPath $sessionPath)){
        $prior=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json
        $probe=Invoke-WbgDockerLocal @('inspect','--format','{{json .State.Running}}',$prior.container_id)
        if($probe.exit_code -eq 0 -and $probe.stdout.Trim() -eq 'true'){throw 'An owned analysis is already running'}
    }
    $requestRoot=Join-Path $stateRoot ('request-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
    $provenance=Join-Path $requestRoot 'provenance'
    [void][IO.Directory]::CreateDirectory($provenance)
    $resourceFile=Join-Path $provenance 'host-resources.json'
    $forward=New-Object 'Collections.Generic.List[string]'
    $mounts=@()
    $exportRoot=[IO.Path]::GetFullPath($containerProfile.export_root)
    $originalConfig=$null
    $sourcePath=$null
    $sourceMount='/inputs/source.c'
    for($index=0;$index -lt $CliArgs.Count;$index++){
        $value=$CliArgs[$index];$forward.Add($value)
        if($value -eq '--config'){
            $index++;if($index -ge $CliArgs.Count -or $originalConfig){throw 'Expected one configuration path'}
            $originalConfig=(Resolve-Path -LiteralPath $CliArgs[$index]).Path
            $metadata=Invoke-WbgDockerLocal (@('run','--rm','--network','none','--read-only','--user','1000:1000','--memory','256m','--cpus','1',
                '--mount',(New-WbgDockerMount 'bind' $originalConfig '/inputs/config' $true),$containerProfile.image,'metadata','/inputs/config'))
            if($metadata.exit_code -ne 0){throw ('Container configuration metadata failed: '+$metadata.stdout+$metadata.stderr)}
            $meta=$metadata.stdout|ConvertFrom-Json
            if([IO.Path]::IsPathRooted($meta.target.source)){$sourcePath=[IO.Path]::GetFullPath($meta.target.source)}
            else{$sourcePath=[IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $originalConfig) $meta.target.source))}
            if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){throw 'Configured target source missing'}
            if((Get-FileHash -LiteralPath $sourcePath).Hash.ToLowerInvariant() -ne $meta.target.sha256){throw 'Configured target SHA256 mismatch'}
            $sourceMount='/inputs/source'+[IO.Path]::GetExtension($sourcePath)
            $mounts+=@('--mount',(New-WbgDockerMount 'bind' $originalConfig '/inputs/config' $true),'--mount',(New-WbgDockerMount 'bind' $sourcePath $sourceMount $true))
            $forward.Add('/inputs/config')
        }elseif($value -eq '--out'){
            $index++;if($index -ge $CliArgs.Count){throw 'Missing output directory'}
            $exportRoot=[IO.Path]::GetFullPath($CliArgs[$index])
            if(Test-Path -LiteralPath $exportRoot){throw 'Output directory must be new'}
            $forward.Add('/exports')
        }
    }
    if($command -eq 'case'){
        $position=[Array]::IndexOf([string[]]$CliArgs,'--case-root')
        if($position -lt 0 -or $position+1 -ge $CliArgs.Count){throw 'case prepare requires --case-root'}
        $caseRoot=[IO.Path]::GetFullPath($CliArgs[$position+1])
        [void][IO.Directory]::CreateDirectory($caseRoot)
        $forward[$position+1]='/case'
        $mounts+=@('--mount',(New-WbgDockerMount 'bind' $caseRoot '/case'))
    }
    if($command -eq 'cleanup'){
        $runPos=[Array]::IndexOf([string[]]$CliArgs,'--run-id')
        if($runPos -lt 0 -or $runPos+1 -ge $CliArgs.Count){throw 'cleanup requires --run-id'}
        $exportsPath=Join-Path $stateRoot 'run-exports.json'
        if(-not(Test-Path -LiteralPath $exportsPath)){throw 'No recorded export for this installation'}
        $exports=Get-Content -LiteralPath $exportsPath -Raw -Encoding UTF8|ConvertFrom-Json
        $exportRoot=$exports.($CliArgs[$runPos+1])
        if(-not $exportRoot -or -not(Test-Path -LiteralPath (Join-Path $exportRoot 'result.json'))){throw 'Export is unavailable; preserve data and locate the task output'}
        $exportResult=Get-Content -LiteralPath (Join-Path $exportRoot 'result.json') -Raw -Encoding UTF8|ConvertFrom-Json
        if($exportResult.run_id -ne $CliArgs[$runPos+1]){throw 'Export run identity mismatch'}
        $forward.Add('--export-root');$forward.Add('/exports')
    }
    [void][IO.Directory]::CreateDirectory($exportRoot)
    & (Join-Path $ToolRoot 'scripts/windows/watch_container_resources.ps1') -Output $resourceFile -WorkRoot $containerProfile.data_root -ExportRoot $exportRoot | Out-Null
    if($containerProfile.prior_accounting -and (Test-Path -LiteralPath $containerProfile.prior_accounting)){
        Copy-Item -LiteralPath $containerProfile.prior_accounting -Destination (Join-Path $provenance 'prior-accounting.json')
        $mounts+=@('--env','WBG_PRIOR_ACCOUNTING=/provenance/prior-accounting.json')
    }
    if($containerProfile.prior_history -and (Test-Path -LiteralPath $containerProfile.prior_history)){
        $mounts+=@('--mount',(New-WbgDockerMount 'bind' $containerProfile.prior_history '/prior-history' $true),
                   '--env','WBG_PRIOR_HISTORY=/prior-history')
    }
    foreach($name in @('budget-authorizations.json','interactive-authorizations.json')){
        $path=Join-Path (Get-WbgPaths $ToolRoot).config_root $name
        if(Test-Path -LiteralPath $path){
            Copy-Item -LiteralPath $path -Destination (Join-Path $provenance $name)
            $variable=if($name -eq 'budget-authorizations.json'){'WBG_BUDGET_AUTHORIZATIONS'}else{'WBG_INTERACTIVE_AUTHORIZATIONS'}
            $mounts+=@('--env',($variable+'=/provenance/'+$name))
        }
    }
    $hostResources=Get-Content -LiteralPath $resourceFile -Raw -Encoding UTF8|ConvertFrom-Json
    if([Math]::Min($hostResources.work_free_bytes,$hostResources.export_free_bytes) -lt 20GB){
        $kind=if($command -in @('analyze','demo','probe')){'resource_limit'}else{'not_ready'}
        return @{exit_code=$(if($kind -eq 'resource_limit'){30}else{2});body=@{schema_version=1;status=$kind;ready=$false;
            reason_code='physical_volume_reserve';resources=$hostResources;reserve_bytes=20GB;
            execution=@{status='not_started'};recovery=@{status='not_attempted'}}}
    }
    $encodedHost=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($WindowsHost|ConvertTo-Json -Depth 24 -Compress)))
    $common=$base+@('--label',('io.whiteboxgrind.owner='+$owner),'--mount',(New-WbgDockerMount 'bind' $provenance '/provenance' $true),
        '--mount',(New-WbgDockerMount 'bind' $exportRoot '/exports'),'--env','WBG_HOST_RESOURCES=/provenance/host-resources.json',
        '--env',('WBG_MOUNTED_SOURCE='+$sourceMount),'--env',('WBG_WINDOWS_HOST_B64='+$encodedHost),
        '--env','WBG_EXPORT_MOUNT_ROOT=1','--env',('WBG_WINDOWS_EXPORT_ROOT='+$exportRoot),'--env',('WBG_LAUNCH_TOKEN='+$WindowsHost.launch_token))+$mounts
    Write-WbgContainerJson (Join-Path $requestRoot 'request.json') @{command=$command;original_args=$CliArgs;original_config=$originalConfig;target_source=$sourcePath;image=$containerProfile.image;export_root=$exportRoot;owner=$owner;docker_args=$common}
    if($command -in @('doctor','history','case','cleanup')){
        $result=Invoke-WbgDockerLocal (@('run','--rm')+$common+@($containerProfile.image)+$forward.ToArray()) 0
        if(-not $result.stdout.Trim()){throw ('Container command returned no JSON: '+$result.stderr)}
        Write-WbgContainerJson (Join-Path $requestRoot 'caller.json') $result
        $body=$result.stdout|ConvertFrom-Json
        if($command -eq 'case'){
            foreach($field in @('case_root','config','next_output')){
                if($body.$field){$relative=([string]$body.$field).Substring(5).TrimStart('/');$body.$field=if($relative){Join-Path $caseRoot $relative}else{$caseRoot}}
            }
        }
        return @{exit_code=$result.exit_code;body=$body}
    }
    $launch=Invoke-WbgDockerLocal (@('run','--detach')+$common+@($containerProfile.image)+$forward.ToArray())
    if($launch.exit_code -ne 0){throw ('Container launch failed: '+$launch.stderr)}
    $id=$launch.stdout.Trim()
    if($id -notmatch '^[0-9a-f]{64}$'){throw 'Docker returned an invalid container ID'}
    $sessionRecord=@{schema_version=1;container_id=$id;image=$containerProfile.image;owner=$owner;request_root=$requestRoot;export_root=$exportRoot;run_id=$null}
    Write-WbgContainerJson $sessionPath $sessionRecord
    function ConvertTo-WbgPsLiteral([string]$Value){return "'"+$Value.Replace("'","''")+"'"}
    $watch='& '+(ConvertTo-WbgPsLiteral (Join-Path $ToolRoot 'scripts/windows/watch_container_resources.ps1'))+
        ' -Output '+(ConvertTo-WbgPsLiteral $resourceFile)+' -WorkRoot '+(ConvertTo-WbgPsLiteral $containerProfile.data_root)+' -ExportRoot '+(ConvertTo-WbgPsLiteral $exportRoot)+
        ' -Container '+(ConvertTo-WbgPsLiteral $id)+' -DockerExecutable '+(ConvertTo-WbgPsLiteral $docker)+' -DockerContext desktop-linux'
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($watch))
    $process=Start-Process -FilePath $WindowsHost.selected_runtime.executable -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-EncodedCommand',$encoded)
    Write-WbgContainerJson (Join-Path $requestRoot 'resource-watcher.json') @{pid=$process.Id;container_id=$id;scope='Only this container; exits at terminal state; no model calls'}
    $body=$null
    $launchExit=0
    for($attempt=0;$attempt -lt 20;$attempt++){
        $view=Invoke-WbgDockerLocal @('exec',$id,'/opt/wbg-engine/venv/bin/python','-m','wbg','status','--json')
        if($view.exit_code -eq 0){$body=$view.stdout|ConvertFrom-Json;if($body.run_id){break}}
        $state=Invoke-WbgDockerLocal @('inspect','--format','{{json .State.Running}}',$id)
        if($state.exit_code -eq 0 -and $state.stdout.Trim() -eq 'false'){
            $logs=Invoke-WbgDockerLocal @('logs',$id)
            $terminalState=Invoke-WbgDockerLocal @('inspect','--format','{{json .State}}',$id)
            $terminal=$terminalState.stdout|ConvertFrom-Json
            if($logs.stdout.Trim()){
                $body=$logs.stdout|ConvertFrom-Json
                $launchExit=[int]$terminal.ExitCode
            }else{
                $body=[pscustomobject]@{schema_version=1;status='error';reason_code='container_entry_failed';
                    detail=$logs.stderr;actual_container_exit_code=$terminal.ExitCode;
                    execution=@{status='not_started'};recovery=@{status='not_attempted'}}
                $launchExit=40
            }
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if(-not $body){$body=[pscustomobject]@{schema_version=1;status='starting';run_id=$null}}
    $sessionRecord.run_id=$body.run_id
    if($body.run_id){
        $exportsPath=Join-Path $stateRoot 'run-exports.json'
        $exports=@{}
        if(Test-Path -LiteralPath $exportsPath){
            $known=Get-Content -LiteralPath $exportsPath -Raw -Encoding UTF8|ConvertFrom-Json
            foreach($prop in $known.PSObject.Properties){$exports[$prop.Name]=$prop.Value}
        }
        $exports[$body.run_id]=$exportRoot
        Write-WbgContainerJson $exportsPath $exports
    }
    Write-WbgContainerJson $sessionPath $sessionRecord
    $body|Add-Member -NotePropertyName container -NotePropertyValue @{id=$id;image=$containerProfile.image;request_root=$requestRoot} -Force
    return @{exit_code=$launchExit;body=$body}
}
