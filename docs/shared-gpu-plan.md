# Plan: Family members use my GPU, and LM Studio ejects the old model before loading a new one

Status: built 2026-09-28 (Parts A–C). Companion plan: `docs/profiles-and-family-plan.md`.

## As built
- **Residency** (`models/residency.py`) parses `GET /api/v1/models` as `{"models": [{"key", "type", "loaded_instances": [{"id"}]}]}`,
  tolerating `id`/`instance_id` variants. Unload is `POST /api/v1/models/unload {instance_id}`, load is `POST /api/v1/models/load {model}`.
  **Confirmed 2026-10-03** against the installed LM Studio (`lms` CLI commit 69d945a): `ensure_loaded` swapped qwen/qwen3-vl-8b →
  gemma-3-12b-it → qwen/qwen3-vl-8b with exactly one model loaded after each step (loads 6–11 s, no out-of-memory error).
  Real replies: load → `{"type": "llm", "instance_id": KEY, "load_time_seconds": N, "status": "loaded"}`; unload → `{"instance_id": KEY}`;
  a loaded instance is `{"id": KEY, "config": {"context_length": 8192, ...}}`, so the instance ID equals the model key.
  `GET /api/v0/models/KEY` gives `arch`, `quantization` (e.g. `Q4_K_M`), `max_context_length` and `loaded_context_length`.
  Note: a model loaded by key gets LM Studio's default context (8192 here), not its maximum. There is no `/api/v0` fallback,
  because v0 cannot unload. A 404 means JIT loading plus a Settings hint about "JIT models auto-evict".
- **Setting** "Keep one model loaded at a time" lives on the new *Model computer* setting (`model_computer.json`), not on each
  model config. Model configs are copied into run options, so adding fields there would change every saved run's options.
- **Client:** `ModelComputer` (`provider`, `gpu_host_url`, `manage_model_loading`) is in `models/vision.py`. The token is in
  `gpu_token.txt` in the control dir and is registered with `model_client.set_token`; it is never part of a config, run option or API response.
  In family-GPU mode the manager points vision/reasoning/reviewer(chat) at the host under role aliases. This PC's own settings stay saved.
  The vision/reasoning settings forms still accept loopback only. `VisionConfig` also accepts a tailnet URL, so saved run options can be re-read.
- **Relay** (`models/gpu_host.py`) is stdlib `ThreadingHTTPServer`, with two listeners on one port: the Tailscale IP (token required) and
  127.0.0.1 (no token, any model). Roles are read from the host's own `vision.json`/`reasoning.json`/`reviewer.json` on each request.
  The relay answers `GET /api/v1/models` with a `managed_by` marker, so an app pointed at it skips its own residency calls.
  Loopback-only `GET /status` shows who is running and queued.
- **Commands:** `home-manager gpu-host [serve --bind 100.x.y.z]`, `gpu-host add-member NAME`, `gpu-host remove-member NAME`, `gpu-host members`.

Decisions already made:
- Each family member runs the app on their own PC.
- They reach the GPU PC over **Tailscale**.
- Only **model calls** leave a member's machine: rendered page images and text prompts. Documents and databases stay local.

## Context
- `models/model_client.py` is the only LM Studio transport.
  - It sends `model=<id>` to `/v1/chat/completions` and relies on LM Studio's JIT loading.
  - It never checks what is loaded and never unloads anything. `docs/financial-reasoning.md` said then that this was deliberate (that paragraph now describes the residency built by this plan).
- **Why two models end up loaded:** every inbox scan runs vision (`self.vision.model`), then reasoning (`reasoning_config.model`) (`manager.py:315-347`). The reviewer can be a third model. LM Studio therefore loads the second model while the first is still resident, which overflows VRAM.
- **Remote access is blocked today:** `VisionConfig` (`models/vision.py:27-29`) accepts only `http://127.0.0.1:PORT/v1`, enforced by `tests/test_vision_batch.py:16`.
- **Family members have no GPU.** They should be able to send their model calls to my PC over Tailscale while their documents and database stay on their machine.

## Part A: Model residency (eject, then load)
- New `models/residency.py`, using LM Studio's native REST API. It is off the `/v1` prefix; `get_json` already takes absolute paths.
  - `loaded_models(config)` → `GET /api/v1/models`, read the loaded instances. Fall back to `GET /api/v0/models` and filter `state == "loaded"`.
  - `ensure_loaded(config, work)`:
    - If the target is the only model loaded, do nothing.
    - Otherwise `POST /api/v1/models/unload {instance_id}` for every other loaded LLM/VLM, skipping embedding models, then `POST /api/v1/models/load {model}`.
    - Report progress stages `"unloading_model"` and `"loading_model"` through `work.report`.
  - A process-wide `threading.Lock` plus a "last ensured" cache. The cache is revalidated with one cheap GET per request, since the user may change models in LM Studio by hand.
  - **Fallback when the native endpoints are missing** (older LM Studio): log a warning and use JIT as today, with a one-time UI hint to enable LM Studio's "JIT auto-evict".
- **Hook:** call `ensure_loaded` at the top of `request_completion` (`model_client.py:154`), before the POST. It is the single choke point for all tasks.
  - This works because the inference queue is already single-worker (`ThreadPoolExecutor(max_workers=1)`, `manager.py:74`).
