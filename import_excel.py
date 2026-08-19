import pandas as pd
import sqlite3
import re
import os
import sys

def sanitize_name(name):
    """Sanitize sheet name to be a valid SQLite table name."""
    # Replace non-alphanumeric characters with underscores
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)

def import_excel_to_sqlite(excel_path, db_path):
    """Reads an Excel file and imports each sheet as a separate table."""
    print(f"Reading {excel_path}...")
    
    # Use pandas to read all sheets
    try:
        xl = pd.ExcelFile(excel_path)
    except Exception as e:
        print(f"Error opening Excel file: {e}")
        return

    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    
    for sheet_name in xl.sheet_names:
        table_name = sanitize_name(sheet_name)
        print(f"Importing sheet '{sheet_name}' into table '{table_name}'...")
        
        # Read the sheet
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        
        # Clean column names (standardize for SQL)
        new_columns = []
        seen_columns = {}
        for col in df.columns:
            # Clean and sanitize
            clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', str(col)).lower()
            
            # Handle duplicates
            if clean_name in seen_columns:
                seen_columns[clean_name] += 1
                clean_name = f"{clean_name}_{seen_columns[clean_name]}"
            else:
                seen_columns[clean_name] = 0
            
            new_columns.append(clean_name)
        
        df.columns = new_columns
        
        # Import to SQLite (replace table if it exists)
        df.to_sql(table_name, conn, if_exists='replace', index=False)
        print(f"Successfully imported {len(df)} rows into '{table_name}'.")
        
    conn.close()
    print("All sheets imported successfully.")

if __name__ == "__main__":
    DB_FILE = 'data/etf_screener.db'
    
    # Get file path from command line argument or prompt
    if len(sys.argv) > 1:
        INPUT_EXCEL = sys.argv[1]
    else:
        INPUT_EXCEL = input("Enter the path to the Excel file: ").strip()
    
    # Run the import
    if os.path.exists(INPUT_EXCEL):
        import_excel_to_sqlite(INPUT_EXCEL, DB_FILE)
    else:
        print(f"File not found: {INPUT_EXCEL}")
