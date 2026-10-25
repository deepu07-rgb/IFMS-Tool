import pytest

from scripts.verify_v2_all_samples import run_verification


pytestmark = [pytest.mark.v2, pytest.mark.smoke]


def test_v2_all_samples_totals_gate(tmp_path):
    report = run_verification(
        db_path=str(tmp_path / "v2_all_samples_gate.db"),
        verbose=True,
    )

    assert not report.failure_messages(), "\n".join(report.failure_messages())
