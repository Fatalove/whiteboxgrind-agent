<# PS5.1 bootstrap -> explicitly checked PS7 -> fixed Linux CLI. #>
# Deliberately no advanced parameter binder: PS5.1 otherwise treats --out as
# an ambiguous abbreviation of the common OutVariable/OutBuffer parameters.
$CliArgs=@($args)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'windows\host.ps1')
$projectRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if($CliArgs.Count -gt 0 -and $CliArgs[0] -eq '--backend'){
    if($CliArgs.Count -lt 3){
        @{schema_version=1;status='error';reason_code='missing_backend_command'}|ConvertTo-Json -Compress
        exit 40
    }
    $selectedBackend=$CliArgs[1];$CliArgs=@($CliArgs|Select-Object -Skip 2)
}else{
    $selectedBackend='wsl2-native'
    $runtimeProfile=Join-Path $projectRoot 'config/runtime.json'
    if(Test-Path -LiteralPath $runtimeProfile){$selectedBackend=(Get-Content -LiteralPath $runtimeProfile -Raw -Encoding UTF8|ConvertFrom-Json).backend}
}
if($selectedBackend -eq 'docker'){
    & (Join-Path $PSScriptRoot 'wbg-container.ps1') @CliArgs
    exit $LASTEXITCODE
}
if($selectedBackend -ne 'wsl2-native'){
    @{schema_version=1;status='unsupported';reason_code='unsupported_backend';backend=$selectedBackend}|ConvertTo-Json -Compress
    exit 20
}
$command=$null; $hostRecord=$null
try {
    if($CliArgs.Count -ge 3 -and $CliArgs[0] -eq '--wbg-bootstrap-record'){
        $hostRecord=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($CliArgs[1]))|ConvertFrom-Json
        $CliArgs=@($CliArgs|Select-Object -Skip 2)
        $current=Get-WbgIdentity
        if(-not $hostRecord.ready -or $current.executable -ine $hostRecord.selected_runtime.executable -or
           $PSVersionTable.PSVersion -lt [version]'7.6' -or $PSVersionTable.PSVersion -ge [version]'7.7'){
            throw 'bootstrap_runtime_identity_mismatch'
        }
    } else {$hostRecord=Get-WbgHost $projectRoot}
    if(-not $CliArgs -or $CliArgs[0] -notin @('doctor','demo','analyze','probe','status','decide','cancel','history')){throw 'expected doctor, demo, analyze, probe, status, decide, cancel, or history'}
    $command=$CliArgs[0]
    if(-not $hostRecord.ready){
        $doctor=$command -eq 'doctor'
        [ordered]@{schema_version=1;command=$command;status=if($doctor){'not_ready'}else{'error'};ready=$false
            reason_code='windows_host_not_ready';windows_host=$hostRecord;linux_backend=@{status='not_checked'}
            execution=@{status='not_started'};recovery=@{status='not_attempted'}}|ConvertTo-Json -Depth 20 -Compress
        if($doctor){exit 2}else{exit 40}
    }
    if((Get-WbgIdentity).executable -ine $hostRecord.selected_runtime.executable){
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($hostRecord|ConvertTo-Json -Depth 20 -Compress)))
        $launchArguments=@('-NoLogo','-NoProfile','-File',$PSCommandPath,'--wbg-bootstrap-record',$encoded)+@($CliArgs)
        $cancel=$null
        if($command -in @('demo','analyze','probe')){$cancel={Request-WbgCancellation $hostRecord $projectRoot}}
        $result=Invoke-WbgProcess $hostRecord.selected_runtime.executable $launchArguments -TimeoutSeconds 0 -OnCancel $cancel
        $outer=$result.stdout|ConvertFrom-Json
        $outer|Add-Member -NotePropertyName windows_bootstrap_transport -NotePropertyValue ([ordered]@{
            cancel_signal_observed=$result.cancel_signal_observed;cancel_attempts=$result.cancel_attempts;cancel_marker_accepted=$result.cancel_marker_accepted;cancel_last_request=$result.cancel_last_request})
        $result.stdout=$outer|ConvertTo-Json -Depth 24 -Compress
    } else {
        $forward=New-Object 'Collections.Generic.List[string]'
        for($index=0;$index -lt $CliArgs.Count;$index++){
            $arg=$CliArgs[$index];$forward.Add($arg)
            if($arg -in @('--config','--out')){
                $index++
                if($index -ge $CliArgs.Count){throw "missing path after $arg"}
                $forward.Add((ConvertTo-WbgWslPath $CliArgs[$index]))
            }
        }
        $linuxRoot=ConvertTo-WbgWslPath $projectRoot
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($hostRecord|ConvertTo-Json -Depth 20 -Compress)))
        $launchArguments=@('-d','Ubuntu-22.04','-u','wbg','--','env',('WBG_LAUNCH_TOKEN='+$hostRecord.launch_token),
            ('WBG_WINDOWS_HOST_B64='+$encoded),'bash',($linuxRoot+'/scripts/wbg'))+@($forward)
        $cancel=$null
        if($command -in @('demo','analyze','probe')){$cancel={Request-WbgCancellation $hostRecord $projectRoot}}
        $result=Invoke-WbgProcess $hostRecord.wsl_executable $launchArguments -TimeoutSeconds 0 -OnCancel $cancel
        try{$body=$result.stdout|ConvertFrom-Json}catch{
            if($command -ne 'doctor'){throw ('backend_start_failed: '+$result.stderr)}
            [ordered]@{schema_version=1;command='doctor';status='not_ready';ready=$false;reason_code='backend_start_failed'
                windows_host=$hostRecord;linux_backend=@{status='not_checked';exit_code=$result.exit_code;stdout=$result.stdout;stderr=$result.stderr}
                execution=@{status='not_started'};recovery=@{status='not_attempted'}}|ConvertTo-Json -Depth 24 -Compress
            exit 2
        }
        if($command -eq 'doctor'){
            $body|Add-Member -NotePropertyName linux_backend -NotePropertyValue ([ordered]@{status=$body.status;ready=$body.ready;checks=@($body.checks)})
            $body.checks=@($hostRecord.checks)+@($body.checks)
        }
        $body|Add-Member -NotePropertyName windows_host -NotePropertyValue $hostRecord -Force
        $body|Add-Member -NotePropertyName windows_transport -NotePropertyValue ([ordered]@{
            cancel_signal_observed=$result.cancel_signal_observed;cancel_attempts=$result.cancel_attempts;cancel_marker_accepted=$result.cancel_marker_accepted;cancel_last_request=$result.cancel_last_request})
        $result.stdout=$body|ConvertTo-Json -Depth 24 -Compress
    }
    Write-Output $result.stdout
    [Console]::Error.Write($result.stderr)
    exit $result.exit_code
} catch {
    [ordered]@{schema_version=1;command=$command;status='error';reason_code='windows_launcher_error'
        detail=$_.Exception.Message;windows_host=$hostRecord;execution=@{status='not_started'}
        recovery=@{status='not_attempted'}}|ConvertTo-Json -Depth 24 -Compress
    exit 40
}
