"""Calculation traces: every figure can show how it was worked out (docs/ui.md "Redesign: calculation observability",
"Trace contract").

No parallel explainer. A calculation takes an optional `recorder`; the default (NULL) does nothing, so ordinary calls
cost nothing. `GET /api/traces/{ref}` runs the same function again with a live Recorder and shapes what it recorded:
- steps, in order, each signed into a running value ("+" adds, "−" takes away), plus a rounding adjustment when the
  calculation made one, so the steps visibly add up to the result (`reconciles`);
- inputs: the leaf values with their provenance and verification;
- the rule set it rests on (finance/rules.py), when there is one;
- inputs_hash, and `stale` when the figure was last shown with different inputs (figure_snapshots).

Verification has three states (docs/ui.md): confirmed (a person confirmed it, or it was imported), checked_automatically
(review_source 'automatic') and needs_review. Only needs_review flags a total as unverified.
"""

from datetime import UTC, datetime
import hashlib
import json
from urllib.parse import parse_qsl, urlencode

from .money import money

VERIFICATION = ("confirmed", "checked_automatically", "needs_review")
INPUTS_PAGE = 200  # Inputs listed in one trace; the rest are counted (steps are never paged).


class NullRecorder:
    """Records nothing: the default for every calculation."""
    live = False

    def step(self, *args, **kwargs):
        pass

    def add(self, *args, **kwargs):
        pass

    def input(self, *args, **kwargs):
        pass

    def rule(self, *args, **kwargs):
        pass

    def round(self, *args, **kwargs):
        pass


NULL = NullRecorder()


class Recorder(NullRecorder):
    """Collects one calculation's steps, inputs, rule and rounding as it runs."""
    live = True

    def __init__(self):
        self.steps, self.inputs, self.rule_card, self.rounding = [], [], None, None

    def step(self, label, op, amount_minor, currency, trace=None, count=None):
        """One term of the result: op is "+" or "−" (U+2212); amount is positive as shown."""
        if op not in ("+", "−"):
            raise ValueError("A step adds (+) or takes away (−).")
        self.steps.append({"label": label, "op": op, "minor": amount_minor, "currency": currency, "trace": trace, "count": count})

    def add(self, label, signed_minor, currency, trace=None, count=None):
        """A step from a signed amount: a negative one takes away."""
        self.step(label, "+" if signed_minor >= 0 else "−", abs(signed_minor), currency, trace, count)

    def input(self, key, label, amount_minor, currency, provenance, verification="confirmed", trace=None):
        if verification not in VERIFICATION:
            raise ValueError(f"Unknown verification {verification}.")
        self.inputs.append({"key": key, "label": label, "value": money(amount_minor, currency), "provenance": provenance,
                            "verification": verification, "trace": trace})

    def rule(self, card):
        self.rule_card = card

    def round(self, adjustment_minor, currency, method="half_even_minor", note=""):
        self.rounding = {"method": method, "adjustment": money(adjustment_minor, currency) if adjustment_minor else None, "note": note}

    def only(self, currency):
        """What was recorded for one currency (a calculation that works every currency at once)."""
        kept = Recorder()
        kept.steps = [item for item in self.steps if item["currency"] == currency]
        kept.inputs = [item for item in self.inputs if item["value"]["currency"] == currency]
        kept.rule_card, kept.rounding = self.rule_card, self.rounding
        return kept


def figure(amount_minor, currency, trace=None, verification=None):
    """A figure as the API returns it: the money() views, plus the ref of its trace and its verification state."""
    return {**money(amount_minor, currency), "trace": trace, "verification": verification}


def ref(name, **params):
    """A stable, URL-safe trace ref: the calculation's name and its arguments, sorted ("spending.net?currency=USD&end=…")."""
    shown = {key: value for key, value in sorted(params.items()) if value is not None}
    return name + ("?" + urlencode(shown) if shown else "")


def parse(text):
    """(name, {param: value}) from a ref."""
    name, _, query = text.partition("?")
    return name, dict(parse_qsl(query, keep_blank_values=False))


def verification_of(inputs):
    """The roll-up over a figure's inputs. verified: nothing needs review; partial: some does; unverified: all does."""
    waiting = [item for item in inputs if item["verification"] == "needs_review"]
    automatic = sum(1 for item in inputs if item["verification"] == "checked_automatically")
    state = "verified" if not waiting else "unverified" if len(waiting) == len(inputs) else "partial"
    found = {"state": state, "unverified_count": len(waiting), "checked_automatically_count": automatic, "first": waiting[0]["key"] if waiting else None}
    if waiting:
        currencies = {item["value"]["currency"] for item in waiting}
        if len(currencies) == 1:
            found["unverified_value"] = money(sum(item["value"]["minor"] for item in waiting), currencies.pop())
    return found


def inputs_hash(inputs, result_minor, extra=None):
    """A digest of what the figure was worked out from (each input's key and value), its result, and anything else it
    depends on (extra: e.g. the tax engine's pinned SHA-256, so a changed engine marks the figure stale)."""
    data = json.dumps([[item["key"], item["value"]["minor"], item["value"]["currency"]] for item in inputs] + [result_minor] + ([extra] if extra else []),
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def build(ref_text, label, result_minor, currency, formula, recorder, hash_extra=None):
    """The trace contract from a live recorder. Running values follow the steps; reconciles says whether the steps plus
    any rounding adjustment equal the result (asserted by tests). hash_extra: what else the figure depends on (inputs_hash)."""
    running, steps = 0, []
    for number, item in enumerate(recorder.steps, 1):
        running += item["minor"] if item["op"] == "+" else -item["minor"]
        steps.append({"n": number, "label": item["label"], "op": item["op"], "value": money(item["minor"], item["currency"]),
                      "running": money(running, currency), "trace": item["trace"], "count": item["count"]})
    adjustment = recorder.rounding["adjustment"]["minor"] if recorder.rounding and recorder.rounding["adjustment"] else 0
    ordered = sorted(recorder.inputs, key=lambda item: VERIFICATION.index(item["verification"]), reverse=True)  # Waiting first.
    return {"ref": ref_text, "label": label, "result": money(result_minor, currency), "formula": formula, "steps": steps,
            "rounding": recorder.rounding, "inputs": ordered[:INPUTS_PAGE],
            "inputs_page": {"total": len(ordered), "shown": min(len(ordered), INPUTS_PAGE)},
            "rule": recorder.rule_card, "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "inputs_hash": inputs_hash(recorder.inputs, result_minor, hash_extra), "stale": False,
            "verification": verification_of(recorder.inputs), "reconciles": running + adjustment == result_minor}


def remember(store, trace):
    """Compare with the inputs this figure was last shown with (figure_snapshots), then keep these: stale is True when
    they changed since."""
    with store.connection() as db:
        row = db.execute("SELECT inputs_hash FROM figure_snapshots WHERE ref=?", (trace["ref"],)).fetchone()
        db.execute("INSERT INTO figure_snapshots(ref,inputs_hash,result_minor,currency,computed_at) VALUES(?,?,?,?,?) ON CONFLICT(ref) DO UPDATE SET "
                   "inputs_hash=excluded.inputs_hash,result_minor=excluded.result_minor,currency=excluded.currency,computed_at=excluded.computed_at",
                   (trace["ref"], trace["inputs_hash"], trace["result"]["minor"], trace["result"]["currency"], trace["computed_at"]))
    return {**trace, "stale": bool(row) and row[0] != trace["inputs_hash"], "previous_hash": row[0] if row else None}
