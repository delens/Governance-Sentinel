import os
import logging

# Silenziamo i warning per un output pulito
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.getLogger('root').setLevel(logging.ERROR)

from data_loader import generate_mock_data
from validators import run_bcbs239_audit
from bias_audit import run_fairness_audit
from reporter import create_pdf_report

print("🚀 Governance-Sentinel: Avvio Framework su Intel Mac...")

try:
    # 1. Pipeline Dati
    df = generate_mock_data()

    # 2. Audit Qualità (Logica BCBS 239)
    dq_results = run_bcbs239_audit(df)
    print(f"Audit DQ completato: {dq_results}")

    # 3. Audit Bias (Logica EU AI Act)
    bias_score = run_fairness_audit(df)
    print(f"Audit Bias completato: Score {bias_score:.2f}")

    # 4. Generazione Report PDF
    create_pdf_report(dq_results, bias_score)
    
    print("\n✅ OPERAZIONE COMPLETATA!")
    print("📂 Controlla la cartella: il file 'Audit_Report.pdf' è stato generato.")

except Exception as e:
    print(f"❌ Errore durante l'esecuzione: {e}")