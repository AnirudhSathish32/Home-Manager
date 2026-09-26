"""Encrypted library sharing: one .hmshare file, opened only with its passphrase.

A share is a verified backup (backup.py) packed as a tar stream and encrypted in 1 MiB chunks
with AES-256-GCM. The key comes from the passphrase through scrypt; the passphrase is never
stored or logged. Each chunk's nonce carries its position and whether it is the last one, and
the file header is authenticated with every chunk, so reordering, truncation, a changed header
or a wrong passphrase all fail to decrypt rather than yield partial data.

Opening a share decrypts it into a temporary folder, verifies every file against the backup
manifest, and restores it as a separate library. Nothing is extracted outside that folder:
entries are checked against the backup layout and written by this module, never by tarfile.
"""

import io
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import tarfile
import unicodedata
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .backup import BackupService, DATABASE, MANIFEST, manifest_path, restore_backup
from .jobs import Work
from .paths import PathError, safe_path
from .storage import now

MAGIC, VERSION = b"HMSHARE1", 1
CHUNK = 1024 * 1024
TAG = 16
# scrypt cost: 2^17 x 8 needs about 128 MB and a fraction of a second, per the usual interactive guidance.
SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P = 17, 8, 1
MIN_PASSPHRASE = 12
MAX_ENTRIES, MAX_TOTAL_BYTES = 200_000, 8 * 1024 ** 3
SHARE_INFO = "share.json"
EXTENSION = ".hmshare"
HEADER = struct.Struct(">8sBBBB16s7s")  # magic, version, log2 N, r, p, salt, nonce prefix


class ShareError(ValueError):
    pass


def check_passphrase(passphrase):
    if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE:
        raise ShareError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters, such as four unrelated words.")
    if len(passphrase) > 1024:
        raise ShareError("The passphrase is too long.")
    return unicodedata.normalize("NFC", passphrase).encode()


def derive_key(passphrase, salt, log_n, r, p):
    if not (10 <= log_n <= 22 and 1 <= r <= 32 and p == 1):
        raise ShareError("This share uses unsupported key settings.")
    return Scrypt(salt=salt, length=32, n=2 ** log_n, r=r, p=p).derive(check_passphrase(passphrase))


def nonce(prefix, counter, last):
    if counter >= 2 ** 32:
        raise ShareError("The share is too large.")
    return prefix + struct.pack(">IB", counter, 1 if last else 0)


class EncryptingWriter(io.RawIOBase):
    """File-like sink: plaintext in, authenticated chunks out. finish() seals the final chunk.

    Sealing is explicit, never done by close() or garbage collection, so a failed export cannot end
    in a validly sealed but incomplete file.
    """

    def __init__(self, target, passphrase):
        salt, self.prefix = secrets.token_bytes(16), secrets.token_bytes(7)
        self.header = HEADER.pack(MAGIC, VERSION, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P, salt, self.prefix)
        self.aead = AESGCM(derive_key(passphrase, salt, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P))
        self.target, self.buffer, self.counter = target, bytearray(), 0
        target.write(self.header)

    def writable(self):
        return True

    def write(self, data):
        self.buffer += data
        while len(self.buffer) > CHUNK:  # Strictly more, so the last chunk is always sealed by close().
            self._emit(bytes(self.buffer[:CHUNK]), last=False)
            del self.buffer[:CHUNK]
        return len(data)

    def _emit(self, plain, last):
        self.target.write(self.aead.encrypt(nonce(self.prefix, self.counter, last), plain, self.header))
        self.counter += 1

    def finish(self):
        self._emit(bytes(self.buffer), last=True)
        self.buffer.clear()
        self.close()


