# Governance-Sentinel

[![CI](https://github.com/delens/Governance-Sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/delens/Governance-Sentinel/actions/workflows/ci.yml)

A compliance-as-code prototype for a data-governance review: declarative data-quality rules on a seeded book of risk transactions, mapped to BCBS 239, with a business glossary, technical lineage, a transaction-to-aggregate reconciliation, a disparate-impact illustration, a PDF, and a Streamlit scorecard.

**Notice.** Personal research sandbox. The data is synthetic. This project is not affiliated with any employer, client, or production system. The full notice is at the end of this file.

## Run it

Requires **Python 3.12**.

```bash
python -m pip install -r requirements.txt
python main.py
python -m governance_sentinel audit --input data/sample_transactions.csv --rules rules/dq_rules.yml --out Audit_Report.pdf
```

`python main.py` generates 4,000 rows (seed 239), audits them, and writes `Audit_Report.pdf`. The module command audits the committed 150-row sample. Both exit 0.

| Command | What it writes |
| --- | --- |
| `python main.py` | `data/generated_transactions.csv`, `Audit_Report.pdf`, `lineage.mmd`, `lineage.json`, `openlineage.json`, `glossary.json`, `glossary.csv`, `reconciliation.csv`, `governance_sentinel.log` |
| `python -m governance_sentinel generate --rows 4000 --seed 239 --out data/generated_transactions.csv` | A seeded extract and a copy of the counterparty master. No audit. |
| `python main.py --mode real --csv data/sample_transactions.csv` | Reads a CSV. It does not regenerate it. |

`--log-level` sets the root logger (default `INFO`, or the `LOG_LEVEL` environment variable).

## Dashboard

The scorecard, the trend, the lineage graph, the glossary, the fairness result, and a PDF download are in `streamlit_app.py`.

```bash
streamlit run streamlit_app.py
```

The app opens on the committed 150-row sample and the six-point history in `runs/history.jsonl`. It does not need an API key.

Streamlit Community Cloud can run this repository as it is:

- Main file path: `streamlit_app.py`
- Requirements file: `requirements.txt`
- Python version: 3.12

This repository does not deploy the app and does not create an account.

![Scorecard on the committed sample](docs/dashboard_scorecard.png)

![Lineage graph with data-quality status](docs/dashboard_lineage.png)

![Run history for pass rate and disparate impact](docs/dashboard_trend.png)

![Disparate-impact result](docs/dashboard_fairness.png)

## Report

![First page of the audit report](docs/audit_report_preview.png)

![Reconciliation and disparate-impact section](docs/audit_report_reconciliation.png)

`Audit_Report.pdf` in the repository root is the output of `python main.py` (4,000 rows, seed 239). A later run overwrites it. The PDF carries the run id, the SHA-256 of the input file, the scorecard (rows checked, rows failed, pass percentage, minimum pass percentage, PASS or FAIL), remediation with sample failing ids, the reconciliation, and the fairness result.

## Pipeline

```mermaid
flowchart TD
  start["python main.py or python -m governance_sentinel audit"] --> load["Load a seeded extract or a CSV"]
  load --> rules["Evaluate rules/dq_rules.yml"]
  rules --> fairness["Disparate-impact ratio"]
  fairness --> lineage["Lineage, glossary export, reconciliation"]
  lineage --> pdf["PDF, Mermaid, OpenLineage JSON"]
```

A failed rule does not stop the run. A missing file, a missing column, or an empty fairness group does. `main` logs the traceback and exits 1.

## What a rule records

`threshold` in `rules/dq_rules.yml` is the minimum pass percentage. A rule PASSes when at least one record was checked and the pass percentage is at least that figure. The result stores rows checked, rows failed, the pass percentage, the threshold, PASS or FAIL, and up to five failing record ids. The full failing-id list stays on the result object for tests.

Validity is a data-quality dimension. It is not a BCBS 239 principle. Domain rules support Principle 3, paragraph 37, the dictionary of concepts.

| Rule | Dimension | What it checks | Principle it supports |
| --- | --- | --- | --- |
| `txn_id_populated` | Completeness | `transaction_id` is present | 4, paragraphs 41-43 |
| `txn_id_unique` | Accuracy | Non-missing identifiers are unique | 3, paragraph 36 |
| `exposure_populated` | Completeness | `exposure_amount` is present | 4 |
| `exposure_non_negative` | Accuracy | Non-missing amount is at least 0 | 3, paragraphs 36 and 40 |
| `exposure_outlier` | Accuracy | Interquartile-range screen on amounts at or above 0 | 3, paragraph 40 |
| `currency_populated`, `currency_domain` | Completeness, validity | Currency present and on the glossary list | 4 and 3, paragraph 37 |
| `rating_populated`, `rating_domain` | Completeness, validity | Rating present and on the scale. NR is a grade, not a blank | 4 and 3, paragraph 37 |
| `legal_entity_domain` | Validity | Group legal-entity identifier | 2, paragraph 33 |
| `product_domain` | Validity | Product family on the glossary list | 3, paragraph 37 |
| `counterparty_known` | Accuracy | Present on the counterparty master. A blank is a fail | 3, paragraph 36(c) and 36(d) |
| `availability_t_plus_1` | Timeliness | Business-day lag from `reporting_date` to `availability_date` is 0 or 1 | 5, paragraphs 44-47 |
| `reporting_date_populated` | Completeness | The as-of date is present | 5 |

The timeliness rule uses the numpy business-day calendar and the default weekmask. It has no holiday calendar. Principle 5 leaves the real deadline to the bank. T+1 is the worked example in this demo, not a supervisory SLA.

The outlier rule is an interquartile-range fence with k = 1.5. Values below 0 are left to the range rule. The fence is a screening heuristic, not a risk limit and not an accounting-materiality test. Paragraph 40 expects the bank to measure and monitor accuracy. This screen is a small version of that idea.

On the default 4,000-row file, eight rules fail and six pass. The failures are the injected defects sitting past their thresholds. The passes are the rules whose defect rate is inside the threshold.

The original four boolean checks remain in `validators.py` and are still unit-tested. The audit the CLI runs is the YAML engine.

## Synthetic book

`governance_sentinel/synthetic.py` builds the book. The default is 4,000 rows, seed 239, inside the 1,000 to 10,000 band. `data/sample_transactions.csv` is the first 150 rows of that same seed, committed so the dashboard and the module command have a file to open. `data/counterparties.csv` is the 40-row master. Fictional legal entities: Lumiere Banque SA, Nordhafen Bank AG, Thames Retail plc, Harbor National NA, Straits Markets Pte Ltd, Alpine Custody AG.

Defect counts are `round(rate * n)`. At 4,000 rows the rates below are exact. A row can carry more than one defect when the defects are on different columns. Within one column the defects do not overlap.

| Defect | Rate |
| --- | --- |
| Missing `transaction_id` | 1.0% |
| Duplicate `transaction_id` | 0.4% of rows overwritten, plus the donor row |
| Null exposure | 1.5% |
| Negative exposure | 1.0% |
| Exposure spike (500,000) | 0.8% |
| Invalid currency `XYZ` | 1.2% |
| Null currency | 0.4% |
| Orphan counterparty | 2.0% |
| Null counterparty | 0.5% |
| Availability more than T+1 | 3.0% |
| Unparseable availability date | 0.3% |
| Invalid rating `BAD` | 1.0% |
| Null rating | 0.8% |
| Null `age_category` | 0.4% |
| Null `loan_approved` | 0.2% |

Target approval rates, before those nulls: 0.78 for the privileged group and 0.54 for the unprivileged group. The expected disparate-impact ratio is about 0.69. The realised ratio depends on the seed. On seed 239 and 4,000 rows it is below 0.80. The 150-row sample is too small for that ratio to be stable. The history file uses 1,200 rows per point.

The reported exposure total copies the transaction sum and then adds 250,000 on LE-UK in EUR. That break is injected so the reconciliation has a difference to explain. The tolerance is 0.1 percent of the absolute transaction total. The 500,000 spikes are above the interquartile fence and small enough that 250,000 still exceeds the tolerance on the LE-UK EUR slice.

## Lineage and glossary

```mermaid
flowchart LR
  src_transactions["core_banking.transactions\nNOT_MEASURED"]
  stg_transactions["staging.risk_transactions\nFAIL"]
  agg_exposure["risk_mart.exposure_by_entity\nFAIL"]
  src_transactions --> stg_transactions
  stg_transactions --> agg_exposure
```

`docs/lineage.mmd` is that picture, generated from the metadata for the committed sample. A test checks that the file matches the generator. The source node is `NOT_MEASURED`: this prototype does not have a separate booking extract. Rules run on the staged CSV. The aggregate inherits a staging FAIL, and it also FAILs when the reconciliation FAILs. `networkx` builds the same directed graph for the dashboard.

Column flow: every staged column is a copy of the source column. The aggregate keeps `legal_entity_id`, `currency`, and `reporting_date` as group keys and sums `exposure_amount`.

The reconciliation supports:

- Principle 3, paragraph 36(c): risk data reconciled with the bank's sources. Footnote 17 defines reconciliation as comparing items and explaining the difference.
- Principle 7, paragraph 53(a): a defined tie from a reported total back to risk data. This is not a board risk report. Paragraphs 52 and 54-56 are not implemented.
- Principle 6, paragraph 49(a): one aggregate grain. Paragraph 50, an on-demand subset for a supervisory query, is not implemented.

Principle 2, footnote 16, is about automated reconciliation where more than one data model is in use. The check here is one transaction extract against one aggregate. That is the Principle 3 / Principle 7 case, not that footnote.

`catalog/glossary.yml` links each business term to a CDE, a physical column, the DQ rules, and an owner. A term that cites a missing rule or a missing column is rejected at load. Each run writes `glossary.json` and `glossary.csv`.

`openlineage.json` is one COMPLETE event. It fills `dataQualityMetrics` (null count, count, distinct count, and sum/min/max on exposure) and `dataQualityAssertions` (one assertion per rule). It is a minimal document in the shape of the public OpenLineage facets. It is not a Marquez client and it does not talk to a server.

## Disparate impact

AIF360's `BinaryLabelDatasetMetric.disparate_impact` is:

$$DI = \frac{P(\text{loan approved} \mid \text{unprivileged})}{P(\text{loan approved} \mid \text{privileged})}$$

`age_category` 1 is the unprivileged group in this demo (label `40_and_over`). `age_category` 2 is the privileged group (label `under_40`). Those labels are synthetic. They are not a legal age classification.

The PDF and the dashboard treat a ratio below 0.80 as a fail against the US EEOC four-fifths rule of thumb. That figure is a heuristic here. It is not a threshold in the EU AI Act, and it is not an EU legal requirement. The metric sits next to Article 10 (data and data governance). It is not an Article 13 transparency file, and it is not a conformity assessment.

Rows are dropped only when `age_category` or `loan_approved` is missing. A null in any other column, including `transaction_id`, stays in the metric. If either group has no complete row, the audit raises instead of returning a silent NaN. If the privileged selection rate is zero, the ratio is undefined and the status is `UNDEFINED`.

TensorFlow is not installed or imported. AIF360's TensorFlow extra is only for adversarial debiasing, which this prototype does not run.

## BCBS 239

Principle numbers follow the Basel Committee on Banking Supervision, *Principles for effective risk data aggregation and risk reporting* (BCBS 239), January 2013: <https://www.bis.org/publ/bcbs239.pdf>.

A pass on a rule is the field check. It is narrower than the principle it supports.

| Principle | Paragraphs used here | What this prototype actually does |
| --- | --- | --- |
| 2 Data architecture and IT infrastructure | 33, and 34 for named owners | Glossary, single identifiers for legal entity and counterparty, owner and steward on every rule |
| 3 Accuracy and Integrity | 36, including 36(c) and 36(d), 37, 40 | Range, uniqueness, referential check, dictionary lists, IQR screen, reconciliation to the transaction sum |
| 4 Completeness | 41-43 | Not-null rules, and a legal-entity identifier so the book can be cut by entity |
| 5 Timeliness | 44-47 | Business-day lag from reporting date to availability date. The deadline is the demo's, not the Committee's |
| 6 Adaptability | 49(a) only | One aggregate grain. Not paragraph 50 |
| 7 Accuracy | 53(a) and the idea of 53(b) | The tie-out, and the rule inventory as a validation list. Not a board report |
| 11 Distribution | 72-73 | Not implemented |

```mermaid
flowchart TB
  subgraph measured ["Measured in this repository"]
    identifiers["Legal entity and counterparty identifiers"] --> principle2["Principle 2, paragraph 33"]
    dictionary["Glossary and domain lists"] --> principle3dict["Principle 3, paragraph 37"]
    reconcile["Transaction sum versus reported total"] --> principle3rec["Principle 3, paragraph 36(c)"]
    reconcile --> principle7["Principle 7, paragraph 53(a)"]
    populated["Not-null rules on identifiers and amounts"] --> principle4["Principle 4"]
    lag["Reporting date versus availability date"] --> principle5["Principle 5"]
    grain["One exposure aggregate"] --> principle6["Principle 6, paragraph 49(a)"]
  end
  subgraph notYet ["Not implemented"]
    paragraph50["Principle 6, paragraph 50, on-demand subsets"]
    board["Principle 7, paragraphs 52 and 54-56, a board risk report"]
    principle11["Principle 11, Distribution"]
  end
```

## Modules

```mermaid
flowchart LR
  mainPy["main.py"]
  cli["python -m governance_sentinel"]
  pipeline["governance_sentinel.pipeline"]
  synthetic["governance_sentinel.synthetic"]
  rulesPy["governance_sentinel.rules"]
  lineagePy["governance_sentinel.lineage"]
  catalogPy["governance_sentinel.catalog"]
  biasPy["bias_audit.py"]
  reporterPy["reporter.py"]
  app["streamlit_app.py"]

  mainPy --> pipeline
  cli --> pipeline
  pipeline --> synthetic
  pipeline --> rulesPy
  pipeline --> lineagePy
  pipeline --> catalogPy
  pipeline --> biasPy
  pipeline --> reporterPy
  app --> synthetic
  app --> rulesPy
  app --> lineagePy
  app --> catalogPy
  app --> biasPy
```

`validators.py` and `data_loader.py` still hold the original five-row field checks. `python main.py` does not call them. Column lists and the stops are in [docs/architecture.md](docs/architecture.md).

## Roadmap

Shipped: the seeded book and its defect manifest, the YAML rules including referential, T+1, and the IQR screen, the PDF scorecard, the glossary, lineage with downstream status, the reconciliation, a minimal OpenLineage event, the disparate-impact audit, the CLI, and the Streamlit app.

Still out, on purpose: automated fixes, a loader other than CSV, a running OpenLineage or Marquez server, an on-demand aggregate for a supervisory query (Principle 6, paragraph 50), a board risk report (the rest of Principle 7), and distribution controls (Principle 11).

```mermaid
flowchart TB
  subgraph shipped ["In the repository"]
    book["Seeded risk book"]
    yamlRules["YAML rules and thresholds"]
    lineageBox["Lineage, glossary, reconciliation"]
    pdfBox["PDF and OpenLineage JSON"]
    dashboard["Streamlit scorecard"]
  end
  subgraph backlog ["Backlog"]
    fixes["Automated fixes"]
    otherLoaders["Loaders other than CSV"]
    marquez["An OpenLineage server"]
    adHoc["On-demand subsets, Principle 6 paragraph 50"]
    distribution["Principle 11, Distribution"]
  end
  shipped -.->|"left out on purpose"| backlog
```

## Checks

```bash
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
mypy
pytest
```

GitHub Actions runs those commands on Python 3.12 (`.github/workflows/ci.yml`).

## Changelog

### [2.0.0]

#### Added

- Seeded risk-transaction generator, a 150-row committed sample, and a counterparty master. Defect rates are documented and tested.
- YAML rules with rows checked, rows failed, pass percentage, threshold, PASS or FAIL, and sample failing ids.
- Referential orphan check, business-day T+1 timeliness check, and an interquartile-range outlier screen.
- PDF scorecard, remediation, run id, and SHA-256 of the input file.
- Business glossary exported as JSON and CSV. Technical lineage from source to staging to aggregate, with status pushed downstream. Mermaid from the metadata, and a networkx graph.
- Reconciliation of the transaction sum to a reported total, with one injected 250,000 break on LE-UK EUR.
- One OpenLineage COMPLETE event.
- `python -m governance_sentinel audit` and `generate`, with `python main.py` kept.
- Streamlit dashboard and Community Cloud entry instructions.
- Fairness audit that drops a row only for a missing protected attribute or label, and that raises on an empty group.

#### Changed

- The 0.80 cutoff is described as the US EEOC four-fifths heuristic. It is not presented as an EU requirement.
- Framework version is 2.0.0.

### [1.2.0] - 2026-10-23

ASCII PDF, corrected BCBS 239 principle numbers, UTC timestamps, pytest, and GitHub Actions. The field checks in that release are the four boolean checks that `validators.py` still runs.

### [1.1.0] - 2026-05-24

The audit copies the frame. Nulls fail the check that owns the field. Logging goes to the console and to a file.

### [1.0.0] - 2026-05-01

First data-quality checks, the AIF360 ratio, and a PDF. An early note cited the wrong principle numbers. 1.2.0 corrected them.

## License

MIT. See [LICENSE](LICENSE).

## Full notice

**This repository is a personal sandbox environment, developed entirely in my own time and on my own initiative.**

The project was created to explore open-source tooling — Python, draw.io, Mermaid, AI libraries — applied to regulatory scenarios inspired by publicly available frameworks such as BCBS 239 and the EU AI Act. Its purpose is strictly educational and experimental.

> **All data used in this project is entirely synthetic and artificially generated.** It does not contain, reproduce, or derive from any real data, systems, internal processes, documentation, or intellectual property belonging to any organisation. Any resemblance to real business scenarios is purely coincidental and a natural consequence of working with publicly documented regulatory frameworks.

This project is not connected in any way to any professional activity, employer (past or present), client, or production system. No proprietary code, data, process, or business know-how has been used, reproduced, or exported.
