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
"""

import pandas as pd
from database import ETFScreenerDatabase


def print_menu():
    """Print the main menu options."""
    print("\n" + "="*60)
    print("ETF Screener Results Query Tool")
    print("="*60)
    print("1. List recent runs")
    print("2. List recent runs for a specific profile")
    print("3. Get full results for a specific run")
    print("4. Query funds by filters (ticker, score, category)")
    print("5. Get latest results for a profile")
    print("6. Export query results to Excel")
    print("0. Exit")
    print("="*60)


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
        date_str = run['run_timestamp'].strftime('%Y-%m-%d %H:%M:%S') if run['run_timestamp'] else 'N/A'
        print(f"{run_id:<40} {run['profile_name']:<15} {date_str:<20} {run['total_funds']:<10}")


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
        date_str = run['run_timestamp'].strftime('%Y-%m-%d %H:%M:%S') if run['run_timestamp'] else 'N/A'
        print(f"{run_id:<40} {date_str:<20} {run['total_funds']:<10}")


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


def main():
    """Main interactive loop."""
    db = ETFScreenerDatabase()
    
    while True:
        print_menu()
        choice = input("Enter your choice (0-6): ").strip()
        
        if choice == '0':
            print("Exiting...")
            break
        elif choice == '1':
            list_recent_runs(db)
        elif choice == '2':
            list_runs_for_profile(db)
        elif choice == '3':
            get_results_for_run(db)
        elif choice == '4':
            df = query_funds_by_filters(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '5':
            df = get_latest_for_profile(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '6':
            print("Please run a query first (options 4 or 5).")
        else:
            print("Invalid choice. Please try again.")
    
    db.close()


if __name__ == "__main__":
    main()
