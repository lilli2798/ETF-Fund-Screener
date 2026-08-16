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
from etf_screener.database import ETFScreenerDatabase


def print_menu():
    """Print the main menu options."""
    print("\n" + "="*60)
    print("ETF Screener Results Query Tool")
    print("="*60)
    print("1. List recent runs")
    print("2. List recent runs for a specific profile")
    print("3. Get full results for a specific run")
    print("4. Query funds by filters (ticker, score, category)")
    print("5. Query funds by concept scores")
    print("6. Compare metrics between runs (historical analysis)")
    print("7. Get latest results for a profile")
    print("8. Export query results to Excel")
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


def main():
    """Main interactive loop."""
    db = ETFScreenerDatabase()
    
    while True:
        print_menu()
        choice = input("Enter your choice (0-8): ").strip()
        
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
            df = query_funds_by_concept_scores(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '6':
            df = compare_metrics_between_runs(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '7':
            df = get_latest_for_profile(db)
            if df is not None and not df.empty:
                export = input("\nExport results to Excel? (y/n): ").strip().lower()
                if export == 'y':
                    export_to_excel(df)
        elif choice == '8':
            print("Please run a query first (options 4, 5, 6, or 7).")
        else:
            print("Invalid choice. Please try again.")
    
    db.close()


if __name__ == "__main__":
    main()
