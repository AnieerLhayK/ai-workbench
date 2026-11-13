<#
.SYNOPSIS
Copy an owned icon beside the deployed application data.
.DESCRIPTION
Explorer does not load shortcut icons that resolve inside the sandboxed
workspace, so each installer deploys a trusted copy beside the application data
and points the shortcut at that copy. Returns the destination path.
#>
function Copy-ShortcutIcon {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Owned icon must be generated before deployment: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    return $Destination
}
