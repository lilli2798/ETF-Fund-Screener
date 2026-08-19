"""
Query Utility for ETF Screener Results Database

This script provides an interactive command-line interface to search and filter
historical screener results stored in SQLite database.

Usage:
    python query_results.py

Examples of queries you can make:
    - List recent runs
    - Get results for a specific run
    - Search by ticker
    - Filter by score range
    - Filter by category
    - Get latest results for a profile
    - Import Excel file to database table
"""

import pandas as pd
from etf_screener.database import ETFScreenerDatabase
from pathlib import Path


def print_menu():
    """Print the main menu options."""
    print("\n" + "="*60)
    print("ETF Screener Results Query Tool")
    print("="*60)
    print("1. List all database tables")
    print("2. List recent runs")
    print("3. List recent runs for a specific profile")
    print("4. Get full results for a specific run")
    print("5. Query funds by filters (ticker, score, category)")
    print("6. Query funds by concept scores")
    print("7. Compare metrics between runs (historical analysis)")
    print("8. Get latest results for a profile")
    print("9. Export query results to Excel")
    print("10. Drop a table")
    print("11. Check columns in a table")
    print("12. Import Excel file to database table")
    print("0. Exit")
    print("="*60)


def list_all_tables(db: ETFScreenerDatabase):
    """List all tables in the database."""
    print("\n--- Database Tables ---")
    tables = db.list_tables()
    
    if not tables:
        print("No tables found in database.")
        return
    
    print(f"Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table}")


