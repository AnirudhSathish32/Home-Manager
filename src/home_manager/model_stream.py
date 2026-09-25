"""Bounded Chat Completions SSE reader; partial output is never published."""

import json
import time

IDLE_SECONDS = 900
MAX_SECONDS = 7200
MAX_WIRE_BYTES = 16 * 1024**2
MAX_TEXT_BYTES = 4 * 1024**2


def read_completion(response, work, clock=time.monotonic):
    """Return (text, stats). stats carries first-token time and any server usage/timings."""
    started = clock()
    last_report = started - 2
    chunks, wire_bytes, text_bytes = [], 0, 0
    stats = {"first_token": None, "finish_reason": None, "usage": None, "timings": None, "output_bytes": 0}
    event_lines = []

    def consume():
        nonlocal text_bytes, last_report
        if not event_lines:
            return False
        data = "\n".join(event_lines)
        event_lines.clear()
        if data == "[DONE]":
            if stats["finish_reason"] != "stop":
                raise ValueError("Model response was incomplete or truncated; no extraction was published.")
            return True
        event = json.loads(data)
        if event.get("error"):
            raise ValueError("Model server reported an error during generation. Check its log; partial output was not saved.")
        # Usage/timing metadata is untrusted and only ever used for telemetry.
        for key in ("usage", "timings"):
            if isinstance(event.get(key), dict):
                stats[key] = event[key]
        for choice in event.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            text = (choice.get("delta") or {}).get("content") or ""
            if not isinstance(text, str):
                raise ValueError("Invalid streamed model content.")
            if text and stats["first_token"] is None:
                stats["first_token"] = clock()
            text_bytes += len(text.encode("utf-8"))
            if text_bytes > MAX_TEXT_BYTES:
                raise ValueError("Model response exceeded the size limit.")
            chunks.append(text)
            if choice.get("finish_reason") is not None:
                stats["finish_reason"] = choice["finish_reason"]
        current = clock()
        if current - last_report >= 1:
            work.report({"stage": "generating", "characters": sum(map(len, chunks)), "elapsed_seconds": int(current - started)})
            last_report = current
        return False

    work.report({"stage": "waiting_for_tokens", "characters": 0, "elapsed_seconds": 0})
    if "text/event-stream" not in (response.getheader("Content-Type") or "").lower():
        raise ValueError("Model server did not return an event stream. Enable streaming support; no partial result was saved.")
    while True:
        work.check()
        if clock() - started > MAX_SECONDS:
            raise ValueError("Model generation exceeded the two-hour limit. Use a smaller model or shorter document; no partial result was saved.")
        line = response.readline(65537)
        if len(line) > 65536:
            raise ValueError("Model stream event line exceeded the size limit.")
        wire_bytes += len(line)
        if wire_bytes > MAX_WIRE_BYTES:
            raise ValueError("Model stream exceeded the size limit.")
        if not line:
            # Require the explicit completion marker, not merely syntactically valid partial JSON.
            raise ValueError("Model stream disconnected before completion. No partial result was saved.")
        if line in (b"\n", b"\r\n"):
            if consume():
                stats["output_bytes"] = text_bytes
                work.report({"stage": "validating", "characters": sum(map(len, chunks)), "elapsed_seconds": int(clock() - started)})
                return "".join(chunks), stats
        elif line.startswith(b"data:"):
            event_lines.append(line[5:].decode("utf-8").strip())
