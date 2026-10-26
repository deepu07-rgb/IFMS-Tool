"""Single-process data directory and restore coordination for local launchers."""

import os, sys
from pathlib import Path


def data_directory():
    if os.environ.get("IFMS_DATA_DIR"):
        root = Path(os.environ["IFMS_DATA_DIR"])
    elif getattr(sys, "frozen", False):
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "IFMSWorkspace"
    else:
        root = Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def startup():
    root = data_directory()
    handle = (root / "workspace.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(
            "Another IFMS workspace is already using this data directory. Close it before restarting."
        )
    from ifms_suite.backups import apply_pending

    apply_pending(root)
    return handle
