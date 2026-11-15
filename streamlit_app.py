"""Governance-Sentinel dashboard.

Local run::

    streamlit run streamlit_app.py

Streamlit Community Cloud uses this file as the entry point and
``requirements.txt`` for the environment. The app reads the committed sample,
rules, glossary, ownership matrix, and run history. It does not call an
external API. When ``history/governance_history.duckdb`` is missing or empty,
the Trend page uses the committed series in ``runs/kpi_demo.json``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st

from governance_sentinel.column_lineage import (
    COLUMN_EDGES,
    column_lineage_mermaid,
    term_ids_for_edge,
    trace_glossary_term,
)
from governance_sentinel.dashboard_data import DashboardData, load_dashboard
from governance_sentinel.executive import build_summary, write_executive_pdf
from governance_sentinel.history import (
    StoredRun,
    compare_runs,
    history_frame,
    kpi_frame,
    rule_status_frame,
)
from governance_sentinel.lineage import lineage_graph
from governance_sentinel.ownership import ownership_records
from governance_sentinel.rules import dimension_rollup
from governance_sentinel.scores import DASHBOARD_PRINCIPLES
from reporter import FRAMEWORK_VERSION, create_pdf_report

ROOT = Path(__file__).resolve().parent

STATUS_COLOR = {"PASS": "#2e7d32", "FAIL": "#c62828", "NOT_MEASURED": "#757575"}


st.set_page_config(page_title="Governance-Sentinel", layout="wide")
st.title("Governance-Sentinel")
st.caption(
    f"Version {FRAMEWORK_VERSION}. Synthetic risk data. A rule PASS is not compliance "
    "with a BCBS 239 principle. The 0.80 cutoff on the fairness page is the US EEOC "
    "four-fifths heuristic. It is not an EU requirement."
)


@st.cache_data(show_spinner=False)
def _load() -> DashboardData:
    return load_dashboard(ROOT)


def _rules_frame(data: DashboardData) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Rule": item.rule_id,
                "CDE": item.cde,
                "Dimension": item.dimension,
                "Checked": item.records_checked,
                "Failed": item.records_failed,
                "Pass %": round(item.pass_pct, 2),
                "Min %": item.threshold,
                "Status": item.status,
                "Owner": item.owner,
                "Principle": item.principle,
            }
            for item in data.rules
        ]
    )


def _scorecard(data: DashboardData) -> None:
    st.subheader("Scorecard")
    st.write(
        f"Source file: `{data.source_name}` ({len(data.frame)} rows). "
        "Threshold is the minimum pass percentage."
    )
    rollup = dimension_rollup(list(data.rules))
    columns = st.columns(len(rollup))
    for column, (dimension, status, count, failed) in zip(columns, rollup, strict=True):
        column.metric(dimension, status, help=f"{failed} of {count} rules failed")
    frame = _rules_frame(data)
    choice = st.selectbox("Dimension", ["all", *[item[0] for item in rollup]])
    if choice != "all":
        frame = frame.loc[frame["Dimension"] == choice]
    st.dataframe(frame, hide_index=True, width="stretch")


def _trend(data: DashboardData) -> None:
    st.subheader("Principle KPIs")
    runs = data.kpi_runs
    if not runs:
        st.info("No principle history. Run python -m governance_sentinel seed-history.")
    else:
        _kpi_trend(runs)
    st.subheader("Dimension pass rate")
    st.caption(
        "The six committed points in runs/history.jsonl use a fixed defect rate, "
        "so the dimension lines do not move. The disparate-impact ratio does. "
        "The principle chart uses history/governance_history.duckdb when that file "
        "exists and has runs. A missing or empty file, including a Streamlit "
        "Community Cloud deploy, uses the twelve-week demo in runs/kpi_demo.json."
    )
    frame = history_frame(list(data.history))
    if frame.empty:
        st.info("No committed history in runs/history.jsonl.")
        return
    rate_columns = [column for column in frame.columns if column.startswith("pass_pct_")]
    x_values = list(range(len(frame)))
    x_labels = [str(value)[:10] for value in frame["generated_at"]]
    figure, axis = plt.subplots(figsize=(8, 3.2))
    for column in rate_columns:
        axis.plot(
            x_values,
            frame[column],
            marker="o",
            label=column.removeprefix("pass_pct_"),
        )
    axis.set_ylim(90, 100)
    axis.set_ylabel("Pass %")
    axis.set_xticks(x_values)
    axis.set_xticklabels(x_labels, rotation=30, ha="right")
    axis.legend(loc="lower right", ncol=4, fontsize=8)
    figure.tight_layout()
    st.pyplot(figure)
    plt.close(figure)
    st.caption("Mean pass percentage of the rules in each dimension. The scale starts at 90.")
    if "disparate_impact" in frame.columns:
        ratio_figure, ratio_axis = plt.subplots(figsize=(8, 3.2))
        ratio_axis.plot(x_values, frame["disparate_impact"], marker="o", color="#1565c0")
        ratio_axis.axhline(0.80, color="#c62828", linestyle="--", label="0.80 heuristic")
        ratio_axis.set_ylim(0.5, 1.0)
        ratio_axis.set_ylabel("Disparate impact")
        ratio_axis.set_xticks(x_values)
        ratio_axis.set_xticklabels(x_labels, rotation=30, ha="right")
        ratio_axis.legend()
        ratio_figure.tight_layout()
        st.pyplot(ratio_figure)
        plt.close(ratio_figure)
        st.caption("Disparate-impact ratio. The dashed line is the four-fifths heuristic.")
    st.dataframe(
        frame[
            [
                "generated_at",
                "seed",
                "rows",
                "rules_failed",
                "reconciliation_status",
                "fairness_status",
                "disparate_impact",
            ]
        ],
        hide_index=True,
        width="stretch",
    )


def _kpi_trend(runs: tuple[StoredRun, ...]) -> None:
    """Plot principle scores, the latest delta, and rule pass or fail."""
    frame = kpi_frame(runs)
    latest = runs[-1]
    previous = runs[-2] if len(runs) > 1 else None
    comparison = compare_runs(latest, previous)
    if comparison.previous_run_id is None or comparison.overall_delta is None:
        st.write(f"Latest overall score: {comparison.overall_score:.2f}. No previous run.")
    else:
        left, right = st.columns(2)
        left.metric(
            "Overall score",
            f"{comparison.overall_score:.2f}",
            f"{comparison.overall_delta:+.2f}",
        )
        right.metric(
            "Rules failed",
            f"{latest.rules_failed}/{latest.rules_total}",
            f"{latest.rules_failed - (previous.rules_failed if previous else 0):+d}",
            delta_color="inverse",
        )
        deltas = []
        for item in comparison.principles:
            if item.principle not in DASHBOARD_PRINCIPLES:
                continue
            current = "n/a" if item.current is None else f"{item.current:.2f}"
            change = "n/a" if item.delta is None else f"{item.delta:+.2f}"
            deltas.append(
                {
                    "Principle": f"P{item.principle} {item.title}",
                    "Score": current,
                    "Delta": change,
                    "Status": item.current_status,
                }
            )
        st.dataframe(pd.DataFrame(deltas), hide_index=True, width="stretch")
        if comparison.rule_changes:
            changed = pd.DataFrame(
                [
                    {
                        "Rule": item.rule_id,
                        "Previous": item.previous_status,
                        "Current": item.current_status,
                    }
                    for item in comparison.rule_changes
                ]
            )
            st.write("Rules that changed status versus the previous run")
            st.dataframe(changed, hide_index=True, width="stretch")
        else:
            st.write("No rule changed status versus the previous run.")
    score_columns = [
        f"p{principle}" for principle in DASHBOARD_PRINCIPLES if f"p{principle}" in frame.columns
    ]
    plotted = [
        column for column in score_columns if column != "p11" and frame[column].notna().any()
    ]
    x_values = list(range(len(frame)))
    x_labels = [str(value)[:10] for value in frame["run_at"]]
    figure, axis = plt.subplots(figsize=(8, 3.4))
    for column in plotted:
        axis.plot(x_values, frame[column], marker="o", label=f"P{column[1:]}")
    axis.set_ylabel("Score")
    axis.set_xticks(x_values)
    axis.set_xticklabels(x_labels, rotation=30, ha="right")
    axis.legend(loc="lower right", ncol=3, fontsize=8)
    figure.tight_layout()
    st.pyplot(figure)
    plt.close(figure)
    st.caption(
        "P3, P4, and P5 are the mean pass percentage of the rules that cite them. "
        "P6 is 100 because one aggregate grain is defined; paragraph 50 is not scored. "
        "P7 is the share of reconciliation slices inside tolerance. "
        "P11 is not measured, so it is not on the chart. "
        "A score is not compliance with the principle."
    )
    failed_figure, failed_axis = plt.subplots(figsize=(8, 2.6))
    failed_axis.plot(x_values, frame["rules_failed"], marker="o", color="#c62828")
    failed_axis.set_ylabel("Rules failed")
    failed_axis.set_xticks(x_values)
    failed_axis.set_xticklabels(x_labels, rotation=30, ha="right")
    failed_figure.tight_layout()
    st.pyplot(failed_figure)
    plt.close(failed_figure)
    status = rule_status_frame(runs)
    st.write("Rule pass or fail over time")
    st.dataframe(status, hide_index=True, width="stretch")


def _lineage(data: DashboardData) -> None:
    st.subheader("Lineage")
    graph = lineage_graph(data.lineage.statuses)
    positions = {
        "src_transactions": (0.0, 0.0),
        "stg_transactions": (1.0, 0.0),
        "agg_exposure": (2.0, 0.0),
    }
    short_name = {
        "src_transactions": "source",
        "stg_transactions": "staging",
        "agg_exposure": "aggregate",
    }
    colors = [STATUS_COLOR.get(graph.nodes[node]["status"], "#757575") for node in graph.nodes]
    figure, axis = plt.subplots(figsize=(10, 3.4))
    nx.draw_networkx_nodes(graph, positions, ax=axis, node_color=colors, node_size=1800)
    nx.draw_networkx_edges(
        graph,
        positions,
        ax=axis,
        arrows=True,
        arrowsize=18,
        width=1.4,
        node_size=1800,
    )
    for node, (x_pos, y_pos) in positions.items():
        status = str(graph.nodes[node]["status"])
        axis.text(
            x_pos,
            y_pos - 0.28,
            f"{short_name.get(node, node)}\n{status}",
            ha="center",
            va="top",
            fontsize=9,
        )
    axis.set_xlim(-0.55, 2.55)
    axis.set_ylim(-0.85, 0.55)
    axis.set_axis_off()
    figure.tight_layout()
    st.pyplot(figure)
    plt.close(figure)
    rows = [
        {
            "Dataset": node.dataset,
            "Layer": node.layer,
            "Status": data.lineage.statuses.get(node.node_id, "NOT_MEASURED"),
            "Description": node.description,
        }
        for node in data.lineage.nodes
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    recon = data.lineage.reconciliation
    st.write(
        f"Reconciliation: **{recon.status}** at {recon.tolerance_pct:.1f} percent tolerance. "
        "The reported LE-UK EUR total is 250000 above the transaction sum. "
        "That break is injected."
    )
    failed = [
        {
            "Legal entity": item.legal_entity_id,
            "Currency": item.currency,
            "Reporting date": item.reporting_date,
            "Transactions": item.transaction_total,
            "Reported": item.reported_total,
            "Difference": item.difference,
        }
        for item in recon.failed_slices
    ]
    if failed:
        st.dataframe(pd.DataFrame(failed), hide_index=True, width="stretch")
    with st.expander("Mermaid source, generated from the metadata"):
        st.code(data.lineage.mermaid, language="mermaid")
    st.write("Column lineage")
    st.caption(
        "direct is a copy. aggregation is the exposure sum. derivation is the "
        "age_band label of age_category. filter drops null exposure amounts before the sum."
    )
    column_rows = [
        {
            "Source": f"{edge.source_dataset}.{edge.source_column}",
            "Target": f"{edge.target_dataset}.{edge.target_column}",
            "Transformation": edge.transformation,
            "Glossary terms": ", ".join(term_ids_for_edge(edge, data.glossary.terms)) or "none",
        }
        for edge in COLUMN_EDGES
    ]
    st.dataframe(pd.DataFrame(column_rows), hide_index=True, width="stretch")
    with st.expander("Column-level Mermaid"):
        st.code(column_lineage_mermaid(), language="mermaid")


def _glossary(data: DashboardData) -> None:
    st.subheader("Glossary")
    labels = {term.term: term for term in data.glossary.terms}
    selected = st.selectbox("Term", list(labels))
    if not isinstance(selected, str):
        return
    term = labels[selected]
    st.write(term.definition)
    st.write(f"CDE: `{term.cde}`")
    st.write(f"Physical column: `{term.physical_dataset}.{term.physical_column}`")
    st.write(f"Owner: {term.owner}")
    st.write(f"Steward: {term.steward}")
    st.write("Principles: " + ", ".join(term.principles))
    st.write("DQ rules: " + ", ".join(term.dq_rule_ids))
    trace = trace_glossary_term(term)
    st.write("Physical columns, from the booking extract through the aggregate:")
    for ref in trace.columns:
        anchor = ref.dataset == term.physical_dataset and ref.column == term.physical_column
        suffix = " (this term)" if anchor else ""
        st.write(f"`{ref.dataset}.{ref.column}`{suffix}")


def _ownership(data: DashboardData) -> None:
    st.subheader("Ownership matrix")
    st.write(
        "Each glossary term has a data owner and a data steward. Both are roles, "
        "not named people. The tolerance is the lowest minimum pass percentage "
        "of the linked rules. The same file is checked when the audit runs."
    )
    frame = pd.DataFrame(ownership_records(data.ownership))
    st.dataframe(frame, hide_index=True, width="stretch")
    buffer = StringIO()
    frame.to_csv(buffer, index=False)
    st.download_button(
        "Download ownership CSV",
        data=buffer.getvalue(),
        file_name="ownership.csv",
        mime="text/csv",
    )


def _fairness(data: DashboardData) -> None:
    st.subheader("Disparate impact")
    result = data.fairness
    ratio = f"{result.ratio:.4f}" if result.defined else "undefined"
    left, middle, right = st.columns(3)
    left.metric("Disparate impact", ratio)
    middle.metric("Unprivileged rate", f"{result.unprivileged_rate:.4f}")
    right.metric("Privileged rate", f"{result.privileged_rate:.4f}")
    st.write(f"Status: **{result.status}** against a cutoff of {result.threshold:.2f}.")
    st.write(
        f"Unprivileged n={result.unprivileged_count} (age_category 1, label 40_and_over). "
        f"Privileged n={result.privileged_count} (age_category 2, label under_40). "
        f"Rows excluded because the group or the label is missing: {result.rows_excluded}."
    )
    st.write(
        "The ratio is the unprivileged selection rate divided by the privileged "
        "selection rate. 0.80 is the US EEOC four-fifths rule of thumb. It is a "
        "heuristic in this demo. It is not a threshold in the EU AI Act and it is "
        "not an EU legal requirement. The figure sits next to Article 10 (data and "
        "data governance). It is not an Article 13 file and not a conformity assessment."
    )


def _report(data: DashboardData) -> None:
    st.subheader("PDF report")
    st.write(
        "The full PDF includes the scorecard, remediation with the ownership "
        "matrix on each failed rule, the reconciliation, and this fairness "
        "result. The one-page summary is the board view of the same sample. "
        "It does not use the twelve-week series, because that series is a "
        "different extract. Both downloads are built on screen."
    )
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "Audit_Report.pdf"
        create_pdf_report(
            data.rules,
            data.fairness,
            run_id="dashboard-sample",
            dataset_sha256="sample-not-hashed-in-the-view",
            row_count=len(data.frame),
            output_path=str(path),
            dataset_name=data.source_name,
            lineage=data.lineage,
            ownership=data.ownership,
        )
        payload = path.read_bytes()
        summary_path = Path(temporary) / "Executive_Summary.pdf"
        summary = build_summary(
            data.rules,
            data.lineage.reconciliation,
            data.ownership,
            run_id="dashboard-sample",
            run_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            dataset_name=data.source_name,
            row_count=len(data.frame),
            input_sha256="sample-not-hashed-in-the-view",
            as_of=datetime.now(timezone.utc).date(),
            previous=None,
        )
        write_executive_pdf(summary, str(summary_path))
        summary_payload = summary_path.read_bytes()
    st.download_button(
        "Download PDF",
        data=payload,
        file_name="Audit_Report.pdf",
        mime="application/pdf",
    )
    st.download_button(
        "Download one-page executive summary",
        data=summary_payload,
        file_name="Executive_Summary.pdf",
        mime="application/pdf",
    )


def main() -> None:
    """Render the page selected in the sidebar."""
    data = _load()
    pages = ("Scorecard", "Trend", "Lineage", "Glossary", "Ownership", "Fairness", "Report")
    requested = st.query_params.get("page", "Scorecard")
    page = st.sidebar.radio(
        "View",
        pages,
        index=pages.index(requested) if requested in pages else 0,
    )
    st.sidebar.write(
        f"{len(data.frame)} sample rows. History points: {len(data.history)}. "
        f"KPI runs: {len(data.kpi_runs)}."
    )
    if page == "Scorecard":
        _scorecard(data)
    elif page == "Trend":
        _trend(data)
    elif page == "Lineage":
        _lineage(data)
    elif page == "Glossary":
        _glossary(data)
    elif page == "Ownership":
        _ownership(data)
    elif page == "Fairness":
        _fairness(data)
    else:
        _report(data)


main()
