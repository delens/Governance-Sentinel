"""
data_loader.py — Data Loading Pipeline
========================================
Gestisce il caricamento dei dati finanziari in due modalità:

    mode='mock' : genera un dataset sintetico con anomalie intenzionali
                  per demo, test e sviluppo locale. Le anomalie coprono
                  tutti i casi di FAIL attesi dal BCBS 239 audit engine:
                    - transaction_id nullo  (viola Principle 3 - Completeness)
                    - amount negativo/fuori soglia (viola Principle 4 - Accuracy)
                    - valuta non ISO (XYZ)  (viola Principle 6 - Validity)
                    - timestamp pre-2023   (viola Principle 11 - Timeliness)

    mode='real' : carica dati da un file CSV reale (Phase 2).
                  Il percorso si imposta tramite il parametro `csv_path`.

Uso:
    from data_loader import generate_mock_data

    df = generate_mock_data()              # mock (default)
    df = generate_mock_data(mode='real', csv_path='data/transactions.csv')

Autore : Daniele Delens — Senior Data Governance & BCBS 239 Specialist
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Colonne obbligatorie che il framework si aspetta in input.
# Qualsiasi sorgente dati (mock o reale) deve rispettare questo schema.
REQUIRED_COLUMNS = [
    "transaction_id",   # CDE — identificatore primario transazione
    "client_id",        # CDE — identificatore cliente
    "amount",           # CDE — importo transazione
    "currency",         # CDE — valuta ISO 4217
    "timestamp",        # CDE — data/ora transazione (formato ISO 8601)
    "age_category",     # Attributo protetto per fairness audit (EU AI Act)
    "loan_approved",    # Label binaria — output del modello di credit scoring
]


def generate_mock_data(
    mode: str = "mock",
    csv_path: str = "raw_financial_data.csv",
) -> pd.DataFrame:
    """
    Carica o genera i dati finanziari per la pipeline di audit.

    Args:
        mode (str): Modalità di caricamento.
                    'mock' → dataset sintetico con anomalie intenzionali.
                    'real' → caricamento da CSV reale (csv_path obbligatorio).
        csv_path (str): Percorso del CSV sorgente.
                        In mode='mock' viene anche usato come path di output
                        per salvare il dataset generato (utile per debug).

    Returns:
        pd.DataFrame: Dataset con le colonne definite in REQUIRED_COLUMNS.

    Raises:
        ValueError: Se mode non è 'mock' o 'real'.
        FileNotFoundError: Se mode='real' e csv_path non esiste.
    """
    if mode == "mock":
        return _load_mock(csv_path)
    elif mode == "real":
        return _load_real(csv_path)
    else:
        raise ValueError(f"Modalità non riconosciuta: '{mode}'. Usa 'mock' o 'real'.")


# ─────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_mock(output_path: str) -> pd.DataFrame:
    """
    Genera un dataset sintetico di 5 transazioni con anomalie intenzionali.

    Ogni riga è progettata per coprire uno specifico scenario di audit:
        Riga 1 (101): valida in tutte le dimensioni → PASS atteso
        Riga 2 (102): amount negativo (-50) → FAIL Accuracy
        Riga 3 (None): transaction_id nullo + timestamp pre-2023 → FAIL Completeness + Timeliness
        Riga 4 (104): valuta non autorizzata (XYZ) → FAIL Validity
        Riga 5 (105): amount > 1.000.000 → FAIL Accuracy
    """
    logger.info("Modalità MOCK: generazione dataset sintetico con anomalie intenzionali.")

    data = {
        "transaction_id": [101,          102,   None,       104,   105      ],
        "client_id":      ["C01",        "C02", "C03",      "C04", "C05"    ],
        "amount":         [1500,         -50,   3000,       4500,  9_999_999],
        "currency":       ["EUR",        "EUR", "USD",      "XYZ", "EUR"    ],
        "timestamp":      ["2023-10-01", "2023-10-01", "2022-01-01",
                           "2023-10-02", "2023-10-03"                       ],
        "age_category":   [1,            2,     1,          1,     2        ],
        # Attributo protetto: 1 = Senior (unprivileged), 2 = Junior (privileged)
        "loan_approved":  [0,            1,     0,          0,     1        ],
    }

    df = pd.DataFrame(data)

    # Salva su CSV per consentire ispezione manuale e debug
    df.to_csv(output_path, index=False)
    logger.info("Dataset mock salvato in: %s (%d righe)", output_path, len(df))

    return df


def _load_real(csv_path: str) -> pd.DataFrame:
    """
    Carica un dataset reale da CSV e verifica la presenza delle colonne obbligatorie.

    Questa funzione è predisposta per la Phase 2 del framework.
    In produzione, sostituire o estendere con connettori a database,
    API REST o data lake (es. Azure Data Lake, AWS S3).

    Args:
        csv_path (str): Percorso assoluto o relativo al file CSV.

    Returns:
        pd.DataFrame: Dataset validato con le colonne REQUIRED_COLUMNS.

    Raises:
        FileNotFoundError: Se il file non esiste.
        ValueError: Se mancano colonne obbligatorie.
    """
    logger.info("Modalità REAL: caricamento dati da '%s'", csv_path)

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        logger.error("File CSV non trovato: %s", csv_path)
        raise

    # Schema validation: tutte le colonne obbligatorie devono essere presenti
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        logger.error("Colonne mancanti nel CSV: %s", missing)
        raise ValueError(
            f"Il CSV '{csv_path}' non contiene le colonne obbligatorie: {missing}. "
            f"Schema atteso: {REQUIRED_COLUMNS}"
        )

    logger.info("Dataset reale caricato: %d righe, %d colonne", len(df), len(df.columns))
    return df
