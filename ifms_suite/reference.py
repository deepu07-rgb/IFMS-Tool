"""Verified source snapshots; never updated silently from the network."""

import json
from pathlib import Path


def reference_rates():
    return json.loads(
        (Path(__file__).parent / "data" / "rajasthan_rates.json").read_text()
    )


def load_reference(db):
    from .rate_library import rate_key, next_rate_id

    saved = 0
    archived = [
        json.loads(r["payload"])
        for r in db.execute("SELECT payload FROM suite_rate_archives")
    ]
    for p in reference_rates():
        existing = [
            json.loads(r["payload"])
            for r in db.execute("SELECT payload FROM suite_rates")
        ]
        if any(rate_key(q) == rate_key(p) for q in archived):
            continue
        if any(
            q["allowance"].upper() == p["allowance"]
            and q.get("category", "") == p["category"]
            and q["effective_from"] == p["effective_from"]
            for q in existing
        ):
            continue
        db.execute(
            "INSERT INTO suite_rates(id,payload) VALUES(?,?)",
            (next_rate_id(db), json.dumps(p)),
        )
        saved += 1
    if not db.execute("SELECT 1 FROM suite_rules WHERE name='DA'").fetchone():
        db.execute(
            "INSERT INTO suite_rules VALUES(?,?)",
            (
                "DA",
                json.dumps(
                    dict(
                        name="DA",
                        basis="basic",
                        proration="calendar",
                        rounding="rupee",
                        rounding_scope="month",
                        reference="F.6(3)FD(Rules)/2017; confirm service proration rule",
                    )
                ),
            ),
        )
    return saved
