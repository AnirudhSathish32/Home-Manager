"""Profiles on this computer: each person's own library, or a family view over its members.

The registry is <control>/profiles.json. An individual profile names its own library folder (its own
inventory.sqlite3, originals and Inbox). A family profile names a family folder (app/family_sync.py) and
holds no records of its own. Each profile keeps its own financial preferences in
<control>/profiles/<id>/household.json; model settings stay per computer.
"""

import base64
import json
from pathlib import Path
import shutil
import threading
import uuid

from ..core.paths import PathError, path_key, safe_path, write_atomic
from ..finance.ledger import HouseholdConfig
from ..library.storage import now

KINDS = ("individual", "family")
MAX_PROFILES = 50


def clean_name(value, fallback="Profile"):
    name = " ".join(str(value or "").split())[:60]
    return name or fallback


class Profiles:
    def __init__(self, control: Path):
        self.control = control
        self.path = safe_path(control / "profiles.json")
        self.folder = safe_path(control / "profiles")
        self.lock = threading.RLock()
        self.data = {"active": None, "profiles": []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                    self.data = {"active": data.get("active"), "profiles": [item for item in data["profiles"] if isinstance(item, dict) and item.get("id")]}
            except (ValueError, OSError):
                pass  # An unreadable registry starts empty; library folders are never touched.

    def exists(self):
        return self.path.exists()

    def save(self):
        with self.lock:
            self.control.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(self.data, indent=2))

    def all(self):
        with self.lock:
            return [dict(item) for item in self.data["profiles"]]

    def get(self, profile_id):
        with self.lock:
            for item in self.data["profiles"]:
                if item["id"] == profile_id:
                    return item
        raise ValueError("Profile not found.")

    def active(self):
        with self.lock:
            try:
                return self.get(self.data["active"]) if self.data["active"] else None
            except ValueError:
                return None

    def by_folder(self, folder: Path):
        with self.lock:
            return next((item for item in self.data["profiles"] if path_key(item["folder"]) == path_key(folder)), None)

    def add(self, name, kind, folder: Path, **extra):
        if kind not in KINDS:
            raise ValueError("Unknown profile kind.")
        with self.lock:
            if len(self.data["profiles"]) >= MAX_PROFILES:
                raise ValueError(f"Home Manager keeps at most {MAX_PROFILES} profiles on one computer.")
            if self.by_folder(folder):
                raise PathError("Another profile already uses that folder.")
            profile = {"id": uuid.uuid4().hex[:12], "name": clean_name(name), "kind": kind, "folder": str(folder), "created_at": now(), **extra}
            self.data["profiles"].append(profile)
            self.save()
            return profile

    def update(self, profile_id, **changes):
        with self.lock:
            profile = self.get(profile_id)
            for key, value in changes.items():
                if value is None:
                    profile.pop(key, None)
                else:
                    profile[key] = value
            self.save()
            return profile

    def remove(self, profile_id):
        """Forget a profile. Its library folder and records stay on disk."""
        with self.lock:
            profile = self.get(profile_id)
            if self.data["active"] == profile_id:
                raise RuntimeError("Switch to another profile before removing this one.")
            self.data["profiles"].remove(profile)
            self.save()
            shutil.rmtree(self.folder / profile_id, ignore_errors=True)
            return profile

    def set_active(self, profile_id):
        with self.lock:
            self.get(profile_id)
            self.data["active"] = profile_id
            self.save()

    # Per-profile financial preferences ----------------------------------------------

    def household_path(self, profile_id):
        return safe_path(self.folder / profile_id / "household.json")

    def household(self, profile_id):
        path = self.household_path(profile_id)
        try:
            return HouseholdConfig.model_validate_json(path.read_bytes()) if path.exists() else HouseholdConfig()
        except (ValueError, OSError):
            return HouseholdConfig()

    def save_household(self, profile_id, config: HouseholdConfig):
        path = self.household_path(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, config.model_dump_json())


def public(profile):
    """What the interface may show: never the family key."""
    view = {key: profile.get(key) for key in ("id", "name", "kind", "folder", "created_at")}
    link = profile.get("family")
    if link:
        view["family"] = {key: link.get(key) for key in ("family_id", "family_name", "member_id", "sync", "publishing", "published_at",
                                                          "publish_error", "local")}
    return view


def encode_key(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


def decode_key(text) -> bytes:
    try:
        key = base64.b64decode(str(text), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("The family key is invalid.") from exc
    if len(key) != 32:
        raise ValueError("The family key is invalid.")
    return key
