"""Governance-Sentinel dashboard.

Local run::

    streamlit run streamlit_app.py

Streamlit Community Cloud uses this file as the entry point and
``requirements.txt`` for the environment. The app reads the committed sample,
rules, glossary, and run history. It does not call an external API.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st

from governance_sentinel.dashboard_data import DashboardData, load_dashboard
from governance_sentinel.history import history_frame
from governance_sentinel.lineage import lineage_graph
from governance_sentinel.rules import dimension_rollup
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
    st.subheader("Run history")
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
        "The PDF includes the scorecard, remediation, the reconciliation, the "
        "SHA-256 of the input when the command-line audit writes it, and this "
        "fairness result. The download below is built from the sample on screen."
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
        )
        payload = path.read_bytes()
    st.download_button(
        "Download PDF",
        data=payload,
        file_name="Audit_Report.pdf",
        mime="application/pdf",
    )


def main() -> None:
    """Render the page selected in the sidebar."""
    data = _load()
    pages = ("Scorecard", "Trend", "Lineage", "Glossary", "Fairness", "Report")
    requested = st.query_params.get("page", "Scorecard")
    page = st.sidebar.radio(
        "View",
        pages,
        index=pages.index(requested) if requested in pages else 0,
    )
    st.sidebar.write(f"{len(data.frame)} sample rows. History points: {len(data.history)}.")
    if page == "Scorecard":
        _scorecard(data)
    elif page == "Trend":
        _trend(data)
    elif page == "Lineage":
        _lineage(data)
    elif page == "Glossary":
        _glossary(data)
    elif page == "Fairness":
        _fairness(data)
    else:
        _report(data)


main()
