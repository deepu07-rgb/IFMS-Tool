import sqlite3
from app import app, init_db
from ifms_engine.db import init_v2_schema


def test_inner_excel_mime_does_not_depend_on_host_file_associations(
    tmp_path, monkeypatch
):
    path = tmp_path / "mime.db"
    exports = tmp_path / "exports"
    exports.mkdir()
    for key, value in dict(
        DATABASE=str(path), EXPORT_FOLDER=str(exports), USE_V2_PARSER=True
    ).items():
        monkeypatch.setitem(app.config, key, value)
    init_db()
    init_v2_schema(str(path))
    with sqlite3.connect(path) as db:
        bid = db.execute(
            "INSERT INTO bills_v2(source_filename,bill_no) VALUES('synthetic.pdf','B1')"
        ).lastrowid
        db.execute(
            "INSERT INTO employees_v2(bill_id,source_filename,employee_id,raw_name,gross_amount,sum_deduction,net_total) VALUES(?,'synthetic.pdf','TEST','Synthetic Employee',1000,100,900)",
            (bid,),
        )
    monkeypatch.setattr(
        "werkzeug.utils.mimetypes.guess_type", lambda *args, **kwargs: (None, None)
    )
    r = app.test_client().get("/api/export")
    assert r.status_code == 200
    assert (
        r.content_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert r.data.startswith(b"PK")
