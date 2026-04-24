# Governance-Sentinel 🛡️
### Automated Data Governance Framework for BCBS 239 & EU AI Act Compliance

**Governance-Sentinel** is a Python-based framework designed to bridge the gap between regulatory requirements and automated data oversight. It provides a modular approach to monitoring financial data integrity and ensuring algorithmic fairness in high-risk AI systems (e.g., Credit Scoring).

### ⚖️ Technical Focus: Disparate Impact Analysis
To comply with the **EU AI Act's** requirements for non-discrimination in high-risk AI, this framework calculates the **Disparate Impact (DI)** ratio. 

* **Metric Definition**: DI compares the selection rate of a protected group (e.g., Seniors) against a privileged group (e.g., Juniors).
* **Compliance Threshold**: Following international regulatory standards, a DI ratio below **0.80** indicates a "Disparate Impact," signaling that the underlying data or model may be discriminatory.
* **Governance Action**: In this framework, a DI of **0.00** was detected, triggering an immediate "High Risk" alert in the Audit Report, necessitating a full review of the training dataset's representative quality.
---

## 📌 Executive Summary
In the modern banking landscape, manual governance is a liability. This project demonstrates a "Compliance-as-Code" approach to handle:
1. **BCBS 239**: Risk data aggregation and reporting accuracy.
2. **EU AI Act**: Ethical oversight and bias detection in automated decision-making.

---

## 🛠️ Technical Architecture & Libraries
The framework is built using a modular Python architecture:
* **Data Processing**: `Pandas` for robust data manipulation and cleaning.
* **Algorithmic Fairness**: `AIF360` (IBM Toolkit) to measure the **Disparate Impact Ratio**, ensuring non-discriminatory outcomes for protected groups (Age, Gender, etc.).
* **Automated Reporting**: `FPDF` for generating executive-level Audit Reports.

---

## 📋 Governance Pillars (Implementation Details)

### 1. Data Quality Framework (BCBS 239 Alignment)
The engine validates 4 critical dimensions of data:
* **Completeness**: Ensures no missing values in critical identifiers (e.g., Transaction IDs).
* **Accuracy**: Validates financial amounts against predefined risk thresholds.
* **Validity**: Checks data against official dictionaries (e.g., ISO Currency Codes).
* **Timeliness**: Ensures data points fall within the required reporting period.

### 2. AI Ethics & Fairness Audit (EU AI Act Compliance)
Simulating an audit for a **High-Risk AI system** (Credit Scoring), the framework:
* Identifies "Protected Attributes" (e.g., Age Category).
* Calculates the **Disparate Impact Ratio**. 
* **Risk Threshold**: A score below **0.80** triggers a "High Risk" alert, indicating potential systemic discrimination that requires immediate remediation before model deployment.

---

## 🚀 Roadmap & Remediation Strategy
This project includes a managed **GitHub Roadmap** (see Projects tab) focusing on:
* **Remediation workflows** for failed DQ checks.
* **Continuous Monitoring** integration for real-time compliance dashboards.
* **Metadata Lineage** tracking for end-to-end data traceability.

---

## 💻 How to Run (Local Environment)
1. Clone the repository.
2. Install dependencies: `pip install pandas aif360 fpdf fairlearn`.
3. Execute the audit: `python3 main.py`.
4. Review the generated `Audit_Report.pdf`.