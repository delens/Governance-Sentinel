"""
main.py — Governance-Sentinel Entry Point
==========================================
Orchestratore principale del framework di audit.

Pipeline di esecuzione:
    1. Data Loading   : carica (o genera) i dati finanziari
    2. BCBS 239 Audit : valida le dimensioni DQ sui Critical Data Elements
    3. Fairness Audit : misura il Disparate Impact per EU AI Act (Art. 10)
    4. Report PDF     : genera documentazione formale per stakeholder regolatori

Uso:
    python3 main.py                  # esecuzione standard con dati mock
    python3 main.py --mode real      # (Phase 2) con dati reali da CSV/DB

Autore : Daniele Delens — Senior Data Governance & BCBS 239 Specialist
"""

import os
import sys
import logging

# --- Silenzia warning TensorFlow / AIF360 per output pulito in console ---
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# --- Logging strutturato: output su console E su file per audit trail ---
# Il file governance_sentinel.log è la traccia permanente di ogni esecuzione.
# È fondamentale per dimostrare evidenza dei controlli a revisori regolatori.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("governance_sentinel.log", encoding="utf-8"),
    ],
)
# Sopprimi i logger verbosi di librerie terze (aif360, sklearn, tensorflow)
for noisy_lib in ("root", "aif360", "sklearn", "tensorflow"):
    logging.getLogger(noisy_lib).setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

from data_loader import generate_mock_data
from validators import run_bcbs239_audit
from bias_audit import run_fairness_audit
from reporter import create_pdf_report


def main() -> None:
    """
    Esegue la pipeline completa di audit e genera il report PDF.

    Gli errori vengono loggati con traceback completo su file e console,
    garantendo tracciabilità anche in caso di fallimento (requisito audit).
    """
    logger.info("=" * 60)
    logger.info("🚀 Governance-Sentinel: avvio framework")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # STEP 1 — DATA LOADING
    # mode='mock' : dati sintetici con anomalie intenzionali per il demo.
    # mode='real' : (Phase 2) sostituire con caricamento da CSV/DB reale.
    # ------------------------------------------------------------------
    logger.info("STEP 1/4 — Caricamento dati (mode=mock)")
    df = generate_mock_data()
    logger.info("Dataset caricato: %d righe, %d colonne", len(df), len(df.columns))

    # ------------------------------------------------------------------
    # STEP 2 — BCBS 239 DQ AUDIT
    # ------------------------------------------------------------------
    logger.info("STEP 2/4 — Avvio BCBS 239 Data Quality Audit")
    dq_results = run_bcbs239_audit(df)
    logger.info("Risultati DQ: %s", dq_results)
    print(f"   Audit DQ completato: {dq_results}")

    # ------------------------------------------------------------------
    # STEP 3 — EU AI ACT FAIRNESS AUDIT (Disparate Impact)
    # ------------------------------------------------------------------
    logger.info("STEP 3/4 — Avvio EU AI Act Fairness Audit")
    bias_score = run_fairness_audit(df)
    logger.info("Disparate Impact Score: %.4f", bias_score)
    print(f"   Audit Bias completato: Score {bias_score:.4f}")

    # ------------------------------------------------------------------
    # STEP 4 — GENERAZIONE REPORT PDF
    # ------------------------------------------------------------------
    logger.info("STEP 4/4 — Generazione Audit Report PDF")
    create_pdf_report(dq_results, bias_score)

    logger.info("✅ Pipeline completata con successo.")
    print("\n✅ OPERAZIONE COMPLETATA!")
    print("📂 File generati: Audit_Report.pdf  |  governance_sentinel.log")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # logging.exception cattura il traceback completo → essenziale per il debug
        # in ambienti regolatori dove non si può accedere alla console in produzione.
        logger.exception("❌ Errore fatale durante l'esecuzione: %s", exc)
        sys.exit(1)
