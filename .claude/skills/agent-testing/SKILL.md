---
name: agent-testing
description: How an AI agent explores Home Manager's synthetic test instance in a browser and records what it finds. Use when asked to test, explore, QA or look for bugs in the running app with Playwright or playwright-cli, or to record a finding in docs/bugs.md. Covers verify and session.json, the "Test data" marker check, screenshots under the instance's evidence folder, and the finding command, which is the only way to record a finding.
---

# Testing Home Manager as an agent

You test a **synthetic** copy of Home Manager: the agent test instance (docs/development.md "Agent test instance").
It holds made-up data, runs in test mode (real data and the internet are refused), and is the only Home Manager you
may open. The developer's real app on port **8765** is off limits: never open it, screenshot it or record findings
from it.

## Before you start

1. Run `python scripts/test_instance.py verify`. Every check must say PASS (WARN lines are fine). If it fails, stop and
   tell the developer what it printed. Don't run `reset`, `start` or `stop` unless the developer asked you to.
2. Read `tests/.tmp/session.json` (or `<root>/session.json` if the developer gave you another root). Use **only** its
   `base_url` (`http://127.0.0.1:<port>`) and `link` (the base URL with `#token=`). Never type another address,
   never port 8765, and never paste the token anywhere else.
3. Note `seed_date`: the seeded household's dates are relative to it.

## Exploring

- Open the `link` with the `playwright-cli` skill, using the project's config:
  `playwright-cli open --config=.playwright/cli.config.json "<link>"` (Edge, headless). Its output folder,
  `.playwright-cli/`, may hold the token and is gitignored; don't copy from it into files that are tracked.
- **Check the marker before every screenshot and every finding.** `#test-instance-marker` ("Test data", or "Test" on
  the narrow sidebar) must be visible:
  `playwright-cli eval "document.querySelector('#test-instance-marker')?.checkVisibility() === true"` must print
  `true`. If it doesn't, you aren't on the test instance: take no screenshot, delete any you just took, and stop.
- Files to upload are in `<root>/uploads/` (`README.txt` lists them: receipts, statements, a pay stub, a bill, a refund,
  an offer letter, and one receipt that tries a prompt injection). Use only those files.
- Never type a folder or file path outside the instance root into the app (profiles, watched folders, backups,
  restores, sharing). Test mode refuses them anyway; the refusal is expected, not a bug.
- Don't upload documents while the developer's real app is scanning: both share LM Studio. `verify` warns when
  something is listening on 8765.
- Readings by the real models vary. Report states (stuck, failed with no message, wrong screen), not exact values.

## Recording a finding

1. Take the screenshot (after the marker check) and save it under `<root>/evidence/`, for example
   `playwright-cli screenshot --filename=tests/.tmp/evidence/transactions-category.png`.
2. Read the `## Agent findings` section at the end of `docs/bugs.md`. If an entry already describes the same problem
   on the same route, reuse **exactly** its route and symptom text, so the command records "Seen again" instead of a
   duplicate. A repeat on the same day adds nothing.
3. Record it with the finding command, the **only** way to write to `docs/bugs.md`. Never edit that file by hand:

   ```
   python scripts/test_instance.py finding --url "<the page's current URL>" --route "#/transactions"
       --symptom "category select does nothing" --kind bug|friction|console-error --severity low|medium|high
       --steps "1. ... 2. ..." --expected "..." --actual "..." --screenshot tests/.tmp/evidence/<file>.png
       --agent "<your name or session>"
   ```

   - `--url` is the page's current URL (`playwright-cli eval "location.href"`), the page the screenshot shows.
   - Exit 0: recorded (or already recorded today). Exit 2 or 3: refused. The command says why and has deleted the
     screenshot. Fix the cause and take a new screenshot; don't work around the refusal.
4. One finding per problem. Console errors are `--kind console-error`. Keep symptoms short and specific: they are the
   duplicate key together with the route.

## Never

- Open, read, list or type anything under `P:\Finances`, `P:\EvalCorpus` or `%LOCALAPPDATA%\HomeManager`.
- Use port 8765, a `base_url` you didn't read from `session.json`, or any address that isn't `127.0.0.1`.
- Edit `docs/bugs.md` by hand, or change `session.json`, `seed.json` or the instance's `control/` and `library/` folders
  outside the app. Screenshots in `evidence/` are the only files you write there.
