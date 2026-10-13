param(
    [Parameter(Mandatory)][string]$DataRoot,
    [Parameter(Mandatory)][string]$DesktopRoot,
    [Parameter(Mandatory)][string]$Pythonw,
    [Parameter(Mandatory)][string]$Terminal,
    [Parameter(Mandatory)][string]$PowerShell
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
if ((Test-Path -LiteralPath $configPath) -or (Test-Path -LiteralPath $shortcutPath)) { throw 'Existing deployment: inspect configuration and shortcut before any change.' }
[void][IO.Directory]::CreateDirectory($DataRoot)
@{data_root=$DataRoot;pythonw=$Pythonw;terminal=$Terminal;powershell=$PowerShell} |
    ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '-B "' + (Join-Path $PSScriptRoot 'launch_experiment_box.py') + '" --config "' + $configPath + '"'
$shortcut.WorkingDirectory = $DataRoot
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = '个人试验盒 - 手动启动、记录结果与继续试验'
$shortcut.Save()
Write-Output "Created $shortcutPath"
