"""Bounded data-only personal archives, shared by CLI and diary evidence intake.

Confirmation receipts are local audit evidence, not cryptographic proof of a
human identity. Trusted maintenance must obtain the owner's approval separately.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

import yaml

MAX_FILE = 256 * 1024
MAX_ENTRIES = 2000
MAX_BYTES = 16 * 1024 * 1024
MAX_RESULTS = 20
MAX_CHARS = 12000
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
STATES = {"candidate", "confirmed", "superseded", "rejected"}
KINDS = {"fact", "self_report", "interpretation"}


class ArchiveError(ValueError):
    """Safe diagnostic: never include imported text or parser error details."""


class _DataLoader(yaml.SafeLoader):
    """Reject aliases and deep structures before constructing imported objects."""
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ArchiveError("档案 YAML 不接受别名")
        self.archive_depth = getattr(self, "archive_depth", 0) + 1
        if self.archive_depth > 20:
            raise ArchiveError("档案 YAML 嵌套过深")
        try:
            return super().compose_node(parent, index)
        finally:
            self.archive_depth -= 1

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if any(not isinstance(k, str) for k in keys) or len(keys) != len(set(keys)):
            raise ArchiveError("档案 YAML 键无效或重复")
        return super().construct_mapping(node, deep=deep)


def _yaml(text):
    return yaml.load(text, Loader=_DataLoader)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def review_digest(metadata, body):
    """Fingerprint the exact content shown for review, excluding lifecycle fields."""
    payload = {k: v for k, v in metadata.items() if k not in {"status", "confirmation"}}
    return _hash(json.dumps({"metadata": payload, "body": body}, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


class _Reader:
    def __init__(self, root):
        if not isinstance(root, (str, os.PathLike)):
            raise ArchiveError("档案根目录类型无效")
        self.root = Path(root)
        if not self.root.is_absolute() or any(_linked(p) for p in (self.root, *self.root.parents)):
            raise ArchiveError("档案根目录须为绝对路径且不能经过链接")
        if not self.root.is_dir():
            raise ArchiveError("档案根目录不存在")
        self.root = self.root.resolve()
        self.count = self.size = 0
        self.warnings, self.errors = [], []

    def path(self, relative):
        part = PurePosixPath(relative)
        if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
            raise ArchiveError("档案包含越界路径")
        target = self.root.joinpath(*part.parts)
        if any(_linked(p) for p in (target, *target.parents)):
            raise ArchiveError("档案路径不能经过链接")
        if not target.resolve().is_relative_to(self.root):
            raise ArchiveError("档案路径越界")
        return target

    def read(self, relative):
        target = self.path(relative)
        size = target.stat().st_size
        if size > MAX_FILE:
            raise ArchiveError("档案文件超过 256 KiB，未读取")
        if self.size + size > MAX_BYTES:
            raise ArchiveError("档案达到 16 MiB 扫描预算，覆盖不完整")
        # Bound the read itself, including a file that grows after stat().
        with target.open("rb") as stream:
            value = stream.read(min(MAX_FILE, MAX_BYTES - self.size) + 1)
        if len(value) > MAX_FILE or self.size + len(value) > MAX_BYTES:
            raise ArchiveError("档案读取达到字节预算，覆盖不完整")
        self.size += len(value)
        return value.decode("utf-8-sig")

    def registry(self, name, key):
        try:
            payload = _yaml(self.read(name))
            if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
                raise ArchiveError("档案注册表版本无效")
            entries = payload.get(key)
            if not isinstance(entries, dict) or len(entries) > MAX_ENTRIES:
                raise ArchiveError("档案注册表格式或数量无效")
            return entries
        except (yaml.YAMLError, UnicodeError, RecursionError):
            raise ArchiveError("档案注册表无法安全解析") from None


def _strings(value):
    return isinstance(value, list) and len(value) <= 100 and all(isinstance(s, str) and len(s) <= 500 for s in value)


def _day(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArchiveError("适用日期必须为引号内的 ISO 日期或 null")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ArchiveError("适用日期无效") from None
    return value


def _record(text, relative, category, sources):
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ArchiveError("记录缺少 YAML 头部")
    front, body = text[4:].split("\n---\n", 1)
    metadata = _yaml(front)
    if not isinstance(metadata, dict):
        raise ArchiveError("记录头部必须为映射")
    if not isinstance(metadata.get("id"), str) or not ID.fullmatch(metadata["id"]):
        raise ArchiveError("记录 ID 无效")
    if metadata.get("category") != category or metadata.get("kind") not in KINDS or metadata.get("status") not in STATES:
        raise ArchiveError("记录分类、性质或状态无效")
    if not isinstance(metadata.get("title"), str) or not metadata["title"].strip() or len(metadata["title"]) > 200 or not body.strip():
        raise ArchiveError("记录需要标题与正文")
    for key in ("aliases", "tags", "related_ids", "conflicts_with", "supersedes"):
        if not _strings(metadata.get(key, [])):
            raise ArchiveError("记录列表字段无效")
    validity = metadata.get("validity", {})
    if not isinstance(validity, dict):
        raise ArchiveError("适用时间格式无效")
    lower, upper = _day(validity.get("from")), _day(validity.get("to"))
    if lower and upper and lower > upper:
        raise ArchiveError("适用时间起止颠倒")
    evidence = metadata.get("sources")
    if not isinstance(evidence, list) or not evidence or len(evidence) > 100:
        raise ArchiveError("记录必须有来源")
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str) or item["source_id"] not in sources:
            raise ArchiveError("来源未登记")
        if not isinstance(item.get("locator"), str) or not item["locator"].strip():
            raise ArchiveError("来源缺少定位")
        excerpt = item.get("excerpt", "")
        if not isinstance(excerpt, str) or len(excerpt) > 4000 or item.get("excerpt_sha256") != _hash(excerpt.encode("utf-8")):
            raise ArchiveError("来源摘录指纹无效")
        if item.get("at") is not None:
            if not isinstance(item["at"], str):
                raise ArchiveError("来源时间须为 ISO 时间或 null")
            try:
                datetime.fromisoformat(item["at"].replace("Z", "+00:00"))
            except ValueError:
                raise ArchiveError("来源时间无效") from None
    fingerprint = review_digest(metadata, body)
    if metadata["status"] in {"confirmed", "superseded"}:
        confirmation = metadata.get("confirmation")
        if not isinstance(confirmation, dict) or confirmation.get("actor") != "owner" or confirmation.get("digest") != fingerprint:
            raise ArchiveError("缺少本人确认或确认版本已过期")
        if not isinstance(confirmation.get("approval_ref"), str) or not confirmation["approval_ref"].strip():
            raise ArchiveError("确认缺少人工授权依据")
        try:
            datetime.fromisoformat(confirmation["at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ArchiveError("确认时间无效") from None
    # JSON serializability also rejects unexpected YAML scalar types.
    json.dumps(metadata)
    return {**metadata, "body": body, "path": relative, "fingerprint": fingerprint}


def _load(root):
    reader = _Reader(root)
    records = []
    try:
        categories = reader.registry("categories.yaml", "categories")
        sources = reader.registry("sources.yaml", "sources")
        for key, value in sources.items():
            if not isinstance(key, str) or not ID.fullmatch(key) or not isinstance(value, dict) or not isinstance(value.get("type"), str):
                raise ArchiveError("来源登记无效")
        paths = set()
        for category, spec in categories.items():
            if not isinstance(category, str) or not ID.fullmatch(category) or not isinstance(spec, dict):
                raise ArchiveError("分类登记无效")
            relative = spec.get("path")
            if relative != "records/" + category or relative in paths:
                raise ArchiveError("分类目录必须是 records/<分类 ID>")
            paths.add(relative)
            folder = reader.path(relative)
            if not folder.is_dir():
                raise ArchiveError("分类目录缺失")
            with os.scandir(folder) as entries:
                for entry in entries:
                    reader.count += 1
                    if reader.count > MAX_ENTRIES:
                        raise ArchiveError("档案达到 2000 项扫描预算，覆盖不完整")
                    if entry.name == ".gitkeep":
                        continue
                    if _linked(Path(entry.path)) or not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".md"):
                        reader.errors.append("分类内存在非 Markdown 文件、目录或链接")
                        continue
                    name = relative + "/" + entry.name
                    try:
                        records.append(_record(reader.read(name).replace("\r\n", "\n"), name, category, sources))
                    except (ArchiveError, OSError, UnicodeError, yaml.YAMLError, TypeError, RecursionError):
                        # Do not expose raw imported content, filenames or parser diagnostics.
                        reader.errors.append("有记录无效或确认过期，已排除；使用 validate 定位登记范围")
    except (ArchiveError, OSError, UnicodeError, yaml.YAMLError, TypeError, RecursionError):
        reader.errors.append("注册表、目录或读取预算检查未通过，覆盖不完整")
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        reader.errors.append("存在重复记录 ID，已排除全部重复项")
        records = [r for r in records if ids.count(r["id"]) == 1]
    known = {r["id"] for r in records}
    bad = set()
    for record in records:
        links = [v for k in ("related_ids", "conflicts_with", "supersedes") for v in record.get(k, [])]
        if any(v not in known or v == record["id"] for v in links):
            bad.add(record["id"])
    if bad:
        reader.errors.append("记录关联缺失或自引用，相关记录已排除")
        records = [r for r in records if r["id"] not in bad]
    return reader, records


def validate(root):
    """Validate registered data only; never dereference source locators."""
    try:
        reader, records = _load(root)
        return {"status": "ERROR" if reader.errors else "PASS", "records": len(records),
                "entries_scanned": min(reader.count, MAX_ENTRIES), "bytes_read": reader.size,
                "errors": list(dict.fromkeys(reader.errors)), "warnings": reader.warnings}
    except (ArchiveError, OSError):
        return {"status": "ERROR", "records": 0, "errors": ["档案根目录无效或不可读"], "warnings": []}


def _terms(text):
    text = text.casefold()
    words = set(re.findall(r"[a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", text[:40000]))
    return words | {w[i:i+2] for w in words if re.fullmatch(r"[\u4e00-\u9fff]+", w) for i in range(len(w)-1)}


def query(root, text="", categories=None, period=None, *, status="confirmed"):
    """Return bounded, cited context. Candidate lookup is explicit maintenance only."""
    if status not in STATES:
        raise ArchiveError("查询状态无效")
    try:
        reader, records = _load(root)
    except (ArchiveError, OSError):
        return {"records": [], "warnings": ["个人档案未配置、缺失或不可读；不能据此推断个人事实"]}
    warnings = list(reader.errors)
    # A confirmed successor makes the former record historical immediately,
    # even before its lifecycle label is changed in a separate file.
    replaced = {v for r in records if r["status"] == "confirmed" for v in r.get("supersedes", [])}
    eligible = [r for r in records if r["status"] == status and (status != "confirmed" or r["id"] not in replaced)
                and (not categories or r["category"] in categories)]
    terms = _terms(text)
    scored = []
    for r in eligible:
        strong = " ".join([r["title"], *r.get("aliases", []), *r.get("tags", [])]).casefold()
        score = sum(4 if t in strong else 1 if t in r["body"].casefold() else 0 for t in terms)
        if not text or score:
            scored.append((score, r))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    wanted = {v for _, r in scored[:MAX_RESULTS] for v in [*r.get("related_ids", []), *r.get("conflicts_with", [])]}
    selected = [r for _, r in scored] + [r for r in eligible if r["id"] in wanted and all(r["id"] != s["id"] for _, s in scored)]
    result, used = [], 2  # Serialized result-list brackets.
    for r in selected:
        validity = r.get("validity", {})
        if period and ((validity.get("to") and validity["to"] < period[0][:10]) or
                       (validity.get("from") and validity["from"] > period[1][:10])):
            timing = "适用时间不在本期，仅作历史或后续背景"
        else:
            timing = "长期背景；未知时间不能视为本期事件，旧感受不能认定为当前状态"
        item = {**r, "timing": timing}
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True)
        addition = len(serialized) + (2 if result else 0)  # Default JSON comma/space separator.
        if len(result) >= MAX_RESULTS or used + addition > MAX_CHARS:
            warnings.append("档案结果达到 20 条或 12000 字符预算，部分相关记录未采用")
            continue
        result.append(item)
        used += addition
    if not result:
        warnings.append("未检索到可采用的个人档案记录；不代表相关事实不存在")
    return {"records": result, "warnings": list(dict.fromkeys(warnings))}


def push_private(root, repository):
    """Push committed main only after checking the effective push URL and visibility."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ArchiveError("远端仓库标识无效")
    if validate(root)["status"] != "PASS":
        raise ArchiveError("档案校验失败，停止推送")
    def run(argv):
        result = subprocess.run(argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        if result.returncode:
            raise ArchiveError("Git 或远端核验失败；保留本地提交，不推断已同步")
        return result.stdout.strip()
    top = run(["git", "rev-parse", "--show-toplevel"])
    if Path(top).resolve() != Path(root).resolve():
        raise ArchiveError("档案必须是独立 Git 仓库根目录，停止推送")
    if run(["git", "branch", "--show-current"]) != "main" or run(["git", "status", "--porcelain"]):
        raise ArchiveError("请先完成本次提交并保持 main 工作树干净")
    urls = run(["git", "remote", "get-url", "--push", "--all", "origin"]).splitlines()
    permitted = {f"git@github.com:{repository}.git", f"https://github.com/{repository}.git",
                 f"ssh://git@ssh.github.com:443/{repository}.git"}
    if len(urls) != 1 or urls[0] not in permitted:
        raise ArchiveError("远端身份不匹配，停止推送")
    try:
        remote = json.loads(run(["gh", "api", f"repos/{repository}"]))
    except (ValueError, TypeError):
        raise ArchiveError("远端核验响应无效，停止推送") from None
    if remote.get("full_name", "").casefold() != repository.casefold() or remote.get("private") is not True:
        raise ArchiveError("目标不是指定 private 仓库，停止推送")
    # Explicit refspec, no force and no tags. A changed remote tip rejects normally.
    run(["git", "push", "--no-follow-tags", "origin", "HEAD:refs/heads/main"])
    return {"status": "PASS", "repository": repository, "visibility": "private"}


def main():
    parser = argparse.ArgumentParser(description="本地个人档案校验与引用检索（不执行档案代码）")
    parser.add_argument("command", choices=("validate", "query", "review-digest", "push-private"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--category", action="append")
    parser.add_argument("--status", choices=sorted(STATES), default="confirmed")
    parser.add_argument("--repository", help="Only for an explicitly authorized private GitHub target")
    args = parser.parse_args()
    if args.command == "push-private":
        try:
            result = push_private(args.root, args.repository or "")
        except (ArchiveError, OSError, subprocess.TimeoutExpired):
            result = {"status": "ERROR", "errors": ["私人同步核验失败；本地提交保留，须检查身份、private 状态及 Git 状态"]}
    elif args.command == "validate":
        result = validate(args.root)
    else:
        result = query(args.root, args.text, args.category, status="candidate" if args.command == "review-digest" else args.status)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get("status") == "ERROR")


if __name__ == "__main__":
    raise SystemExit(main())
