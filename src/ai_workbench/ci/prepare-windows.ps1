param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Backup)
$ErrorActionPreference = 'Stop'
$target = Get-Item -LiteralPath $Root -Force
if (-not $target.PSIsContainer -or ($target.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected ordinary private directory' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$sid = $identity.User
$tokenOwner = $identity.Owner
$acl = Get-Acl -LiteralPath $target.FullName
$owner = $acl.GetOwner([Security.Principal.SecurityIdentifier])
# Elevated runners (including GitHub windows-latest) create new directories
# owned by the token owner (Administrators), not by the user SID. Both are the
# caller's own effective identities; any other owner still stops preparation.
$expected = @($sid.Value)
if ($tokenOwner) { $expected += $tokenOwner.Value }
if ($owner.Value -notin $expected) { throw "Private directory owner mismatch (owner $($owner.Value); expected $($expected -join ' or '))" }
$acl.Sddl | Set-Content -LiteralPath $Backup -Encoding utf8
$rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::TakeOwnership,([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $target.FullName -AclObject $acl
