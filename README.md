# 🛡️ Governance-Sentinel: AI-Driven Compliance & Data Integrity Framework

**Governance-Sentinel** is an enterprise-grade "Compliance-as-Code" solution developed to automate the oversight of high-risk financial data ecosystems. It specifically addresses the regulatory intersection of **BCBS 239** (Risk Data Aggregation) and the **EU AI Act** (Algorithmic Fairness and Transparency).

---

## ⚠️ Important Notice — Personal Research Sandbox

**This repository is a personal sandbox environment, developed entirely in my own time and on my own initiative.**

The project was created to explore open-source tooling — Python, draw.io, Mermaid, AI libraries — applied to regulatory scenarios inspired by publicly available frameworks such as BCBS 239 and the EU AI Act. Its purpose is strictly educational and experimental.

> **All data used in this project is entirely synthetic and artificially generated.** It does not contain, reproduce, or derive from any real data, systems, internal processes, documentation, or intellectual property belonging to any organisation. Any resemblance to real business scenarios is purely coincidental and a natural consequence of working with publicly documented regulatory frameworks.

This project is not connected in any way to any professional activity, employer (past or present), client, or production system. No proprietary code, data, process, or business know-how has been used, reproduced, or exported.

---

## 🏢 Strategic Overview
In the current regulatory climate, financial institutions face a dual challenge: maintaining the highest standards of data quality while ensuring that the transition to AI-driven decision-making remains ethical and compliant. This framework acts as an automated **Second Line of Defense (2LoD)**, providing continuous monitoring and executive-level assurance.

---

## 🛠️ Technical Architecture & Pillars

### 1. Risk Data Integrity Engine (BCBS 239 Implementation)
The framework implements a rigorous validation layer designed to satisfy the **Principles for Effective Risk Data Aggregation and Risk Reporting**. It maps technical checks to specific DQ dimensions:

* **Completeness (Principle 3)**: Automated detection of orphans and null values in critical data elements (CDEs) like `transaction_id`.
* **Accuracy (Principle 4)**: Outlier detection and threshold validation for financial amounts to prevent data corruption in risk models.
* **Validity**: Alignment with ISO-compliant metadata (e.g., Currency Codes) and internal master data dictionaries.
* **Timeliness (Principle 11)**: Temporal verification to ensure data availability within regulatory reporting windows (e.g., T+1).

### 2. Algorithmic Fairness Audit (EU AI Act - Art. 10 & 13)
Targeting **High-Risk AI systems** (such as Credit Scoring and Loan Underwriting), the framework integrates the **IBM AIF360** toolkit to perform quantitative bias auditing.

#### **The Mathematics of Fairness: Disparate Impact Ratio**
The engine monitors the **Disparate Impact (DI)** ratio, a key metric for detecting indirect discrimination. It uses **Conditional Probability** to compare selection rates across demographic groups:

$$DI = \frac{P(\text{Outcome} = 1 \mid \text{Unprivileged Group})}{P(\text{Outcome} = 1 \mid \text{Privileged Group})}$$

* **Metric Interpretation**: A DI of **1.0** indicates perfect equity.
* **Regulatory Threshold**: In accordance with international standards (e.g., US EEOC 4/5ths rule), any score below **0.80** triggers a **Critical Remediation Alert**.
* **The "0.00" Scenario**: Our current audit detected a DI of **0.00**, indicating a total exclusion of the protected group (Seniors). This demonstrates the framework's ability to identify systemic bias before model deployment.

---

## 📊 Executive Reporting & Audit Trail
Unlike standard scripts, Governance-Sentinel produces a **Formal Audit Report (PDF)**. This document is designed for stakeholders such as:
* **Chief Data Officers (CDO)** for DQ oversight.
* **Internal Audit** for evidence of control effectiveness.
* **Regulators (ECB/EBA)** as part of the technical documentation for AI systems.

---

## 📈 Managed Roadmap & Scalability
This project follows a managed lifecycle, documented in the **GitHub Projects** tab:
1.  **Phase 1 (Completed)**: Core DQ Validation & Bias Detection modules.
2.  **Phase 2 (Active)**: Automated PDF Reporting and Executive Dashboarding.
3.  **Phase 3 (Backlog)**: Integration with **Data Lineage** tools and automated remediation (self-healing data).

---

## 🚀 Deployment & Usage

### Prerequisites

- Python 3.10+

```bash
pip install -r requirements.txt
```

### Execution

```bash
python3 main.py
```

### Generated outputs

- `Audit_Report.pdf` — formal audit report
- `governance_sentinel.log` — structured execution log (audit trail)
- `raw_financial_data.csv` — synthetic dataset (mock mode only)

---

## 📋 Changelog

### [1.1.0] — 2026-05-24

#### Fixed
- `validators.py` — Added `df.copy()` to prevent in-place mutation of the original DataFrame across modules.
- `validators.py` — Extended null check to all CDEs (`amount`, `currency`, `timestamp`) before domain-level controls.
- `main.py` — Replaced bare `except Exception` with `logging.exception()` for full traceback capture on file.
- `reporter.py` — Added generation timestamp and framework version to the PDF (mandatory for ECB/EBA audit trail).

#### Added
- `data_loader.py` — `mode='mock'|'real'` flag to cleanly separate synthetic from real data; schema validation via `REQUIRED_COLUMNS`.
- `data_loader.py` — `_load_real()` function prepared for Phase 2 (CSV/DB/API loading with schema validation).
- `reporter.py` — Explicit BCBS 239 Principle mapping per DQ dimension in the PDF; dedicated handling of DI = 0.00 (systemic bias alert).
- `main.py` — Structured logging to both console and permanent `governance_sentinel.log` file; pipeline organised in 4 numbered steps.
- `requirements.txt` — New file with pinned dependency versions for CI/CD and regulatory audit reproducibility.

### [1.0.0] — 2026-05-01

#### Added
- Core DQ Validation Engine (BCBS 239 — Principles 3, 4, 6, 11).
- Algorithmic Fairness Audit via IBM AIF360 (EU AI Act Art. 10 & 13).
- Automated PDF Audit Report generation via fpdf.
- Synthetic dataset with intentional anomalies for demo and testing.

---

## 👤 Author & Leadership
**Daniele Delens**
Data Governance & BCBS239 Specialist
* **LinkedIn**: https://www.linkedin.com/in/delens/
