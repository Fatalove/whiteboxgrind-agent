param([string]$Runtime,[string]$EvidenceRoot)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $projectRoot 'scripts\windows\host.ps1')
$records=New-Object 'Collections.Generic.List[object]'
$parentIdentity=Get-WbgIdentity
$label=if($PSVersionTable.PSVersion.Major -eq 5){'ps51'}else{'ps7'}
New-Item -ItemType Directory -Path $EvidenceRoot -Force|Out-Null
function Check-Wbg {
    param([string]$Name,[bool]$Passed,$Evidence)
    $records.Add([ordered]@{test=$Name;passed=$Passed;test_only=$true;evidence=$Evidence})
    if(-not $Passed){throw "Test failed: $Name"}
}
$savedRuntime=$env:WBG_POWERSHELL
$savedPath=$env:PATH
try {
    $env:WBG_POWERSHELL=$Runtime
    $root=Join-Path $EvidenceRoot ('test-only-'+$label)
    New-Item -ItemType Directory -Path $root -Force|Out-Null
    $fakeProject=Join-Path $root 'project'
    New-Item -ItemType Directory -Path $fakeProject -Force|Out-Null
    $identity=Test-WbgRuntime $Runtime
    Check-Wbg 'runtime-api-real-child-smoke' ($identity.argument_list -and $identity.argv_smoke) $identity
    $values=@('',('unicode-'+[char]0x4e2d+[char]0x6587),'space value','a&b','a"b','C:\trailing\','back\\"quote','$(no-execution);|')
    foreach($legacy in @($false,$true)){
        $fixture=Join-Path $PSScriptRoot 'echo_args.ps1'
        $result=Invoke-WbgProcess $Runtime (@('-NoProfile','-File',$fixture)+$values) -LegacyArguments:$legacy
        $decoded=$result.stdout|ConvertFrom-Json
        $all=@(); foreach($item in $decoded){$all += [string]$item}
        $received=@(); for($i=$all.Count-$values.Count;$i -lt $all.Count;$i++){$received += [string]$all[$i]}
        $expected=ConvertTo-Json -InputObject $values -Compress
        $observed=ConvertTo-Json -InputObject $received -Compress
        Check-Wbg ('native-argv-roundtrip-legacy-'+$legacy) ($result.exit_code -eq 0 -and $observed -eq $expected) @{expected=$values;received=$received;stderr=$result.stderr}
    }
    foreach($code in @(0,10,20,30,40,130)){
        $result=Invoke-WbgProcess $Runtime @('-NoProfile','-File',(Join-Path $PSScriptRoot 'exit_fixture.ps1'),[string]$code)
        Check-Wbg ('test-only-exit-'+$code) ($result.exit_code -eq $code) $result
    }
    $hostRecord=Get-WbgHost $fakeProject
    Check-Wbg 'explicit-runtime-outside-PATH' $hostRecord.ready $hostRecord
    $env:WBG_POWERSHELL=Join-Path $root 'missing\pwsh.exe'
    $missing=Get-WbgHost $fakeProject
    Check-Wbg 'invalid-explicit-selection-no-silent-fallback' (-not $missing.ready) $missing
    $env:WBG_POWERSHELL=$null
    $configDir=(Get-WbgPaths $fakeProject).config_root
    New-Item -ItemType Directory -Path $configDir -Force|Out-Null
    $configPath=Join-Path $configDir 'windows-runtime.json'
    [IO.File]::WriteAllText($configPath,(@{schema_version=1;powershell_path=$Runtime}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $configured=Get-WbgHost $fakeProject
    Check-Wbg 'saved-runtime-selection' ($configured.ready -and $configured.selection -eq 'saved_configuration') $configured
    Remove-Item -LiteralPath $configPath
    if($PSVersionTable.PSVersion.Major -eq 5){
        $env:PATH=Join-Path $env:SystemRoot 'System32'
        $missing=Get-WbgHost $fakeProject
        Check-Wbg 'ps51-only-missing-runtime-actionable' (-not $missing.ready -and $missing.resolutions.Count -eq 3) $missing
    }
} finally {
    $env:WBG_POWERSHELL=$savedRuntime;$env:PATH=$savedPath
    $report=[ordered]@{test_only=$true;bootstrap=$parentIdentity;records=@($records.ToArray());passed=@($records|Where-Object{-not $_.passed}).Count -eq 0}
    [IO.File]::WriteAllText((Join-Path $EvidenceRoot ($label+'-unit.json')),($report|ConvertTo-Json -Depth 24),[Text.UTF8Encoding]::new($false))
}
$report|ConvertTo-Json -Depth 24 -Compress
