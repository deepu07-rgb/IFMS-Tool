import pytest

from app import app
from scripts.verify_v2_all_samples import run_verification


pytestmark = [pytest.mark.v2, pytest.mark.smoke]


def test_employee_master_large_batch_pagination_and_filters(tmp_path):
    db_path = tmp_path / "employee_master_large_batch.db"
    report = run_verification(db_path=str(db_path), verbose=False)
    assert report.passed, "\n".join(report.failure_messages())

    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    client = app.test_client()

    page1 = client.get("/api/employees?page=1&per_page=100")
    assert page1.status_code == 200
    payload = page1.get_json()
    assert payload["total"] >= 500
    assert payload["total"] == 1118
    assert len(payload["employees"]) == 100
    assert payload["pages"] > 1

    for row in payload["employees"]:
        assert row["source_file"]
        assert row["group_name"]
        assert row["employee_name"]
        if not row["employee_id"]:
            assert row["employee_data_status"] == "MISSING_CRITICAL_FIELD"
        assert row["pan"]
        if not row["pay_scale"]:
            assert row["employee_data_status"] == "MISSING_CRITICAL_FIELD"
        assert row["printed_gross"] >= 0
        assert row["printed_net"] == row["printed_gross"] - row["printed_deduction"]

    income_tax = client.get("/api/employees?has_income_tax=true&page=1&per_page=50")
    assert income_tax.status_code == 200
    income_payload = income_tax.get_json()
    assert income_payload["total"] > 0
    assert all(row["income_tax"] != 0 for row in income_payload["employees"])

    lic = client.get("/api/employees?has_lic=true&page=1&per_page=50")
    assert lic.status_code == 200
    lic_payload = lic.get_json()
    assert lic_payload["total"] > 0
    assert all(row["lic"] != 0 for row in lic_payload["employees"])

    l11 = client.get("/api/employees?pay_scale=L11&page=1&per_page=50")
    assert l11.status_code == 200
    l11_payload = l11.get_json()
    assert l11_payload["total"] > 0
    assert all(row["pay_scale"] == "L11" for row in l11_payload["employees"])
