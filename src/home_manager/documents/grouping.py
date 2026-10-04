"""Several images that are one document (docs/documents.md, "Several images as one document").

Suggestions are deterministic and never applied on their own: images captured together from the same folder whose
names continue one series (IMG_0012, IMG_0013; scan (1), scan (2); receipt_p1, receipt_p2) and whose files were
saved within two minutes of each other. The user confirms or dismisses a suggestion, or combines images directly.
A confirmed group reads as one multi-page document under its first page (the lead); its other pages are hidden.
"""

import re

from ..core.formats import IMAGES, extension
from ..library.storage import now

MAX_PAGES = 20
NEAR_NS = 120 * 10**9  # Files saved within two minutes of each other.
# A name's series and its number: "IMG_0012", "scan (2)", "receipt_p2", "page-3".
SERIES = re.compile(r"^(?P<stem>.*?)(?P<number>\d+)\)?$")


def series(relative_path):
    """(folder, stem, number) of a file name in a numbered series, or None."""
    folder, _, name = relative_path.replace("\\", "/").rpartition("/")
    match = SERIES.match(name.rsplit(".", 1)[0])
    return (folder, match["stem"].lower(), int(match["number"])) if match else None


class Groups:
    def __init__(self, store):
        self.store = store

    # Reading ------------------------------------------------------------------

    def get(self, group_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM document_groups WHERE id=?", (group_id,)).fetchone()
            if row is None:
                raise ValueError("Combined document not found.")
            group = dict(row)
            group["pages"] = [dict(page) for page in db.execute(
                "SELECT p.page_no,p.occurrence_id AS document_id,o.relative_path,o.current_hash,o.deleted_at FROM document_group_pages p "
                "JOIN occurrences o ON o.id=p.occurrence_id WHERE p.group_id=? ORDER BY p.page_no", (group_id,))]
        return group

    def of(self, document_id, statuses=("proposed", "confirmed")):
        """The active group a document belongs to, or None."""
        with self.store.connection() as db:
            row = db.execute(f"SELECT g.id FROM document_groups g JOIN document_group_pages p ON p.group_id=g.id WHERE p.occurrence_id=? "
                             f"AND g.status IN ({','.join('?' * len(statuses))}) ORDER BY g.status='confirmed' DESC, g.id DESC LIMIT 1",
                             (document_id, *statuses)).fetchone()
        return self.get(row["id"]) if row else None

    def proposed(self, limit=50):
        with self.store.connection() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM document_groups WHERE status='proposed' ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [self.get(group_id) for group_id in ids]

    def pages(self, document_id):
        """The preserved hashes of a confirmed group's pages in order, when document_id is its lead; else None."""
        group = self.of(document_id, ("confirmed",))
        if not group or group["pages"][0]["document_id"] != document_id:
            return None
        return [page["current_hash"] for page in group["pages"]]

    # Suggesting ----------------------------------------------------------------

    def suggest(self, job):
        """Propose groups among the images this capture job brought in. Returns the new groups' ids."""
        with self.store.connection() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT o.id,o.relative_path,o.source_root,v.source_mtime_ns FROM occurrences o JOIN versions v ON v.occurrence_id=o.id AND v.hash=o.current_hash "
                "WHERE o.deleted_at IS NULL AND EXISTS(SELECT 1 FROM events e WHERE e.job_id=? AND e.relative_path=o.relative_path AND e.hash=o.current_hash "
                "AND e.status IN ('captured','new_version')) AND NOT EXISTS(SELECT 1 FROM document_group_pages p JOIN document_groups g ON g.id=p.group_id "
                "WHERE p.occurrence_id=o.id) AND NOT EXISTS(SELECT 1 FROM receipts r WHERE r.blob_hash=o.current_hash AND r.review_source='user')", (job,))]
        candidates = sorted(((row["source_root"], *named, row) for row in rows if extension(row["relative_path"]) in IMAGES
                             for named in [series(row["relative_path"])] if named), key=lambda item: item[:4])
        runs, created = [], []
        for root, folder, stem, number, row in candidates:
            last = runs[-1][-1] if runs else None
            if last and (last[0], last[1], last[2]) == (root, folder, stem) and number == last[3] + 1 \
                    and abs((row["source_mtime_ns"] or 0) - (last[4]["source_mtime_ns"] or 0)) <= NEAR_NS and len(runs[-1]) < MAX_PAGES:
                runs[-1].append((root, folder, stem, number, row))
            else:
                runs.append([(root, folder, stem, number, row)])
        for run in runs:
            if len(run) > 1:
                created.append(self.create([item[4]["id"] for item in run], "proposed",
                                           "Numbered in one series and saved within two minutes of each other."))
        return created

    # Changing ------------------------------------------------------------------

    def create(self, document_ids, status="confirmed", reason="Combined by you."):
        """A group of these images, pages in the order given."""
        self.check(document_ids)
        with self.store.connection() as db:
            cursor = db.execute("INSERT INTO document_groups(status,reason,created_at,updated_at) VALUES(?,?,?,?)", (status, reason, now(), now()))
            db.executemany("INSERT INTO document_group_pages(group_id,occurrence_id,page_no) VALUES(?,?,?)",
                           [(cursor.lastrowid, document_id, page) for page, document_id in enumerate(document_ids, 1)])
            if status == "confirmed":  # A document joins one group at a time: other suggestions for it are dropped.
                self.drop_other_suggestions(db, cursor.lastrowid, document_ids)
        return cursor.lastrowid

    def check(self, document_ids, group_id=None):
        if not 2 <= len(document_ids) <= MAX_PAGES or len(set(document_ids)) != len(document_ids):
            raise ValueError(f"Choose 2 to {MAX_PAGES} different images to combine.")
        with self.store.connection() as db:
            for document_id in document_ids:
                doc = db.execute("SELECT relative_path,deleted_at FROM occurrences WHERE id=?", (document_id,)).fetchone()
                if doc is None or doc["deleted_at"]:
                    raise ValueError("One of the chosen documents is missing or in Trash.")
                if extension(doc["relative_path"]) not in IMAGES:
                    raise ValueError("Only PNG and JPEG images can be combined into one document. A PDF already has pages.")
                if db.execute("SELECT 1 FROM document_group_pages p JOIN document_groups g ON g.id=p.group_id WHERE p.occurrence_id=? "
                              "AND g.status='confirmed' AND g.id IS NOT ?", (document_id, group_id)).fetchone():
                    raise ValueError("One of the chosen images is already part of a combined document. Separate it first.")

    @staticmethod
    def drop_other_suggestions(db, group_id, document_ids):
        marks = ",".join("?" * len(document_ids))
        db.execute(f"UPDATE document_groups SET status='dismissed',updated_at=? WHERE status='proposed' AND id<>? AND id IN "
                   f"(SELECT group_id FROM document_group_pages WHERE occurrence_id IN ({marks}))", (now(), group_id, *document_ids))

    def set_status(self, group_id, status):
        """Confirm a suggestion, or dismiss a suggestion or a confirmed group (its images become separate documents again)."""
        group = self.get(group_id)
        if status not in ("confirmed", "dismissed") or group["status"] == "dismissed" or (status == "confirmed" and group["status"] == "confirmed"):
            raise ValueError("That change does not apply to this combined document.")
        if status == "confirmed":
            self.check([page["document_id"] for page in group["pages"]], group_id)
        with self.store.connection() as db:
            db.execute("UPDATE document_groups SET status=?,updated_at=? WHERE id=?", (status, now(), group_id))
            if status == "confirmed":
                self.drop_other_suggestions(db, group_id, [page["document_id"] for page in group["pages"]])
        return self.get(group_id)

    def reorder(self, group_id, document_ids):
        group = self.get(group_id)
        if group["status"] == "dismissed" or sorted(document_ids) != sorted(page["document_id"] for page in group["pages"]):
            raise ValueError("Give every page of this combined document once, in the new order.")
        with self.store.connection() as db:  # Rewritten whole, as page numbers are unique per group.
            db.execute("DELETE FROM document_group_pages WHERE group_id=?", (group_id,))
            db.executemany("INSERT INTO document_group_pages(group_id,occurrence_id,page_no) VALUES(?,?,?)",
                           [(group_id, document_id, page) for page, document_id in enumerate(document_ids, 1)])
            db.execute("UPDATE document_groups SET updated_at=? WHERE id=?", (now(), group_id))
        return self.get(group_id)
