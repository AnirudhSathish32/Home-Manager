"""The HTTP server base for the GPU host relay, the family hub (and the tests' synthetic model server).

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
import ipaddress
import shutil
import socket
import struct
import subprocess

CLOSE_WAIT_SECONDS = 10  # A client that never closes is cut off after this.
ABORT = struct.pack("hh", 1, 0)  # SO_LINGER on with a zero timeout: close() sends a reset.
TAILNET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's address range (CGNAT space).


def check_bind(address: str, loopback: bool, what="This server"):
    """Allow loopback (127.0.0.1 only) or a Tailscale address (100.64.0.0/10), and nothing else: never 0.0.0.0 or a
    LAN address. Shared by the GPU relay and the family hub (docs/family.md "Families", "Security")."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        raise ValueError(f"{address} is not an IP address.") from None
    if loopback and address != "127.0.0.1":
        raise ValueError("The loopback listener binds to 127.0.0.1 only.")
    if not loopback and ip not in TAILNET:
        raise ValueError(f"{what} listens only on a Tailscale address (100.64.0.0/10), not {address}.")


def tailnet_address():
    """This computer's Tailscale IPv4 address, or None."""
    candidates = []
    try:
        candidates = [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    command = shutil.which("tailscale")
    if command:
        try:
            output = subprocess.run([command, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout
            candidates += output.split()
        except (OSError, subprocess.SubprocessError):
            pass
    for value in candidates:
        try:
            if ipaddress.ip_address(value) in TAILNET:
                return value
        except ValueError:
            continue
    return None


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
