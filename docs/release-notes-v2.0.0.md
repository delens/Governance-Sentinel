# Governance-Sentinel 2.0.0

These notes are ready to paste into a GitHub release. Creating the release,
the tag, and any deploy is a separate step. This repository does not do that
as part of the change that added the notes.

Version 2.0.0 is the portfolio audit: a seeded risk book, declarative
data-quality rules mapped to BCBS 239, a glossary, technical and column
lineage, a reconciliation, one OpenLineage COMPLETE event, a DuckDB history
of principle scores, a disparate-impact illustration, a PDF, and a Streamlit
scorecard. The data is synthetic. A rule PASS is not compliance with a
principle.

## Run it

Python 3.12.

```bash
python -m pip install -r requirements.txt
python main.py
python -m governance_sentinel audit --input data/sample_transactions.csv --rules rules/dq_rules.yml --out Audit_Report.pdf
python -m governance_sentinel seed-history
python -m governance_sentinel history
streamlit run streamlit_app.py
```

`python main.py` writes a 4,000-row extract (seed 239), the PDF, the lineage
files, and `history/governance_history.duckdb`. `--no-history` skips the
database. `--history-db` changes its path. The database is gitignored.
`runs/kpi_demo.json` is the same twelve-week series the dashboard charts
when no local database is present.

## What 2.0.0 adds

Pulled together from pull request #3 and the history and column-lineage work:

- Seeded transactions (default 4,000 rows, seed 239) with documented defect
  rates, a 150-row sample, and a counterparty master.
- YAML rules with rows checked, rows failed, pass percentage, threshold, and
  PASS or FAIL. Includes a referential check, a business-day T+1 check, and
  an interquartile-range screen. T+1 is the demo deadline, not a supervisory
  SLA. The fence is a screen, not a risk limit.
- Glossary export (JSON and CSV). Dataset lineage from
  `core_banking.transactions` (not measured) to `staging.risk_transactions`
  to `risk_mart.exposure_by_entity`, with status pushed downstream.
- Column lineage with transformation types direct, aggregation, derivation,
  and filter. `age_band` is derived from `age_category`. The exposure sum
  drops null amounts. A glossary term can be traced to the physical columns
  from the extract to the aggregate. Mermaid:
  `docs/column_lineage.mmd`. Exports: `column_lineage.json` and
  `column_lineage.csv`.
- OpenLineage COMPLETE event with `schema`, `columnLineage`,
  `dataQualityMetrics`, and `dataQualityAssertions`. Direct copies use type
  `DIRECT`. Aggregation, derivation, and filter use `INDIRECT`. This is not
  a Marquez client.
- Reconciliation with one injected 250,000 break on LE-UK in EUR. Tolerance
  is 0.1 percent of the absolute transaction total. On the default book,
  40 of 41 slices tie. The LE-UK EUR transaction sum is 9,410,289.81.
- DuckDB history: run id, UTC time, input SHA-256, every rule result, the
  principle scores, and the overall score. `history` prints the trend.
  `seed-history` writes twelve deterministic weeks from 3 June 2026 through
  19 August 2026. The PDF adds a short comparison when a previous run exists.
- Streamlit views for the scorecard, the trend, lineage (including the
  column table), the glossary trace, the fairness result, and a PDF download.
- Disparate impact on the synthetic approval label. Rows are dropped only
  when the group or the label is missing. On the default book the ratio is
  0.6664. The 0.80 cutoff is the US EEOC four-fifths heuristic. It is not an
  EU legal requirement.

## Scores, and what they are not

Principles 2, 3, 4, and 5 are the mean pass percentage of the rules that
cite them. The status is FAIL when any of those rules fail. Principle 6 is
100 because one aggregate grain is defined (paragraph 49(a) only). Principle
7 is the share of reconciliation slices inside tolerance. Principle 11 is
not measured. The overall score averages principles 2, 3, 4, 5, 6, and 7.

On the default 4,000-row book the overall score is 98.989. Eight rules fail
and six pass. Principle 3 is 98.949 and FAIL.

On the twelve-week demo the overall score is 98.62 on 3 June (9 of 14 rules
failed), 99.82 on 15 July (0 of 14 rules failed), and 98.74 on 19 August
(9 of 14 rules failed). Principle 6 stays at 100. The movement is the defect
scale and the on-or-off reconciliation break.

## Still out

Automated fixes, a loader other than CSV, a running OpenLineage server,
on-demand subsets (Principle 6, paragraph 50), a board risk report (the rest
of Principle 7), and distribution controls (Principle 11).

## Earlier releases

1.2.0 (23 October 2026) corrected the BCBS 239 principle numbers, made the
PDF ASCII, and added pytest, ruff, mypy, and GitHub Actions. Pull request #2
added the Mermaid diagrams without a version bump. 1.1.0 and 1.0.0 are the
first field checks and the first PDF. See `CHANGELOG.md`.