def list_recent_runs(db: ETFScreenerDatabase):
    """List recent runs across all profiles."""
    print("\n--- Recent Runs ---")
    runs = db.get_run_ids(limit=20)
    
    if not runs:
        print("No runs found in database.")
        return
    
    print(f"{'Run ID':<40} {'Profile':<15} {'Date':<20} {'Funds':<10}")
    print("-" * 85)
    for run in runs:
        run_id = run['run_id'][:37] + "..." if len(run['run_id']) > 37 else run['run_id']
        # Handle both string and datetime timestamps
        if run['run_timestamp']:
            if hasattr(run['run_timestamp'], 'strftime'):
                date_str = run['run_timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                date_str = str(run['run_timestamp'])
        else:
            date_str = 'N/A'
        print(f"{run_id:<40} {run['profile_name']:<15} {date_str:<20} {run['total_funds_count']:<10}")


def list_runs_for_profile(db: ETFScreenerDatabase):
    """List recent runs for a specific profile."""
    profile_name = input("Enter profile name (e.g., A): ").strip()
    
    if not profile_name:
        print("Profile name cannot be empty.")
        return
    
    print(f"\n--- Recent Runs for Profile {profile_name} ---")
    runs = db.get_run_ids(profile_name=profile_name, limit=20)
    
    if not runs:
        print(f"No runs found for profile '{profile_name}'.")
        return
    
    print(f"{'Run ID':<40} {'Date':<20} {'Funds':<10}")
    print("-" * 70)
    for run in runs:
        run_id = run['run_id'][:37] + "..." if len(run['run_id']) > 37 else run['run_id']
        # Handle both string and datetime timestamps
        if run['run_timestamp']:
            if hasattr(run['run_timestamp'], 'strftime'):
                date_str = run['run_timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                date_str = str(run['run_timestamp'])
        else:
            date_str = 'N/A'
        print(f"{run_id:<40} {date_str:<20} {run['total_funds_count']:<10}")


def get_results_for_run(db: ETFScreenerDatabase):
    """Get and display full results for a specific run."""
    run_id = input("Enter run ID (or paste from list): ").strip()
    
    if not run_id:
        print("Run ID cannot be empty.")
        return
    
    print(f"\n--- Results for Run: {run_id} ---")
    df = db.get_results_by_run_id(run_id)
    
    if df is None:
        print(f"No results found for run_id '{run_id}'.")
        return
    
    print(f"Found {len(df)} funds in this run.")
    print("\nFirst 10 rows:")
    print(df.head(10).to_string(index=False))
    
    # Ask if user wants to see more
    while True:
        choice = input("\nShow more rows? (n for next 10, q to quit): ").strip().lower()
        if choice == 'n':
            print(df.head(20).tail(10).to_string(index=False))
        elif choice == 'q':
            break
        else:
            break


def query_funds_by_filters(db: ETFScreenerDatabase):
    """Query funds with various filters."""
    print("\n--- Query Funds by Filters ---")
    print("Leave fields empty to skip that filter")
    
    profile_name = input("Profile name (e.g., A): ").strip() or None
    ticker = input("Ticker (partial match, e.g., SPY): ").strip() or None
    min_score = input("Minimum total score (e.g., 80): ").strip()
    min_score = float(min_score) if min_score else None
    max_score = input("Maximum total score (e.g., 100): ").strip()
    max_score = float(max_score) if max_score else None
    category = input("Category (partial match, e.g., Large): ").strip() or None
    limit = input("Max results (default 100): ").strip()
    limit = int(limit) if limit else 100
    
    print("\nQuerying database...")
    df = db.query_funds(
        profile_name=profile_name,
        ticker=ticker,
        min_score=min_score,
        max_score=max_score,
        category=category,
        limit=limit
    )
    
    if df.empty:
        print("No funds found matching your criteria.")
        return
    
    print(f"\nFound {len(df)} funds matching your criteria:")
    print(df.to_string(index=False))
    
    return df


def query_funds_by_concept_scores(db: ETFScreenerDatabase):
    """Query funds with concept score filters."""
    print("\n--- Query Funds by Concept Scores ---")
    print("Leave fields empty to skip that filter")
    
    profile_name = input("Profile name (e.g., A): ").strip() or None
    ticker = input("Ticker (partial match, e.g., SPY): ").strip() or None
    category = input("Category (partial match, e.g., Large): ").strip() or None
    
    print("\nConcept Score Filters (minimum values):")
    min_long_term = input("Min Long Term Return Performance Score: ").strip()
    min_long_term = float(min_long_term) if min_long_term else None
    min_short_term = input("Min Short Term Return Performance Score: ").strip()
    min_short_term = float(min_short_term) if min_short_term else None
    min_risk_adjusted = input("Min Risk Adjusted Score: ").strip()
    min_risk_adjusted = float(min_risk_adjusted) if min_risk_adjusted else None
    min_volatility = input("Min Volatility Score: ").strip()
    min_volatility = float(min_volatility) if min_volatility else None
    min_tracking = input("Min Tracking Score: ").strip()
    min_tracking = float(min_tracking) if min_tracking else None
    min_liquidity = input("Min Liquidity Size Score: ").strip()
    min_liquidity = float(min_liquidity) if min_liquidity else None
    min_quality = input("Min Quality Valuation Score: ").strip()
    min_quality = float(min_quality) if min_quality else None
    min_costs = input("Min Costs Score: ").strip()
    min_costs = float(min_costs) if min_costs else None
    
    limit = input("Max results (default 100): ").strip()
    limit = int(limit) if limit else 100
    
    print("\nQuerying database...")
    df = db.query_funds_by_concept_scores(
        profile_name=profile_name,
        ticker=ticker,
        category=category,
        min_long_term_score=min_long_term,
        min_short_term_score=min_short_term,
        min_risk_adjusted_score=min_risk_adjusted,
        min_volatility_score=min_volatility,
        min_tracking_score=min_tracking,
        min_liquidity_score=min_liquidity,
        min_quality_score=min_quality,
        min_costs_score=min_costs,
        limit=limit
    )
    
    if df.empty:
        print("No funds found matching your criteria.")
        return
    
    print(f"\nFound {len(df)} funds matching your criteria:")
    print(df.to_string(index=False))
    
    return df


def compare_metrics_between_runs(db: ETFScreenerDatabase):
    """Compare metrics between two runs to find funds with increasing values."""
    print("\n--- Compare Metrics Between Runs ---")
    
    # Show available runs first
    print("\nAvailable runs:")
    runs = db.get_run_ids(limit=10)
    if not runs:
        print("No runs found in database.")
        return
    
    print(f"{'#':<3} {'Run ID':<40} {'Profile':<15} {'Date':<20}")
    print("-" * 78)
    for i, run in enumerate(runs, 1):
        run_id = run['run_id'][:37] + "..." if len(run['run_id']) > 37 else run['run_id']
        # Handle both string and datetime timestamps
        if run['run_timestamp']:
            if hasattr(run['run_timestamp'], 'strftime'):
                date_str = run['run_timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                date_str = str(run['run_timestamp'])
        else:
            date_str = 'N/A'
        print(f"{i:<3} {run_id:<40} {run['profile_name']:<15} {date_str:<20}")
    
    print("\nAvailable metrics:")
    print("  - better_worst_diff")
    print("  - better_pct")
    print("  - worst_pct")
    print("  - worst_three_month_return")
    print("  - profile_score")
    print("  - long_term_return_performance_score")
    print("  - short_term_return_performance_score")
    print("  - risk_adjusted_score")
    print("  - volatility_score")
    print("  - tracking_score")
    print("  - liquidity_size_score")
    print("  - quality_valuation_score")
    print("  - costs_score")
    
    metric = input("\nEnter metric to compare: ").strip()
    if not metric:
        print("Metric cannot be empty.")
        return
    
    print("\nSelect runs to compare:")
    print("You can enter run IDs directly or use numbers from the list above")
    old_run_input = input("Old run ID (or number from list, leave empty for second most recent): ").strip()
    new_run_input = input("New run ID (or number from list, leave empty for most recent): ").strip()
    
    # Handle numeric input
    if old_run_input and old_run_input.isdigit():
        idx = int(old_run_input) - 1
        if 0 <= idx < len(runs):
            old_run_id = runs[idx]['run_id']
        else:
            print("Invalid number selection.")
            return
    else:
        old_run_id = old_run_input or None
    
    if new_run_input and new_run_input.isdigit():
        idx = int(new_run_input) - 1
        if 0 <= idx < len(runs):
            new_run_id = runs[idx]['run_id']
        else:
            print("Invalid number selection.")
            return
    else:
        new_run_id = new_run_input or None
    
    limit = input("Max results (default 20): ").strip()
    limit = int(limit) if limit else 20
    
    print("\nQuerying database...")
    df = db.compare_metric_between_runs(
        metric=metric,
        old_run_id=old_run_id,
        new_run_id=new_run_id,
        limit=limit
    )
    
    if df.empty:
        print("No funds found with increasing values for this metric.")
        return
    
    print(f"\nFound {len(df)} funds with increasing {metric}:")
    print(df.to_string(index=False))
    
    return df


def get_latest_for_profile(db: ETFScreenerDatabase):
    """Get the most recent results for a profile."""
    profile_name = input("Enter profile name (e.g., A): ").strip()
    
    if not profile_name:
        print("Profile name cannot be empty.")
        return
    
    print(f"\n--- Latest Results for Profile {profile_name} ---")
    run_id = db.get_latest_run_for_profile(profile_name)
    
    if not run_id:
        print(f"No runs found for profile '{profile_name}'.")
        return
    
    print(f"Latest run ID: {run_id}")
    df = db.get_results_by_run_id(run_id)
    
    if df is None:
        print(f"Could not retrieve results for run_id '{run_id}'.")
        return
    
    print(f"Found {len(df)} funds in latest run.")
    print("\nFirst 10 rows:")
    print(df.head(10).to_string(index=False))
    
    return df


def export_to_excel(df: pd.DataFrame):
    """Export query results to Excel."""
    if df is None or df.empty:
        print("No data to export.")
        return
    
    from datetime import datetime
    filename = f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(filename, index=False)
    print(f"\nResults exported to: {filename}")


def drop_table(db: ETFScreenerDatabase):
    """Drop a table from the database with confirmation."""
    print("\n--- Drop Table ---")
    
    # First, list all tables
    tables = db.list_tables()
    
    if not tables:
        print("No tables found in database.")
        return
    
    print(f"Found {len(tables)} tables:")
    for i, table in enumerate(tables, 1):
        print(f"  {i}. {table}")
    
    # Get table name to drop
    table_input = input("\nEnter table name or number to drop (or 'cancel' to abort): ").strip()
    
    if table_input.lower() == 'cancel':
        print("Operation cancelled.")
        return
    
    # Handle numeric input
    if table_input.isdigit():
        idx = int(table_input) - 1
        if 0 <= idx < len(tables):
            table_name = tables[idx]
        else:
            print("Invalid number selection.")
            return
    else:
        table_name = table_input
    
    # Validate table exists
    if table_name not in tables:
        print(f"Table '{table_name}' not found in database.")
        return
    
    # Safety confirmation
    print(f"\n⚠️  WARNING: You are about to drop table '{table_name}'")
    print("This action cannot be undone!")
    confirmation = input(f"Type 'DROP {table_name}' to confirm: ").strip()
    
    if confirmation == f"DROP {table_name}":
        try:
            cursor = db.conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            db.conn.commit()
            print(f"✓ Table '{table_name}' has been dropped successfully.")
        except Exception as e:
            print(f"✗ Error dropping table: {e}")
    else:
        print("Operation cancelled - confirmation did not match.")


def check_columns(db: ETFScreenerDatabase):
    """Check and display columns in a specific table."""
    print("\n--- Check Columns in Table ---")
    
    # First, list all tables
    tables = db.list_tables()
    
    if not tables:
        print("No tables found in database.")
        return
    
    print(f"Found {len(tables)} tables:")
    for i, table in enumerate(tables, 1):
        print(f"  {i}. {table}")
    
    # Get table name to check
    table_input = input("\nEnter table name or number to check columns (or 'cancel' to abort): ").strip()
    
    if table_input.lower() == 'cancel':
        print("Operation cancelled.")
        return
    
    # Handle numeric input
    if table_input.isdigit():
        idx = int(table_input) - 1
        if 0 <= idx < len(tables):
            table_name = tables[idx]
        else:
            print("Invalid number selection.")
            return
    else:
        table_name = table_input
    
    # Validate table exists
    if table_name not in tables:
        print(f"Table '{table_name}' not found in database.")
        return
    
    # Get column information
    try:
        cursor = db.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        if not columns:
            print(f"No columns found in table '{table_name}'.")
            return
        
        print(f"\n--- Columns in table '{table_name}' ---")
        print(f"{'Column Name':<30} {'Type':<15} {'Not Null':<10} {'Default':<15} {'Primary Key':<12}")
        print("-" * 82)
        
        for col in columns:
            col_id, col_name, col_type, not_null, default_val, pk = col
            not_null_str = "YES" if not_null else "NO"
            pk_str = "YES" if pk else "NO"
            default_str = str(default_val) if default_val else ""
            
            print(f"{col_name:<30} {col_type:<15} {not_null_str:<10} {default_str:<15} {pk_str:<12}")
        
        print(f"\nTotal columns: {len(columns)}")
        
    except Exception as e:
        print(f"✗ Error retrieving columns: {e}")


def import_excel_to_table(db: ETFScreenerDatabase):
    """Import an Excel file to a database table."""
    print("\n--- Import Excel to Database Table ---")
    
    # Get Excel file path
    excel_path = input("Enter Excel file path (or 'cancel' to abort): ").strip()
    
    if excel_path.lower() == 'cancel':
        print("Operation cancelled.")
        return
    
    if not Path(excel_path).exists():
        print(f"✗ File not found: {excel_path}")
        return
    
    # Get sheet name
    try:
        xls = pd.ExcelFile(excel_path)
        print(f"\nAvailable sheets in {excel_path}:")
        for i, sheet in enumerate(xls.sheet_names, 1):
            print(f"  {i}. {sheet}")
        
        sheet_input = input("\nEnter sheet name or number (or 'cancel' to abort): ").strip()
        
        if sheet_input.lower() == 'cancel':
            print("Operation cancelled.")
            return
        
        # Handle numeric input
        if sheet_input.isdigit():
            idx = int(sheet_input) - 1
            if 0 <= idx < len(xls.sheet_names):
                sheet_name = xls.sheet_names[idx]
            else:
                print("Invalid number selection.")
                return
        else:
            sheet_name = sheet_input
        
        if sheet_name not in xls.sheet_names:
            print(f"✗ Sheet '{sheet_name}' not found in Excel file.")
            return
        
    except Exception as e:
        print(f"✗ Error reading Excel file: {e}")
        return
    
    # Use sheet name as default table name (sanitized for SQL)
    default_table_name = sheet_name.replace(" ", "_").replace("-", "_").replace("/", "_").replace("(", "").replace(")", "").replace("%", "_")
    if default_table_name and default_table_name[0].isdigit():
        default_table_name = f"tbl_{default_table_name}"
    
    # Get table name (default to sheet name)
    table_name = input(f"Enter table name [default: {default_table_name}] (or 'cancel' to abort): ").strip()
    
    if table_name.lower() == 'cancel':
        print("Operation cancelled.")
        return
    
    if not table_name:
        table_name = default_table_name
    
    # Validate table name (SQL-safe)
    table_name = table_name.replace(" ", "_").replace("-", "_").replace("/", "_")
    if table_name and table_name[0].isdigit():
        table_name = f"tbl_{table_name}"
    
    # Confirm if table exists
    cursor = db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    table_exists = cursor.fetchone() is not None
    
    if table_exists:
        print(f"\n⚠️  Table '{table_name}' already exists in database.")
        overwrite = input("Do you want to drop and recreate it? (yes/no): ").strip().lower()
        if overwrite != 'yes':
            print("Operation cancelled.")
            return
        
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            db.conn.commit()
            print(f"✓ Dropped existing table '{table_name}'")
        except Exception as e:
            print(f"✗ Error dropping table: {e}")
            return
    
    # Read Excel data
    try:
        print(f"\nReading sheet '{sheet_name}' from Excel file...")
        df = pd.read_excel(excel_path, sheet_name=sheet_name)
        
        if df.empty:
            print("✗ Excel sheet is empty.")
            return
        
        print(f"✓ Read {len(df)} rows and {len(df.columns)} columns")
        
    except Exception as e:
        print(f"✗ Error reading Excel data: {e}")
        return
    
    # Convert column names to SQL-safe identifiers
    column_mapping = {}
    columns_sql = []
    
    for col in df.columns:
        sql_col = str(col).replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_").replace("-", "_").replace("%", "_")
        if sql_col and sql_col[0].isdigit():
            sql_col = f"col_{sql_col}"
        column_mapping[str(col)] = sql_col
        columns_sql.append(f'"{sql_col}" TEXT')
    
    columns_def = ",\n            ".join(columns_sql)
    
    # Create table
    try:
        create_sql = f"""
            CREATE TABLE {table_name} (
                {columns_def}
            )
        """
        cursor.execute(create_sql)
        db.conn.commit()
        print(f"✓ Created table '{table_name}' with {len(columns_sql)} columns")
        
    except Exception as e:
        print(f"✗ Error creating table: {e}")
        return
    
    # Insert data
    try:
        sql_cols = list(column_mapping.values())
        placeholders = ", ".join(["?"] * len(sql_cols))
        insert_sql = f"""
            INSERT INTO {table_name} ({", ".join(sql_cols)})
            VALUES ({placeholders})
        """
        
        inserted_count = 0
        for _, row in df.iterrows():
            values = []
            for df_col in column_mapping.keys():
                value = row.get(df_col)
                # Convert NaN to None for SQL NULL
                if pd.isna(value):
                    values.append(None)
                # Convert datetime/timestamp to string
                elif hasattr(value, 'strftime'):
                    values.append(str(value))
                else:
                    values.append(value)
            
            try:
                cursor.execute(insert_sql, values)
                inserted_count += 1
            except Exception as e:
                print(f"  Warning: Failed to insert row: {e}")
        
        db.conn.commit()
        print(f"✓ Inserted {inserted_count} rows into table '{table_name}'")
        print(f"\n✓ Successfully imported Excel data to table '{table_name}'")
        
    except Exception as e:
        print(f"✗ Error inserting data: {e}")
        return


def main():
    """Main interactive loop."""
    db = ETFScreenerDatabase()
    
    while True:
        print_menu()
        choice = input("Enter your choice (0-12): ").strip()
        
        if choice == '0':
            print("Exiting...")
            break
        elif choice == '1':
            list_all_tables(db)
        elif choice == '2':
            list_recent_runs(db)
        elif choice == '3':
            list_runs_for_profile(db)
        elif choice == '4':
            get_results_for_run(db)
        elif choice == '5':
            df = query_funds_by_filters(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '6':
            df = query_funds_by_concept_scores(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '7':
            df = compare_metrics_between_runs(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '8':
            df = get_latest_for_profile(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '9':
            print("Please run a query first (options 5, 6, 7, or 8).")
        elif choice == '10':
            drop_table(db)
        elif choice == '11':
            check_columns(db)
        elif choice == '12':
            import_excel_to_table(db)
        else:
            print("Invalid choice. Please try again.")
    
    db.close()


if __name__ == "__main__":
    main()
