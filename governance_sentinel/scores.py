"""Principle scores for one audit run.

A score is the control this prototype actually computes. It is not a
judgement that the BCBS 239 principle is met.

- Principles 2, 3, 4, and 5: the mean pass percentage of the YAML rules
  that cite the principle. The status is FAIL when any of those rules fail,
  including when the mean is still high.
- Principle 6: 100 when the exposure aggregate is defined at one grain
  (paragraph 49(a)). Paragraph 50 is not scored, so this score does not move
  when the data changes.
- Principle 7: the share of reconciliation slices inside tolerance. One
  failed slice fails the reconciliation. This is not a board risk report.
- Principle 11: not implemented. The score is absent.

The overall score is the unweighted mean of the measured scores for
principles 2, 3, 4, 5, 6, and 7. Principle 11 is left out because it is
not measured.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from governance_sentinel.lineage import ReconciliationResult
from governance_sentinel.models import RuleResult
from governance_sentinel.principles import PRINCIPLE_TITLES

OVERALL_PRINCIPLES: tuple[str, ...] = ("2", "3", "4", "5", "6", "7")
DASHBOARD_PRINCIPLES: tuple[str, ...] = ("3", "4", "5", "6", "7", "11")
STORED_PRINCIPLES: tuple[str, ...] = ("2", "3", "4", "5", "6", "7", "11")

_RULE_PRINCIPLES: tuple[str, ...] = ("2", "3", "4", "5")

_BASIS: dict[str, str] = {
    "2": "Mean pass percentage of the rules that support Principle 2.",
    "3": (
        "Mean pass percentage of the rules that support Principle 3. "
        "A high mean can sit next to a failed rule."
    ),
    "4": "Mean pass percentage of the rules that support Principle 4.",
    "5": (
        "Mean pass percentage of the rules that support Principle 5. "
        "The deadline in those rules is the demo T+1, not a supervisory SLA."
    ),
    "6": (
        "Paragraph 49(a): one exposure aggregate grain is defined. "
        "Paragraph 50 is not scored. The score does not move with data defects."
    ),
    "7": (
        "Share of legal-entity, currency, and reporting-date slices inside "
        "the 0.1 percent tolerance. Any failed slice fails the reconciliation. "
        "This is not a board risk report."
    ),
    "11": "Principle 11 (Distribution) is not implemented. No score is stored.",
}


@dataclass(frozen=True)
class PrincipleScore:
    """One principle on one run."""

    principle: str
    title: str
    score: float | None
    measured: bool
    status: str
    basis: str

    def to_dict(self) -> dict[str, object]:
        return {
            "principle": self.principle,
            "title": self.title,
            "score": self.score,
            "measured": self.measured,
            "status": self.status,
            "basis": self.basis,
        }


def score_principles(
    results: Sequence[RuleResult],
    reconciliation: ReconciliationResult,
) -> tuple[PrincipleScore, ...]:
    """Score every stored principle. The order is ``STORED_PRINCIPLES``."""
    scored = [_from_rules(principle, results) for principle in _RULE_PRINCIPLES]
    scored.append(_principle_6())
    scored.append(_principle_7(reconciliation))
    scored.append(_not_measured("11"))
    return tuple(scored)


def overall_score(scores: Sequence[PrincipleScore]) -> float:
    """Unweighted mean of the measured scores that enter the overall figure."""
    values = [
        item.score
        for item in scores
        if item.principle in OVERALL_PRINCIPLES and item.measured and item.score is not None
    ]
    if not values:
        raise ValueError("No measured principle score to average.")
    return round(sum(values) / len(values), 6)


def _from_rules(principle: str, results: Sequence[RuleResult]) -> PrincipleScore:
    group = [item for item in results if item.principle == principle]
    if not group:
        return _not_measured(principle)
    score = round(sum(item.pass_pct for item in group) / len(group), 6)
    status = "FAIL" if any(item.status == "FAIL" for item in group) else "PASS"
    return PrincipleScore(
        principle=principle,
        title=PRINCIPLE_TITLES[principle],
        score=score,
        measured=True,
        status=status,
        basis=_BASIS[principle],
    )


def _principle_6() -> PrincipleScore:
    return PrincipleScore(
        principle="6",
        title=PRINCIPLE_TITLES["6"],
        score=100.0,
        measured=True,
        status="PASS",
        basis=_BASIS["6"],
    )


def _principle_7(reconciliation: ReconciliationResult) -> PrincipleScore:
    slices = reconciliation.slices
    if not slices:
        score = 0.0
    else:
        passed = sum(1 for item in slices if item.status == "PASS")
        score = round(100.0 * passed / len(slices), 6)
    status = "PASS" if reconciliation.status == "PASS" else "FAIL"
    return PrincipleScore(
        principle="7",
        title=PRINCIPLE_TITLES["7"],
        score=score,
        measured=True,
        status=status,
        basis=_BASIS["7"],
    )


def _not_measured(principle: str) -> PrincipleScore:
    return PrincipleScore(
        principle=principle,
        title=PRINCIPLE_TITLES[principle],
        score=None,
        measured=False,
        status="NOT_MEASURED",
        basis=_BASIS[principle],
    )
