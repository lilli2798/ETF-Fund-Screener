"""
Populate morningstar table from existing Excel file
"""
import pandas as pd

from etf_screener.database import ETFScreenerDatabase

# Load the Excel file from today's run
excel_path = "output/etf_screener/results_profile_A_2026-08-18_03-31-07.xlsx"
df = pd.read_excel(excel_path)

print(f"Loaded {len(df)} rows from Excel file")
print(f"Columns: {len(df.columns)}")

# Save to morningstar table
db = ETFScreenerDatabase()
db.save_morningstar_data(df)
db.close()

print("Morningstar table populated successfully")
