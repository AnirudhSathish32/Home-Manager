"""Hammer the synthetic model server over loopback and report every failure (docs/development.md, "Windows loopback resets").

    .venv\\Scripts\\python.exe scripts\\loopback_stress.py --requests 5000
    .venv\\Scripts\\python.exe scripts\\loopback_stress.py --mode app --requests 20000

--mode raw (default) sends POSTs through model_client's connection class phase by phase and records where each failure
happens (connect, send, status line, body) and after how long: about 19 s means a lost segment, near 0 a reset.
--mode app calls request_completion, the app's real path, including any retry it makes. Synthetic data only.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from home_manager.models import model_client  # noqa: E402
from model_server import ModelServer, start_model_server  # noqa: E402


def raw_request(config, body):
    """One POST, timed per phase. Returns (phase, error or None, seconds)."""
    t0, phase = time.monotonic(), "connect"
    connection, prefix = model_client._connection(config, 60)
    try:
        connection.connect()
        phase = "send"
        connection.request("POST", prefix + "/chat/completions", body, {"Content-Type": "application/json"})
        phase = "status"
        response = connection.getresponse()
        phase = "body"
        response.read()
        return "ok", None, time.monotonic() - t0
    except Exception as exc:  # Every failure is the measurement.
        return phase, exc, time.monotonic() - t0
    finally:
        connection.close()


def app_request(config, body):
    t0 = time.monotonic()
    try:
        model_client.request_completion(config, {"messages": [{"role": "user", "content": body.decode()}]})
        return "ok", None, time.monotonic() - t0
    except Exception as exc:
        cause = exc.__cause__ or exc
        return "app", cause, time.monotonic() - t0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--body-bytes", type=int, default=4000)
    parser.add_argument("--response-bytes", type=int, default=0, help="Size of the model output the server streams back.")
    parser.add_argument("--mode", choices=("raw", "app"), default="raw")
    parser.add_argument("--backlog", type=int, default=ModelServer.request_queue_size)
    args = parser.parse_args()
    ModelServer.request_queue_size = args.backlog
    state, stop = start_model_server()
    state["forget_requests"] = True
    if args.response_bytes:
        state["output"] = {"full_text": "y" * args.response_bytes}
    body = json.dumps({"messages": [{"role": "user", "content": "x" * args.body_bytes}]}).encode()
    send = raw_request if args.mode == "raw" else app_request
    failures, durations, lock, counter = [], [], threading.Lock(), iter(range(args.requests))

    def worker():
        while True:
            with lock:
                index = next(counter, None)
            if index is None:
                return
            phase, error, seconds = send(state["config"], body)
            with lock:
                durations.append(seconds)
                if error is not None:
                    failures.append((index, phase, type(error).__name__, getattr(error, "winerror", None) or getattr(error, "errno", None), round(seconds, 2)))
                    print(f"  failure #{len(failures)} at request {index}: {failures[-1][1:]}", flush=True)
                if (index + 1) % 1000 == 0:
                    print(f"{index + 1} requests, {len(failures)} failures", flush=True)

    started = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(args.threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stop()
    durations.sort()
    print(f"\nmode={args.mode} requests={args.requests} threads={args.threads} body={args.body_bytes} response={args.response_bytes} backlog={args.backlog} "
          f"in {time.monotonic() - started:.0f} s")
    print(f"failures: {len(failures)}  by phase/error: {dict(Counter((f[1], f[2], f[3]) for f in failures))}")
    print(f"latency p50={durations[len(durations) // 2] * 1000:.1f} ms  p99={durations[int(len(durations) * 0.99)] * 1000:.1f} ms  "
          f"max={durations[-1] * 1000:.0f} ms  over 2 s: {sum(1 for d in durations if d > 2)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
