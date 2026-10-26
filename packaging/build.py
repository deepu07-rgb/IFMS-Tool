"""Build a portable local application; never include office records or caches."""

import argparse, hashlib, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-dir", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32" and not args.ocr_dir:
        raise SystemExit(
            "Supply a verified installed Tesseract directory with --ocr-dir"
        )
    if args.ocr_dir:
        src = args.ocr_dir.resolve()
        if not (src / "tesseract.exe").is_file():
            raise SystemExit("Tesseract executable not found in supplied directory")
        # Runtime DLLs are copied from the checksum-verified package-manager installation.
        for p in src.iterdir():
            if (
                p.is_file()
                and p.suffix.lower() in (".exe", ".dll")
                and ("unins" not in p.name.lower())
            ):
                shutil.copy2(p, ROOT / "ocr" / p.name)
    from PyInstaller.__main__ import run

    data = [
        ("THIRD_PARTY", "THIRD_PARTY"),
        ("templates", "templates"),
        ("static", "static"),
        ("ifms_suite/templates", "ifms_suite/templates"),
        ("ifms_suite/static", "ifms_suite/static"),
        ("ifms_suite/data", "ifms_suite/data"),
        ("reference_orders", "reference_orders"),
        ("ocr", "ocr"),
        ("IFMS Group Management - Analyzer.html", "."),
    ]
    flags = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "IFMSWorkspace",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
    ]
    for src, dest in data:
        flags += ["--add-data", str(ROOT / src) + os.pathsep + dest]
    flags += [
        "--collect-submodules",
        "ifms_engine",
        "--collect-submodules",
        "ifms_suite",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "playwright",
        str(ROOT / "launch.py"),
    ]
    os.chdir(ROOT)
    run(flags)
    package = ROOT / "dist" / "IFMSWorkspace"
    files = [p for p in package.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    if size >= 500_000_000:
        raise SystemExit(
            f"Installed package is {size:,} bytes; limit is strictly below 500,000,000 bytes"
        )
    if any(
        p.suffix.lower() in (".db", ".7z")
        or "test_fixtures" in p.parts
        or "uploads" in p.parts
        or "backups" in p.parts
        for p in files
    ):
        raise SystemExit("Private data or source archives were included unexpectedly")
    report = {
        "platform": sys.platform,
        "python": sys.version,
        "installed_bytes": size,
        "limit_bytes": 500_000_000,
        "files": len(files),
        "ocr_bundled": bool(args.ocr_dir),
        "sha256": {
            p.relative_to(package)
            .as_posix(): hashlib.sha256(p.read_bytes())
            .hexdigest()
            for p in files
        },
    }
    (package / "PACKAGE-MANIFEST.json").write_text(json.dumps(report, indent=2))
    size = sum(p.stat().st_size for p in package.rglob("*") if p.is_file())
    if size >= 500_000_000:
        raise SystemExit("Manifest makes package exceed size budget")
    (ROOT / "dist" / "size-report.json").write_text(
        json.dumps(
            {
                "installed_bytes": size,
                "platform": sys.platform,
                "limit_bytes": 500_000_000,
                "ocr_bundled": bool(args.ocr_dir),
            },
            indent=2,
        )
    )
    shutil.make_archive(
        str(ROOT / "dist" / ("IFMSWorkspace-" + sys.platform)),
        "zip",
        ROOT / "dist",
        "IFMSWorkspace",
    )
    print("Installed package bytes:", size)


if __name__ == "__main__":
    main()
