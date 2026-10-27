"""Review-only cell OCR for ruled reference statements."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from flask import current_app, request, jsonify
from .storage import database


def register_statement_grid_routes(suite):
    @suite.post("/api/imports/<int:id>/statement_grid")
    def statement_grid(id):
        import pymupdf
        from PIL import Image
        from .statement_grid import (
            extract_statement_grid,
            _mapped_rows,
            GRID_EXTRACTION_VERSION,
        )
        from .due_drawn import parse_statement_table

        query = request.get_json() or {}
        page_number = query.get("page")
        if type(page_number) is not int or page_number < 1:
            raise ValueError("Choose an original source page")
        with database() as db:
            row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
            if not row:
                return jsonify(error="Import not found"), 404
            payload = json.loads(row["payload"])
            if payload.get("file_kind") != "pdf":
                raise ValueError("Choose a PDF source page")
            path = (
                Path(current_app.config["UPLOAD_FOLDER"])
                / "suite"
                / (row["sha256"] + ".pdf")
            )
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Original source changed")
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if page_number > len(doc):
                    raise ValueError("Source page does not exist")
                grid = payload.get("statement_grids", {}).get(str(page_number))
                if (
                    grid is None
                    or grid.get("extraction_version") != GRID_EXTRACTION_VERSION
                ):
                    import onnxruntime

                    onnxruntime.disable_telemetry_events()
                    from rapidocr_onnxruntime import RapidOCR

                    recognizer = RapidOCR(
                        intra_op_num_threads=2, inter_op_num_threads=1
                    )
                    pix = doc[page_number - 1].get_pixmap(dpi=200)
                    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    grid = extract_statement_grid(
                        image,
                        recognizer,
                        source_sha256=row["sha256"],
                        page_number=page_number,
                    )
                    grid["extraction_version"] = GRID_EXTRACTION_VERSION
                    grid["review_required"] = True
                    grid["notice"] = (
                        "Handwritten cell recognition is a candidate only. Check critical digits and source totals; confidence is not proof of correctness."
                    )
                    payload.setdefault("statement_grids", {})[str(page_number)] = grid
            response = deepcopy(grid)
            if query.get("mapping") is not None:
                if (
                    query.get("reviewed") is not True
                    or not str(query.get("reference", "")).strip()
                ):
                    raise ValueError(
                        "Confirm column mapping against original printed headers with a reference"
                    )
                response["semantic_rows"] = parse_statement_table(
                    _mapped_rows(response.get("table_rows", []), query["mapping"])
                )
                response["assisted"] = True
                payload.setdefault("statement_reference_rows", {})[str(page_number)] = (
                    response["semantic_rows"]
                )
                payload.setdefault("statement_column_reviews", []).append(
                    dict(
                        page=page_number,
                        mapping=query["mapping"],
                        reference=query["reference"],
                        source_sha256=row["sha256"],
                    )
                )
            updated = db.execute(
                "UPDATE suite_imports SET payload=? WHERE id=? AND payload=? AND status=?",
                (json.dumps(payload), id, row["payload"], row["status"]),
            )
            if updated.rowcount != 1:
                raise ValueError("Source changed during OCR; reload it")
            return jsonify(response)
