import json
from flask import request, jsonify
from .storage import database
from .payroll import identity


def value(row, *names):
    fields = {
        str(k).lower().replace("_", "").replace(" ", ""): v for k, v in row.items()
    }
    for name in names:
        k = name.lower().replace("_", "").replace(" ", "")
        if str(fields.get(k, "")).strip():
            return fields[k]
    return ""


def profile_signature(record):
    return json.dumps(
        {k: v for k, v in record.items() if not str(k).startswith(("__", "source_"))},
        sort_keys=True,
    )


def register_groups(suite):
    @suite.get("/api/group_imports")
    def group_imports():
        with database() as db:
            return jsonify(
                [
                    dict(
                        id=r["id"],
                        payload=json.loads(r["payload"]),
                        reviewed=bool(
                            db.execute(
                                "SELECT 1 FROM suite_group_reviews WHERE import_id=?",
                                (r["id"],),
                            ).fetchone()
                        ),
                    )
                    for r in db.execute(
                        "SELECT * FROM suite_group_imports ORDER BY id DESC"
                    )
                ]
            )

    @suite.post("/api/group_imports/<int:id>/review")
    def review_group(id):
        p = request.get_json() or {}
        if p.get("reviewed") is not True:
            raise ValueError("Confirm employee identity review")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM suite_group_reviews WHERE import_id=?", (id,)
            ).fetchone():
                raise ValueError("Group import already reviewed")
            row = db.execute(
                "SELECT payload FROM suite_group_imports WHERE id=?", (id,)
            ).fetchone()
            if not row:
                return jsonify(error="Group import not found"), 404
            records = json.loads(row["payload"])["records"]
            groups = {}
            selected = []
            for index, r in enumerate(records):
                code = identity(value(r, "employeeCode", "employee_code"))
                if not code:
                    raise ValueError(
                        "Missing official employee code on row " + str(index + 1)
                    )
                groups.setdefault(code, []).append(index)
            for code, indices in groups.items():
                unique = {profile_signature(records[i]) for i in indices}
                pick = p.get("selections", {}).get(
                    code, indices[0] if len(unique) == 1 else None
                )
                if isinstance(pick, bool) or pick not in indices:
                    raise ValueError("Select the correct source row for " + code)
                r = records[pick]
                profile = dict(
                    employee_code=code,
                    name=str(value(r, "employeeName", "name")).strip(),
                    group=value(r, "groupName", "group"),
                    internal_id=value(r, "empId"),
                    designation=value(r, "designation", "desgEn", "post"),
                    office_name=value(r, "officeName", "office_name"),
                    ddo_code=value(r, "ddoCode", "ddo_code"),
                    source_group_import=id,
                )
                if not profile["name"]:
                    raise ValueError("Employee name missing for " + code)
                old = db.execute(
                    "SELECT payload FROM suite_employees WHERE employee_code=?", (code,)
                ).fetchone()
                if old:
                    q = json.loads(old["payload"])
                    if (
                        q.get("name") != profile["name"]
                        or q.get("group", "") != profile["group"]
                    ) and p.get("replace_current") is not True:
                        return (
                            jsonify(
                                error="Existing profile differs for "
                                + code
                                + ". Explicitly approve replacing the current profile; prior version is retained."
                            ),
                            409,
                        )
                selected.append((code, profile, old["payload"] if old else None))
            for code, profile, previous in selected:
                db.execute(
                    "INSERT INTO suite_profile_audit(employee_code,source,previous_payload,new_payload) VALUES(?,?,?,?)",
                    (code, "Group import " + str(id), previous, json.dumps(profile)),
                )
                db.execute(
                    "INSERT INTO suite_employees VALUES(?,?,?) ON CONFLICT(employee_code) DO UPDATE SET name=excluded.name,payload=excluded.payload",
                    (code, profile["name"], json.dumps(profile)),
                )
            db.execute(
                "INSERT INTO suite_group_reviews VALUES(?,?)", (id, json.dumps(p))
            )
        return jsonify(saved=len(selected))
