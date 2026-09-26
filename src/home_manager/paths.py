"""Path confinement and OS file handling. Source handles are read-only."""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import stat


class PathError(ValueError):
    pass


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse point
    )


def safe_path(path: Path) -> Path:
    """Reject links in every existing component, not merely the final name."""
    path = Path(os.path.abspath(path))
    for item in [*reversed(path.parents), path]:
        try:
            if is_link(item):
                raise PathError("Symbolic links and Windows reparse points are not allowed.")
        except FileNotFoundError:
            continue
    return path


def local_absolute(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise PathError("Choose an absolute path on a local drive (not a network share).")
    path = safe_path(path)
    if os.name == "nt":
        # Mapped network drives do not necessarily begin with a UNC prefix.
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))
        if drive_type == 4:
            raise PathError("Mapped network drives are not supported.")
    return path


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def path_key(path: Path | str) -> str:
    return os.path.normcase(str(path))


def validate_managed(managed_value: str, control: Path) -> Path:
    managed = local_absolute(managed_value)
    if managed.exists() and not managed.is_dir():
        raise PathError("The library path must be a directory.")
    if managed == Path(managed.anchor):
        raise PathError("Choose a dedicated folder, not a drive root.")
    for reserved in reserved_paths(control):
        if overlaps(managed, reserved):
            raise PathError("Choose a library folder outside the application and its settings directory.")
    return managed


def reserved_paths(control: Path) -> tuple[Path, Path]:
    """This checkout/package and the application settings: never inventoried or written as data."""
    package = Path(__file__).resolve().parent
    checkout = package.parents[1] if (package.parents[1] / "pyproject.toml").exists() else package
    return checkout, control


def separate_folder(value: str, control: Path, others=()) -> Path:
    """A local folder for backup or restore that overlaps no library, settings or application folder."""
    path = local_absolute(value)
    if path == Path(path.anchor):
        raise PathError("Choose a dedicated folder, not a drive root.")
    for reserved in (*reserved_paths(control), *(Path(item) for item in others if item)):
        if overlaps(path, reserved):
            raise PathError("Choose a folder outside the library, backups being read, and the application's own folders.")
    return path


def write_atomic(path: Path, data: bytes | str, limit: int | None = None):
    """Durably replace an app-owned file; readers see the old or the complete new bytes."""
    data = data.encode("utf-8") if isinstance(data, str) else data
    if limit is not None and len(data) > limit:
        raise ValueError(f"Output exceeds the {limit // 1024**2} MiB limit; no truncated result was saved.")
    temp = safe_path(path.with_name(path.name + ".pending"))
    with open(temp, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, safe_path(path))


def signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    # Python 3.13 on Windows reports different ctime meanings through stat and
    # CRT fstat after an edit. Identity + size + mtime are comparable; Windows
    # share-deny handles and byte rehashing provide the stronger consistency check.
    ctime = 0 if os.name == "nt" else info.st_ctime_ns
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, ctime


@contextmanager
def source_reader(path: Path):
    safe_path(path)
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # FILE_SHARE_READ denies concurrent write/delete handles for the capture.
        handle = create(str(path), 0x80000000, 1, None, 3, 0x08000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, "rb") as stream:
            yield stream
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            yield stream


class DirectoryLock:
    """OS-held lock released on process death; no stale PID-file guessing."""

    def __init__(self, directory: Path):
        safe_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = safe_path(directory / ".home-manager.lock")
        self.stream = open(lock_path, "a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise PathError("This directory is already in use by another Home Manager process.") from exc

    def close(self):
        if not self.stream.closed:
            self.stream.close()
