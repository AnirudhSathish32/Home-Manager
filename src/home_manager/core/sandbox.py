"""Test mode for the agent test instance: real data is off limits and nothing leaves this computer.

Off by default. Only scripts/test_instance.py turns it on (docs/development.md "Agent test instance"); nothing here reads
the environment to decide, so the live launcher can never start in test mode.

- Paths: paths.local_absolute calls check_path first, before any filesystem call. The check is lexical, so a protected
  folder is never opened, listed or stat'd, even to refuse it.
- Network: an audit hook refuses name lookups and connections to any host that isn't loopback. It covers every caller in
  this process (exchange rates, crypto prices, item lookups, the family client), not child processes, and TCP and lookups
  only (nothing in the app sends UDP).
"""

import ipaddress
import logging
import os
from pathlib import Path
import socket
import sys
import threading

log = logging.getLogger("home_manager.sandbox")

REFUSED = "Test instance: outbound internet is off"
PROBE_HOST = "egress-probe.invalid"


class _State:
    active = False
    root: str | None = None
    allowed: tuple[str, ...] = ()  # norm()'d
    protected: tuple[str, ...] = ()  # As given (absolute), for messages; norm()'d when compared
    hook_installed = False
    logged: set = set()


_state = _State()
_quiet = threading.local()  # Set while status() probes, so the probe adds no log line.


def norm(value) -> str:
    """The path as compared here: absolute, normalized and case-folded, from the string alone (no filesystem call)."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(os.fspath(value))))


def under(path: str, root: str) -> bool:
    """path is root or inside it; both already norm()'d."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def default_protected() -> tuple[str, ...]:
    """The live data roots (CLAUDE.md): the finance library, the donated corpus and the live settings folder."""
    roots = [r"P:\Finances", r"P:\EvalCorpus"]
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "HomeManager"))
    return tuple(roots)


def activate(root, allowed=(), protected=()):
    """Turn test mode on for this process. root and allowed are the only folders paths may name; protected adds to the
    live data roots (tests pass decoys)."""
    _state.root = os.path.abspath(root)
    _state.allowed = (norm(root), *(norm(item) for item in allowed))
    _state.protected = tuple(os.path.abspath(item) for item in (*default_protected(), *protected))
    _state.logged = set()
    if not _state.hook_installed:
        sys.addaudithook(_hook)  # Audit hooks can't be removed; _hook does nothing while test mode is off.
        _state.hook_installed = True
    _state.active = True


def deactivate():
    """Turn test mode off (in-process tests)."""
    _state.active = False
    _state.root, _state.allowed, _state.protected = None, (), ()


def active() -> bool:
    return _state.active


def root() -> Path | None:
    return Path(_state.root) if _state.root else None


def in_root(value) -> bool:
    return bool(_state.active and _state.root and under(norm(value), norm(_state.root)))


def check_path(value):
    """Refuse a path under a protected root, or outside the instance's folders. Lexical only."""
    if not _state.active:
        return
    from .paths import PathError
    path = norm(value)
    for protected in _state.protected:
        if under(path, norm(protected)):
            raise PathError(f"Test instance: {protected} holds real data and is off limits.")
    if not any(under(path, allowed) for allowed in _state.allowed):
        raise PathError(f"Test instance: only folders inside {_state.root} can be used.")


def status() -> dict:
    """Whether each guard actually refuses right now. Probes rather than reporting a flag, so a broken guard shows."""
    if not _state.active:
        return {"paths": False, "egress": False}
    return {"paths": _probe_paths(), "egress": _probe_egress()}


def _probe_paths() -> bool:
    from .paths import PathError
    if not _state.protected:
        return False
    try:
        check_path(os.path.join(_state.protected[0], "probe"))
    except PathError:
        return True
    return False


def _probe_egress() -> bool:
    if not _state.hook_installed:
        return False
    _quiet.on = True
    try:
        socket.getaddrinfo(PROBE_HOST, 443)
    except socket.gaierror as exc:
        return REFUSED in str(exc)
    except OSError:
        return False
    finally:
        _quiet.on = False
    return False


def loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").split("%")[0]
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _refuse(host, error):
    if not getattr(_quiet, "on", False) and host not in _state.logged:
        _state.logged.add(host)
        log.warning("test instance: refused outbound host=%s", host)
    raise error


def _hook(event, args):
    if event in ("socket.getaddrinfo", "socket.connect") and _state.active:
        _audit(event, args)


def _audit(event, args):
    if event == "socket.getaddrinfo":
        host = args[0]
        if host in (None, "", b"") or loopback(host):  # None and "" are passive lookups for a bind.
            return
        _refuse(host, socket.gaierror(socket.EAI_NONAME, f"{REFUSED} ({host})."))
    address = args[1]
    if not isinstance(address, tuple) or loopback(address[0]):  # A str address is a local (AF_UNIX) socket.
        return
    _refuse(address[0], ConnectionRefusedError(f"{REFUSED} ({address[0]})."))
