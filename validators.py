"""
validators.py — BCBS 239 Data Quality Audit Engine
====================================================
Mappa i Principi BCBS 239 in controlli logici automatizzati
sulle dimensioni di qualità dei Critical Data Elements (CDE).

Principi coperti:
    - Principle 3  : Completeness
    - Principle 4  : Accuracy
    - Principle 6  : Validity (allineamento con master data / ISO)
    - Principle 11 : Timeliness (disponibilità entro T+1)

Autore : Daniele Delens — Senior Data Governance & BCBS 239 Specialist
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


def run_bcbs239_audit(df: pd.DataFrame) -> dict:
    """
    Esegue la validazione DQ sulle dimensioni BCBS 239.

    Il DataFrame originale NON viene modificato: si lavora su una copia
    per evitare effetti collaterali tra moduli (side-effect safety).

    Args:
        df (pd.DataFrame): Dataset finanziario grezzo con almeno le colonne:
                           transaction_id, amount, currency, timestamp.

    Returns:
        dict: Mappa {dimensione: bool} con il risultato PASS/FAIL per ciascun
              principio BCBS 239 verificato.
    """
    # --- Copia difensiva: non mutare mai il DataFrame originale ---
    df = df.copy()

    # ----------------------------------------------------------------
    # PRE-CHECK: null check su tutti i CDE prima dei controlli di dominio.
    # Se una colonna critica è completamente nulla, i controlli successivi
    # potrebbero restituire falsi positivi (es. .all() su serie vuota = True).
    # ----------------------------------------------------------------
    critical_columns = ["transaction_id", "amount", "currency", "timestamp"]
    for col in critical_columns:
        if col not in df.columns:
            logger.error("Colonna CDE mancante: %s — audit interrotto.", col)
            raise ValueError(f"Colonna CDE obbligatoria non trovata: '{col}'")

    # ----------------------------------------------------------------
    # PRINCIPLE 3 — COMPLETENESS
    # Tutti i CDE chiave non devono contenere valori nulli.
    # transaction_id è l'identificatore primario: un null indica
    # una transazione non tracciabile → violazione critica.
    # ----------------------------------------------------------------
    completeness_ok = df["transaction_id"].notnull().all()
    logger.debug("Completeness check: %s", completeness_ok)

    # ----------------------------------------------------------------
    # PRINCIPLE 4 — ACCURACY
    # Gli importi devono essere positivi e rientrare nella soglia massima
    # autorizzata (1.000.000) per prevenire corruzione nei modelli di rischio.
    # Nota: importi negativi indicano errori di imputazione, non rimborsi
    # (quelli andrebbero su colonne separate nel modello dati).
    # ----------------------------------------------------------------
    accuracy_ok = (
        df["amount"].notnull().all()
        and ((df["amount"] >= 0) & (df["amount"] <= 1_000_000)).all()
    )
    logger.debug("Accuracy check: %s", accuracy_ok)

    # ----------------------------------------------------------------
    # PRINCIPLE 6 — VALIDITY
    # La valuta deve appartenere alla whitelist ISO 4217 approvata
    # dall'istituzione. Valute non riconosciute (es. "XYZ") invalidano
    # il flusso di aggregazione del rischio.
    # ----------------------------------------------------------------
    valid_currencies = {"EUR", "USD", "GBP"}
    validity_ok = (
        df["currency"].notnull().all()
        and df["currency"].isin(valid_currencies).all()
    )
    logger.debug("Validity check: %s", validity_ok)

    # ----------------------------------------------------------------
    # PRINCIPLE 11 — TIMELINESS
    # I dati devono essere disponibili a partire dal 2023-01-01 (soglia T+1).
    # La conversione a datetime viene fatta sulla copia, mai sull'originale.
    # ----------------------------------------------------------------
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    timeliness_ok = (
        df["timestamp"].notnull().all()
        and (df["timestamp"] >= "2023-01-01").all()
    )
    logger.debug("Timeliness check: %s", timeliness_ok)

    results = {
        "Completeness": bool(completeness_ok),
        "Accuracy":     bool(accuracy_ok),
        "Validity":     bool(validity_ok),
        "Timeliness":   bool(timeliness_ok),
    }

    logger.info("BCBS 239 audit completato: %s", results)
    return results
