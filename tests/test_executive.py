"""One-page executive summary: lights, owners, due dates, and a single A4 page."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pypdf import PdfReader

from governance_sentinel.catalog import load_glossary
from governance_sentinel.executive import (
    ExecutiveSummary,
    build_summary,
    rag_light,
    write_executive_pdf,
)
from governance_sentinel.history import StoredRun
from governance_sentinel.lineage import build_lineage
from governance_sentinel.ownership import load_ownership
from governance_sentinel.rules import evaluate_rules, load_rules
from governance_sentinel.scores import PrincipleScore

REPO = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 15)


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def _assert_one_a4_page(path: Path) -> None:
    reader = PdfReader(str(path))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert abs(float(box.width) - 595.27) < 1.5
    assert abs(float(box.height) - 841.89) < 1.5


def _sample_summary(previous: StoredRun | None = None) -> ExecutiveSummary:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    frame = pd.read_csv(REPO / "data" / "sample_transactions.csv")
    reference = pd.read_csv(REPO / "data" / "counterparties.csv")
    results = evaluate_rules(frame, ruleset, {"counterparties": reference})
    lineage = build_lineage(frame, results, inject_break=True)
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    ownership = load_ownership(REPO / "governance" / "ownership.yml", glossary, ruleset)
    summary = build_summary(
        results,
        lineage.reconciliation,
        ownership,
        run_id="sample-run",
        run_at="2026-11-15T00:00:00Z",
        dataset_name="sample_transactions.csv",
        row_count=len(frame),
        input_sha256="a" * 64,
        as_of=AS_OF,
        previous=previous,
    )
    return summary


def test_rag_bands() -> None:
    green = PrincipleScore("6", "Adaptability", 100.0, True, "PASS", "grain")
    amber = PrincipleScore("4", "Completeness", 98.5, True, "PASS", "mean")
    red = PrincipleScore("3", "Accuracy and Integrity", 99.9, True, "FAIL", "mean")
    blank = PrincipleScore("11", "Distribution", None, False, "NOT_MEASURED", "none")
    assert rag_light(green) == "GREEN"
    assert rag_light(amber) == "AMBER"
    assert rag_light(red) == "RED"
    assert rag_light(blank) == "NOT MEASURED"


def test_sample_summary_is_one_a4_page(tmp_path: Path) -> None:
    summary = _sample_summary()
    path = tmp_path / "exec.pdf"
    write_executive_pdf(summary, str(path))
    _assert_one_a4_page(path)
    text = _text(path)
    assert "P11" in text
    assert "NOT MEASURED" in text
    assert "RED" in text
    assert "GREEN" in text
    assert "No previous run is stored" in text
    assert "Group Risk Data Office" in text
    assert "injects a 250000" in text
    assert "2026-11-29" in text
    assert "2026-12-06" in text
    assert "2026-12-15" in text
    assert len(summary.risks) == 3
    assert summary.risks[0].owner == "Group Risk Data Office"
    for banned in ("\u2713", "\u2717", "\u2014"):
        assert banned not in text


def test_previous_run_is_named_and_still_one_page(tmp_path: Path) -> None:
    current = _sample_summary()
    previous = StoredRun(
        run_id="prev123",
        run_at="2026-08-12T00:00:00Z",
        input_sha256="b" * 64,
        input_name="earlier.csv",
        row_count=150,
        overall_score=current.comparison.overall_score - 1.5,
        rules_passed=0,
        rules_failed=1,
        rules_total=14,
        framework_version="2.0.0",
        principles=current.scores,
        rules=(),
    )
    summary = _sample_summary(previous)
    path = tmp_path / "trend.pdf"
    write_executive_pdf(summary, str(path))
    _assert_one_a4_page(path)
    text = _text(path)
    assert "prev123" in text
    assert "delta" in text
    assert summary.comparison.overall_delta == pytest.approx(1.5)


def test_exec_summary_command_writes_one_page(tmp_path: Path) -> None:
    output = tmp_path / "board.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "governance_sentinel",
            "exec-summary",
            "--input",
            str(REPO / "data" / "sample_transactions.csv"),
            "--out",
            str(output),
            "--history-db",
            str(tmp_path / "missing.duckdb"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Overall score" in result.stdout
    _assert_one_a4_page(output)
    assert "No previous run is stored" in _text(output)
