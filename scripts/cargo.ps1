# Keep native flags such as -D out of PowerShell's common-parameter binding.
# When forwarding Cargo's separator from PowerShell, quote it as '--'.
$taskCargoArguments = $args
$ErrorActionPreference = 'Stop'
$taskCommand = Get-Command cargo -ErrorAction SilentlyContinue
if ($taskCommand) {
    $taskCargo = $taskCommand.Source
} else {
    $taskRuntime = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\tools\rust'))
    $taskCargo = Join-Path $taskRuntime 'cargo\bin\cargo.exe'
    if (-not (Test-Path -LiteralPath $taskCargo)) {
        throw 'Rust is not installed. Install Rust from https://rust-lang.org/tools/install/ first.'
    }
    $env:CARGO_HOME = Join-Path $taskRuntime 'cargo'
    $env:RUSTUP_HOME = Join-Path $taskRuntime 'rustup'
}
Push-Location (Join-Path $PSScriptRoot '..')
try { & $taskCargo @taskCargoArguments; $taskExit = $LASTEXITCODE }
finally { Pop-Location }
exit $taskExit
