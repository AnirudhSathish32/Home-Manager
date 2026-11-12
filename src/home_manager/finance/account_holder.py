"""Who a bill's account holder is, and what its Person column shows (docs/money.md "Bills and their lines"; specs/bill-total-and-account-holder FR-137, FR-138).

A bill's account holder is the name its account-name line prints (documents/extraction.py `account_holder`). It is matched to a person only when the
record is shown, against the people the open profile knows, so renaming a profile or a family member changes what is shown with no re-read and the
profile's name is never written into the library. A match is display only: a name never sets a line's member (FR-140).
"""

import re
import unicodedata

TITLES = frozenset(("mr", "mrs", "ms", "mx", "dr"))
SUFFIXES = frozenset(("jr", "sr", "ii", "iii", "iv"))
JOINT = re.compile(r"[&/+]|\band\b")
NOT_A_NAME = "my profile"  # A profile nobody has named yet.
TRAILING_NUMBER = re.compile(r"[\d()\-\s]+$")  # A phone line's number after the name on a bill line's holder (`Alex 555-201-1111`).

SOURCES = {"member": "Set for this line", "line": "Printed for this line", "account": "Account name on the bill", "shared": "Nobody is named on this line"}


def words_of(name):
    """A printed name as comparable words (FR-137): NFKC, accents removed, case ignored, `Last, First` read as `First Last`, titles and suffixes dropped,
    other punctuation removed. [] for a name containing no letter or naming two people (`&`, `and`, `/`, `+`)."""
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char)).casefold()
    if JOINT.search(text) or not re.search(r"[^\W\d_]", text):
        return []
    if text.count(",") == 1:
        last, first = (part.strip() for part in text.split(","))
        text = f"{first} {last}" if first and last else text
    text = re.sub(r"[^\w\s]|_", "", text.replace("-", " "))  # A hyphen separates words (Mary-Jane); any other punctuation goes (O'Brien, J.).
    return [word for word in text.split() if word not in TITLES and word not in SUFFIXES]


def names_match(printed, known):
    """Whether two names are one person's (FR-137): both of two or more words with equal first and last words and any middle word both have in the same
    place equal or the other's initial; or one is a single word equal to the other's first word. A first-name initial never matches."""
    one, two = words_of(printed), words_of(known)
    if not one or not two or len(one[0]) < 2 or len(two[0]) < 2 or NOT_A_NAME in (" ".join(one), " ".join(two)):
        return False
    if len(one) == 1 or len(two) == 1:
        return one[0] == two[0]
    if one[0] != two[0] or one[-1] != two[-1]:
        return False
    return all(a == b or len(a) == 1 and b.startswith(a) or len(b) == 1 and a.startswith(b) for a, b in zip(one[1:-1], two[1:-1]))


def person_of(printed, people):
    """The one of `people` (dicts with a "name"; "you" for the profile's owner) a printed name is, else None: none or several matching is no match."""
    found = [person for person in people if names_match(printed, person["name"])]
    return found[0] if len(found) == 1 else None


def holder_of(details):
    """The account holder's printed text from a bill's details, or None (a cleared or never-read one)."""
    text = " ".join(str((details or {}).get("account_holder", {}).get("text") or "").split())
    return text or None


def annotate(record, people):
    """Add what the page shows to a bill read from its printed lines (FR-138, FR-139): `account_holder_view` ({text, display, you, name, locator} or None)
    and each line's `person` ({text, source, title}). people: [{"name", "you"?, "member_id"?}], the open profile's people (Manager.account_people)."""
    if record.get("document_kind") != "bill" or record.get("items") is None:
        return record
    details = record.get("details") or {}
    printed = holder_of(details)
    match = person_of(printed, people) if printed else None
    shown = (match["name"] if match else printed) or None
    record["account_holder_view"] = ({"text": printed, "display": f"{printed} (you)" if match and match.get("you") else f"{printed} ({match['name']})" if match else printed,
                                      "name": match["name"] if match else None, "you": bool(match and match.get("you")),
                                      "locator": (details.get("account_holder") or {}).get("locator")} if printed else None)
    by_line = bool((record.get("share") or {}).get("member_id"))  # A bill shared by line: a line nobody is named on is shared out, so it says Shared (FR-138).
    names = {person["member_id"]: person["name"] for person in people if person.get("member_id")}
    for item in record["items"]:
        holder = " ".join((item.get("line_holder") or "").split())
        if item.get("member_id"):
            text, source = names.get(item["member_id"], "Someone in the family"), "member"
        elif holder:
            known = person_of(re.sub(r"\d", "", holder), people)
            text, source = (known["name"] if known else TRAILING_NUMBER.sub("", holder) or "—"), "line"
        elif shown and not by_line:
            text, source = shown, "account"
        else:
            text, source = "Shared", "shared"
        item["person"] = {"text": text, "source": source, "title": SOURCES[source]}
    return record
