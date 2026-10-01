"""The relay's HTTP server waits for the client to close first (models/http_server.py; docs/development.md,
"Windows loopback resets"). Loopback only, synthetic replies."""

from http.server import BaseHTTPRequestHandler
import socket
import threading
import time

import pytest

from home_manager.models.http_server import GracefulHTTPServer

REPLY = b"y" * 200_000  # Many segments: the case that used to lose its tail.


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(REPLY)))
        self.end_headers()
        self.wfile.write(REPLY)


@pytest.fixture
def server():
    server = GracefulHTTPServer(("127.0.0.1", 0), Handler)
    server.close_wait = 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def fetch(server):
    """The whole reply, read by Content-Length as the app's client does; the socket is left open."""
    sock = socket.create_connection(server.server_address, timeout=30)
    sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
    data = b""
    while b"\r\n\r\n" not in data or len(data.partition(b"\r\n\r\n")[2]) < len(REPLY):
        chunk = sock.recv(65536)
        assert chunk, "The server closed before the whole reply arrived."
        data += chunk
    return sock, data.partition(b"\r\n\r\n")[2]


def test_the_server_never_closes_first(server):
    sock, body = fetch(server)
    assert body == REPLY
    sock.settimeout(0.3)
    with pytest.raises(TimeoutError):
        sock.recv(1)  # No FIN yet: the server is waiting for this client to close.
    sock.close()


def test_a_client_that_never_closes_is_cut_off_after_the_wait(server):
    sock, _ = fetch(server)
    started = time.monotonic()
    sock.settimeout(5)
    assert sock.recv(1) == b""  # The server's close, after close_wait (1 s here).
    assert 0.5 < time.monotonic() - started < 4
    sock.close()


def test_many_large_replies_all_arrive_whole(server):
    # Before the fix about 1 in 75 of these lost its tail and stalled for 19 s on this Windows machine.
    for _ in range(300):
        sock, body = fetch(server)
        sock.close()
        assert len(body) == len(REPLY)
