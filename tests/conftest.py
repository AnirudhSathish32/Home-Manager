"""Synthetic local model server; never sends documents outside the test process."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import pytest

from home_manager.scanner import Scanner, ScanLimits
from home_manager.vision import VisionConfig


def inbox_scan(store, files=None, **limits):
    """Put files directly in Library/Inbox, the only way documents enter a library, and capture them."""
    for name, data in (files or {}).items():
        (store.library.inbox / name).write_bytes(data)
    job = store.create_job()
    Scanner(store, ScanLimits(stability_seconds=0, **limits)).run(job)
    return job


def documents_by_name(store):
    return {doc["relative_path"]: doc for doc in store.documents()["items"]}


@pytest.fixture
def local_model():
    state = {"requests": [], "finish_reason": "stop", "status": 200,
             # Served by GET /v1/models; changing model_meta simulates different weights under one ID.
             "models": ["synthetic-vision", "synthetic-reasoning", "test-reasoning", "reasoner"],
             "model_meta": {"size": 4_000_000_000, "n_params": 9_000_000_000},
             "output": {"full_text": "LOCAL TEST CAFE\n2026-09-22\nUSD\nSubtotal 20.00\nTax 2.00\nTip 3.00\nTotal 25.00\nReturns within 14 days"}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            super().setup()

        def respond(self, status, body, content_type):
            # One write per response. On this Windows host, a second back-to-back loopback
            # segment is occasionally never acknowledged (retransmits for ~19 s, then a reset),
            # which made the synthetic server flaky; real model servers are unaffected by this.
            head = f"HTTP/1.0 {status} {HTTPStatus(status).phrase}\r\nContent-Type: {content_type}\r\n"
            if status == 302:
                head += "Location: http://example.invalid/never-follow\r\n"
            try:
                self.wfile.write((head + f"Content-Length: {len(body)}\r\n\r\n").encode("latin-1") + body)
            except OSError:
                pass  # The client cancelled and closed the connection.

        def do_GET(self):
            if self.path != "/v1/models" or state.get("models") is None:
                self.respond(404, b"", "application/json")
                return
            self.respond(200, json.dumps({"object": "list", "data": [
                {"id": model, "object": "model", "owned_by": "synthetic", "created": 0, "meta": state["model_meta"]}
                for model in state["models"]]}).encode(), "application/json")

        def do_POST(self):
            state["requests"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            state["path"] = self.path
            if state.get("response_gate"):
                state["response_gate"].wait(timeout=15)  # Like prompt processing: nothing sent yet.
            if "error_body" in state:
                self.respond(state["status"], json.dumps({"error": state["error_body"]}).encode(), "text/event-stream")
                return
            output = state["outputs"].pop(0) if state.get("outputs") else state["output"]
            event = {"choices": [{"finish_reason": state["finish_reason"],
                                  "delta": {"content": json.dumps(output)}}]}
            stream = "data: " + json.dumps(event) + "\n\n"
            if state.get("timings"):
                stream += "data: " + json.dumps({"choices": [], "timings": state["timings"],
                                                 "usage": {"prompt_tokens": state["timings"]["prompt_n"],
                                                           "completion_tokens": state["timings"]["predicted_n"]}}) + "\n\n"
            self.respond(state["status"], (stream + "data: [DONE]\n\n").encode(), "text/event-stream")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["config"] = VisionConfig(base_url=f"http://127.0.0.1:{server.server_port}/v1", model="synthetic-vision")
    try:
        yield state
    finally:
        if state.get("response_gate"):
            state["response_gate"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
