# Sharing a library

One person exports an encrypted `.hmshare` file; another opens it as a temporary, separate library. Implemented 2026-09-25 (`share.py`, `Manager.start_share_export` / `start_session` / `end_session`).

## Use

- **Share:** Settings → Sharing → *Share your library*. Choose a folder, an optional name, and a passphrase of at least 12 characters. Send the file; tell the passphrase another way (a call, not the same message).
- **Open:** Settings → Sharing → *Open a shared library*. A banner shows whose library is open. **End session** deletes the copy and reopens your library.

## Guarantees

- **Your library is never written during a session.** It is closed when the session opens and reopened when it ends. Settings keep naming your library; switching library folders, backups and share exports are refused during a session.
- **The copy is temporary.** It lives in `<settings folder>\sessions\<id>` and is deleted when the session ends, when Home Manager exits, or at the next start after a crash. Anything done in the session (questions, readings, reviews, descriptions) goes to the copy only and is discarded with it.
- **Encryption:** AES-256-GCM in 1 MiB chunks; key from the passphrase with scrypt (N = 2^17, r = 8, p = 1, about 0.25 s and 128 MB). The header is authenticated with every chunk, and each nonce encodes the chunk's position and whether it is the last, so a wrong passphrase, a changed byte, reordered chunks or a truncated file all fail. Passphrases are never stored, logged or echoed in errors; validation errors from the API never repeat submitted values.
- **Import safety:** the archive is read as a stream and written by Home Manager itself. Only plain files at paths inside the backup layout are accepted (no absolute paths, drives, `..`, links); size and entry limits apply. Every file is then checked against the backup manifest and the database's integrity before the copy opens.

## Limits

- A share is a snapshot. Later changes in the sender's library need a new share.
- Sessions do not persist across restarts by design.
- The passphrase is the only protection once the file leaves the sender's computer; use four or more unrelated words.
