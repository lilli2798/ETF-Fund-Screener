import pandas as pd

file_path = 'output/etf_screener/results_profile_A_2026-08-18_03-31-07.xlsx'
try:
    xl = pd.ExcelFile(file_path)
    print("Sheets:", xl.sheet_names)
    for sheet in xl.sheet_names:
        df = pd.read_excel(file_path, sheet_name=sheet)
        print(f"--- Sheet: {sheet} ---")
        print("Columns:", df.columns.tolist())
        print("First 2 rows:\n", df.head(2))
except Exception as e:
    print(f"Error: {e}")
