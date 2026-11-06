"""Real Windows preparation with a controlled SDK transport, no model or account."""
import os
from pathlib import Path
import pytest

from ai_workbench.ci.agents import NativeAgent


@pytest.mark.skipif(os.name != "nt", reason="Windows preparation contract")
def test_verification_preparation_ignores_inherited_incompatible_powershell_modules(monkeypatch, tmp_path):
    from ai_workbench.ci import dsh
    poisoned = tmp_path / "foreign-modules" / "Microsoft.PowerShell.Security"
    poisoned.mkdir(parents=True)
    (poisoned / "Microsoft.PowerShell.Security.psd1").write_text("@{ ModuleVersion='99.0'; RootModule='broken.psm1'; FunctionsToExport=@('Get-Acl') }", encoding="utf-8")
    (poisoned / "broken.psm1").write_text("throw 'incompatible foreign runtime module'", encoding="utf-8")
    inherited = str(poisoned.parent)
    monkeypatch.setenv("PSModulePath", inherited)
    skill = tmp_path / "skill"
    for name in ("SKILL.md", "LICENSE.txt", "agents/openai.yaml", "scripts/inspect_pr_checks.py", "assets/github-small.svg", "assets/github.png"):
        target = skill / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"controlled fixture")
    workspace = tmp_path / "private-clone"
    workspace.mkdir()
    monkeypatch.setattr(dsh, "installation", lambda value: tmp_path / "controlled.exe")
    monkeypatch.setattr(dsh, "read_file", lambda *args: '{"version":"0.2.1-rc.2"}')
    class Transport:
        def __init__(self, *args):
            pass
        def request(self, method, params, timeout):
            assert method == "ci/verify"
            return {"value": {"exitCode": 0, "stdout": {"text": "controlled verifier"}, "stderr": {"text": ""}}}
        def close(self):
            pass
    monkeypatch.setattr(dsh, "Connection", Transport)
    result = NativeAgent().verify(workspace, ["python", "-m", "unittest"], {"agent": "dsh", "repository": "owner/repo", "skill_path": str(skill), "test_command": ["python", "-m", "unittest"]})
    assert result.returncode == 0
    assert os.environ["PSModulePath"] == inherited