- **Setting:** `manage_model_loading: bool = True` on `VisionConfig`/`ReasoningConfig`, with a checkbox in the model settings form (`index.html:450-466`).
- Update the comment on `check_connection` and `docs/financial-reasoning.md:21` to match.
- Implementation must first confirm the endpoint shapes against the installed LM Studio version:
  - `GET /api/v1/models` on the user's server. This only lists models and loads nothing.
  - The user runs it and pastes the output, or I run it against their local LM Studio with permission.

## Part B: GPU host relay over Tailscale
- New `models/gpu_host.py` plus a CLI entry `home-manager gpu-host`.
  - It is a small separate process, independent of the main app, so it can run as a Windows startup task.
  - It is built on the same stdlib/uvicorn stack as the app.
- **Listens** on my Tailscale IP (100.64.0.0/10) at port 8766. It refuses to bind to any other interface.
- **Allowed endpoints:** only `GET /v1/models` (filtered to allowed models), `GET /api/v0/models/{id}` (needed by `model_identity`) and `POST /v1/chat/completions` (streamed straight through to local LM Studio at `127.0.0.1:1234`).
- **Auth:** a per-member bearer token.
  - `gpu-host add-member <name>` prints a token and stores only its SHA-256.
  - Tailscale already provides WireGuard encryption and device identity. The token adds revocation per person.
- **Role aliases:** members ask for `home-manager/vision` or `home-manager/reasoning`, and the host maps those to my configured model IDs. Family members never need to know or choose model names, and I can change models centrally.
- **Queue and residency:**
  - One FIFO single-flight queue across all clients, including my own app.
  - `ensure_loaded` from Part A runs before forwarding.
  - Requests are grouped by model when several are waiting, to minimise swaps: waiting requests for the already-loaded model go first, with a cap so nothing starves.
  - While queued, the relay sends SSE comment keepalives (`: queued 2`). `model_stream.read_completion` already ignores non-`data:` lines (`model_stream.py:78`), and the keepalives keep the 900 s idle timer alive.
- **My own app on the GPU PC** points its base URL at the relay via loopback (no token needed on loopback), so family requests and my own requests share one queue and one residency manager.
- **Privacy:**
  - The relay never logs or stores request or response bodies.
  - It logs only member, model role, token counts and duration.
  - It shows a small status list: "Mom — reasoning — 00:42".
  - Payloads are already only rendered PNGs and text, since originals and databases never leave the member's PC (`vision.py:57,73`).

## Part C: Client side (family members' app)
- `VisionConfig` gains `provider: "local" | "family_gpu"`, `gpu_host_url` and `gpu_token` (the token is stored in the control dir, never returned by the settings API).
  - **Validator:** `local` keeps the loopback-only rule.
  - `family_gpu` allows `http://<100.64.0.0/10 IP or *.ts.net host>:PORT/v1` and nothing else.
  - The loopback test stays and gains a tailnet-accepted/public-rejected test.
- `model_client._connection` and `request_completion` add the `Authorization: Bearer` header for `family_gpu`.
  - `server_error` 401/403 text gets a "Your family GPU token was rejected — ask <host> for a new one" variant.
  - Connection failures read "The family GPU computer is offline or not on Tailscale."
- **Settings UI:** "Model computer: This PC / Family GPU (Tailscale)", with URL + token fields. The existing "Test connection" button (`processing.js:83-90`) works unchanged through `/v1/models`.
- **Residency on clients:** `ensure_loaded` is skipped for `family_gpu`; the host owns residency.
- ~~Laya keeps running in-process on CPU as today (`laya_runtime.py`).~~ Superseded 2026-10-03: Laya was removed. An LM Studio
  [decision model](decision-models.md) is shared as the `home-manager/decision` role, and the relay forwards `/v1/responses` for that role only.

## Critical files
- new `models/residency.py`, `models/gpu_host.py`
- `models/model_client.py`: residency hook, auth header, error text
- `models/vision.py`, `documents/reasoning.py`, `documents/reviewer.py`: provider fields and validator
- `__main__.py`: `gpu-host` subcommand
- `app/static/index.html`, `app.js`, `processing.js`: settings
- `docs/financial-reasoning.md`, `docs/architecture.md`
- `tests/conftest.py`: fake server gains `/api/v1/models`, load and unload, plus a tracked `loaded` set

## Verification
- **Residency tests** with the fake server:
  - It loads when nothing is loaded.
  - It does nothing when the target is already loaded.
  - It unloads a different model before loading.
  - It skips embedding models.
  - It falls back cleanly when `/api/v1` returns 404.
  - A vision → reasoning scan produces the exact call order unload → load → chat.
- **Relay tests:**
  - It rejects a missing or bad token.
  - It refuses non-tailnet binds.
  - It only allows the listed endpoints.
  - Two concurrent clients are serialised.
  - Keepalives are ignored by `read_completion`.
  - Aliases map correctly.
  - No request body appears in the logs.
- **Manual check:**
  - Run `gpu-host` on my PC, point a second control dir (or a family laptop on Tailscale) at it.
  - Scan a synthetic receipt, and watch LM Studio show only one model loaded at a time.
- Run only the touched tests: `test_vision_batch.py`, `test_jobs.py`, new `test_residency.py` and `test_gpu_host.py`.
