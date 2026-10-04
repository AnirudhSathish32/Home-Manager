"""Model transport: cancellation, inference telemetry and model identity.

http.client never consults proxy settings and never follows redirects, so neither
can be inherited or triggered by a document. Endpoints are validated URLs: a loopback
server on this computer, or a family GPU computer on the tailnet (models/gpu_host.py).
"""

from contextlib import contextmanager
import hashlib
import http.client
import ipaddress
import json
import logging
import queue
import re
import socket
import threading
import time
from urllib.parse import quote, urlsplit

from ..core.jobs import Cancelled, Work
from ..core.logs import log_failure
from ..library.storage import now
from .model_stream import IDLE_SECONDS, read_completion

log = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.1
UNENFORCED_SCHEMA = "Reply with one JSON object and nothing else. It must match this JSON schema:\n"
# Listing fields that change without the model bytes changing.
VOLATILE_METADATA = {"created", "object", "state", "loaded_context_length"}
TAILNET = ipaddress.ip_network("100.64.0.0/10")
TS_NET_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net$")
REMOTE_OFFLINE = "The family GPU computer is offline or not on Tailscale. Check that Tailscale is connected on both computers and the GPU host is running."
# host:port -> bearer token for a family GPU computer. Set by the app from its control
# directory; never part of a model config, so it never reaches run options or the database.
_tokens = {}
# In-process callbacks that see every attempt's raw output (evals). Never persisted by the app.
_recorders = []
_recorders_lock = threading.Lock()


def is_tailnet_host(host):
    """A Tailscale address (100.64.0.0/10) or MagicDNS name (*.ts.net)."""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host) in TAILNET
    except ValueError:
        return bool(TS_NET_HOST.match(host.lower()))


def is_remote(config):
    return urlsplit(config.base_url).hostname != "127.0.0.1"


def set_token(base_url, token):
    netloc = urlsplit(base_url).netloc
    if token:
        _tokens[netloc] = token
    else:
        _tokens.pop(netloc, None)


def _headers(config, headers):
    token = is_remote(config) and _tokens.get(urlsplit(config.base_url).netloc)
    return {**headers, "Authorization": f"Bearer {token}"} if token else headers


class ModelHTTPError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def server_error(status, body: bytes, remote=False):
    # Inspect only for known diagnostic categories. Server bodies can echo receipt
    # contents, paths or prompts, so never persist or display the raw error body.
    body = body.decode("utf-8", errors="replace").lower()
    prefix = f"{'Family GPU computer' if remote else 'Local model server'} returned HTTP {status}. "
    if status in (401, 403):
        if remote:
            return prefix + "Your family GPU token was rejected. Ask the person who runs the GPU computer for a new one."
        return prefix + "The server requires authorization. This adapter currently supports a loopback server without API-token authentication."
    if any(value in body for value in ("out of memory", "cuda out", "failed to allocate", "insufficient memory")):
        return prefix + "The server reported insufficient memory. Unload other models, reduce GPU offload/context, or use a smaller model."
    if any(value in body for value in ("context length", "context window", "n_ctx", "context size")):
        return prefix + "The server reported a context limit. Allow room for the input plus the requested output tokens in model load settings."
    if any(value in body for value in ("response_format", "json_schema", "json_object", "grammar")):
        return prefix + "The server rejected structured output. Update the local server/runtime and check its JSON-schema support."
    if any(value in body for value in ("mmproj", "vision encoder", "does not support images", "image input is not supported")):
        return prefix + "The server could not process images. Load a vision-capable model with its matching vision component."
    return prefix + "Check the model server's log immediately after this request for the rejection reason. Request bodies alone do not show it."


def _connection(config, timeout):
    url = urlsplit(config.base_url)  # Already validated as http://127.0.0.1:PORT/v1 or a tailnet host.
    return http.client.HTTPConnection(url.hostname, url.port, timeout=timeout), url.path


def _check_status(response, remote=False):
    if 300 <= response.status < 400:
        raise ModelHTTPError(response.status, "Model server redirects are not permitted.")
    if response.status != 200:
        raise ModelHTTPError(response.status, server_error(response.status, response.read(65536), remote))


