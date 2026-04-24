from aif360.datasets import BinaryLabelDataset
from aif360.metrics import BinaryLabelDatasetMetric

def run_fairness_audit(df):
    """
    Rileva bias statistico (EU AI Act) usando AIF360.
    Filtra solo le colonne numeriche rilevanti per evitare errori di conversione.
    """
    # 1. Pulizia: togliamo i nulli
    df_clean = df.dropna().copy()
    
    # 2. Selezione Colonne: Teniamo solo i dati numerici per l'audit di bias
    # age_category (protetto) e loan_approved (risultato)
    relevant_cols = ['age_category', 'loan_approved']
    df_numeric = df_clean[relevant_cols].astype(float)
    
    # 3. Creazione Dataset AIF360
    dataset = BinaryLabelDataset(df=df_numeric, 
                                 label_names=['loan_approved'], 
                                 protected_attribute_names=['age_category'])
    
    privileged_groups = [{'age_category': 2}]   # Junior
    unprivileged_groups = [{'age_category': 1}] # Senior
    
    metric = BinaryLabelDatasetMetric(dataset, 
                                      unprivileged_groups=unprivileged_groups,
                                      privileged_groups=privileged_groups)
    
    return metric.disparate_impact()