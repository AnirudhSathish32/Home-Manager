"""Explicit work records: progress, cooperative cancellation and model-run attribution."""

from contextlib import contextmanager
import threading
import uuid

from .storage import now

QUEUES = ("capture", "inference")


class Cancelled(Exception):
    def __init__(self):
        super().__init__("Cancelled by the user. No partial result was published; earlier results remain available.")


class Work:
    """One queued operation. Cancellation is cooperative plus registered abort hooks."""

    def __init__(self, queue, kind, label, sink=None):
        self.id, self.queue, self.kind, self.label = uuid.uuid4().hex, queue, kind, label
        self.status, self.progress, self.created_at, self.started_at = "queued", None, now(), None
        self.sink = sink  # sink(task, owner_id, prompt_version, identity, metrics)
        self.attribution = ("unattributed", None, None, None)
        self.cancel_event = threading.Event()
        self._aborts, self._lock = {}, threading.Lock()

    @classmethod
    def detached(cls):
        return cls("inference", "direct", "Direct model call")

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def check(self):
        if self.cancelled:
            raise Cancelled()

    def report(self, value):
        self.progress = value

    def cancel(self):
        self.cancel_event.set()
        if self.status in ("queued", "running"):
            self.status = "cancel_requested"
        with self._lock:
            aborts = list(self._aborts.values())
        for abort in aborts:
            try:
                abort()
            except Exception:
                pass  # Abort hooks are best effort; cooperative checks still stop the work.

    @contextmanager
    def on_cancel(self, abort):
        """Run abort (e.g. close a socket, kill a child) if cancellation arrives while inside."""
        key = object()
        with self._lock:
            self._aborts[key] = abort
        try:
            if self.cancelled:
                abort()
            yield
        finally:
            with self._lock:
                self._aborts.pop(key, None)

    @contextmanager
    def attribute(self, task, owner_id, prompt_version=None, identity=None):
        previous, self.attribution = self.attribution, (task, owner_id, prompt_version, identity)
        try:
            yield
        finally:
            self.attribution = previous

    def record(self, metrics):
        if self.sink:
            self.sink(*self.attribution, metrics)

    def summary(self):
        return {"id": self.id, "queue": self.queue, "kind": self.kind, "label": self.label, "status": self.status,
                "progress": self.progress, "created_at": self.created_at, "started_at": self.started_at}
