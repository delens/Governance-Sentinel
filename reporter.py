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
from governance_sentinel.history import RunComparison
from governance_sentinel.lineage import LineageReport
from governance_sentinel.models import FairnessResult, RuleResult
from governance_sentinel.ownership import OwnershipMatrix, ownership_sentence
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
    lineage: LineageReport | None = None,
    trend: RunComparison | None = None,
    ownership: OwnershipMatrix | None = None,
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
        if ownership is not None:
            _paragraph(pdf, ownership_sentence(ownership, item.rule_id))
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
    _paragraph(
        pdf,
        "Principle 6 (Adaptability), paragraphs 48-50: the exposure aggregate "
        "is one grain, by legal entity, currency, and reporting date "
        "(paragraph 49(a)). It is not an on-demand subset for a supervisory "
        "query (paragraph 50). Principle 7 (Accuracy), paragraphs 52-56: the "
        "reconciliation, when this run includes one, is the paragraph 53(a) "
        "tie from a reported total back to transaction risk data. It is not "
        "a board risk report. Principle 11 (Distribution) is not implemented. "
        "The rule inventory is a validation list of the kind paragraph 53(b) "
        "describes. Holding the list is not an accurate risk report.",
    )
    pdf.ln(2)

    next_section = 3
    if lineage is not None:
        _write_lineage(pdf, lineage, next_section)
        next_section += 1
    if trend is not None and trend.previous_run_id is not None:
        _write_trend(pdf, trend, next_section)
        next_section += 1

    _font(pdf, 13, "B")
    _line(pdf, f"{next_section}. Algorithmic fairness (disparate impact)", 7)
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


def _write_lineage(pdf: FPDF, lineage: LineageReport, section: int) -> None:
    _font(pdf, 13, "B")
    _line(pdf, f"{section}. Lineage and reconciliation", 7)
    _font(pdf, 9)
    _paragraph(
        pdf,
        "Flow: core_banking.transactions to staging.risk_transactions to "
        "risk_mart.exposure_by_entity. The source node is NOT_MEASURED. "
        "Rules run on the staged extract. The aggregate inherits a staging "
        "FAIL, and it also FAILs when the transaction sum does not tie to "
        "the reported total. Principle 3, paragraph 36(c), and Principle 7, "
        "paragraph 53(a), are the basis for that tie. Footnote 17 defines "
        "reconciliation as comparing items and explaining the difference.",
    )
    for node in lineage.nodes:
        status = lineage.statuses.get(node.node_id, "NOT_MEASURED")
        _line(pdf, f"{node.dataset} ({node.layer}): {status}", 5)
    recon = lineage.reconciliation
    _line(
        pdf,
        f"Reconciliation: {recon.status} at tolerance {recon.tolerance_pct:.1f} percent.",
        5,
    )
    if recon.injected_break:
        _paragraph(
            pdf,
            "The reported total copies the transaction sum, then adds 250000 "
            "on LE-UK in EUR. That break is injected so the control has a "
            "known difference to explain.",
        )
    failed = recon.failed_slices
    if not failed:
        _paragraph(pdf, "No reconciliation slice failed.")
    for item in failed[:8]:
        _paragraph(
            pdf,
            f"{item.legal_entity_id} {item.currency} {item.reporting_date}: "
            f"transactions {item.transaction_total:.2f}, "
            f"reported {item.reported_total:.2f}, "
            f"difference {item.difference:.2f}.",
        )
    pdf.ln(2)


def _write_trend(pdf: FPDF, trend: RunComparison, section: int) -> None:
    """Short comparison with the previous stored run. Omitted when there is none."""
    _font(pdf, 13, "B")
    _line(pdf, f"{section}. Trend versus the previous run", 7)
    _font(pdf, 9)
    previous_overall = trend.previous_overall
    if previous_overall is None:
        return
    _paragraph(
        pdf,
        f"Compared with run {trend.previous_run_id}. "
        f"Overall score {trend.overall_score:.2f} versus {previous_overall:.2f} "
        f"(delta {_signed(trend.overall_delta)} percentage points). "
        "The overall score is the unweighted mean of the measured principle "
        "scores for principles 2, 3, 4, 5, 6, and 7. Principle 11 is not "
        "measured and is excluded. A principle score is the control in this "
        "prototype. It is not compliance with the principle.",
    )
    for item in trend.principles:
        if item.current is None:
            _paragraph(pdf, f"P{item.principle} {item.title}: not measured.")
            continue
        if item.previous is None or item.delta is None:
            _paragraph(pdf, f"P{item.principle} {item.title}: {item.current:.2f}.")
            continue
        _paragraph(
            pdf,
            f"P{item.principle} {item.title}: {item.current:.2f} versus "
            f"{item.previous:.2f} (delta {_signed(item.delta)}). "
            f"Status {item.previous_status} to {item.current_status}.",
        )
    if trend.rule_changes:
        changed = ", ".join(
            f"{item.rule_id} {item.previous_status} to {item.current_status}"
            for item in trend.rule_changes
        )
        _paragraph(pdf, f"Rules that changed status: {changed}.")
    else:
        _paragraph(pdf, "No rule changed status versus the previous run.")
    pdf.ln(2)


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"


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
