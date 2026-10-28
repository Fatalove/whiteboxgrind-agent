# Test-only native argv observer; does not evaluate received strings.
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
[Environment]::GetCommandLineArgs()|ConvertTo-Json -Compress