class DecryptingReader(io.RawIOBase):
    """File-like source over an encrypted share; raises ShareError on any authentication failure."""

    def __init__(self, source, passphrase):
        header = source.read(HEADER.size)
        if len(header) != HEADER.size:
            raise ShareError("This is not a Home Manager share file.")
        magic, version, log_n, r, p, salt, self.prefix = HEADER.unpack(header)
        if magic != MAGIC:
            raise ShareError("This is not a Home Manager share file.")
        if version != VERSION:
            raise ShareError("This share was made by a newer Home Manager version.")
        self.header, self.source = header, source
        self.aead = AESGCM(derive_key(passphrase, salt, log_n, r, p))
        self.counter, self.buffer, self.done = 0, b"", False
        self.pending = source.read(CHUNK + TAG)

    def readable(self):
        return True

    def _next(self):
        following = self.source.read(CHUNK + TAG)
        last = not following
        try:
            plain = self.aead.decrypt(nonce(self.prefix, self.counter, last), self.pending, self.header)
        except InvalidTag as exc:
            raise ShareError("Wrong passphrase, or the share file is damaged or incomplete." if self.counter == 0
                             else "The share file is damaged or incomplete.") from exc
        self.counter += 1
        self.pending, self.done = following, last
        return plain

    def readinto(self, target):
        while not self.buffer and not self.done:
            self.buffer = self._next()
        count = min(len(target), len(self.buffer))
        target[:count] = self.buffer[:count]
        self.buffer = self.buffer[count:]
        return count


def export_share(store, destination: Path, passphrase, label, work=None):
    """Write <destination>/home-manager-share-….hmshare. Returns its path. The library is only read."""
    work = work or Work.detached()
    check_passphrase(passphrase)
    label = " ".join((label or "").split())[:60] or "Shared library"
    destination = safe_path(destination)
    if not destination.is_dir():
        raise PathError("Choose an existing folder for the share file.")
    share_id = uuid.uuid4().hex
    final = safe_path(destination / f"home-manager-share-{now()[:10]}-{share_id[:8]}{EXTENSION}")
    partial = safe_path(final.with_name(final.name + ".partial"))
    staging = safe_path(store.work / f"share-{share_id}")
    try:
        staging.mkdir()
        manifest = BackupService(store).write(staging, share_id, work)
        info = {"label": label, "created_at": now(), "files": len(manifest["files"])}
        with open(partial, "xb") as raw:
            sink = EncryptingWriter(raw, passphrase)
            with tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, data in ((SHARE_INFO, json.dumps(info).encode()), (MANIFEST, json.dumps(manifest, sort_keys=True).encode())):
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
                for item in manifest["files"]:
                    work.check()
                    archive.add(staging.joinpath(*manifest_path(item["path"]).parts), arcname=item["path"], recursive=False)
            sink.finish()
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(partial, final)
        return {"path": str(final), "label": label, "files": len(manifest["files"]), "issues": manifest["issues"]}
    finally:
        # Only this export's own staging copy and unfinished file are removed.
        shutil.rmtree(staging, ignore_errors=True)
        partial.unlink(missing_ok=True)


def open_share(share_file: Path, passphrase, target: Path, work=None):
    """Decrypt, verify and restore a share as a new library in target (which must not exist yet)."""
    work = work or Work.detached()
    share_file, target = safe_path(share_file), safe_path(target)
    if not share_file.is_file():
        raise PathError("Choose the .hmshare file itself.")
    if target.exists():
        raise PathError("The session folder already exists.")
    unpacked = safe_path(target.with_name(target.name + "-unpacked"))
    unpacked.mkdir(parents=True)
    try:
        info, count, total = None, 0, 0
        with open(share_file, "rb") as raw, tarfile.open(fileobj=DecryptingReader(raw, passphrase), mode="r|") as archive:
            for entry in archive:
                work.check()
                count += 1
                total += max(entry.size, 0)
                if count > MAX_ENTRIES or total > MAX_TOTAL_BYTES:
                    raise ShareError("The share is larger than Home Manager accepts.")
                if not entry.isfile():
                    raise ShareError("The share contains an entry that is not a plain file.")
                if entry.name not in (SHARE_INFO, MANIFEST):
                    manifest_path(entry.name)  # Refuses absolute paths, drives, '..' and anything outside the backup layout.
                path = safe_path(unpacked.joinpath(*entry.name.split("/")))
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(entry) as reader, open(path, "xb") as writer:
                    shutil.copyfileobj(reader, writer, CHUNK)
                if entry.name == SHARE_INFO:
                    info = json.loads(path.read_text(encoding="utf-8"))
        if info is None or not (unpacked / MANIFEST).is_file() or not (unpacked / DATABASE).is_file():
            raise ShareError("The share is incomplete.")
        restored = restore_backup(unpacked, target, work)
        return {**restored, "label": str(info.get("label") or "Shared library")[:60], "shared_at": info.get("created_at")}
    except (tarfile.TarError, EOFError) as exc:
        raise ShareError("The share file is damaged or incomplete.") from exc
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(unpacked, ignore_errors=True)
