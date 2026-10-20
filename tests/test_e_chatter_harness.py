"""Opt-in official Harness integration; only a local synthetic model endpoint."""
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_workbench.e_chatter import deepseek
from ai_workbench.e_chatter.files import ChatterError


@pytest.mark.skipif(os.environ.get("E_CHATTER_RUN_DSH") != "1", reason="requires separately qualified official Windows Harness runtime")
@pytest.mark.parametrize("mode", ["success", "cancel", "tool"])
def test_official_harness_tool_free_stream_against_local_synthetic_endpoint(tmp_path, monkeypatch, mode):
    received = []
    arrived, release = threading.Event(), threading.Event()
    reply = json.dumps(dict(reply="synthetic harness stream", status="completed", files=[], diagnosis="", handoff="", build_intake=""))

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if mode == "cancel":
                self.wfile.write(b": synthetic stream waiting\n\n")
                self.wfile.flush()
                arrived.set()
                release.wait(10)
                return
            events = [
                ("message_start", {"message": {"id": "synthetic-message", "type": "message", "role": "assistant", "content": [], "model": "deepseek-flash", "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}}}),
                ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": reply[:40]}}),
                ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": reply[40:]}}),
                ("content_block_stop", {"index": 0}),
                ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 20}}),
                ("message_stop", {}),
            ]
            if mode == "tool":
                events[1:5] = [
                    ("content_block_start", {"index": 0, "content_block": {"type": "tool_use", "id": "synthetic-call", "name": "forbidden_fixture_tool", "input": {}}}),
                    ("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
                    ("content_block_stop", {"index": 0}),
                ]
                events[-2][1]["delta"]["stop_reason"] = "tool_use"
            for kind, data in events:
                self.wfile.write(("event: " + kind + "\ndata: " + json.dumps({"type": kind, **data}) + "\n\n").encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original_dump = deepseek.yaml.safe_dump

    def composition(value, **kwargs):
        # Test-only internal seam; public settings cannot select an arbitrary endpoint.
        for row in value:
            if row.get("id") == "llm-deepseek" and "config" in row:
                row["config"]["baseURL"] = f"http://127.0.0.1:{server.server_port}"
        return original_dump(value, **kwargs)

    monkeypatch.setattr(deepseek.yaml, "safe_dump", composition)
    adapter = deepseek.DeepSeek(tmp_path / "harness", auth="api_key")
    try:
        adapter.authenticate("save_key", key="synthetic-fixture-not-a-real-key")
        catalog = adapter.account()
        assert catalog["connected"] and catalog["models"]
        request = {"task_id": "synthetic-task", "session_id": "synthetic-conversation", "execution": {"agent": "deepseek", "model": catalog["models"][0]["id"], "effort": "off"}, "payload": {"role": "chat", "user": "Synthetic writing-only request", "history": [], "character": {}}}
        streamed = []
        if mode == "cancel":
            cancelled, ended, failures = threading.Event(), threading.Event(), []
            def run():
                try:
                    adapter.generate(request, cancelled, streamed.append)
                except ChatterError as error:
                    failures.append(error)
                finally:
                    ended.set()
            threading.Thread(target=run, daemon=True).start()
            assert arrived.wait(15)
            cancelled.set()
            assert ended.wait(5) and failures and not adapter.jobs
            return
        if mode == "tool":
            with pytest.raises(ChatterError, match="工具"):
                adapter.generate(request, threading.Event(), streamed.append)
            assert not adapter.jobs
            return
        result = adapter.generate(request, threading.Event(), streamed.append)
        assert result["reply"] == "synthetic harness stream"
        assert streamed and streamed[-1] == result["reply"]
        assert request["execution"]["actual_model"]
        assert len(received) == 1 and not received[0].get("tools")
    finally:
        release.set()
        adapter.close()
        server.shutdown()
        server.server_close()
