"""Portable snapshots include original documents as well as the entire database."""

import hashlib, io, json, sqlite3, tempfile, zipfile, os, shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from flask import request, current_app, send_file, jsonify

MAX_EXPANDED = 2 * 1024**3


def create_bundle(db_path, uploads):
    b = io.BytesIO()
    manifest = {
        "format": "ifms-suite-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    with tempfile.TemporaryDirectory(prefix="ifms-snapshot-") as td:
        snapshot = Path(td) / "database.sqlite"
        src = sqlite3.connect(db_path)
        dest = sqlite3.connect(snapshot)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as z:
            files = [("database.sqlite", snapshot)]
            root = Path(uploads).resolve()
            if root.exists():
                files.extend(
                    ("sources/" + p.relative_to(root).as_posix(), p)
                    for p in root.rglob("*")
                    if p.is_file()
                    and p.suffix.lower() in (".pdf", ".xlsx", ".docx")
                    and not p.is_symlink()
                    and p.resolve().is_relative_to(root)
                )
            if sum(p.stat().st_size for name, p in files) > MAX_EXPANDED:
                raise ValueError(
                    "Backup exceeds the 2 GB portable snapshot limit; archive documents separately"
                )
            for name, p in files:
                data = p.read_bytes()
                z.writestr(name, data)
                manifest["files"][name] = hashlib.sha256(data).hexdigest()
            z.writestr("manifest.json", json.dumps(manifest))
    b.seek(0)
    return b


def validate_bundle(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = z.infolist()
            names = [i.filename for i in entries]
            if len(entries) > 20000 or sum(i.file_size for i in entries) > MAX_EXPANDED:
                raise ValueError("Backup expanded size or file count exceeds limits")
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive entries")
            for name in names:
                p = PurePosixPath(name)
                if (
                    "\\" in name
                    or ":" in name
                    or p.is_absolute()
                    or ".." in p.parts
                    or name.endswith("/")
                ):
                    raise ValueError("Unsafe backup path")
                if name not in ("manifest.json", "database.sqlite") and not (
                    name.startswith("sources/")
                    and name.lower().endswith((".pdf", ".xlsx", ".docx"))
                ):
                    raise ValueError("Unsupported backup entry")
            manifest = json.loads(z.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or not isinstance(manifest.get("files"), dict)
                or not isinstance(manifest.get("created_at"), str)
            ):
                raise ValueError("Invalid backup manifest")
            if manifest.get("format") != "ifms-suite-1":
                raise ValueError("Unsupported backup format")
            if set(manifest["files"]) != set(names) - {"manifest.json"}:
                raise ValueError("Backup manifest does not match its files")
            for name, digest in manifest["files"].items():
                if hashlib.sha256(z.read(name)).hexdigest() != digest:
                    raise ValueError("Backup checksum mismatch")
            with tempfile.TemporaryDirectory(prefix="ifms-validate-") as td:
                path = Path(td) / "db"
                path.write_bytes(z.read("database.sqlite"))
                db = sqlite3.connect(path)
                try:
                    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Backup database integrity failed")
                finally:
                    db.close()
            return manifest
    except (
        zipfile.BadZipFile,
        KeyError,
        json.JSONDecodeError,
        sqlite3.DatabaseError,
    ) as e:
        raise ValueError("Invalid backup archive") from e


def apply_pending(data_dir):
    root = Path(data_dir)
    pending = root / "pending-restore.zip"
    if not pending.exists():
        return
    data = pending.read_bytes()
    validate_bundle(data)
    dbpath = root / "ifms_data.db"
    uploads = root / "uploads"
    backupdir = root / "backups"
    backupdir.mkdir(parents=True, exist_ok=True)
    if dbpath.exists():
        previous = create_bundle(dbpath, uploads)
        name = "before-restore-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".zip"
        (backupdir / name).write_bytes(previous.getvalue())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        staging = root / "restore-staging.sqlite"
        staging.write_bytes(z.read("database.sqlite"))
        # Called only by the exclusive launcher before Flask or worker threads start.
        for suffix in ("-wal", "-shm"):
            path = Path(str(dbpath) + suffix)
            if path.exists():
                path.unlink()
        os.replace(staging, dbpath)
        for name in z.namelist():
            if name.startswith("sources/"):
                target = uploads / PurePosixPath(name).relative_to("sources")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    pending.unlink()


def register_backups(suite):
    @suite.get("/api/backup")
    def backup():
        b = create_bundle(
            current_app.config["DATABASE"], current_app.config["UPLOAD_FOLDER"]
        )
        return send_file(
            b,
            mimetype="application/zip",
            as_attachment=True,
            download_name="IFMS-complete-backup-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + ".zip",
        )

    @suite.post("/api/restore/preview")
    def preview_restore():
        f = request.files.get("file")
        if not f:
            raise ValueError("Choose a trusted backup file")
        data = f.read(MAX_EXPANDED + 1)
        if len(data) > MAX_EXPANDED:
            raise ValueError("Backup too large")
        manifest = validate_bundle(data)
        return jsonify(
            created_at=manifest["created_at"],
            files=len(manifest["files"]),
            database_ok=True,
        )

    @suite.post("/api/restore/stage")
    def stage_restore():
        if request.form.get("confirmation") != "RESTORE":
            raise ValueError("Type RESTORE to confirm replacement after restart")
        f = request.files.get("file")
        if not f:
            raise ValueError("Choose a trusted backup file")
        data = f.read(MAX_EXPANDED + 1)
        if len(data) > MAX_EXPANDED:
            raise ValueError("Backup too large")
        validate_bundle(data)
        root = Path(current_app.config["DATABASE"]).parent
        (root / "pending-restore.zip").write_bytes(data)
        return jsonify(
            status="staged",
            message="Close IFMS and restart using the workspace launcher. A pre-restore backup will be created before replacement.",
        )
