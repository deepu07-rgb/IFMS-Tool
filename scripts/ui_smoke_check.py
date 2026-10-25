from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


EXPECTED_BUILD_LABEL = "Phase3-Full-Stable"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BAD_MOJIBAKE = ("\u00c3\u00b0\u00c5\u00b8", "\u00c3\u00a2", "\u00c3\u0192", "\ufffd")
HTML_LABELS = (
    "Upload PDFs",
    "Dashboard",
    "Employee Data",
    "Schedules",
    "Official Schedule Comparison",
    "Monthly Comparison",
    "Master Register",
    "Group Summary",
    "Exception Center",
    "Dictionary",
    "Backup & Restore",
    "Export Center",
    "System Diagnostics",
    "Help",
)
ENDPOINTS = (
    "/",
    "/api/version",
    "/api/v3/smoke_status",
    "/api/v3/health_check",
    "/api/v3/ui_action_inventory",
    "/api/employees",
    "/api/v3/dictionary",
    "/api/v3/schedules/types",
    "/api/v3/schedules/reconciliation",
    "/api/v3/official_schedules/uploads",
    "/api/v3/monthly_comparison/options",
    "/api/v3/master_register/summary",
    "/api/v3/export_center/history",
    "/api/v3/backup/list",
)


@dataclass
class Response:
    status_code: int
    text: str


def _fetch_url(base_url: str, path: str, timeout: int = 10) -> Response:
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return Response(response.status, body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return Response(exc.code, body)
    except urllib.error.URLError as exc:
        return Response(0, str(exc.reason))


def _fetch_test_client(path: str) -> Response:
    from app import app

    client = app.test_client()
    response = client.get(path)
    return Response(response.status_code, response.get_data(as_text=True))


def _client_for(args):
    if args.test_client:
        return "test-client", _fetch_test_client
    failures = []
    for path in ("/", "/api/version"):
        response = _fetch_url(args.base_url, path, args.timeout)
        if response.status_code != 200:
            failures.append(f"{path} returned {response.status_code}")
            continue
        if path == "/api/version":
            try:
                build = json.loads(response.text).get("build_label")
            except json.JSONDecodeError:
                build = ""
            if build != EXPECTED_BUILD_LABEL:
                failures.append(f"/api/version build label was {build!r}")
    if failures and not args.no_fallback:
        print("WARNING: Live app URL is unavailable or stale: " + "; ".join(failures))
        print("Using Flask test client fallback for API/HTML smoke.")
        return "test-client fallback mode", _fetch_test_client
    return "live mode", lambda path: _fetch_url(args.base_url, path, args.timeout)


def _check_playwright():
    try:
        __import__("playwright")
        print("Playwright installed; API/HTML smoke completed without browser automation.")
    except ImportError:
        print("Playwright not installed; API/HTML smoke completed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IFMS UI/API smoke check")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--test-client", action="store_true")
    parser.add_argument("--no-fallback", action="store_true")
    args = parser.parse_args(argv)

    mode, fetch = _client_for(args)
    errors = []
    responses = {}
    for path in ENDPOINTS:
        response = fetch(path)
        responses[path] = response
        if response.status_code != 200:
            errors.append(f"{path} returned {response.status_code}")

    html = responses.get("/", Response(0, "")).text
    for label in HTML_LABELS:
        if label not in html:
            errors.append(f"HTML missing label: {label}")
    for bad in BAD_MOJIBAKE:
        if bad in html:
            errors.append(f"HTML contains mojibake sequence: {bad.encode('unicode_escape').decode('ascii')}")

    version_text = responses.get("/api/version", Response(0, "{}")).text
    try:
        version = json.loads(version_text)
    except json.JSONDecodeError:
        version = {}
        errors.append("/api/version did not return JSON")
    if version.get("build_label") != EXPECTED_BUILD_LABEL:
        errors.append(f"build_label mismatch: {version.get('build_label')!r}")

    smoke_text = responses.get("/api/v3/smoke_status", Response(0, "{}")).text
    try:
        smoke = json.loads(smoke_text)
    except json.JSONDecodeError:
        smoke = {}
        errors.append("/api/v3/smoke_status did not return JSON")
    if smoke and not smoke.get("db_ok"):
        errors.append("smoke_status db_ok is false")

    health_text = responses.get("/api/v3/health_check", Response(0, "{}")).text
    try:
        health = json.loads(health_text)
    except json.JSONDecodeError:
        health = {}
        errors.append("/api/v3/health_check did not return JSON")
    if health and not health.get("database_ok"):
        errors.append("health_check database_ok is false")

    inventory_text = responses.get("/api/v3/ui_action_inventory", Response(0, "{}")).text
    try:
        inventory = json.loads(inventory_text)
    except json.JSONDecodeError:
        inventory = {}
        errors.append("/api/v3/ui_action_inventory did not return JSON")
    if inventory and not inventory.get("sections"):
        errors.append("ui_action_inventory returned no sections")

    print(f"Mode: {mode}")
    print(f"Base URL: {args.base_url}")
    print(f"Build label: {version.get('build_label', '')}")
    print(f"Employee count: {smoke.get('employee_count', 0)}")
    print(f"Bill count: {smoke.get('bill_count', 0)}")
    print(f"Schedule type count: {smoke.get('schedule_types_count', 0)}")
    print(f"Health status: {health.get('overall_status', '')}")
    _check_playwright()

    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
