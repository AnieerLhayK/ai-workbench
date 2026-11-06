param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Backup)
$ErrorActionPreference = 'Stop'
$target = Get-Item -LiteralPath $Root -Force
if (-not $target.PSIsContainer -or ($target.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected ordinary private directory' }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -LiteralPath $target.FullName
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'Private directory owner mismatch' }
$acl.Sddl | Set-Content -LiteralPath $Backup -Encoding utf8
$rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::TakeOwnership,([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $target.FullName -AclObject $acl
