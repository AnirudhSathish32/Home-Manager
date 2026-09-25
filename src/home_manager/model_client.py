"""Loopback model transport: cancellation, inference telemetry and model identity.

http.client never consults proxy settings and never follows redirects, so neither
can be inherited or triggered by a document. Endpoints are validated loopback URLs.
"""

import hashlib
import http.client
import json
import queue
import socket
import threading
import time
from urllib.parse import quote, urlsplit

from .jobs import Cancelled, Work
from .model_stream import IDLE_SECONDS, read_completion
from .storage import now

# Listing fields that change without the model bytes changing.
VOLATILE_METADATA = {"created", "object", "state", "loaded_context_length"}


class ModelHTTPError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def server_error(status, body: bytes):
    # Inspect only for known diagnostic categories. Server bodies can echo receipt
    # contents, paths or prompts, so never persist or display the raw error body.
    body = body.decode("utf-8", errors="replace").lower()
    prefix = f"Local model server returned HTTP {status}. "
    if status in (401, 403):
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
    url = urlsplit(config.base_url)  # Already validated as http://127.0.0.1:PORT/v1.
    return http.client.HTTPConnection(url.hostname, url.port, timeout=timeout), url.path


def _check_status(response):
    if 300 <= response.status < 400:
        raise ModelHTTPError(response.status, "Model server redirects are not permitted.")
    if response.status != 200:
        raise ModelHTTPError(response.status, server_error(response.status, response.read(65536)))


def get_json(config, path, timeout=5, limit=1024**2):
    connection, _ = _connection(config, timeout)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        _check_status(response)
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Model server response exceeds the size limit.")
        return json.loads(raw)
    finally:
        connection.close()


def post_json(config, path, payload, timeout=60, limit=65536):
    connection, prefix = _connection(config, timeout)
    try:
        connection.request("POST", prefix + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        response = connection.getresponse()
        _check_status(response)
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


def request_completion(config, payload, work=None):
    """Stream one chat completion. Cancellation releases the caller immediately.

    The HTTP exchange runs on a helper thread: on Windows a socket shutdown does not
    interrupt a receive already blocked during prompt processing, but it does abort
    the connection when the next token arrives, which also stops server generation.
    """
    work = work or Work.detached()
    payload.update(model=config.model, stream=True, temperature=0.1, stream_options={"include_usage": True})
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
            connection.request("POST", prefix + "/chat/completions", body,
                               {"Content-Type": "application/json", "Accept": "text/event-stream"})
            response = connection.getresponse()
            _check_status(response)
            text, stats = read_completion(response, work)
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
        mapped = ValueError("Local model returned an invalid completion stream.")
    elif isinstance(error, (OSError, http.client.HTTPException)):
        status, category = "failed", "connection"
        mapped = ValueError("Local model connection failed or disconnected. Check the server log and loaded model; no partial result was saved.")
    elif error is not None:
        status, category = "failed", "invalid_or_truncated_output"
    work.record(telemetry(config, len(body), started_at, t0, time.monotonic(), stats, status, category))
    if mapped is not None:
        raise mapped from (error if mapped is not error else None)
    return text


def check_connection(config, limit=50):
    """Ask the loopback server which models it serves. Sends no document content and loads nothing."""
    t0 = time.monotonic()
    try:
        listing = get_json(config, "/v1/models")
    except ModelHTTPError as exc:
        return {"reachable": True, "model_listed": False, "available_models": [], "latency_ms": None, "problem": str(exc)}
    except (OSError, ValueError, http.client.HTTPException):
        return {"reachable": False, "model_listed": False, "available_models": [], "latency_ms": None,
                "problem": f"No local model server answered at {config.base_url}. Start the server and load a model, then test again."}
    latency = round((time.monotonic() - t0) * 1000)
    entries = listing.get("data", []) if isinstance(listing, dict) else []
    ids = sorted({item["id"] for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str)})
    listed = bool(config.model) and config.model in ids
    problem = None if listed else ("Enter the model ID to use." if not config.model else
                                   "The server is running but does not list this model ID. Choose one of the listed models.")
    return {"reachable": True, "model_listed": listed, "available_models": ids[:limit], "latency_ms": latency, "problem": problem}
