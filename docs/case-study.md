# A synthetic review of risk-data aggregation

Patrick Lens

November 2026

This note is a hypothetical review of a fictional banking group. Every row,
every counterparty, and every figure below was produced by Governance-Sentinel
on synthetic data. The six legal entities (Lumiere Banque SA, Nordhafen Bank AG,
Thames Retail plc, Harbor National NA, Straits Markets Pte Ltd, and Alpine
Custody AG) are invented. There is no client, no production system, and no
supervisory filing behind the numbers.

## The problem

BCBS 239 asks a bank to aggregate risk data that is accurate, complete, and
available when reporting needs it, and to tie a reported total back to the
transactions that produced it. The practical difficulty is not the principle
statement. It is knowing which field check supports which principle, which
physical column a business term names, and whether last week's numbers moved
for a reason that can be explained.

The exercise is a small version of that question. One staged extract of risk
transactions feeds one exposure aggregate. The aggregate is a sum by legal
entity, currency, and reporting date. A glossary names the critical data
elements. A history of weekly runs shows whether the scores move when the
defect rate moves.

## The approach

Fourteen YAML rules run on the staged extract. Each rule records rows checked,
rows failed, a pass percentage, a minimum pass percentage, and PASS or FAIL.
The rules that cite Principle 3 cover uniqueness, ranges, the rating and
currency lists, the product list, the counterparty master, and an
interquartile-range screen. Principle 4 is the not-null checks. Principle 5
is the business-day lag from the reporting date to the availability date,
with a demo limit of T+1. That limit is the example used here. Principle 5
leaves the real deadline to the bank.

The reported total copies the transaction sum and then adds 250,000 on the
LE-UK EUR slice. The tolerance is 0.1 percent of the absolute transaction
total. A failed slice fails the reconciliation. That tie supports Principle 3,
paragraph 36(c), and Principle 7, paragraph 53(a). It is not a board risk
report.

Principle 6 is scored only for paragraph 49(a): one aggregate grain exists.
The score is 100, and it does not change when the data changes. Paragraph 50,
an on-demand subset, is not scored. Principle 11, distribution, is not
implemented, so the history stores no score for it.

Column lineage is declared, not discovered from a second booking file. A
staged column is a direct copy, except `age_band`, which is the label of
`age_category`. The aggregate amount is a sum, after rows with a null amount
are dropped. Each glossary term can be walked from the column it names back
to the extract and forward to the aggregate when an edge exists. The same
mapping is written as an OpenLineage `columnLineage` facet.

The overall score is the unweighted mean of the measured principle scores
for principles 2, 3, 4, 5, 6, and 7. A high mean can sit next to a failed
rule. The status of a rule-based principle follows the failed rule, not the
mean.

## The results

The default book is 4,000 rows, seed 239. Eight of the fourteen rules failed
and six passed. The failures are the injected defects that sit past their
thresholds: missing and duplicate transaction identifiers, missing and
negative exposure, the outlier screen, the invalid currency, the unknown
counterparty, and availability later than T+1. Legal entity, product, the
populated rating, the rating domain, the populated currency, and the
reporting date passed.

The principle scores on that run were:

| Principle | Score | Status |
| --- | ---: | --- |
| 2 Data architecture and IT infrastructure | 100.000 | PASS |
| 3 Accuracy and Integrity | 98.949 | FAIL |
| 4 Completeness | 99.075 | FAIL |
| 5 Timeliness | 98.350 | FAIL |
| 6 Adaptability | 100.000 | PASS |
| 7 Accuracy of the tie-out | 97.561 | FAIL |
| 11 Distribution | not measured | NOT_MEASURED |

The overall score was 98.989. Principle 3's mean is 98.949 and its status is
still FAIL, because at least one of its rules failed. Forty of the 41
reconciliation slices tied. The exception is LE-UK in EUR: the transaction
sum is 9,410,289.81 and the reported total is 250,000.00 higher. The extra
slices beyond the thirty entity-and-currency pairs are the invalid currency
code `XYZ`, which the aggregate keeps as its own currency. The disparate-impact
ratio on the synthetic approval label is 0.6664 (2,015 unprivileged rows and
1,961 privileged rows), below the 0.80 four-fifths heuristic used in this
demo. That heuristic is not a threshold in the EU AI Act.

The twelve-week history uses 800 rows, seeds 239 through 250, and a defect
scale that starts at 1.6, falls to 0.3, and returns to 1.35. The
reconciliation break is turned off for the four weeks from 1 July through
22 July. On 3 June the overall score was 98.62 and 9 of 14 rules failed. On
15 July the overall score was 99.82 and 0 of 14 rules failed. Principle 7
was 100 on each of the four weeks without the injected break, and below 100
on the weeks with it. On 19 August the overall score was 98.74 and 9 of 14
rules failed again. Principle 6 stayed at 100.000 on every week. Principle 11
was not measured on any week.

The move is the defect scale and the on-or-off break, not a change in the
rule definitions. From 8 July to 15 July the two rules that flipped from
FAIL to PASS were `txn_id_unique` and `counterparty_known`. From 22 July to
29 July, when the scale rose and the break returned, the overall score fell
by 0.605 and four rules flipped back to FAIL.

## Lessons

A mean is a poor headline on its own. Principle 3 on the 4,000-row book is
98.949 and still FAIL. The history keeps the mean and the status.

Principle 6 does not describe data quality in this prototype. It describes
the fact that one grain is defined. A flat 100 is the honest chart, and the
basis text says paragraph 50 is outside the score.

Principle 11 should stay blank until a distribution control exists. Storing
a zero would look like a measured failure.

The reconciliation catches the break it was given. That shows the control
can explain a difference. It does not show that a reported total in a real
bank is wrong. The 250,000 figure is injected.

Column lineage here is a declared map. It will stay accurate only while the
aggregate code and the edge list describe the same sum and the same filter.
The OpenLineage document records that map. It does not replace a lineage
server.

The weekly series is a demonstration that the scores move when the injection
moves, and that they move back when the injection returns. It is not a
forecast and not a remediation programme.
