# Test-only exit transport fixture, never a recovery result.
param([int]$ReturnCode)
[Console]::Write(('{"test_only":true,"exit_code":'+$ReturnCode+'}'))
exit $ReturnCode
