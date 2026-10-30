import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from ai_workbench.chatgpt_export import parse_chatgpt_export, read_chatgpt_export


def test_preserves_roles_branches_and_current_node(tmp_path):
    value = [{"id": "c", "current_node": "b", "mapping": {
        "a": {"parent": None, "children": ["b", "c"], "message": {
            "author": {"role": "user"}, "content": {"parts": ["好"]}}},
        "b": {"parent": "a", "children": [], "message": {
            "author": {"role": "assistant"}, "content": {"parts": ["好"]}}},
        "c": {"parent": "a", "children": [], "message": {
            "author": {"role": "system"}, "content": {"parts": ["context"]}}}}}]
    text = json.dumps(value)
    result = parse_chatgpt_export(text)
    assert [d["role"] for d in result.documents] == ["user", "assistant", "system"]
    assert result.documents[0]["children"] == ["b", "c"]
    assert all(d["current_node"] == "b" for d in result.documents)
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", text)
    from_file = read_chatgpt_export(path)
    assert from_file.documents == result.documents
    assert from_file.diagnostics == result.diagnostics
    assert from_file.source_sha256 == sha256(path.read_bytes()).hexdigest()
    assert len(list(tmp_path.iterdir())) == 1


def test_diagnostics_and_collision_free_flat_ids():
    result = parse_chatgpt_export(json.dumps([
        {"messages": [{"content": "same"}]}, {"messages": [{"content": "same"}]}, None]))
    assert len({d["id"] for d in result.documents}) == 2
    assert result.diagnostics == ("invalid_conversation:2",)
    with pytest.raises(ValueError, match="chatgpt_expected_conversations"):
        parse_chatgpt_export("42")


def test_fingerprint_is_independent_of_logical_namespace_and_tracks_bom(tmp_path):
    text = json.dumps({"body": "synthetic"})
    result = parse_chatgpt_export(text, source_id="logical-source")
    assert result.source_sha256 == sha256(text.encode("utf-8")).hexdigest()
    assert "logical-source" in result.documents[0]["id"]
    path = tmp_path / "export.json"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert read_chatgpt_export(path).source_sha256 == sha256(path.read_bytes()).hexdigest()


def test_pure_import_does_not_load_qt_or_diary():
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    subprocess.run([sys.executable, "-c", "import sys; import ai_workbench.chatgpt_export; "
        "assert not any(n.startswith(('PySide6', 'ai_workbench.e_diary')) for n in sys.modules)"], check=True, env=environment)


def test_unsupported_content_layout_is_diagnosed_separately_from_empty_text():
    value = [{"mapping": {
        "unsupported": {"message": {"author": {"role": "user"},
            "content": {"content_type": "code", "text": "synthetic text"}}},
        "empty": {"message": {"author": {"role": "user"},
            "content": {"content_type": "text", "parts": []}}}}}]
    result = parse_chatgpt_export(json.dumps(value))
    assert len(result.documents) == 2
    assert [d["body"] for d in result.documents] == ["", ""]
    assert result.diagnostics == ("unsupported_content_layout:0",)
