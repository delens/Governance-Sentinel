"""Write the audit PDF.

The report uses Helvetica, a core PDF font limited to Latin-1. Status labels
are ASCII (``PASS`` / ``FAIL``) so generation does not depend on a Unicode font.

``threshold`` on each rule is the minimum pass percentage. A field-level PASS
is not the same thing as compliance with the BCBS 239 principle the rule cites.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from governance_sentinel import __version__
from governance_sentinel.models import FairnessResult, RuleResult
from governance_sentinel.principles import NOT_IMPLEMENTED
from governance_sentinel.rules import dimension_rollup

logger = logging.getLogger(__name__)

# Keep this aligned with governance_sentinel.__version__ and the changelog.
FRAMEWORK_VERSION = __version__

# US EEOC four-fifths rule, used only as a heuristic cutoff.
DI_THRESHOLD = 0.80

_TABLE_WIDTHS = (42, 28, 24, 16, 16, 18, 18, 18)


def create_pdf_report(
    rule_results: Sequence[RuleResult],
    fairness: FairnessResult,
    *,
    run_id: str,
    dataset_sha256: str,
    row_count: int,
    output_path: str = "Audit_Report.pdf",
    dataset_name: str = "",
) -> None:
    """Write the audit PDF to ``output_path``.

    ``generated_at`` is timezone-aware UTC. A naive local clock labelled "UTC"
    is not used.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    pdf = FPDF(format="A4")
    pdf.set_title("Governance-Sentinel Audit Report")
    pdf.set_author("Daniele Delens")
    pdf.set_subject("BCBS 239 data-quality rules and a disparate-impact audit")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    _font(pdf, 16, "B")
    _centered(pdf, "Governance-Sentinel Audit Report", 9)
    _font(pdf, 9)
    _centered(pdf, f"Framework version: {FRAMEWORK_VERSION}", 5)
    _centered(pdf, f"Generated: {generated_at}", 5)
    _centered(pdf, "Reference: BCBS 239, Basel Committee, January 2013", 5)
    pdf.ln(2)

    _font(pdf, 11, "B")
    _line(pdf, "Run", 6)
    _font(pdf, 9)
    _line(pdf, f"run_id: {run_id}", 5)
    _line(pdf, f"Records: {row_count}", 5)
    if dataset_name:
        _paragraph(pdf, f"Dataset: {dataset_name}")
    _paragraph(pdf, f"SHA-256: {dataset_sha256}")
    pdf.ln(1)

    _font(pdf, 13, "B")
    _line(pdf, "1. Data-quality scorecard", 7)
    _font(pdf, 9)
    _paragraph(
        pdf,
        "Each rule is a field check on a critical data element. The threshold "
        "is the minimum pass percentage. PASS means at least one record was "
        "checked and the pass percentage is at least the threshold. A PASS on "
        "one rule is not compliance with the BCBS 239 principle it supports. "
        "Validity is a data-quality dimension. It is not a BCBS 239 principle. "
        "The timeliness rule measures business-day lag from the reporting date "
        "to the availability date. The demo limit is T+1. Principle 5 leaves "
        "the real deadline to the bank. The exposure outlier rule is an "
        "interquartile-range screen. It is a heuristic, not a risk limit.",
    )

    _font(pdf, 10, "B")
    _line(pdf, "Dimension rollup", 6)
    _font(pdf, 9)
    for dimension, status, rule_count, failed_count in dimension_rollup(list(rule_results)):
        _line(
            pdf,
            f"{dimension}: {status} ({failed_count} of {rule_count} rules failed)",
            5,
        )
    pdf.ln(1)

    headers = (
        "Rule",
        "CDE",
        "Dimension",
        "Checked",
        "Failed",
        "Pass %",
        "Min %",
        "Status",
    )
    _table_header(pdf, headers)
    for item in rule_results:
        _table_row(
            pdf,
            (
                item.rule_id,
                item.cde,
                item.dimension,
                str(item.records_checked),
                str(item.records_failed),
                f"{item.pass_pct:.2f}",
                f"{item.threshold:.2f}",
                item.status,
            ),
        )
    pdf.ln(3)

    _font(pdf, 13, "B")
    _line(pdf, "2. Remediation", 7)
    _font(pdf, 9)
    failed_rules = [item for item in rule_results if item.status == "FAIL"]
    if not failed_rules:
        _paragraph(pdf, "No failed rule. No remediation item on this run.")
    for item in failed_rules:
        _font(pdf, 10, "B")
        _line(pdf, f"{item.rule_id}: FAIL", 5)
        _font(pdf, 9)
        _paragraph(
            pdf,
            f"Principle {item.principle} ({item.principle_title}). "
            f"Owner: {item.owner}. Steward: {item.steward}.",
        )
        _paragraph(
            pdf,
            f"Checked {item.records_checked}, failed {item.records_failed}, "
            f"pass {item.pass_pct:.2f}%, minimum {item.threshold:.2f}%.",
        )
        if item.sample_failing_ids:
            extra = len(item.failing_ids) - len(item.sample_failing_ids)
            sample = ", ".join(item.sample_failing_ids)
            suffix = f" (+{extra} more)" if extra > 0 else ""
            _paragraph(pdf, f"Sample failing ids: {sample}{suffix}.")
        _paragraph(pdf, item.description)
        if item.detail:
            _paragraph(pdf, item.detail)
        _paragraph(pdf, f"Action: {item.remediation}")
        pdf.ln(1)

    _font(pdf, 9)
    not_implemented = ", ".join(
        f"Principle {number} ({title})" for number, title in NOT_IMPLEMENTED
    )
    _paragraph(
        pdf,
        "Not implemented as a control in this report: "
        f"{not_implemented}. Principle 7 is about how accurately risk reports "
        "convey aggregated data. It is separate from Principle 3. Principle 6 "
        "is the ability to aggregate on demand. Principle 11 is distribution "
        "and confidentiality. The rule inventory above is a validation list "
        "of the kind paragraph 53(b) describes. Holding the list is not an "
        "accurate risk report.",
    )
    pdf.ln(2)

    _font(pdf, 13, "B")
    _line(pdf, "3. Algorithmic fairness (disparate impact)", 7)
    _font(pdf, 9)
    _paragraph(
        pdf,
        "Illustrative bias measure for discussions of EU AI Act Article 10 "
        "(data and data governance). This is not an Article 13 transparency "
        "file and not a conformity assessment. "
        f"The {fairness.threshold:.2f} cutoff is the US EEOC four-fifths rule "
        "of thumb. It is a heuristic for this demo. It is not a threshold in "
        "the EU AI Act, and it is not an EU legal requirement.",
    )
    _paragraph(
        pdf,
        "The ratio is P(loan approved | age_category 1) divided by "
        "P(loan approved | age_category 2). In this synthetic file, "
        "age_category 1 is the unprivileged group (label 40_and_over) and "
        "age_category 2 is the privileged group (label under_40). Those labels "
        "are not a legal age classification. Rows are excluded only when "
        "age_category or loan_approved is missing. A null in another column, "
        "including transaction_id, stays in the metric.",
    )
    _line(pdf, f"Rows excluded (missing group or label): {fairness.rows_excluded}", 5)
    _line(
        pdf,
        "Unprivileged n="
        f"{fairness.unprivileged_count}, selection rate {fairness.unprivileged_rate:.4f}",
        5,
    )
    _line(
        pdf,
        f"Privileged n={fairness.privileged_count}, selection rate {fairness.privileged_rate:.4f}",
        5,
    )
    ratio_text = f"{fairness.ratio:.4f}" if fairness.defined else "undefined"
    _line(pdf, f"Disparate impact ratio: {ratio_text}", 5)
    _line(
        pdf,
        f"Heuristic cutoff: {fairness.threshold:.2f} (US EEOC four-fifths rule)",
        5,
    )
    _line(pdf, f"Status: {_fairness_status(fairness)}", 5)
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


