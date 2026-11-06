"""Read-only GitHub Actions discovery through the user's existing gh login."""
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from .service import CIError


class GitHubChecks:
    def __init__(self, run=subprocess.run):
        self.run = run

    def scan(self, repository):
        path = Path(repository["path"])
        if not path.is_dir():
            raise CIError("本地仓库目录不存在")
        try:
            result = self.run(["gh", "pr", "list", "--repo", repository["slug"], "--state", "open", "--limit", "100", "--json", "number,url,headRefOid,statusCheckRollup"], cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
            if result.returncode:
                raise CIError("GitHub 查询失败，请检查 gh 登录、仓库权限和网络")
            if len(result.stdout) > 4 * 1024 * 1024:
                raise CIError("GitHub 响应过大")
            rows = json.loads(result.stdout)
            if not isinstance(rows, list):
                raise ValueError()
            failures = []
            for row in rows:
                checks = []
                for check in row.get("statusCheckRollup") or []:
                    url = urlsplit(check.get("detailsUrl") or "")
                    if url.scheme == "https" and url.hostname == "github.com" and url.path.lower().startswith("/" + repository["slug"].lower() + "/actions/runs/") and (check.get("conclusion") or "").upper() in ("FAILURE", "TIMED_OUT", "ACTION_REQUIRED", "CANCELLED"):
                        checks.append(str(check.get("name", "Actions"))[:200])
                if checks:
                    failures.append({"number": row["number"], "head": row["headRefOid"], "url": row["url"], "checks": checks})
            return failures
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CIError("无法运行 gh，或查询超时") from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            if isinstance(error, CIError):
                raise
            raise CIError("GitHub 返回的检查数据格式无效") from error
