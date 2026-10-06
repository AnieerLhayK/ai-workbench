param(
    [Parameter(Mandatory)][string]$DataRoot,
    [Parameter(Mandatory)][string]$DesktopRoot,
    [Parameter(Mandatory)][string]$Pythonw,
    [Parameter(Mandatory)][string]$Npx,
    [Parameter(Mandatory)][string]$Node,
    [Parameter(Mandatory)][string]$HermesHome,
    [Parameter(Mandatory)][string]$HermesPythonw,
    [Parameter(Mandatory)][string]$HermesExe,
    [string]$Terminal,
    [string]$PowerShell,
    [string]$CodexCli,
    [string]$ClaudeCli
)
$ErrorActionPreference = 'Stop'
foreach ($runtimePath in @($Pythonw,$Npx,$Node,$HermesPythonw,$HermesExe)) {
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) { throw "Missing runtime: $runtimePath" }
}
$packageRoot = Split-Path $PSScriptRoot -Parent
$iconPath = Join-Path $packageRoot 'src/ai_workbench/assets/muti-ai.ico'
if (-not (Test-Path -LiteralPath $iconPath)) { throw 'Owned icon must be generated before deployment.' }
$configPath = Join-Path $DataRoot 'config.json'
if (Test-Path -LiteralPath $configPath) { throw 'Existing deployment: review config instead of overwriting it.' }
$shortcutPath = Join-Path $DesktopRoot 'muti-ai.lnk'
if (Test-Path -LiteralPath $shortcutPath) { throw 'Existing shortcut: review before replacement.' }
[void][IO.Directory]::CreateDirectory($DataRoot)
$config = @{data_root=$DataRoot;pythonw=$Pythonw;npx=$Npx;node=$Node;hermes_home=$HermesHome;hermes_pythonw=$HermesPythonw;hermes_exe=$HermesExe}
foreach ($entry in @{terminal=$Terminal;powershell=$PowerShell;codex_cli=$CodexCli;claude_cli=$ClaudeCli}.GetEnumerator()) {
    if ($entry.Value) {
        if (-not [IO.Path]::IsPathRooted($entry.Value) -or -not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) { throw "Missing launcher path: $($entry.Key)" }
        $config[$entry.Key] = $entry.Value
    }
}
$config |
    ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '-B "' + (Join-Path $PSScriptRoot 'launch.py') + '" --config "' + $configPath + '"'
$shortcut.WorkingDirectory = $DataRoot
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = 'muti-ai - local controls and project terminal launchers'
$shortcut.Save()
Write-Output "Created $shortcutPath"
