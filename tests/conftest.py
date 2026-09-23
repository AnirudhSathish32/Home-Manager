"""Synthetic local model server; never sends documents outside the test process."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from home_manager.vision import VisionConfig


@pytest.fixture
def local_model():
    state = {"requests": [], "finish_reason": "stop", "status": 200,
             "output": {"title": "Local Test Cafe - 2026-09-22",
                        "folder": "03_Purchases/Receipts",
                        "full_text": "LOCAL TEST CAFE\n2026-09-22\nUSD\nSubtotal 20.00\nTax 2.00\nTip 3.00\nTotal 25.00\nReturns within 14 days"}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state["requests"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            state["path"] = self.path
            self.send_response(state["status"])
            if state["status"] == 302:
                self.send_header("Location", "http://example.invalid/never-follow")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if "error_body" in state:
                self.wfile.write(json.dumps({"error": state["error_body"]}).encode())
                return
            self.wfile.write(json.dumps({"choices": [{"finish_reason": state["finish_reason"],
                                                     "message": {"content": json.dumps(state["output"])}}]}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["config"] = VisionConfig(base_url=f"http://127.0.0.1:{server.server_port}/v1", model="synthetic-vision")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
