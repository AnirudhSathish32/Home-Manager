"""One generative model resident at a time: eject the others, then load the target.

Every scan runs a vision model and then a reasoning model. With LM Studio's JIT
loading alone, the second model loads while the first is still resident and VRAM
overflows. Before each chat request this asks LM Studio's native REST API (off the
/v1 prefix) what is loaded, unloads every other LLM/VLM and loads the target.
Embedding models are left alone. Only loopback servers are managed: a family GPU
computer owns residency for the requests it relays.
"""

import http.client
import logging
import threading
from urllib.parse import urlsplit

from .model_client import ModelHTTPError, get_json, is_remote, post_json
from .model_stream import IDLE_SECONDS

log = logging.getLogger(__name__)

# The GPU host relay answers its listing with this marker: it manages residency itself.
MANAGED_MARKER = "home-manager-gpu-host"
EMBEDDING_TYPES = {"embedding", "embeddings"}
UNSUPPORTED_HINT = ("This LM Studio cannot load and unload models through its API, so two models may stay loaded at once. "
                    "Update LM Studio, or turn on \"JIT models auto-evict\" in its Developer settings.")

_lock = threading.Lock()  # Process-wide: one residency change at a time, whichever queue asks.
_unsupported = set()  # Loopback servers without the native load/unload API; JIT loading is used as before.
_settings = {"enabled": True}


def configure(enabled):
    _settings["enabled"] = bool(enabled)


def hint():
    """A one-time note for the settings page when a server lacked the load/unload API."""
    return UNSUPPORTED_HINT if _settings["enabled"] and _unsupported else None


def loaded_models(config):
    """[{key, instance_id, type}] for every loaded instance, or None when the native API is missing.

    LM Studio's GET /api/v1/models lists every downloaded model with its loaded instances.
    Parsed defensively: a model's key may be "key" or "id", an instance's id "id" or "instance_id".
    """
    try:
        listing = get_json(config, "/api/v1/models")
    except ModelHTTPError as exc:
        if exc.status in (404, 405, 501):
            return None
        raise
    if not isinstance(listing, dict):
        return None
    if listing.get("managed_by") == MANAGED_MARKER:
        return MANAGED_MARKER
    models = listing.get("models")
    if not isinstance(models, list):
        return None
    loaded = []
    for item in models:
        if not isinstance(item, dict):
            continue
        key = item.get("key") or item.get("id")
        for instance in item.get("loaded_instances") or []:
            if isinstance(instance, dict) and isinstance(key, str):
                loaded.append({"key": key, "instance_id": instance.get("id") or instance.get("instance_id") or key,
                               "type": str(item.get("type") or "llm").lower()})
    return loaded


def ensure_loaded(config, work):
    """Make config.model the only loaded generative model on a loopback server."""
    if not _settings["enabled"] or not config.model or is_remote(config):
        return
    server = urlsplit(config.base_url).netloc
    with _lock:
        if server in _unsupported:
            return
        try:
            loaded = loaded_models(config)  # One cheap GET per request: the user may change models in LM Studio by hand.
        except (OSError, ValueError, http.client.HTTPException):
            return  # The chat request reports an unreachable server in the usual words.
        if loaded == MANAGED_MARKER:
            return
        if loaded is None:
            log.warning("Model server %s has no load/unload API; relying on JIT loading.", server)
            _unsupported.add(server)
            return
        generative = [item for item in loaded if item["type"] not in EMBEDDING_TYPES]
        if [item["key"] for item in generative] == [config.model]:
            return
        try:
            for item in generative:
                if item["key"] != config.model:
                    work.check()
                    work.report({"stage": "unloading_model", "characters": 0, "elapsed_seconds": 0})
                    post_json(config, "/api/v1/models/unload", {"instance_id": item["instance_id"]})
            if not any(item["key"] == config.model for item in generative):
                work.check()
                work.report({"stage": "loading_model", "characters": 0, "elapsed_seconds": 0})
                post_json(config, "/api/v1/models/load", {"model": config.model}, timeout=IDLE_SECONDS)
        except (OSError, http.client.HTTPException) as exc:
            raise ValueError("The model server stopped responding while switching models. Check LM Studio, then try again.") from exc
