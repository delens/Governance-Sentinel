"""
reporter.py — Audit Report Generator
=====================================
Genera il report PDF formale di audit per stakeholder regolatori
(CDO, Internal Audit, ECB/EBA) a partire dai risultati DQ e bias.

Il report include:
    - Metadata di generazione (timestamp, versione framework)
    - Risultati BCBS 239 per dimensione DQ (PASS/FAIL)
    - Score di fairness algoritmica EU AI Act (Disparate Impact)
    - Indicazione della soglia regolatoria EEOC (0.80)

Autore : Daniele Delens — Senior Data Governance & BCBS 239 Specialist
"""

import logging
from datetime import datetime
from fpdf import FPDF

# Versione del framework: aggiornare ad ogni release significativa
FRAMEWORK_VERSION = "1.0.0"

# Soglia minima Disparate Impact (regola 4/5 EEOC / standard internazionale)
DI_THRESHOLD = 0.80

logger = logging.getLogger(__name__)


def create_pdf_report(
    dq_results: dict,
    bias_score: float,
    output_path: str = "Audit_Report.pdf",
) -> None:
    """
    Genera il report PDF di audit e lo salva su disco.

    Args:
        dq_results  (dict):  Risultati BCBS 239 {dimensione: bool}.
        bias_score  (float): Disparate Impact ratio da AIF360.
        output_path (str):   Percorso del file PDF di output.
                             Default: "Audit_Report.pdf" nella directory corrente.

    Returns:
        None.  Il file viene scritto su disco e il percorso loggato.
    """
    # Timestamp di generazione: obbligatorio per audit trail regolatorio.
    # Un report senza data/ora non è accettabile per revisori ECB/EBA.
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    pdf = FPDF()
    pdf.add_page()

    # ----------------------------------------------------------------
    # HEADER — Titolo e metadata di generazione
    # ----------------------------------------------------------------
    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(200, 10, "Governance-Sentinel Audit Report", ln=True, align="C")

    pdf.set_font("Arial", size=9)
    pdf.cell(200, 6, f"Framework Version : {FRAMEWORK_VERSION}", ln=True, align="C")
    pdf.cell(200, 6, f"Generated         : {generated_at}", ln=True, align="C")
    pdf.ln(8)

    # ----------------------------------------------------------------
    # SEZIONE 1 — BCBS 239 DQ Audit (Principle mapping)
    # ----------------------------------------------------------------
    pdf.set_font("Arial", style="B", size=13)
    pdf.cell(200, 8, "1. BCBS 239 Data Quality Audit", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.ln(2)

    # Mappa dimensione → principio BCBS per contesto regolatorio nel report
    principle_map = {
        "Completeness": "Principle 3",
        "Accuracy":     "Principle 4",
        "Validity":     "Principle 6",
        "Timeliness":   "Principle 11",
    }

    for dimension, passed in dq_results.items():
        status_label = "PASS ✓" if passed else "FAIL ✗"
        principle    = principle_map.get(dimension, "—")
        line = f"  [{principle}]  {dimension:<15} :  {status_label}"
        pdf.cell(200, 8, line, ln=True)

    pdf.ln(4)

    # ----------------------------------------------------------------
    # SEZIONE 2 — EU AI Act Fairness Audit (Art. 10 & 13)
    # ----------------------------------------------------------------
    pdf.set_font("Arial", style="B", size=13)
    pdf.cell(200, 8, "2. EU AI Act — Algorithmic Fairness Audit", ln=True)
    pdf.set_font("Arial", size=11)
    pdf.ln(2)

    # Disparate Impact: 1.0 = perfetta equità, < 0.80 = alert critico (EEOC)
    di_status = "PASS ✓" if bias_score >= DI_THRESHOLD else "FAIL ✗  [CRITICAL REMEDIATION REQUIRED]"
    pdf.cell(200, 8, f"  Disparate Impact Ratio : {bias_score:.4f}", ln=True)
    pdf.cell(200, 8, f"  Regulatory Threshold   : {DI_THRESHOLD} (EEOC 4/5 Rule)", ln=True)
    pdf.cell(200, 8, f"  Status                 : {di_status}", ln=True)

    if bias_score == 0.0:
        pdf.ln(3)
        pdf.set_font("Arial", style="I", size=10)
        pdf.cell(
            200, 7,
            "  NOTE: DI = 0.00 indicates total exclusion of the unprivileged group.",
            ln=True,
        )
        pdf.cell(
            200, 7,
            "  This is a systemic bias condition requiring immediate model review.",
            ln=True,
        )

    pdf.ln(6)

    # ----------------------------------------------------------------
    # FOOTER — Firma e disclaimer
    # ----------------------------------------------------------------
    pdf.set_font("Arial", size=9)
    pdf.cell(200, 6, "─" * 80, ln=True)
    pdf.cell(200, 6, "Prepared by: Daniele Delens — Senior Data Governance & BCBS 239 Specialist", ln=True)
    pdf.cell(200, 6, "This document constitutes evidence of automated control effectiveness (2LoD).", ln=True)

    pdf.output(output_path)
    logger.info("Report PDF generato: %s", output_path)
    print(f"📄 Report salvato in: {output_path}")
