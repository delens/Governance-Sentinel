import pandas as pd

def run_bcbs239_audit(df):
    """
    Esegue la validazione DQ usando Pandas puro.
    Mappa i principi BCBS 239 in controlli logici.
    """
    # 1. COMPLETENESS: transaction_id non deve avere null
    c_ok = df['transaction_id'].notnull().all()
    
    # 2. ACCURACY: amount deve essere positivo e sotto 1 milione
    a_ok = ((df['amount'] >= 0) & (df['amount'] <= 1000000)).all()
    
    # 3. VALIDITY: currency deve essere in una lista autorizzata
    valid_currencies = ["EUR", "USD", "GBP"]
    v_ok = df['currency'].isin(valid_currencies).all()
    
    # 4. TIMELINESS: timestamp deve essere dal 2023 in poi
    # Convertiamo in datetime per sicurezza
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    t_ok = (df['timestamp'] >= "2023-01-01").all()
    
    return {
        "Completeness": bool(c_ok),
        "Accuracy": bool(a_ok),
        "Validity": bool(v_ok),
        "Timeliness": bool(t_ok)
    }