from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple


PATTERNS = {
    "emails": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "urls": re.compile(r"https?://[^\s)）]+|www\.[^\s)）]+"),
    "phones": re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
    "id_numbers": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "qq_wechat": re.compile(r"(?:QQ|qq|微信|WeChat|wechat|wx|WX)[:：\s_-]*[A-Za-z0-9_-]{5,}"),
    "addresses": re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,40}(?:省|市|区|县|镇|乡|路|街|巷|号楼|单元|室|号)"),
}

NAME_PATTERN = re.compile(
    r"(?:(?:姓名|作者|联系人|收件人|发件人|我叫|我是)[:：\s]*)"
    r"([赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹][\u4e00-\u9fff]{1,2})"
)


def anonymize_text(text: str, privacy_level: str = "high") -> Tuple[str, Dict[str, int]]:
    counts = {key: 0 for key in PATTERNS}
    counts["chinese_names"] = 0

    replacements = {
        "emails": "[EMAIL_REDACTED]",
        "urls": "[URL_REDACTED]",
        "phones": "[PHONE_REDACTED]",
        "id_numbers": "[ID_REDACTED]",
        "qq_wechat": "[ACCOUNT_REDACTED]",
        "addresses": "[ADDRESS_REDACTED]",
    }

    sanitized = text
    for key, pattern in PATTERNS.items():
        sanitized, n = pattern.subn(replacements[key], sanitized)
        counts[key] += n

    if privacy_level == "high":
        def replace_name(match: re.Match) -> str:
            counts["chinese_names"] += 1
            prefix = match.group(0).replace(match.group(1), "")
            return f"{prefix}[NAME_REDACTED]"

        sanitized = NAME_PATTERN.sub(replace_name, sanitized)

    return sanitized, counts


def anonymize_documents(documents: List[Dict], config: Dict) -> Tuple[List[Dict], Dict[str, int]]:
    totals = {key: 0 for key in [*PATTERNS.keys(), "chinese_names"]}
    sanitized_docs: List[Dict] = []
    for doc in documents:
        sanitized_text, counts = anonymize_text(doc["text"], config.get("privacy_level", "high"))
        for key, value in counts.items():
            totals[key] += value
        sanitized_docs.append({**doc, "text": sanitized_text, "chars": len(sanitized_text)})
    return sanitized_docs, totals


def render_privacy_report(config: Dict, counts: Dict[str, int]) -> str:
    lines = [
        "# Privacy Report",
        "",
        f"- Character ID: `{config['character_id']}`",
        f"- Privacy level: `{config['privacy_level']}`",
        f"- Quote policy: `{config['quote_policy']}`",
        f"- Max quote characters: `{config['max_quote_chars']}`",
        "",
        "## Redaction Summary",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This report intentionally records counts only. It must not expose raw private values.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_privacy_report(config: Dict, counts: Dict[str, int], output_path: Path) -> Path:
    report_path = output_path / "reports" / "privacy_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_privacy_report(config, counts), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    raise SystemExit("Use build_character.py as the public entry point.")
