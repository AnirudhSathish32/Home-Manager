"""Who is making a change (docs/ui.md "Redesign: calculation observability", "Who").

The person chosen in the who's-here picker arrives on each request as the X-HM-Actor header. The API checks it against
the profile's people and holds it here for that request, so every writer (corrections, review events, tax input
changes, budget changes, manual entries) can store it without the value being passed through every call. Outside a
request, or when nobody was chosen, it is None: the change is stored with no person, never with a guessed one.
"""

from contextlib import contextmanager
from contextvars import ContextVar

HEADER = "X-HM-Actor"
MAX_LENGTH = 80

_current: ContextVar[str | None] = ContextVar("actor", default=None)


def current():
    """The person making the change in this request, or None."""
    return _current.get()


@contextmanager
def acting_as(person):
    """Hold `person` (already checked) as the actor until the block ends."""
    token = _current.set(person)
    try:
        yield
    finally:
        _current.reset(token)


def checked(value, people):
    """The header's value when it names one of `people` (case and spacing as listed), None when absent; ValueError
    otherwise, so an unknown name is refused instead of stored."""
    text = " ".join((value or "").split())
    if not text:
        return None
    if len(text) > MAX_LENGTH:
        raise ValueError("The person's name is too long.")
    for person in people:
        if person.casefold() == text.casefold():
            return person
    raise ValueError(f"{text} isn't one of this profile's people. Choose who's here again.")
