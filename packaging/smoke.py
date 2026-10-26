"""Exercise a real packaged server in an empty private data directory."""

import json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path


def main():
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="ifms-package-smoke-") as td:
        env = os.environ.copy()
        env.update(IFMS_OPEN_BROWSER="0", IFMS_PORT="5068", IFMS_DATA_DIR=td)
        log = Path(td) / "startup.log"
        with log.open("w") as stream:
            process = subprocess.Popen(
                [str(executable)], env=env, stdout=stream, stderr=subprocess.STDOUT
            )
            try:
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError("Packaged server exited: " + log.read_text())
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:5068/suite/", timeout=1
                        ) as r:
                            if r.status == 200:
                                break
                    except OSError:
                        time.sleep(0.5)
                else:
                    raise RuntimeError(
                        "Packaged server did not become ready: " + log.read_text()
                    )

                def req(path, payload=None):
                    data = json.dumps(payload).encode() if payload is not None else None
                    with urllib.request.urlopen(
                        urllib.request.Request(
                            "http://127.0.0.1:5068" + path,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        ),
                        timeout=180,
                    ) as r:
                        return r.read()

                assert b"IFMS Workspace" in req("/suite/")
                assert b"function openModule" in req("/suite/static/suite.js")
                claim = json.loads(
                    req(
                        "/suite/api/claims",
                        dict(
                            employee_code="TEST",
                            allowance="DA",
                            start="2025-01-01",
                            end="2025-01-31",
                            segments=[
                                dict(
                                    start="2025-01-01",
                                    end="2025-01-31",
                                    basic="50000",
                                    due_rate="55",
                                    drawn_rate="53",
                                )
                            ],
                        ),
                    )
                )
                assert claim["calculation"]["total"] == "1000.00"
                assert req(f"/suite/api/claims/{claim['id']}/excel").startswith(b"PK")
                assert req(f"/suite/api/claims/{claim['id']}/pdf").startswith(b"%PDF")
                assert json.loads(req("/api/v3/health_check"))["database_integrity"][
                    "ok"
                ]
                increment = json.loads(
                    req(
                        "/suite/api/increment_check",
                        dict(
                            employee_code="INCREMENT-SMOKE",
                            start="2026-07-01",
                            end="2026-07-31",
                            new_basic="55500",
                            category="Y",
                            reviewed=True,
                            pay_order_reference="Synthetic reviewed increment",
                            drawn_reference="Synthetic reviewed GA55",
                            drawn={
                                "BASIC": "53900",
                                "DA": "32340",
                                "HRA": "10780",
                                "HDA": "7187",
                            },
                            hda_rule={
                                "numerator": "1",
                                "denominator": "12",
                                "reference": "Synthetic reviewed fraction",
                            },
                        ),
                    )
                )
                assert increment["total"] == "3093.00", increment
                # OCR resources are checked through the actual executable environment.
                status = json.loads(req("/suite/api/ocr_status"))
                if sys.platform == "win32":
                    assert status["available"] and {"eng", "hin"}.issubset(
                        status["languages"]
                    )
                if status["available"]:
                    import pymupdf

                    source = pymupdf.open()
                    p = source.new_page()
                    p.insert_text((50, 60), "BASIC 50000.00 DA 27500.00", fontsize=20)
                    image = p.get_pixmap(dpi=150).tobytes("png")
                    scan = pymupdf.open()
                    p = scan.new_page()
                    p.insert_image(p.rect, stream=image)
                    data = scan.tobytes()
                    scan.close()
                    source.close()
                    boundary = "IFMS-SMOKE-MULTIPART"
                    body = (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\nga55\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="scan.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
                        + data
                        + f"\r\n--{boundary}--\r\n".encode()
                    )
                    request = urllib.request.Request(
                        "http://127.0.0.1:5068/suite/api/imports",
                        data=body,
                        headers={
                            "Content-Type": "multipart/form-data; boundary=" + boundary
                        },
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:
                        imported = json.loads(response.read())
                    result = json.loads(
                        req(
                            f"/suite/api/imports/{imported['id']}/ocr",
                            {"language": "eng+hin"},
                        )
                    )
                    assert "50000" in "".join(result["pages"]), result
                print(
                    "Packaged HTTP, calculation, exports, database and real raster OCR checks passed"
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