def get_json(config, path, timeout=5, limit=1024**2):
    connection, _ = _connection(config, timeout)
    try:
        connection.request("GET", path, headers=_headers(config, {"Accept": "application/json"}))
        response = connection.getresponse()
        _check_status(response, is_remote(config))
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Model server response exceeds the size limit.")
        return json.loads(raw)
    finally:
        connection.close()


def post_json(config, path, payload, timeout=60, limit=65536):
    """POST to an absolute path, like get_json (LM Studio's native API is off the /v1 prefix)."""
    connection, _ = _connection(config, timeout)
    try:
        connection.request("POST", path, json.dumps(payload).encode(), _headers(config, {"Content-Type": "application/json"}))
        response = connection.getresponse()
        _check_status(response, is_remote(config))
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Model server response exceeds the size limit.")
        return json.loads(raw)
    finally:
        connection.close()


def model_identity(config):
    """Fingerprint of server-reported metadata for this model ID, or None when unavailable.

    Servers do not report file hashes. Metadata such as size, parameter count and
    quantization changes when different weights are served under the same ID; an
    unavailable identity disables result reuse rather than trusting the ID alone.
    """
    try:
        listing = get_json(config, "/v1/models")
        entries = [item for item in listing.get("data", []) if isinstance(item, dict) and item.get("id") == config.model]
        if len(entries) != 1:
            return None, {}
        metadata = {"listing": {key: value for key, value in entries[0].items() if key not in VOLATILE_METADATA}}
        try:  # LM Studio's native API adds architecture, format and quantization.
            details = get_json(config, "/api/v0/models/" + quote(config.model, safe=""))
            metadata["details"] = {key: value for key, value in details.items() if key not in VOLATILE_METADATA}
        except (OSError, ValueError, AttributeError):
            pass
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        return None, {}
    canonical = json.dumps({"base_url": config.base_url, "model": config.model, **metadata}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest(), metadata


def resolve_identity(store, config):
    fingerprint, metadata = model_identity(config)
    if fingerprint:
        store.remember_identity(fingerprint, config, metadata)
    return fingerprint


def _positive(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def telemetry(config, input_bytes, started_at, t0, finished, stats, status, error_category=None):
    stats = stats or {}
    usage, timings = stats.get("usage") or {}, stats.get("timings") or {}
    first = stats.get("first_token")
    total_ms = (finished - t0) * 1000
    prompt_tokens = _positive(usage.get("prompt_tokens")) or _positive(timings.get("prompt_n"))
    completion_tokens = _positive(usage.get("completion_tokens")) or _positive(timings.get("predicted_n"))
    local_generation_ms = (finished - first) * 1000 if first else None
    prompt_eval_ms = prompt_tps = None
    if _positive(timings.get("predicted_ms")):
        source, generation_ms = "server_timings", timings["predicted_ms"]
        prompt_eval_ms, prompt_tps = _positive(timings.get("prompt_ms")), _positive(timings.get("prompt_per_second"))
        generation_tps = _positive(timings.get("predicted_per_second"))
    else:
        generation_ms = local_generation_ms
        seconds = (generation_ms or 0) / 1000
        if completion_tokens and seconds > 0:
            source, generation_tps = "server_usage", completion_tokens / seconds
        else:
            # About four characters per token: an estimate, labelled as such.
            source = "estimated"
            generation_tps = (stats.get("output_bytes", 0) / 4) / seconds if seconds > 0 else None
    return {"model_id": config.model, "base_url": config.base_url, "started_at": started_at,
            "time_to_first_token_ms": (first - t0) * 1000 if first else None, "finished_at": now(),
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "prompt_eval_ms": prompt_eval_ms,
            "generation_ms": generation_ms, "total_ms": total_ms, "prompt_tokens_per_second": prompt_tps,
            "generation_tokens_per_second": generation_tps, "metrics_source": source, "input_bytes": input_bytes,
            "output_bytes": stats.get("output_bytes", 0), "finish_reason": stats.get("finish_reason"),
            "status": status, "error_category": error_category}


@contextmanager
def recording(callback):
    """Call callback(attempt) after every model request in this process while inside, success or not.

    attempt holds the raw output text (None when the request failed), the finish reason, status, error
    category, the sampling sent, the work's attribution and the request's telemetry. A correction-turn
    retry is two attempts, the second with follow_up set. A callback that raises is logged and ignored, so recording never changes results.
    """
    with _recorders_lock:
        _recorders.append(callback)
    try:
        yield
    finally:
        with _recorders_lock:
            _recorders.remove(callback)


def _record_attempt(work, payload, text, metrics):
    with _recorders_lock:
        recorders = list(_recorders)
    if not recorders:
        return
    task, owner_id, prompt_version, _ = work.attribution
    # follow_up: the request carried an earlier model answer, as a correction turn (or an agent's next step) does.
    follow_up = any(isinstance(message, dict) and message.get("role") == "assistant" for message in payload.get("messages", []))
    attempt = {"work_id": work.id, "task": task, "owner_id": owner_id, "prompt_version": prompt_version, "text": text, "follow_up": follow_up,
               "finish_reason": metrics["finish_reason"], "status": metrics["status"], "error_category": metrics["error_category"],
               "params": {key: payload.get(key) for key in ("temperature", "seed", "max_tokens")}
               | {"schema_enforced": "response_format" in payload},
               "metrics": metrics}
    for recorder in recorders:
        try:
            recorder(attempt)
        except Exception as exc:  # A broken recorder never fails the model request it observed.
            log_failure(log, "attempt recorder", exc, work=work.id)


def apply_sampling(config, payload):
    """Set the request's sampling from the config's overrides (models/vision.py Sampling), else the app's defaults."""
    temperature = getattr(config, "temperature", None)
    payload.update(model=config.model, stream=True, temperature=DEFAULT_TEMPERATURE if temperature is None else temperature,
                   stream_options={"include_usage": True})
    if getattr(config, "seed", None) is not None:
        payload["seed"] = config.seed
    if not getattr(config, "schema_enforced", True) and "response_format" in payload:
        # Unenforced: the model sees the same schema as an instruction, and the caller's validation is unchanged.
        schema = payload.pop("response_format").get("json_schema", {}).get("schema")
        if schema is not None:
            instruction = UNENFORCED_SCHEMA + json.dumps(schema, separators=(",", ":"))
            messages = payload["messages"]
            if messages and messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
                messages[0] = {**messages[0], "content": messages[0]["content"] + "\n\n" + instruction}
            else:
                messages.insert(0, {"role": "system", "content": instruction})
    return payload


def request_completion(config, payload, work=None):
    """Stream one chat completion. Cancellation releases the caller immediately."""
    from .residency import ensure_loaded  # Imports this module.

    work = work or Work.detached()
    # The single choke point for every model task: eject other models, then load this one.
    ensure_loaded(config, work)
    apply_sampling(config, payload)
    return _exchange(config, "/chat/completions", payload, "text/event-stream", read_completion, work,
                     "Local model returned an invalid completion stream.")


def _usage(usage):
    """Chat completions report prompt/completion tokens; the Responses API reports input/output tokens."""
    usage = usage if isinstance(usage, dict) else {}
    return {"prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens"))}


