param(
    [switch]$Demo,
    [string]$Config,
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path $PSScriptRoot -Parent
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $packageRoot 'src'
    & $PythonExe -c "import sys, PySide6; assert sys.version_info >= (3,13); assert PySide6.__version__ == '6.9.2'"
    if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.13+ with PySide6 6.9.2.' }
    if ($Demo) { & $PythonExe -B -m ai_workbench --demo }
    elseif ($Config) { & $PythonExe -B -m ai_workbench --config $Config }
    else { throw 'Provide -Config for local controls or -Demo for simulation.' }
    if ($LASTEXITCODE -ne 0) { throw "Workbench exited with code $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
