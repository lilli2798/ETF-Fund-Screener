#!/usr/bin/env python3
"""
Update fund ratings in the database from Morningstar data.
This script is designed to run monthly to update rating information
without running the full screener pipeline.
"""

import pandas as pd
from pathlib import Path
from database import ETFScreenerDatabase
from data_loading import load_morningstar_data
from datetime import datetime
import sys

def main():
    """Main function to update fund ratings."""
    print(f"Starting fund rating update at {datetime.now()}")
    
    # Initialize database
    db = ETFScreenerDatabase()
    
    # Load Morningstar data from the data directory
    data_dir = Path("data")
    
    # Find all Morningstar Excel files in the data directory
    excel_files = list(data_dir.glob("*.xlsx"))
    
    if not excel_files:
        print("No Morningstar data files found in data directory")
        sys.exit(1)
    
    print(f"Found {len(excel_files)} data files to process")
    
    total_updated = 0
    
    for file_path in excel_files:
        print(f"Processing {file_path.name}...")
        try:
            # Load data from this file
            df = load_morningstar_data(str(file_path))
            
            # Update ratings in database
            updated = db.update_fund_ratings(df)
            total_updated += updated
            print(f"  Updated {updated} funds from {file_path.name}")
            
        except Exception as e:
            print(f"  Error processing {file_path.name}: {e}")
            continue
    
    db.close()
    
    print(f"\nRating update complete. Total funds updated: {total_updated}")
    print(f"Completed at {datetime.now()}")

if __name__ == "__main__":
    main()
