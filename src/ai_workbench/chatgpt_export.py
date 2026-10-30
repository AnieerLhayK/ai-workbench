"""Pure, local ChatGPT export parsing. No Qt, settings, accounts or writes.

All returned content and identifiers remain private. Parsing preserves branches;
it does not choose a research population or claim anonymization.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from io import BytesIO
from pathlib import Path
import zipfile

PARSER_VERSION = "chatgpt-export/1"
MAX_EXPORT_BYTES = 150_000_000


@dataclass(frozen=True)
class ExportRead:
    documents: tuple[dict, ...]
    diagnostics: tuple[str, ...]
    source_sha256: str
    parser_version: str = PARSER_VERSION


def _timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    return value if isinstance(value, str) else None


def parse_chatgpt_export(text: str, *, source_id: str | None = None) -> ExportRead:
    """Parse mapping/messages/body JSON without filtering roles or branches.

    Raises ValueError for malformed document structure. Non-text content and
    malformed entries are explicitly diagnosed; diagnostics never quote input.
    Document dictionaries retain the e-Diary body/at/id interface.
    """
    fingerprint = sha256(text.encode("utf-8")).hexdigest()
    key = source_id or fingerprint
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValueError("chatgpt_invalid_json") from error
    conversations = value if isinstance(value, list) else value.get("conversations", [value]) if isinstance(value, dict) else None
    if not isinstance(conversations, list):
        raise ValueError("chatgpt_expected_conversations")
    documents, diagnostics = [], []
    for ci, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            diagnostics.append(f"invalid_conversation:{ci}")
            continue
        cid = str(conversation.get("id", f"{key}:{ci}"))
        title = conversation.get("title", "ChatGPT 对话")
        mapping = conversation.get("mapping")
        if mapping:
            if not isinstance(mapping, dict):
                raise ValueError("chatgpt_expected_mapping")
            for node_id, node in mapping.items():
                if not isinstance(node, dict):
                    diagnostics.append(f"invalid_node:{ci}")
                    continue
                message = node.get("message")
                if message is None:
                    continue  # Structural/root node; graph references remain intact.
                if not isinstance(message, dict):
                    diagnostics.append(f"invalid_message:{ci}")
                    continue
                author, content = message.get("author") or {}, message.get("content") or {}
                if not isinstance(author, dict) or not isinstance(content, dict):
                    diagnostics.append(f"invalid_message_content:{ci}")
                    continue
                if "parts" not in content:
                    diagnostics.append(f"unsupported_content_layout:{ci}")
                parts = content.get("parts", [])
                if not isinstance(parts, list):
                    diagnostics.append(f"invalid_parts:{ci}")
                    continue
                if any(not isinstance(part, str) for part in parts):
                    diagnostics.append(f"non_text_parts:{ci}")
                body = "\n".join(part for part in parts if isinstance(part, str))
                documents.append({"id": f"chatgpt:{cid}:{node_id}", "title": title,
                    "body": body, "at": _timestamp(message.get("create_time")),
                    "role": author.get("role", "unknown"), "parent": node.get("parent"),
                    "children": node.get("children", []), "origin": "chatgpt",
                    "conversation_id": cid, "node_id": str(node_id),
                    "current_node": conversation.get("current_node"), "export_format": "mapping"})
        elif isinstance(conversation.get("messages"), list):
            for n, message in enumerate(conversation["messages"]):
                if not isinstance(message, dict):
                    diagnostics.append(f"invalid_message:{ci}:{n}")
                    continue
                content = message.get("content", "")
                if not isinstance(content, str):
                    diagnostics.append(f"non_text_content:{ci}:{n}")
                    content = ""
                documents.append({"id": f"import:{key}:{ci}:{n}", "title": title,
                    "body": content, "role": message.get("role", "unknown"),
                    "at": _timestamp(message.get("create_time") or message.get("timestamp")),
                    "origin": "chatgpt", "conversation_id": cid, "node_id": str(n),
                    "parent": None, "children": [], "current_node": None, "export_format": "messages"})
        elif isinstance(conversation.get("body"), str):
            documents.append({"id": f"import:{key}:{ci}", "title": title,
                "body": conversation["body"], "at": _timestamp(conversation.get("date")),
                "role": "unknown", "origin": "import", "conversation_id": cid})
        else:
            diagnostics.append(f"unsupported_conversation:{ci}")
    return ExportRead(tuple(documents), tuple(diagnostics), fingerprint)


def read_chatgpt_export(path: str | Path) -> ExportRead:
    """Read one JSON or ZIP, bounded by compressed and expanded size.

    ZIP members are read in memory, never extracted to the filesystem.
    source_sha256 fingerprints the exact JSON/ZIP file bytes. The text-only
    parser fingerprints its UTF-8 text input; source_id changes IDs only.
    """
    path = Path(path)
    try:
        if path.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("chatgpt_export_too_large")
        source_bytes = path.read_bytes()
        if len(source_bytes) > MAX_EXPORT_BYTES:
            raise ValueError("chatgpt_export_too_large")
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(BytesIO(source_bytes)) as archive:
                members = [m for m in archive.infolist() if Path(m.filename).name == "conversations.json"]
                if len(members) != 1 or members[0].file_size > MAX_EXPORT_BYTES:
                    raise ValueError("chatgpt_zip_requires_one_bounded_conversations_json")
                with archive.open(members[0]) as handle:
                    raw = handle.read(MAX_EXPORT_BYTES + 1)
        else:
            raw = source_bytes
        if len(raw) > MAX_EXPORT_BYTES:
            raise ValueError("chatgpt_export_too_large")
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise ValueError("chatgpt_unreadable_export") from error
    return replace(parse_chatgpt_export(text), source_sha256=sha256(source_bytes).hexdigest())
