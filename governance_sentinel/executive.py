"""One-page executive summary for a CDO or a board pack.

The page is one A4 sheet. It shows a red / amber / green light for each
principle this prototype scores, the overall score, the movement against the
previous stored run when one exists, the three largest open risks, the
accountable role from the ownership matrix, and a next action with a due date.

A light is the control in this repository. It is not a finding that the
BCBS 239 principle is met. Principle 11 is shown as not measured.

Ranking. A failed reconciliation is listed before field rules, because the
reported total does not tie to the transactions. Field rules are then ordered
by how far the pass percentage sits under the threshold, then by the share of
rows that failed. The 250000 LE-UK EUR difference is injected by the demo.
The impact sentence says so.

Due dates are 14, 21, and 30 days after the as-of date, in that rank order.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from governance_sentinel import __version__
from governance_sentinel.catalog import load_glossary
from governance_sentinel.history import (
    HistoryStore,
    RunComparison,
    StoredRun,
    compare_runs,
    snapshot_run,
)
from governance_sentinel.lineage import ReconciliationResult, build_lineage
from governance_sentinel.models import RuleResult
from governance_sentinel.ownership import OwnershipMatrix, load_ownership
from governance_sentinel.principles import PRINCIPLE_TITLES
from governance_sentinel.rules import evaluate_rules, load_rules
from governance_sentinel.scores import STORED_PRINCIPLES, PrincipleScore

_AMBER_BELOW = 99.0
_DUE_OFFSETS = (14, 21, 30)
_LIGHT_FILL = {
    "RED": (255, 205, 210),
    "AMBER": (255, 224, 178),
    "GREEN": (200, 230, 201),
    "NOT MEASURED": (224, 224, 224),
}

# Plain-language impact. A missing rule id falls back to the rule description.
_IMPACT: dict[str, str] = {
    "txn_id_populated": (
        "Blank identifiers cannot be traced to a booking, so a total can "
        "contain rows the bank cannot explain."
    ),
    "txn_id_unique": "Duplicate identifiers can count the same exposure twice.",
    "exposure_populated": (
        "Missing amounts are left out of the sum, so the reported exposure is short."
    ),
    "exposure_non_negative": (
        "Negative amounts reduce the total. In this extract they are not hedges."
    ),
    "exposure_outlier": (
        "A few very large amounts can move a legal-entity total on their own. "
        "The fence is a screen, not a risk limit."
    ),
    "currency_populated": "A blank currency cannot be added into a currency total.",
    "currency_domain": "An unknown currency code cannot be placed in the exposure by currency.",
    "rating_populated": (
        "A blank rating is not the unrated grade NR. A report that uses the grade "
        "is missing that name."
    ),
    "rating_domain": "A grade off the scale cannot be read as a credit rating.",
    "legal_entity_domain": "An unknown entity code cannot be rolled into a group exposure.",
    "product_domain": "An unknown product cannot be classified in the exposure breakdown.",
    "counterparty_known": (
        "An exposure with no known counterparty cannot be named in a concentration report."
    ),
    "availability_t_plus_1": (
        "Late records miss the demo T+1 window. Principle 5 leaves the real "
        "deadline to the bank. This is not a supervisory SLA."
    ),
    "reporting_date_populated": "Without an as-of date the row has no reporting period.",
}

_ACTION: dict[str, str] = {
    "reconciliation": (
        "Explain the gap between the reported total and the transaction sum, "
        "and correct whichever figure is wrong."
    ),
    "txn_id_populated": (
        "Fill in the blank transaction identifiers before the next reporting date."
    ),
    "txn_id_unique": "Keep one row per transaction identifier and remove the duplicates.",
    "exposure_populated": (
        "Obtain the missing exposure amounts. Do not replace an unknown amount with zero."
    ),
    "exposure_non_negative": "Correct the negative amounts. They are not hedges in this extract.",
    "exposure_outlier": (
        "Review each amount above the interquartile fence and confirm it or correct it."
    ),
    "currency_populated": "Fill in the blank currency codes.",
    "currency_domain": "Replace currency codes that are not on the glossary list.",
    "rating_populated": "Fill in the blank ratings. NR is the grade for unrated, not a blank.",
    "rating_domain": "Replace ratings that are not on the scale.",
    "legal_entity_domain": "Correct legal-entity codes that are not on the group list.",
    "product_domain": "Map product codes onto the glossary list.",
    "counterparty_known": "Match the unknown counterparties to the master, or add them to it.",
    "availability_t_plus_1": (
        "Deliver the late records inside the demo T+1 window, or record the lag as an exception."
    ),
    "reporting_date_populated": "Reject rows that have no reporting date.",
}


@dataclass(frozen=True)
class BoardRisk:
    """One item on the one-page summary."""

    rank_key: str
    title: str
    impact: str
    principle_label: str
    owner: str
    steward: str
    action: str
    due: date
    severity: float


@dataclass(frozen=True)
class ExecutiveSummary:
    """The figures the one-page PDF prints."""

    run_id: str
    dataset_name: str
    row_count: int
    as_of: date
    scores: tuple[PrincipleScore, ...]
    comparison: RunComparison
    risks: tuple[BoardRisk, ...]


def rag_light(score: PrincipleScore) -> str:
    """Red, amber, green, or not measured.

    Red: the control failed. Amber: it passed and the score is under 99.
    Green: it passed and the score is at least 99. Not measured: no score.
    """
    if not score.measured or score.status == "NOT_MEASURED" or score.score is None:
        return "NOT MEASURED"
    if score.status == "FAIL":
        return "RED"
    if score.score < _AMBER_BELOW:
        return "AMBER"
    return "GREEN"


def build_summary(
    results: Sequence[RuleResult],
    reconciliation: ReconciliationResult,
    ownership: OwnershipMatrix,
    *,
    run_id: str,
    run_at: str,
    dataset_name: str,
    row_count: int,
    input_sha256: str,
    as_of: date,
    previous: StoredRun | None = None,
) -> ExecutiveSummary:
    """Score the run, rank at most three risks, and attach due dates."""
    current = snapshot_run(
        run_id=run_id,
        run_at=run_at,
        input_sha256=input_sha256,
        input_name=dataset_name,
        row_count=row_count,
        results=results,
        reconciliation=reconciliation,
    )
    comparison = compare_runs(current, previous)
    risks = _risks(results, reconciliation, ownership, as_of)
    return ExecutiveSummary(
        run_id=run_id,
        dataset_name=dataset_name,
        row_count=row_count,
        as_of=as_of,
        scores=current.principles,
        comparison=comparison,
        risks=risks,
    )


def write_summary_for_extract(
    transactions: Path,
    *,
    rules_path: Path,
    counterparties: Path,
    glossary_path: Path,
    ownership_path: Path,
    output_path: Path,
    history_db: Path | None = None,
    as_of: date | None = None,
    run_id: str | None = None,
) -> ExecutiveSummary:
    """Audit one CSV and write the one-page PDF.

    A missing or empty history file leaves the trend blank. This command
    does not append a run to the history file. The reconciliation uses the
    same injected LE-UK EUR break as the full audit.
    """
    frame = pd.read_csv(transactions)
    ruleset = load_rules(rules_path)
    reference = pd.read_csv(counterparties)
    results = evaluate_rules(frame, ruleset, {"counterparties": reference})
    lineage = build_lineage(frame, results, inject_break=True)
    glossary = load_glossary(glossary_path, ruleset)
    ownership = load_ownership(ownership_path, glossary, ruleset)
    previous = _latest_run(history_db)
    today = datetime.now(timezone.utc).date() if as_of is None else as_of
    digest = hashlib.sha256(transactions.read_bytes()).hexdigest()
    summary = build_summary(
        results,
        lineage.reconciliation,
        ownership,
        run_id=run_id or uuid.uuid4().hex,
        run_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        dataset_name=transactions.name,
        row_count=len(frame),
        input_sha256=digest,
        as_of=today,
        previous=previous,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_executive_pdf(summary, str(output_path))
    return summary


def _latest_run(history_db: Path | None) -> StoredRun | None:
    if history_db is None or not history_db.is_file():
        return None
    stored = HistoryStore(history_db).list_runs()
    if not stored:
        return None
    return stored[-1]


def write_executive_pdf(summary: ExecutiveSummary, output_path: str) -> None:
    """Write the summary. Raises if the content does not fit on one A4 page."""
    pdf = FPDF(format="A4")
    pdf.set_title("Governance-Sentinel Executive Summary")
    pdf.set_author("Daniele Delens")
    pdf.set_subject("One-page BCBS 239 control scorecard")
    pdf.set_margins(12, 10, 12)
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    _font(pdf, 14, "B")
    _centered(pdf, "Governance-Sentinel  |  Executive summary", 6)
    _font(pdf, 8)
    _centered(
        pdf,
        f"Version {__version__}  |  BCBS 239, Basel Committee, January 2013  |  "
        f"As of {summary.as_of.isoformat()}",
        4,
    )
    _centered(
        pdf,
        "A light is the control in this prototype. It is not a finding that the principle is met.",
        4,
    )
    pdf.ln(1)

    _font(pdf, 8)
    _line(
        pdf,
        f"Run {summary.run_id}   |   {summary.row_count} rows   |   {summary.dataset_name}",
        4,
    )
    _paragraph(pdf, _trend_sentence(summary.comparison))
    _paragraph(
        pdf,
        "The overall score is the unweighted mean of principles 2, 3, 4, 5, 6, and 7. "
        "Principle 11 is not in the average. A red principle can sit under a high average. "
        "Principles 1, 8, 9, 10, and 12 to 14 are not scored.",
    )

    _font(pdf, 10, "B")
    _line(pdf, "Principle lights", 5)
    _font(pdf, 7)
    _paragraph(
        pdf,
        "RED: the control failed. AMBER: it passed and the score is under 99. "
        "GREEN: it passed and the score is at least 99. NOT MEASURED: no score.",
    )
    _score_table(pdf, summary.scores)
    pdf.ln(1)

    _font(pdf, 10, "B")
    _line(pdf, "Top risks", 5)
    _font(pdf, 8)
    if not summary.risks:
        _paragraph(pdf, "No failed control on this run.")
    for index, risk in enumerate(summary.risks, start=1):
        _font(pdf, 8, "B")
        _line(pdf, f"{index}. {risk.title}", 4)
        _font(pdf, 8)
        _paragraph(
            pdf,
            f"{risk.principle_label} Accountable owner: {risk.owner}. "
            f"Steward: {risk.steward}. {risk.impact}",
        )

    _font(pdf, 10, "B")
    _line(pdf, "Next actions", 5)
    _font(pdf, 8)
    if not summary.risks:
        _paragraph(pdf, "No action is due from this run.")
    for index, risk in enumerate(summary.risks, start=1):
        _paragraph(
            pdf,
            f"{index}. Due {risk.due.isoformat()}. {risk.owner}. {risk.action}",
        )

    pdf.ln(1)
    _font(pdf, 7)
    _paragraph(
        pdf,
        "Prepared by Daniele Delens. Synthetic data. Not a supervisory filing and "
        "not evidence from a production control. The fairness illustration is in "
        "the full audit report, not on this page.",
    )

    if pdf.page != 1:
        raise RuntimeError(
            "Executive summary exceeded one A4 page "
            f"({pdf.page} pages). Shorten the narrative before writing the file."
        )
    pdf.output(output_path)


def _risks(
    results: Sequence[RuleResult],
    reconciliation: ReconciliationResult,
    ownership: OwnershipMatrix,
    as_of: date,
) -> tuple[BoardRisk, ...]:
    ranked: list[BoardRisk] = []
    reconciliation_risk = _reconciliation_risk(reconciliation, ownership)
    if reconciliation_risk is not None:
        ranked.append(reconciliation_risk)
    for failed in results:
        if failed.status != "FAIL":
            continue
        rows = ownership.for_rule(failed.rule_id)
        if not rows:
            raise ValueError(f"Failed rule {failed.rule_id} has no ownership-matrix row.")
        share = failed.records_failed / failed.records_checked if failed.records_checked else 0.0
        ranked.append(
            BoardRisk(
                rank_key=failed.rule_id,
                title=(
                    f"{failed.rule_id} failed "
                    f"({failed.pass_pct:.2f}% against a minimum of {failed.threshold:.2f}%)"
                ),
                impact=_sentence(_IMPACT.get(failed.rule_id, failed.description)),
                principle_label=f"Principle {failed.principle} ({failed.principle_title}).",
                owner=", ".join(_unique(row.data_owner for row in rows)),
                steward=", ".join(_unique(row.data_steward for row in rows)),
                action=_sentence(_ACTION.get(failed.rule_id, failed.remediation)),
                due=as_of,
                severity=(failed.threshold - failed.pass_pct) + share,
            )
        )
    ranked.sort(key=lambda risk: (-risk.severity, risk.rank_key))
    chosen = ranked[:3]
    dated: list[BoardRisk] = []
    for index, risk in enumerate(chosen):
        dated.append(
            BoardRisk(
                rank_key=risk.rank_key,
                title=risk.title,
                impact=risk.impact,
                principle_label=risk.principle_label,
                owner=risk.owner,
                steward=risk.steward,
                action=risk.action,
                due=as_of + timedelta(days=_DUE_OFFSETS[index]),
                severity=risk.severity,
            )
        )
    return tuple(dated)


def _reconciliation_risk(
    reconciliation: ReconciliationResult,
    ownership: OwnershipMatrix,
) -> BoardRisk | None:
    failed = reconciliation.failed_slices
    if reconciliation.status != "FAIL" or not failed:
        return None
    row = ownership.by_term("aggregated_exposure")
    worst = max(failed, key=lambda item: abs(item.difference))
    noun = "slice" if len(failed) == 1 else "slices"
    verb = "is" if len(failed) == 1 else "are"
    impact = (
        f"The {worst.legal_entity_id} {worst.currency} reported total differs from "
        f"the transaction sum by {worst.difference:.0f}. {len(failed)} {noun} {verb} "
        f"outside the {reconciliation.tolerance_pct:.1f} percent tolerance, so the "
        "pack is not showing the sum of the transactions."
    )
    if reconciliation.injected_break:
        impact += " This demo injects a 250000 difference on LE-UK in EUR."
    return BoardRisk(
        rank_key="",
        title="Reported total does not tie to the transactions",
        impact=_sentence(impact),
        principle_label="Principles 3 and 7, the tie from a reported total back to transactions.",
        owner=row.data_owner,
        steward=row.data_steward,
        action=_ACTION["reconciliation"],
        due=date.min,
        severity=1000.0,
    )


def _trend_sentence(comparison: RunComparison) -> str:
    score = f"{comparison.overall_score:.2f}"
    if comparison.previous_run_id is None or comparison.previous_overall is None:
        return f"Overall score {score}. No previous run is stored, so there is no trend."
    delta = _signed(comparison.overall_delta)
    return (
        f"Overall score {score}. Previous run {comparison.previous_run_id} "
        f"scored {comparison.previous_overall:.2f} (delta {delta})."
    )


def _score_table(pdf: FPDF, scores: Sequence[PrincipleScore]) -> None:
    by_principle = {item.principle: item for item in scores}
    widths = (16, 78, 22, 36)
    headers = ("Principle", "Title", "Score", "Light")
    _font(pdf, 7, "B")
    _cells(pdf, headers, widths, 4.5, fill=None)
    for principle in STORED_PRINCIPLES:
        item = by_principle.get(principle)
        if item is None:
            item = PrincipleScore(
                principle=principle,
                title=PRINCIPLE_TITLES[principle],
                score=None,
                measured=False,
                status="NOT_MEASURED",
                basis="",
            )
        light = rag_light(item)
        score = "n/a" if item.score is None else f"{item.score:.2f}"
        _font(pdf, 7)
        _cells(
            pdf,
            (f"P{principle}", item.title, score, light),
            widths,
            4.5,
            fill=light,
        )


def _cells(
    pdf: FPDF,
    values: tuple[str, ...],
    widths: tuple[float, ...],
    height: float,
    *,
    fill: str | None,
) -> None:
    for index, (value, width) in enumerate(zip(values, widths, strict=True)):
        last = index == len(values) - 1
        painted = fill is not None and index == len(values) - 1
        if painted:
            pdf.set_fill_color(*_LIGHT_FILL[value])
        pdf.cell(
            width,
            height,
            value,
            border=1,
            align="L",
            fill=painted,
            new_x=XPos.LMARGIN if last else XPos.RIGHT,
            new_y=YPos.NEXT if last else YPos.TOP,
        )


def _sentence(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 320:
        return compact
    return compact[:317].rstrip() + "..."


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def _font(pdf: FPDF, size: float, style: str = "") -> None:
    pdf.set_font("Helvetica", style=style, size=size)


def _line(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _centered(pdf: FPDF, text: str, height: float) -> None:
    pdf.cell(0, height, text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _paragraph(pdf: FPDF, text: str) -> None:
    pdf.multi_cell(0, 3.6, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
