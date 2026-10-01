"""The HTTP server base for the GPU host relay (and the tests' synthetic model server).

After a reply, the server waits for the client to close the connection before closing its own end. On Windows, closing a
socket (or sending FIN with shutdown) while a multi-segment reply is still in flight sometimes loses a segment: the
client gets the start of the reply, waits about 19 s for the rest, then sees WinError 10054. Measured 2026-10-01 on
loopback with 40 KB replies: shutdown-and-close at once lost ~1.3% of replies; waiting for the client to close lost none.
Every client of these servers closes first (on Content-Length, or on the stream's [DONE]).

Once the client has closed, it has read the whole reply, so the server ends the connection with a reset. That leaves
neither side in TIME_WAIT: when clients close first, their TIME_WAIT ports otherwise run out after ~16,000 requests in
two minutes (WinError 10048). See docs/development.md, "Windows loopback resets".
"""

from http.server import ThreadingHTTPServer
import socket
import struct

CLOSE_WAIT_SECONDS = 10  # A client that never closes is cut off after this.
ABORT = struct.pack("hh", 1, 0)  # SO_LINGER on with a zero timeout: close() sends a reset.


class GracefulHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    close_wait = CLOSE_WAIT_SECONDS

    def shutdown_request(self, request):
        # Not socketserver's shutdown(SHUT_WR) then close: a FIN right behind the reply is what loses it. Reading until
        # the client's own FIN also drains anything unread.
        client_closed = False
        try:
            request.settimeout(self.close_wait)
            while request.recv(65536):
                pass
            client_closed = True
        except OSError:
            pass
        if client_closed:
            try:
                request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, ABORT)
            except OSError:
                pass
        self.close_request(request)
