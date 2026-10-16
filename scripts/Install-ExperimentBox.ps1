param(
    [Parameter(Mandatory)][string]$DataRoot,
    [Parameter(Mandatory)][string]$DesktopRoot,
    [Parameter(Mandatory)][string]$Pythonw,
    [Parameter(Mandatory)][string]$Terminal,
    [Parameter(Mandatory)][string]$PowerShell,
    [string]$CodexCli,
    [string]$Python,
    [string]$RunnerDisabledReason,
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
foreach ($runtimePath in @($Pythonw,$Terminal,$PowerShell)) {
    if (-not [IO.Path]::IsPathRooted($runtimePath) -or -not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) { throw "Missing runtime: $runtimePath" }
}
foreach ($directory in @($DataRoot,$DesktopRoot)) {
    if (-not [IO.Path]::IsPathRooted($directory)) { throw 'Deployment directories must be absolute.' }
}
if (-not (Test-Path -LiteralPath $DesktopRoot -PathType Container)) { throw 'Desktop root does not exist.' }
$packageRoot = Split-Path $PSScriptRoot -Parent
$configPath = Join-Path $DataRoot 'config.json'
$shortcutPath = Join-Path $DesktopRoot '个人试验盒.lnk'
$iconPath = Join-Path $packageRoot 'src/ai_workbench/assets/experiment-box.ico'
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { throw 'Build the owned experiment-box icon first.' }
if ((Test-Path -LiteralPath $configPath) -or (Test-Path -LiteralPath $shortcutPath)) {
    if (-not $Upgrade) { throw 'Existing deployment: inspect configuration and shortcut; use -Upgrade for this owned app only.' }
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'Cannot upgrade without owned configuration.' }
    $existing = @{}
    $previousConfig = Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($property in $previousConfig.PSObject.Properties) { $existing[$property.Name] = $property.Value }
    if ([IO.Path]::GetFullPath($existing.data_root) -ne [IO.Path]::GetFullPath($DataRoot)) { throw 'Existing configuration belongs to another data root.' }
    if ($existing.ContainsKey('application') -and $existing.application -ne 'experiment-box') { throw 'Configuration belongs to another application.' }
    if (-not $existing.ContainsKey('application') -and -not (Test-Path -LiteralPath $shortcutPath)) { throw 'Legacy config requires its owned desktop shortcut for identity verification.' }
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $shortcutPath) {
        $oldShortcut = $shell.CreateShortcut($shortcutPath)
        $expectedArguments = '-B "' + (Join-Path $PSScriptRoot 'launch_experiment_box.py') + '" --config "' + $configPath + '"'
        if ([IO.Path]::GetFullPath($oldShortcut.TargetPath) -ne [IO.Path]::GetFullPath($Pythonw) -or $oldShortcut.Arguments.Replace('/','\') -ne $expectedArguments.Replace('/','\')) { throw 'Shortcut is not this application; refusing replacement.' }
    }
} else { $existing = @{} }
[void][IO.Directory]::CreateDirectory($DataRoot)
foreach ($pathToCheck in @($DataRoot,$configPath,$shortcutPath,(Join-Path $DataRoot 'experiment-box-cli.py'),(Join-Path $DataRoot 'experiment-box-cli.cmd'))) {
    if ((Test-Path -LiteralPath $pathToCheck) -and ((Get-Item -LiteralPath $pathToCheck -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Deployment target must not be a reparse point.' }
}
if (-not $Python) { $Python = Join-Path (Split-Path $Pythonw -Parent) 'python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Existing console Python is required for the dedicated CLI.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
foreach ($item in @{data_root=$DataRoot;pythonw=$Pythonw;python=$Python;terminal=$Terminal;powershell=$PowerShell;application='experiment-box'}.GetEnumerator()) { $existing[$item.Key] = $item.Value }
if ($CodexCli) {
    if (-not [IO.Path]::IsPathRooted($CodexCli) -or -not (Test-Path -LiteralPath $CodexCli -PathType Leaf)) { throw 'Codex CLI must identify an existing absolute executable or npm launcher.' }
    $existing.codex_cli = $CodexCli
}
if ($PSBoundParameters.ContainsKey('RunnerDisabledReason')) { $existing.runner_disabled_reason = $RunnerDisabledReason }
$source = Join-Path $packageRoot 'src'
# The installer binds the private CLI. There is no public root/config argument.
$bootstrap = Join-Path $DataRoot 'experiment-box-cli.py'
$cli = Join-Path $DataRoot 'experiment-box-cli.cmd'
foreach ($ownedPath in @($bootstrap,$cli)) {
    if (Test-Path -LiteralPath $ownedPath) {
        if ((Get-Content -LiteralPath $ownedPath -Raw -Encoding utf8) -notlike '*ExperimentBox owned CLI*') { throw 'Refusing to replace an unrelated CLI file.' }
        Copy-Item -LiteralPath $ownedPath -Destination ($ownedPath + '.backup-' + $stamp)
    }
}
if (Test-Path -LiteralPath $configPath) { Copy-Item -LiteralPath $configPath -Destination ($configPath + '.backup-' + $stamp) }
if (Test-Path -LiteralPath $shortcutPath) { Copy-Item -LiteralPath $shortcutPath -Destination (Join-Path $DataRoot ('shortcut.backup-' + $stamp + '.lnk')) }
$existing | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
$sourceJson = ConvertTo-Json -InputObject $source -Compress
$configJson = ConvertTo-Json -InputObject $configPath -Compress
@"
# ExperimentBox owned CLI
import sys
sys.path.insert(0, $sourceJson)
from ai_workbench.experiment_box.cli import run_bound
raise SystemExit(run_bound($configJson))
"@ | Set-Content -LiteralPath $bootstrap -Encoding utf8
@"
@rem ExperimentBox owned CLI
@"$Python" -B "%~dp0experiment-box-cli.py" %*
"@ | Set-Content -LiteralPath $cli -Encoding utf8
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '-B "' + (Join-Path $PSScriptRoot 'launch_experiment_box.py') + '" --config "' + $configPath + '"'
$shortcut.WorkingDirectory = $DataRoot
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = '个人试验盒 - Codex 助手、试验审批与继续记录'
$shortcut.Save()
Write-Output "Created $shortcutPath"
Write-Output "Bound CLI: $cli"
