"""Tax lots and realized gains (docs/investments.md, phase 5).

Worked out when read, never stored, so they always follow the activity's review: each confirmed buy with a printed quantity
opens a lot (from a purchase confirmation, or a statement's activity when no confirmation records the same buy), and so does
each lot the user enters (shares bought before the documents here begin). Confirmed sales close lots first in, first out.
A sale's cost is each lot's cost in proportion to the shares taken, and its proceeds are split over those lots in proportion
to their shares; the last piece takes the rounding remainder, so every total adds up exactly. A lot held more than a year
gives a long-term gain. Shares sold with no lot to take them from are reported, never guessed.
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation


def shares(text):
    """A printed quantity as an exact positive Decimal, or None."""
    try:
        value = Decimal((text or "").replace(",", "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def share_text(value):
    return f"{value.normalize():f}"


def rounded(value):
    return int(value.to_integral_value(ROUND_HALF_EVEN))


def long_term(acquired, disposed):
    """Held more than one year: sold after the first anniversary (a lot bought on Feb 29 turns one year on Feb 28)."""
    start = date.fromisoformat(acquired)
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:
        anniversary = start.replace(year=start.year + 1, day=28)
    return date.fromisoformat(disposed) > anniversary


def trades(db, account_id, event_type):
    """Confirmed buys or sells with a quantity, one per trade: a statement listing a confirmed trade again adds nothing."""
    found, seen = [], set()
    for row in db.execute("SELECT id,holding_id,event_date,quantity,amount_minor,confirmation_id FROM investment_events WHERE account_id=? AND event_type=? "
                          "AND review_status='verified' AND holding_id IS NOT NULL AND quantity IS NOT NULL "
                          "ORDER BY event_date,confirmation_id IS NULL,id", (account_id, event_type)):
        key = (row["holding_id"], row["event_date"], row["amount_minor"])
        quantity = shares(row["quantity"])
        if key in seen or quantity is None:
            continue
        seen.add(key)
        found.append({**dict(row), "shares": quantity, "source": "confirmation" if row["confirmation_id"] else "statement"})
    return found


def account_lots(db, account_id):
    """Each holding's open lots, its sales matched to lots, and any shares sold that no lot covers: {holding_id: {...}}."""
    lots = {}
    for buy in trades(db, account_id, "buy"):
        lots.setdefault(buy["holding_id"], []).append({"id": None, "event_id": buy["id"], "acquired_date": buy["event_date"], "shares": buy["shares"],
                                                       "cost_minor": buy["amount_minor"], "source": buy["source"]})
    for row in db.execute("SELECT * FROM tax_lots WHERE account_id=?", (account_id,)):
        quantity = shares(row["quantity"])
        if quantity is not None:
            lots.setdefault(row["holding_id"], []).append({"id": row["id"], "event_id": None, "acquired_date": row["acquired_date"], "shares": quantity,
                                                           "cost_minor": row["cost_minor"], "source": "manual"})
    sells = {}
    for sell in trades(db, account_id, "sell"):
        sells.setdefault(sell["holding_id"], []).append(sell)
    result = {}
    for holding_id in set(lots) | set(sells):
        held = sorted(lots.get(holding_id, []), key=lambda lot: (lot["acquired_date"], lot["event_id"] or 0, lot["id"] or 0))
        for lot in held:
            lot["remaining"], lot["cost_remaining"] = lot["shares"], lot["cost_minor"]
        disposals, missing = [], []
        for sell in sells.get(holding_id, []):
            wanted, pieces = sell["shares"], []
            for lot in held:
                if wanted == 0:
                    break
                if lot["remaining"] == 0 or lot["acquired_date"] > sell["event_date"]:
                    continue
                take = min(lot["remaining"], wanted)
                cost = lot["cost_remaining"] if take == lot["remaining"] else rounded(Decimal(lot["cost_remaining"]) * take / lot["remaining"])
                lot["remaining"] -= take
                lot["cost_remaining"] -= cost
                wanted -= take
                pieces.append((lot, take, cost))
            covered = sell["shares"] - wanted
            proceeds = sell["amount_minor"] if wanted == 0 else rounded(Decimal(sell["amount_minor"]) * covered / sell["shares"])
            left = proceeds
            for index, (lot, take, cost) in enumerate(pieces):
                part = left if index == len(pieces) - 1 else rounded(Decimal(proceeds) * take / covered)
                left -= part
                disposals.append({"sell_event_id": sell["id"], "disposed_date": sell["event_date"], "acquired_date": lot["acquired_date"], "shares": share_text(take),
                                  "proceeds_minor": part, "cost_minor": cost, "gain_minor": part - cost,
                                  "term": "long" if long_term(lot["acquired_date"], sell["event_date"]) else "short"})
            if wanted > 0:
                missing.append({"sell_event_id": sell["id"], "date": sell["event_date"], "shares": share_text(wanted)})
        result[holding_id] = {"lots": [{"id": lot["id"], "acquired_date": lot["acquired_date"], "shares": share_text(lot["remaining"]), "cost_minor": lot["cost_remaining"],
                                        "source": lot["source"]} for lot in held if lot["remaining"] > 0],
                              "disposals": disposals, "missing": missing,
                              "open_shares": share_text(sum((lot["remaining"] for lot in held), Decimal(0))),
                              "open_cost_minor": sum(lot["cost_remaining"] for lot in held)}
    return result


def realized(db, account_ids, year):
    """Realized gains in a tax year across accounts: proceeds, cost, and short- and long-term gains, plus shares sold with no lot."""
    total = {"proceeds_minor": 0, "cost_minor": 0, "short_minor": 0, "long_minor": 0, "missing": []}
    for account_id in account_ids:
        for holding_id, found in account_lots(db, account_id).items():
            for sale in found["disposals"]:
                if sale["disposed_date"][:4] != str(year):
                    continue
                total["proceeds_minor"] += sale["proceeds_minor"]
                total["cost_minor"] += sale["cost_minor"]
                total[f"{sale['term']}_minor"] += sale["gain_minor"]
            total["missing"] += [{**gap, "account_id": account_id, "holding_id": holding_id} for gap in found["missing"] if gap["date"][:4] == str(year)]
    return total
