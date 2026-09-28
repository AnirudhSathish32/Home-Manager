-- Commit file cleanup alongside permanent deletion; retry interrupted cleanup at startup.
CREATE TABLE trash_cleanup (
    relative_path TEXT PRIMARY KEY,
    is_directory INTEGER NOT NULL CHECK (is_directory IN (0,1))
);
PRAGMA user_version=20;
