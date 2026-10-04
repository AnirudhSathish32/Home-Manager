"""Local-only inference for evals: no shared GPU, no relay, no remote host, no web.

Two layers. check_server refuses any endpoint that is not a model server on this computer: the app's own rule
(http://127.0.0.1:PORT/v1), never the family GPU relay's port, and never a server whose listing says it is that relay.
install_network_guard then makes the whole eval process unable to connect anywhere but loopback, so a code path that
tried the web (rates, prices, lookups) fails loudly instead of sending anything.

What this cannot prove: that the program listening on the loopback port does its own inference. Use LM Studio (or
another local server) on this computer, with its remote or cloud features off.
"""

import ipaddress
import sys
from urllib.parse import urlsplit

from home_manager.models.gpu_host import PORT as RELAY_PORT
from home_manager.models.model_client import get_json
from home_manager.models.residency import MANAGED_MARKER
from home_manager.models.vision import ROLE_ALIASES, VisionConfig, endpoint_url

LOOPBACK_NAMES = {"127.0.0.1", "::1", "localhost"}
_guard = {"installed": False}


class GuardError(RuntimeError):
    pass


def check_server(base_url, models=(), probe=True):
    """The validated base URL, or GuardError. probe asks the server whether it is the GPU relay."""
    try:
        url = endpoint_url(base_url)
    except ValueError as exc:
        raise GuardError(f"Evals use a model server on this computer only: {exc}") from None
    if urlsplit(url).port == RELAY_PORT:
        raise GuardError(f"Port {RELAY_PORT} is the family GPU relay's port. Point evals at LM Studio itself (usually port 1234).")
    for model in models:
        if not model or model in ROLE_ALIASES.values() or model.startswith("home-manager/"):
            raise GuardError(f"{model!r} is not a model ID on this computer's server.")
    if probe:
        config = VisionConfig(base_url=url, model=models[0] if models else "")
        try:
            listing = get_json(config, "/api/v1/models")
        except (OSError, ValueError):
            listing = None
        if isinstance(listing, dict) and listing.get("managed_by") == MANAGED_MARKER:
            raise GuardError("This server is the family GPU relay, which forwards to another computer. Point evals at LM Studio itself.")
    return url


def loopback(host):
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _hook(event, args):
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and not loopback(address[0]):
            raise GuardError(f"Evals refused a network connection to {address[0]}: only this computer's model server is allowed.")
    elif event == "socket.getaddrinfo":
        host = args[0]
        if host not in (None, b"", "") and not loopback(host.decode() if isinstance(host, bytes) else host):
            raise GuardError("Evals refused a name lookup: only this computer's model server is allowed.")


def install_network_guard():
    """From now on this process connects only to loopback addresses. Audit hooks cannot be removed; it lasts until exit."""
    if not _guard["installed"]:
        sys.addaudithook(_hook)
        _guard["installed"] = True
