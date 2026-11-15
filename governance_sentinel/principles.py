"""Official BCBS 239 principle titles used by the rules and the report.

Numbers and titles follow the Basel Committee on Banking Supervision,
*Principles for effective risk data aggregation and risk reporting*
(January 2013, https://www.bis.org/publ/bcbs239.pdf).

A rule that names a principle supports that principle. It does not, by
itself, mean the principle is met.
"""

from __future__ import annotations

PRINCIPLE_TITLES: dict[str, str] = {
    "2": "Data architecture and IT infrastructure",
    "3": "Accuracy and Integrity",
    "4": "Completeness",
    "5": "Timeliness",
    "6": "Adaptability",
    "7": "Accuracy",
    "11": "Distribution",
}

# Cited when a control is deliberately absent. Principle 7's title is
# "Accuracy". It is the reporting principle, separate from Principle 3.
NOT_IMPLEMENTED: tuple[tuple[str, str], ...] = (
    ("6", "Adaptability"),
    ("7", "Accuracy"),
    ("11", "Distribution"),
)
