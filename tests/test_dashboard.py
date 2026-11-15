"""Dashboard data load and a headless Streamlit startup."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from governance_sentinel.dashboard_data import load_dashboard

REPO = Path(__file__).resolve().parents[1]


def test_sample_dashboard_has_a_mixed_scorecard() -> None:
    data = load_dashboard(REPO)
    statuses = {item.status for item in data.rules}
    assert statuses == {"PASS", "FAIL"}
    assert data.lineage.statuses["src_transactions"] == "NOT_MEASURED"
    assert data.lineage.statuses["agg_exposure"] == "FAIL"
    assert data.fairness.unprivileged_count > 0
    assert data.fairness.privileged_count > 0
    assert len(data.glossary.terms) >= 8
    assert len(data.ownership.rows) == len(data.glossary.terms)
    assert len(data.history) >= 6
    assert len(data.kpi_runs) == 12


def test_committed_lineage_diagram_matches_the_sample() -> None:
    data = load_dashboard(REPO)
    diagram = (REPO / "docs" / "lineage.mmd").read_text(encoding="utf-8")
    assert diagram == data.lineage.mermaid + "\n"


def test_streamlit_app_starts() -> None:
    app = AppTest.from_file(str(REPO / "streamlit_app.py"), default_timeout=90)
    app.run()
    assert not app.exception
    assert any("Governance-Sentinel" in block.value for block in app.title)
    for page in ("Trend", "Lineage", "Glossary", "Ownership", "Fairness", "Report"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
