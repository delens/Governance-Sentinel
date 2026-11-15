"""End-to-end CLI: ``python main.py`` must exit 0 and write a PDF."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[1]


def _run(
    tmp_path: Path,
    *args: str,
    warn: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if warn:
        command.append("-Wd")
    command.append(str(REPO / "main.py"))
    command.extend(args)
    run_env = os.environ.copy()
    run_env.pop("LOG_LEVEL", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def test_python_main_exits_zero_and_writes_outputs(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    pdf = tmp_path / "Audit_Report.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    assert (tmp_path / "governance_sentinel.log").is_file()
    assert "Governance-Sentinel 2.0.0 starting" in result.stdout
    assert result.stdout.count("STEP 1/5 - Loading data (mode=mock)") == 1
    assert "will be unavailable" not in result.stdout
    assert " UTC |" in result.stdout
    assert "Pipeline completed successfully." in result.stdout
    assert (tmp_path / "data" / "generated_transactions.csv").is_file()
    text = _text(pdf)
    assert "completeness: FAIL" in text
    assert "run_id:" in text
    assert "SHA-256:" in text
    assert "four-fifths" in text
    assert "not an EU legal requirement" in text


def test_main_has_no_fpdf_deprecation_warnings(tmp_path: Path) -> None:
    result = _run(tmp_path, warn=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DeprecationWarning" not in result.stderr
    assert "FPDFUnicodeEncodingException" not in result.stderr + result.stdout


def test_real_mode_flag_reads_csv(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--mode",
        "real",
        "--csv",
        str(REPO / "data" / "sample_transactions.csv"),
        "--output",
        str(tmp_path / "real.pdf"),
        "--log-file",
        str(tmp_path / "real.log"),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "mode=real" in result.stdout
    assert "SHA-256:" in _text(tmp_path / "real.pdf")
    assert not (tmp_path / "data" / "generated_transactions.csv").exists()


def test_missing_csv_exits_one(tmp_path: Path) -> None:
    result = _run(tmp_path, "--mode", "real", "--csv", str(tmp_path / "missing.csv"))
    assert result.returncode == 1
    assert "Fatal error during execution." in result.stdout
    assert "CSV file not found" in result.stdout


def test_log_level_error_hides_info_steps(tmp_path: Path) -> None:
    result = _run(tmp_path, "--log-level", "ERROR", "--rows", "200")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "STEP 1/4" not in result.stdout
    assert (tmp_path / "Audit_Report.pdf").is_file()


def test_log_level_environment_variable(tmp_path: Path) -> None:
    result = _run(tmp_path, "--rows", "200", env={"LOG_LEVEL": "ERROR"})
    assert result.returncode == 0, result.stderr + result.stdout
    assert "STEP 1/4" not in result.stdout


def test_module_audit_writes_a_pdf(tmp_path: Path) -> None:
    output = tmp_path / "module.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "governance_sentinel",
            "audit",
            "--input",
            str(REPO / "data" / "sample_transactions.csv"),
            "--rules",
            str(REPO / "rules" / "dq_rules.yml"),
            "--out",
            str(output),
            "--log-file",
            str(tmp_path / "module.log"),
            "--no-history",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert output.read_bytes().startswith(b"%PDF")
    assert "SHA-256:" in _text(output)
    assert "LE-UK" in _text(output)
    assert "Ownership matrix:" in _text(output)
    ownership_csv = tmp_path / "ownership.csv"
    assert ownership_csv.is_file()
    assert "transaction_identifier" in ownership_csv.read_text(encoding="utf-8")


def test_module_generate_writes_the_extract(tmp_path: Path) -> None:
    output = tmp_path / "generated.csv"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "governance_sentinel",
            "generate",
            "--rows",
            "40",
            "--seed",
            "239",
            "--out",
            str(output),
            "--counterparties",
            str(tmp_path / "parties.csv"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert output.is_file()
    assert "Wrote 40 rows" in result.stdout


def test_no_history_skips_the_database(tmp_path: Path) -> None:
    result = _run(tmp_path, "--rows", "40", "--no-history", "--output", str(tmp_path / "skip.pdf"))
    assert result.returncode == 0, result.stderr + result.stdout
    assert "History persistence skipped." in result.stdout
    assert not (tmp_path / "history" / "governance_history.duckdb").exists()
    assert "Trend versus the previous run" not in _text(tmp_path / "skip.pdf")


def test_second_audit_pdf_includes_the_trend(tmp_path: Path) -> None:
    database = tmp_path / "history.duckdb"
    first = _run(
        tmp_path,
        "--rows",
        "40",
        "--history-db",
        str(database),
        "--output",
        str(tmp_path / "first.pdf"),
    )
    assert first.returncode == 0, first.stderr + first.stdout
    assert "Trend versus the previous run" not in _text(tmp_path / "first.pdf")
    second = _run(
        tmp_path,
        "--rows",
        "40",
        "--seed",
        "240",
        "--history-db",
        str(database),
        "--output",
        str(tmp_path / "second.pdf"),
    )
    assert second.returncode == 0, second.stderr + second.stdout
    assert "Trend versus the previous run" in _text(tmp_path / "second.pdf")
    assert "Principle 11 is not" in _text(tmp_path / "second.pdf")
    listed = subprocess.run(
        [sys.executable, "-m", "governance_sentinel", "history", "--db", str(database)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr + listed.stdout
    assert "runs 2" in listed.stdout
    assert "principle scores" in listed.stdout
    assert "not measured" in listed.stdout


def test_seed_history_command_is_deterministic(tmp_path: Path) -> None:
    first_db = tmp_path / "one.duckdb"
    second_db = tmp_path / "two.duckdb"
    command = [
        sys.executable,
        "-m",
        "governance_sentinel",
        "seed-history",
        "--weeks",
        "2",
        "--rows",
        "40",
        "--rules",
        str(REPO / "rules" / "dq_rules.yml"),
    ]
    first = subprocess.run(
        [*command, "--db", str(first_db)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        [*command, "--db", str(second_db)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr + first.stdout
    assert second.returncode == 0, second.stderr + second.stdout
    assert "Seeded 2 runs" in first.stdout
    assert (
        first.stdout.split("Seeded 2 runs into", maxsplit=1)[1].split("\n", maxsplit=1)[1]
        == (second.stdout.split("Seeded 2 runs into", maxsplit=1)[1].split("\n", maxsplit=1)[1])
    )


def test_import_does_not_set_tensorflow_log_level() -> None:
    script = "import os, main\nassert 'TF_CPP_MIN_LOG_LEVEL' not in os.environ\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if key != "TF_CPP_MIN_LOG_LEVEL"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
