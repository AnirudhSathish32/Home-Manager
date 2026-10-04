# Decision models

A decision model answers typed questions with probabilities instead of text. A yes/no question ("is this claim
supported by its cited line?") returns the probability of yes. A pick-one question ("what kind of document is this?")
returns a probability for every option. These models are also called System One models, after TypeSafe's Jev. The
app uses one for its **independent checks**, and you choose it in Settings like the vision and reasoning models.
Laya, the in-process checkpoint used before, was removed on 2026-10-03.

Code: `src/home_manager/models/decisions.py`. Eval task: `evals/tasks/decisions.py`.

## What it checks

- **Every ledger extraction** (`ExtractionService.assess`):
  - A shadow classification over `DOCUMENT_TYPES`, shown for reference only.
  - A support score for every proposed header value and row, against the lines it cites.
  - A value below `SUPPORT_THRESHOLD` (0.8) sends the record to review with a reason.
- **Audit analyses**, when Independent checks is set to the decision model: the reviewer's provider `decision`, `decision_review`.

The scores are **advisory**. They can send a record to review, but they never approve, reject or file one. A failed
or unreachable decision model never fails an extraction; the error is saved beside the record. The result is saved
under `"decision"` in the extraction result, with the model's provider, ID, calibration temperature and calibrated flag.
The full decision setting is part of the extraction's run options, so changing the model starts a new run instead of
reusing an old one. Extractions saved before 2026-10-03 carry Laya's result under `"laya"`; the inspector still shows it.

## Two providers

| Setting | Server | How probabilities are read |
|---|---|---|
| LM Studio | Any model loaded in LM Studio 0.3.39 or later, at `http://127.0.0.1:PORT/v1` | The options get one-letter labels and the model is asked for one token on `/v1/responses` with `top_logprobs: 20`. LM Studio's `/v1/chat/completions` accepts `logprobs` but returns none. |
| System One server | Any server speaking TypeSafe's `POST /v1/systemone` contract | The server returns the probabilities itself (`noul`, or `probabilities` per option). |

**LM Studio.**
- **Reading the token:** the label's probability is read from the first token's top log-probabilities. Variants of
  one label (`" A"`, `"a"`) are merged, and the result is renormalized over the labels.
- **Coverage:** this is the share of that token's probability that landed on the labels. If it is below 0.5, the
  model didn't answer with a label and the answer is unknown, never guessed.
  - The usual cause is a thinking model whose first token is `<think>`.
  - Use a model that answers directly, or one fine-tuned for decisions (for example Winnow-12B).
- **Requests:** one per question. The state comes first, so LM Studio's prefix cache reuses it across questions.
- **Residency:** decision requests go through the same eject-then-load step as every other model task (`models/residency.py`).

**System One server.**
- Examples:
  - **Kev** (Apache-2.0, Qwen3.5 0.8B–9B and Qwen3.8 27B): `python -m kev.serve --run jaredpalmer/kev-4b --port 8009`,
    then set the URL to `http://127.0.0.1:8009/v1`. Kev ships fitted temperatures. Kev-0.8B needs about 4 GB of
    VRAM and can sit beside LM Studio; Kev-4B needs about 17 GB and has to take turns with it.
  - **Winnow's own llama.cpp-based server**, which also serves chat. In LM Studio, Winnow is used through the LM Studio provider instead.
- **Residency:** the app does not manage this server's loading: it is not LM Studio, so the residency step is skipped.
- **Requests:** each state is one request, with all its questions.

Both providers accept loopback URLs only (`http://127.0.0.1:PORT/v1`). Hosted Jev or any other remote endpoint is refused.
States over 24 KiB are refused, never truncated.

**Test connection** in Settings (`POST /api/decision-model-tests`) asks one fixed yes/no question about a made-up
sentence, never document content. It reports whether the server answers and whether the model replies with an
option letter.

## Family GPU

- **LM Studio provider:** the decision model is shared under the role `home-manager/decision`. The GPU computer's
  owner picks the model in their own `decision.json`. The relay (`models/gpu_host.py`) forwards `/v1/responses` for
  that role only. A queued decision request waits without keep-alive comments, because its reply is one JSON object.
- **System One server:** it is not behind the relay and stays on this PC.

## Calibration

`calibration_temperature` (default 1.0) divides the log-probabilities before they are normalized. `calibrated`
records that it was fitted on this household's documents. Both come from an eval run, never from a guess. Until a
model is calibrated, the review scope and the inspector say so.

To fit the temperature:

1. Add candidates with a `decision` model to `evals/models.toml` (see the commented examples there).
2. Run `python -m evals.tasks --tasks decisions`. The synthetic cases are classification of every synthetic document,
   plus true and planted-wrong claims for the merchant, date and total of every synthetic receipt.
3. The report's decisions section shows, for each candidate:
   - accuracy;
   - expected calibration error;
   - Brier score;
   - the temperature that minimises log loss, with the log loss before and after.
4. Before setting `calibrated`, confirm the result on your own documents (see [private reliability testing](private-reliability-testing.md)).
   Then put the fitted temperature in `decision.json`.

The Settings form keeps the saved calibration values when you save it.
