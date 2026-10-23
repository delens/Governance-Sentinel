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
    assert (tmp_path / "raw_financial_data.csv").is_file()
    assert "Governance-Sentinel 1.2.0 starting" in result.stdout
    assert result.stdout.count("STEP 1/4 - Loading data (mode=mock)") == 1
    assert "will be unavailable" not in result.stdout
    assert " UTC |" in result.stdout
    assert "Pipeline completed successfully." in result.stdout
    text = _text(pdf)
    assert "Completeness: FAIL" in text
    assert "Disparate impact ratio: 0.0000" in text


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
        str(REPO / "raw_financial_data.csv"),
        "--output",
        str(tmp_path / "real.pdf"),
        "--log-file",
        str(tmp_path / "real.log"),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "mode=real" in result.stdout
    assert "Completeness: FAIL" in _text(tmp_path / "real.pdf")
    assert not (tmp_path / "raw_financial_data.csv").exists()


def test_missing_csv_exits_one(tmp_path: Path) -> None:
    result = _run(tmp_path, "--mode", "real", "--csv", str(tmp_path / "missing.csv"))
    assert result.returncode == 1
    assert "Fatal error during execution." in result.stdout
    assert "CSV file not found" in result.stdout


def test_log_level_error_hides_info_steps(tmp_path: Path) -> None:
    result = _run(tmp_path, "--log-level", "ERROR")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "STEP 1/4" not in result.stdout
    assert (tmp_path / "Audit_Report.pdf").is_file()


def test_log_level_environment_variable(tmp_path: Path) -> None:
    result = _run(tmp_path, env={"LOG_LEVEL": "ERROR"})
    assert result.returncode == 0, result.stderr + result.stdout
    assert "STEP 1/4" not in result.stdout


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
