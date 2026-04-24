import pandas as pd

def generate_mock_data():
    data = {
        "transaction_id": [101, 102, None, 104, 105],
        "client_id": ["C01", "C02", "C03", "C04", "C05"],
        "amount": [1500, -50, 3000, 4500, 9999999],
        "currency": ["EUR", "EUR", "USD", "XYZ", "EUR"],
        "timestamp": ["2023-10-01", "2023-10-01", "2022-01-01", "2023-10-02", "2023-10-03"],
        "age_category": [1, 2, 1, 1, 2],
        "loan_approved": [0, 1, 0, 0, 1]
    }
    df = pd.DataFrame(data)
    df.to_csv("raw_financial_data.csv", index=False)
    return df