def read_json_reply(response, work, limit=4 * 1024**2):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Model server response exceeds the size limit.")
    reply = json.loads(raw)
    if not isinstance(reply, dict):
        raise TypeError("Model server reply is not a JSON object.")
    return reply, {"usage": _usage(reply.get("usage")), "output_bytes": len(raw), "finish_reason": reply.get("status")}


def request_json(config, path, payload, work=None, manage_loading=True):
    """POST one non-streaming JSON request under /v1 (decision models). Same residency, cancellation,
    error categories and telemetry as request_completion; the caller sets the payload's model and sampling.
    manage_loading=False skips LM Studio residency, for servers that aren't LM Studio (a /v1/systemone server)."""
    from .residency import ensure_loaded  # Imports this module.

    work = work or Work.detached()
    if manage_loading:
        ensure_loaded(config, work)
    return _exchange(config, path, payload, "application/json", read_json_reply, work, "Local model returned an invalid reply.")


def _exchange(config, path, payload, accept, reader, work, invalid_message):
    """One POST to the model server, run on a helper thread. reader(response, work) -> (value, stats).

    On Windows a socket shutdown does not interrupt a receive already blocked during prompt
    processing, but it does abort the connection when the next token arrives, which also stops
    server generation. Cancellation therefore releases the caller immediately.
    """
    remote = is_remote(config)
    body = json.dumps(payload).encode()
    connection, prefix = _connection(config, IDLE_SECONDS)
    state, lock, outcome = {"sock": None, "aborted": False}, threading.Lock(), queue.Queue(maxsize=1)

    def abort():
        with lock:
            state["aborted"] = True
            sock = state["sock"]
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def exchange():
        stats = None
        try:
            connection.connect()
            with lock:
                if state["aborted"]:
                    raise Cancelled()
                state["sock"] = connection.sock  # getresponse() may detach it from the connection.
            connection.request("POST", prefix + path, body, _headers(config, {"Content-Type": "application/json", "Accept": accept}))
            response = connection.getresponse()
            _check_status(response, remote)
            text, stats = reader(response, work)
            outcome.put((text, stats, None))
        except BaseException as exc:
            outcome.put((None, stats, exc))
        finally:
            connection.close()

    started_at, t0 = now(), time.monotonic()
    work.report({"stage": "connecting_or_loading_model", "characters": 0, "elapsed_seconds": 0})
    with work.on_cancel(abort):
        threading.Thread(target=exchange, name="model-request", daemon=True).start()
        while True:
            try:
                text, stats, error = outcome.get(timeout=0.25)
                break
            except queue.Empty:
                if work.cancelled:
                    text, stats, error = None, None, Cancelled()
                    break
    if error is not None and work.cancelled:
        error = Cancelled()
    status, category, mapped = "succeeded", None, error
    if isinstance(error, Cancelled):
        status, category = "cancelled", "cancelled"
    elif isinstance(error, ModelHTTPError):
        status, category = "failed", f"http_{error.status}"
    elif isinstance(error, TimeoutError):
        status, category = "failed", "timeout"
        mapped = ValueError("Local model request timed out after 15 minutes without socket activity. Model loading or generation may be stalled; no partial result was saved.")
    elif isinstance(error, (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError)):
        status, category = "failed", "invalid_stream"
        mapped = ValueError(invalid_message)
    elif isinstance(error, (OSError, http.client.HTTPException)):
        status, category = "failed", "connection"
        mapped = ValueError(REMOTE_OFFLINE + " No partial result was saved." if remote and stats is None else
                            "Local model connection failed or disconnected. Check the server log and loaded model; no partial result was saved.")
    elif error is not None:
        status, category = "failed", "invalid_or_truncated_output"
    metrics = telemetry(config, len(body), started_at, t0, time.monotonic(), stats, status, category)
    work.record(metrics)
    # Recorders always see the raw reply as text.
    seen = text if error is not None or isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    _record_attempt(work, payload, seen if error is None else None, metrics)
    if mapped is not None:
        raise mapped from (error if mapped is not error else None)
    return text


def check_connection(config, limit=50):
    """Ask the model server which models it serves. Sends no document content and loads nothing."""
    t0 = time.monotonic()
    try:
        listing = get_json(config, "/v1/models")
    except ModelHTTPError as exc:
        return {"reachable": True, "model_listed": False, "available_models": [], "latency_ms": None, "problem": str(exc)}
    except (OSError, ValueError, http.client.HTTPException):
        return {"reachable": False, "model_listed": False, "available_models": [], "latency_ms": None,
                "problem": REMOTE_OFFLINE if is_remote(config) else
                f"No local model server answered at {config.base_url}. Start the server and load a model, then test again."}
    latency = round((time.monotonic() - t0) * 1000)
    entries = listing.get("data", []) if isinstance(listing, dict) else []
    ids = sorted({item["id"] for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str)})
    listed = bool(config.model) and config.model in ids
    problem = None if listed else ("Enter the model ID to use." if not config.model else
                                   "The server is running but does not list this model ID. Choose one of the listed models.")
    return {"reachable": True, "model_listed": listed, "available_models": ids[:limit], "latency_ms": latency, "problem": problem}