def _fairness_status(fairness: FairnessResult) -> str:
    if not fairness.defined or math.isnan(fairness.ratio):
        return "UNDEFINED [privileged selection rate is zero, or the ratio is not finite]"
    if fairness.ratio >= fairness.threshold:
        return "PASS against the four-fifths heuristic"
    return "FAIL against the four-fifths heuristic"


def _table_header(pdf: FPDF, headers: tuple[str, ...]) -> None:
    _font(pdf, 7, "B")
    _cells(pdf, headers, 6)


def _table_row(pdf: FPDF, values: tuple[str, ...]) -> None:
    _font(pdf, 7)
    _cells(pdf, values, 5)


def _cells(pdf: FPDF, values: tuple[str, ...], height: float) -> None:
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()
    for index, (value, width) in enumerate(zip(values, _TABLE_WIDTHS, strict=True)):
        last = index == len(values) - 1
        pdf.cell(
            width,
            height,
            value,
            border=1,
            align="L",
            new_x=XPos.LMARGIN if last else XPos.RIGHT,
            new_y=YPos.NEXT if last else YPos.TOP,
        )


def _font(pdf: FPDF, size: float, style: str = "") -> None:
    pdf.set_font("Helvetica", style=style, size=size)


def _line(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _centered(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _paragraph(pdf: FPDF, text: str) -> None:
    pdf.multi_cell(0, 4.5, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
