param(
    [Parameter(Mandatory)][string]$DataRoot,
    [Parameter(Mandatory)][string]$DesktopRoot,
    [Parameter(Mandatory)][string]$Pythonw,
    [Parameter(Mandatory)][string]$CodexCli,
    [Parameter(Mandatory)][string]$ProsePath,
    [Parameter(Mandatory)][string]$ZfRoot,
    [Parameter(Mandatory)][string]$StagingRoot,
    [Parameter(Mandatory)][string[]]$SourceRoots
)
$ErrorActionPreference = 'Stop'
foreach ($file in @($Pythonw, $CodexCli, $ProsePath)) {
    if (-not [IO.Path]::IsPathRooted($file) -or -not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing file: $file" }
}
foreach ($directory in @($DataRoot, $DesktopRoot, $ZfRoot, $StagingRoot) + $SourceRoots) {
    if (-not [IO.Path]::IsPathRooted($directory)) { throw 'All paths must be absolute.' }
}
if (-not (Test-Path -LiteralPath $DesktopRoot -PathType Container)) { throw 'Desktop root does not exist.' }
if (-not (Test-Path -LiteralPath (Join-Path $ZfRoot 'SKILL.md'))) { throw 'zf SKILL.md is missing.' }
$configPath = Join-Path $DataRoot 'config.json'
$shortcutPath = Join-Path $DesktopRoot 'e-Diary.lnk'
if ((Test-Path -LiteralPath $configPath) -or (Test-Path -LiteralPath $shortcutPath)) { throw 'Existing deployment; inspect before changing it.' }
[void][IO.Directory]::CreateDirectory($DataRoot)
[void][IO.Directory]::CreateDirectory($StagingRoot)
@{data_root=$DataRoot;codex_cli=$CodexCli;prose_path=$ProsePath;zf_root=$ZfRoot;staging_root=$StagingRoot;source_roots=$SourceRoots;read_codex=$true} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding utf8
$packageRoot = Split-Path $PSScriptRoot -Parent
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '-B "' + (Join-Path $PSScriptRoot 'launch_e_diary.py') + '" --config "' + $configPath + '"'
$shortcut.WorkingDirectory = $DataRoot
$shortcut.IconLocation = (Join-Path $packageRoot 'src/ai_workbench/assets/e-diary.ico') + ',0'
$shortcut.Description = 'e-Diary - 日记、开发、工作与个人回顾'
$shortcut.Save()
Write-Output "Created $shortcutPath"
