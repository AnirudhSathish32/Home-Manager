"""The family's tax returns (docs/taxes.md): who files together, and one return's records gathered from its members.

A married couple filing jointly is one return: both members' jobs, interest, tags and payments are gathered from their
shared copies (read-only) and added together, and Tax Zen is worked out for the couple. Each person filing on their own
is a return of their own. The family is Tax Zen when every return is.
"""

import json

from ..library.storage import now

STATUSES = ("single", "married_joint", "head_of_household")


class TaxUnits:
    def __init__(self, store):
        self.store = store

    def list(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM tax_units ORDER BY id").fetchall()
        return [{**dict(row), "members": json.loads(row["members_json"])} for row in rows]

    def add(self, name, members, filing_status, known):
        """known: the family's member ids. Joint returns have two members; the others one."""
        if filing_status not in STATUSES:
            raise ValueError("Choose single, married filing jointly or head of household.")
        members = list(dict.fromkeys(members))
        if any(member not in known for member in members):
            raise ValueError("Choose members of this family.")
        if len(members) != (2 if filing_status == "married_joint" else 1):
            raise ValueError("A joint return is two people; any other return is one.")
        taken = {member for unit in self.list() for member in unit["members"]}
        if taken & set(members):
            raise ValueError("Someone is already on another return; remove that one first.")
        name = " ".join((name or "").split()) or " & ".join(known[member] for member in members)
        with self.store.connection() as db:
            unit_id = db.execute("INSERT INTO tax_units(name,members_json,filing_status,created_at,updated_at) VALUES(?,?,?,?,?)",
                                 (name[:60], json.dumps(members), filing_status, now(), now())).lastrowid
        return next(unit for unit in self.list() if unit["id"] == unit_id)

    def delete(self, unit_id):
        with self.store.connection() as db:
            if db.execute("DELETE FROM tax_units WHERE id=?", (unit_id,)).rowcount == 0:
                raise ValueError("Return not found.")
            db.execute("DELETE FROM tax_years WHERE unit=?", (f"unit-{unit_id}",))
        return {"id": unit_id, "deleted": True}


def combine(parts):
    """One return's gathered records from its members': parts = [(member name, tax_year.gather result)]. Amounts add up;
    jobs, businesses and payments are listed with whose they are."""
    values: dict = {}
    sources: dict = {}
    combined = {"values": values, "sources": sources, "jobs": [], "businesses": [], "state": None, "notes": [],
                "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
    for name, gathered in parts:
        for key, amount in gathered["values"].items():
            if isinstance(amount, list):
                values.setdefault(key, []).extend(amount)
            else:
                values[key] = values.get(key, 0) + amount
        for key, text in gathered["sources"].items():
            sources[key] = f"{sources[key]}; {name}: {text}" if key in sources and len(parts) > 1 else (f"{name}: {text}" if len(parts) > 1 else text)
        combined["jobs"] += [{**job, "key": f"{name}:{job['key']}", "name": f"{name} · {job['name']}" if len(parts) > 1 else job["name"], "owner": name}
                             for job in gathered["jobs"]]
        combined["businesses"] += [{**business, "key": f"{name}:{business['key']}", "owner": name} for business in gathered["businesses"]]
        for line, payments in gathered["estimated_payments"].items():
            combined["estimated_payments"][line] += payments
        combined["state"] = combined["state"] or gathered["state"]
        combined["notes"] += [f"{name}: {note}" if len(parts) > 1 else note for note in gathered["notes"]]
    return combined
