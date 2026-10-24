"""Write the one-page audit PDF.

The report uses Helvetica, a core PDF font limited to Latin-1. Status labels
are ASCII (``PASS`` / ``FAIL``) so generation does not depend on a Unicode font.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from validators import (
    AMOUNT_MAX,
    AMOUNT_MIN,
    APPROVED_CURRENCIES,
    DQ_DIMENSIONS,
    NOT_IMPLEMENTED,
    TIMELINESS_REFERENCE_DATE,
)

logger = logging.getLogger(__name__)

# Keep this aligned with the changelog in README.md.
FRAMEWORK_VERSION = "1.2.0"

# US EEOC four-fifths rule, used only as an illustrative cutoff.
DI_THRESHOLD = 0.80


def create_pdf_report(
    dq_results: Mapping[str, bool],
    bias_score: float,
    output_path: str = "Audit_Report.pdf",
) -> None:
    """Write the audit PDF to ``output_path``.

    ``generated_at`` is timezone-aware UTC. A naive local clock labelled "UTC"
    is not used.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    pdf = FPDF(format="A4")
    pdf.set_title("Governance-Sentinel Audit Report")
    pdf.set_author("Daniele Delens")
    pdf.set_subject("BCBS 239 data-quality checks and a disparate-impact audit")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    _font(pdf, 16, "B")
    _centered(pdf, "Governance-Sentinel Audit Report", 9)
    _font(pdf, 9)
    _centered(pdf, f"Framework version: {FRAMEWORK_VERSION}", 5)
    _centered(pdf, f"Generated: {generated_at}", 5)
    _centered(pdf, "Reference: BCBS 239, Basel Committee, January 2013", 5)
    pdf.ln(3)

    _font(pdf, 13, "B")
    _line(pdf, "1. BCBS 239 data-quality audit", 7)
    _font(pdf, 10)
    _paragraph(
        pdf,
        "Field-level checks on critical data elements. Principle numbers follow "
        "BCBS 239 (BIS, January 2013). A PASS on one field is not the same as "
        "compliance with the whole principle.",
    )

    for dimension in DQ_DIMENSIONS:
        if dimension not in dq_results:
            continue
        _font(pdf, 11)
        _line(pdf, _check_line(dimension, bool(dq_results[dimension])), 6)
        _font(pdf, 9)
        _paragraph(pdf, _check_note(dimension))

    for dimension, passed in dq_results.items():
        if dimension in DQ_DIMENSIONS:
            continue
        logger.warning("No BCBS 239 mapping for dimension %s.", dimension)
        _font(pdf, 11)
        _line(pdf, f"[unmapped] {dimension}: {'PASS' if passed else 'FAIL'}", 6)

    _font(pdf, 9)
    not_implemented = ", ".join(
        f"Principle {number} ({title})" for number, title in NOT_IMPLEMENTED
    )
    _paragraph(
        pdf,
        "Not implemented in this prototype: "
        f"{not_implemented}. Principle 7 is about how accurately risk reports "
        "convey aggregated data. It is separate from Principle 3.",
    )
    pdf.ln(2)

    _font(pdf, 13, "B")
    _line(pdf, "2. Algorithmic fairness (disparate impact)", 7)
    _font(pdf, 10)
    _paragraph(
        pdf,
        "Illustrative bias measure for discussions of EU AI Act Article 10 "
        "(data governance). This is not an Article 13 transparency file and "
        "not a conformity assessment. The 0.80 cutoff is the US EEOC "
        "four-fifths rule, which the EU AI Act does not itself prescribe.",
    )
    _font(pdf, 11)
    _line(pdf, f"Disparate impact ratio: {bias_score:.4f}", 6)
    _line(pdf, f"Illustrative threshold: {DI_THRESHOLD:.2f} (US EEOC four-fifths rule)", 6)
    _line(pdf, f"Status: {_di_status(bias_score)}", 6)
    if bias_score == 0.0:
        _font(pdf, 9)
        _paragraph(
            pdf,
            "DI = 0.00 on this synthetic file: the unprivileged group "
            "(age_category 1) has no positive labels and the privileged group "
            "(age_category 2) does. That is a property of the demo data.",
        )

    pdf.ln(3)
    y_position = pdf.get_y()
    pdf.set_draw_color(80, 80, 80)
    pdf.line(pdf.l_margin, y_position, pdf.w - pdf.r_margin, y_position)
    pdf.ln(3)
    _font(pdf, 9)
    _line(pdf, "Prepared by: Daniele Delens - Senior Data Governance and BCBS 239 Specialist", 5)
    _line(
        pdf,
        "Demo output on synthetic data. Not a supervisory filing and not evidence "
        "from a production control.",
        5,
    )

    pdf.output(output_path)
    logger.info("PDF report written to %s.", output_path)


def _di_status(bias_score: float) -> str:
    if math.isnan(bias_score):
        return "FAIL [SCORE UNDEFINED]"
    if bias_score >= DI_THRESHOLD:
        return "PASS"
    return "FAIL [CRITICAL REMEDIATION REQUIRED]"


def _check_line(dimension: str, passed: bool) -> str:
    info = DQ_DIMENSIONS[dimension]
    status = "PASS" if passed else "FAIL"
    return f"[Principle {info['principle']} - {info['principle_title']}] {dimension}: {status}"


def _check_note(dimension: str) -> str:
    currencies = ", ".join(APPROVED_CURRENCIES)
    notes = {
        "Completeness": (
            "transaction_id must be populated. This supports Principle 4. "
            "It does not, by itself, show group-wide risk-data aggregation."
        ),
        "Accuracy": (
            f"amount must be present and between {AMOUNT_MIN} and {AMOUNT_MAX} "
            "inclusive. This is a threshold check, not a statistical outlier test. "
            "It supports Principle 3, not Principle 7."
        ),
        "Validity": (
            f"currency must be present and one of {currencies}. Validity is a "
            "data-quality dimension supporting Principle 3. It is not a BCBS 239 principle."
        ),
        "Timeliness": (
            "timestamp must be present and on or after "
            f"{TIMELINESS_REFERENCE_DATE}. Demo reference date for Principle 5. "
            "This is not a T+1 control."
        ),
    }
    return notes[dimension]


def _font(pdf: FPDF, size: float, style: str = "") -> None:
    pdf.set_font("Helvetica", style=style, size=size)


def _line(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _centered(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _paragraph(pdf: FPDF, text: str) -> None:
    pdf.multi_cell(
        0,
        4.5,
        text,
        align="L",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
