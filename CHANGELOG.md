# Changelog

All notable changes to Governance-Sentinel are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the version number is `governance_sentinel.__version__`. Git tags have not
been created for these versions.

## [Unreleased]

### Added

- Ownership matrix in `governance/ownership.yml`. One row per glossary term:
  data owner, data steward, source system, criticality, tolerance threshold,
  and the linked data-quality rules. Owners and stewards are roles. The audit
  rejects a term with no row, a rule id that does not exist, or a tolerance
  that is not the lowest linked rule threshold. The run writes `ownership.csv`.
  The dashboard shows the table. The full PDF names the matrix owner on each
  failed rule.
- `python -m governance_sentinel exec-summary` writes one A4 page: a red,
  amber, or green light for each scored principle, Principle 11 as not
  measured, the overall score, the delta versus the latest stored run when
  the history file already has one, the top three open risks in plain
  language, the accountable role, and a due date. The injected LE-UK EUR
  break is described as injected. The command does not append a history run.
- `python -m governance_sentinel export-catalog --target datahub|collibra`
  writes DataHub Metadata Change Proposal JSON, or a Collibra CSV and Import
  API JSON, for datasets, fields, glossary terms, ownership roles, and column
  lineage. No network call and no catalog SDK. The shape and its limits are
  in `docs/catalog-export.md`.
- `docs/img/dashboard-demo.gif`, a headless walkthrough of the Streamlit
  views, embedded at the top of the README. `.streamlit/config.toml`,
  `runtime.txt`, and `.python-version` mark the app as ready for Streamlit
  Community Cloud. A missing DuckDB file still uses `runs/kpi_demo.json`.
  No site is deployed. The live demo URL in the README is marked coming soon.

## [2.0.0] - 2026-11-15

The portfolio audit from pull request #3, plus a local run history and
column-level lineage. The version in the code is 2.0.0. This entry is the
note for that version. It is not a published GitHub release.

### Added

- Seeded risk-transaction generator (`governance_sentinel/synthetic.py`), a
  150-row committed sample, and a 40-row counterparty master. Defect counts
  are `round(rate * n)` and are tested. Pull request #3.
- YAML rules in `rules/dq_rules.yml` with rows checked, rows failed, pass
  percentage, threshold, PASS or FAIL, and sample failing ids. Includes a
  referential orphan check, a business-day T+1 timeliness check, and an
  interquartile-range outlier screen. Pull request #3.
- PDF scorecard and remediation, with the run id and the SHA-256 of the input
  file. Pull request #3.
- Business glossary (`catalog/glossary.yml`) exported as JSON and CSV.
  Technical lineage from source to staging to aggregate, with status pushed
  downstream. Mermaid from the metadata, and a networkx graph. Pull request #3.
- Reconciliation of the transaction sum to a reported total, with one injected
  250,000 break on LE-UK in EUR. Tolerance is 0.1 percent of the absolute
  transaction total. Pull request #3.
- One OpenLineage COMPLETE event with `dataQualityMetrics` and
  `dataQualityAssertions`. Pull request #3.
- `python -m governance_sentinel audit` and `generate`, with `python main.py`
  kept. Streamlit scorecard. Pull request #3.
- Fairness audit that drops a row only when `age_category` or `loan_approved`
  is missing, and that raises when a group is empty. The 0.80 cutoff is
  described as the US EEOC four-fifths heuristic. Pull request #3.
- DuckDB history of every audit run: run id, UTC timestamp, input SHA-256,
  per-rule results, per-principle scores, and an overall score. Default path
  `history/governance_history.duckdb`, configurable with `--history-db`.
  `--no-history` skips the write. The database is gitignored.
- `python -m governance_sentinel history` lists runs and prints the principle
  trend. `seed-history` writes twelve deterministic weekly runs (3 June 2026
  through 19 August 2026) with a changing defect scale. The same command
  writes the same run ids.
- Streamlit Trend view: principle scores for P3, P4, P5, P6, P7, and P11,
  rule pass or fail over time, and the delta versus the previous run. The
  committed series is `runs/kpi_demo.json`. A local database replaces it.
- PDF section "Trend versus the previous run" when a previous run is stored.
- Column lineage from the booking extract to staging to the exposure
  aggregate, with transformation types direct, aggregation, derivation, and
  filter. Glossary terms are attached to the edges they name, and a term can
  be traced to the physical columns from source to aggregate.
- OpenLineage `columnLineage` and `schema` facets on the COMPLETE event.
  `docs/column_lineage.mmd` is generated from the same edges.
  `column_lineage.json` and `column_lineage.csv` are written beside the
  glossary export.
- `docs/release-notes-v2.0.0.md`.

### Changed

- Framework version is 2.0.0.
- Principle 6 is scored as 100 because one aggregate grain is defined
  (paragraph 49(a)). Paragraph 50 is not scored. Principle 11 is stored as
  not measured. Principle 7 is the share of reconciliation slices inside
  tolerance.

## [1.2.0] - 2026-10-23

### Added

- ASCII PDF, so generation no longer depends on characters outside Helvetica.
  Pull request #1.
- Corrected BCBS 239 principle numbers against the January 2013 BIS text.
  Completeness supports Principle 4, accuracy and the currency list support
  Principle 3, timeliness supports Principle 5. Principles 6, 7, and 11 are
  named and were not implemented in this release. Pull request #1.
- UTC timestamps on the report and in the log. Pull request #1.
- pytest, ruff, mypy, and GitHub Actions on Python 3.12. Pull request #1.
- `--mode real` reads a CSV. Pinned `requirements.txt` and
  `requirements-dev.txt`. MIT license. Pull request #1.
- Mermaid diagrams of the pipeline, the module map, the BCBS 239 mapping, and
  the roadmap, in the README and in `docs/architecture.md`. Pull request #2,
  merged on 2026-10-24, with no version bump.

### Changed

- Removed claims the code did not implement: orphan detection, a statistical
  outlier screen, a T+1 SLA, and an executive dashboard. Those three controls
  arrived later, in 2.0.0, and are limited to what the YAML rules and the
  reconciliation actually do.

## [1.1.0] - 2026-05-24

### Changed

- The audit copies the caller's frame. Nulls fail the check that owns the
  field. Logging goes to the console and to a file.

## [1.0.0] - 2026-05-01

### Added

- First data-quality checks, the AIF360 disparate-impact ratio, and a PDF.
  An early note cited the wrong principle numbers. 1.2.0 corrected them.
