<# Calls the installed tool's stable launcher; this plugin contains no engine binaries. #>
param([Parameter(Mandatory=$true)][string]$ToolRoot,
      [Parameter(Mandatory=$true)][string[]]$CliArgs)
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath $ToolRoot).Path
$launcher=Join-Path $root 'scripts/wbg.ps1'
if(-not (Test-Path -LiteralPath $launcher -PathType Leaf)){throw 'tool root must contain scripts/wbg.ps1'}
& $launcher @CliArgs
exit $LASTEXITCODE
