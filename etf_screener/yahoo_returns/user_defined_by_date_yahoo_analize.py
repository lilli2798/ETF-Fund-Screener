"""
Yahoo Finance Historical Data Downloader and Analyzer (User-Defined Date Range)

This script downloads historical price data from Yahoo Finance for a list of tickers,
calculates returns over various time periods (yearly, monthly, weekly), and generates
Excel reports with performance statistics.

Features:
- Rate limiting with batch processing and random delays to avoid Yahoo API limits
- Configurable benchmark indexes for comparison (^IXIC, ^DJI, ^GSPC)
- Error handling for individual ticker failures
- Default file locations for automated runs
- Interactive input with fallback to defaults

Input:
- Excel file (.xlsx) with tickers as index
- Text file (.txt) with one ticker per line
- Or uses default file from config if no input provided

Output:
- Excel file with period and total return sheets
- Includes performance stats vs benchmarks
- Percentile bucket counts

Usage:
    python user_defined_by_date_yahoo_analize.py

    Press Enter at the input-file prompt to use the latest ETF screener
    results (~370 funds). Answer "y" to pick a volatile market period from
    volatile_config.yaml (built by volatile_periods.py) instead of typing dates.

Note: For yearly history cache management, use yearly_cache_manager.py instead.
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

# Sibling modules in this folder import each other by plain name, so make
# sure this folder is importable even when run from another directory.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from benchmark_stats import add_better_worst_stats, add_percentile_bucket_counts, append_index_validation_rows  # noqa: E402
from volatile_periods import pick_period  # noqa: E402
from yahoo_config import DEFAULT_CONFIG, DEFAULT_INDEXES  # noqa: E402
from yearly_cache_manager import to_date, make_return_series, download_adj_close  # noqa: E402


# =========================================================================
# UTILITY FUNCTIONS
# =========================================================================

def period_delta(choice):
    """Convert period choice string to pandas DateOffset.
    
    Args:
        choice: String - 'year', 'month', or 'week'
    
    Returns:
        Tuple of (DateOffset, label_string)
        - DateOffset: pandas DateOffset object for the period
        - label_string: Human-readable period name
    
    Raises:
        ValueError if choice is not year, month, or week
    """
    c = choice.lower().strip()
    if c == "year":
        return pd.DateOffset(years=1), "year"
    if c == "month":
        return pd.DateOffset(months=1), "month"
    if c == "week":
        return pd.DateOffset(weeks=1), "week"
    raise ValueError("current_choice must be year, month, or week")


def safe_tickers(vals):
    """Clean and normalize ticker symbols.
    
    Args:
        vals: Iterable of ticker symbols (strings, indices, etc.)
    
    Returns:
        List of cleaned ticker symbols (uppercase, stripped, non-NAN, non-empty)
    """
    vals = pd.Index(vals).astype(str).tolist()
    vals = [x.strip().upper() for x in vals]
    return [x for x in vals if x and x != "NAN"]


def latest_screener_output(config: Dict = None):
    """Most recent ETF screener result (results_*.xlsx), or None.

    Using the screener's ~370 funds as the default keeps the Yahoo download
    small (a few batches) instead of the full ~5,000-ticker list.
    """
    if config is None:
        config = DEFAULT_CONFIG
    screener_dir = Path(config.get("paths", {})["screener_output_dir"])
    files = list(screener_dir.glob("results_*.xlsx"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def load_input_data(input_file, config: Dict = None):
    """Load input data from Excel or text file with default fallback.
    
    Args:
        input_file: Path to input file (.xlsx or .txt), or None to use default
        config: Configuration dictionary containing default paths
    
    Returns:
        Tuple of (df, tickers, output_file, write_in_place, selected_sheet)
        - df: DataFrame with input data (index contains tickers)
        - tickers: List of cleaned ticker symbols
        - output_file: Path for output Excel file
        - write_in_place: Boolean - True if writing to input file, False if creating new
        - selected_sheet: Sheet name used (for Excel) or None (for text file)
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    # If no input provided, use the latest screener result. Its output goes
    # to default_output_dir, NOT next to the screener results -- alerts.py
    # emails the newest results_*.xlsx there and must not pick this file up.
    used_default = not input_file
    if used_default:
        latest = latest_screener_output(config)
        if latest is None:
            raise FileNotFoundError("No screener results (results_*.xlsx) found; run the ETF screener first or give an input file.")
        input_file = str(latest)
        print(f"Using latest screener results: {input_file}")
    
    input_path = Path(input_file)
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    # Load based on file type
    if input_path.suffix.lower() == ".xlsx":
        xls = pd.ExcelFile(input_file)
        
        # Ask user which sheet to use if multiple
        if len(xls.sheet_names) > 1:
            print(f"Available sheets: {', '.join(xls.sheet_names)}")
            sheet_name = input(f"Select sheet (or press Enter for '{xls.sheet_names[0]}'): ").strip()
            if not sheet_name:
                sheet_name = xls.sheet_names[0]
        else:
            sheet_name = xls.sheet_names[0]
        
        df = pd.read_excel(input_file, sheet_name=sheet_name)
        # Set Ticker as index if it exists as a column
        if 'Ticker' in df.columns:
            df = df.set_index('Ticker')
        df.index = df.index.astype(str)
        tickers = safe_tickers(df.index)
        
        # Create a new output file with timestamp instead of modifying the input file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = input_path.parent
        if used_default:
            out_dir = Path(config.get("paths", {})["default_output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
        output_file = str(out_dir / f"{input_path.stem}_yahoo_analysis_{timestamp}.xlsx")
        write_in_place = False
        selected_sheet = sheet_name
        return df, tickers, output_file, write_in_place, selected_sheet
    
    elif input_path.suffix.lower() == ".txt":
        with open(input_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]
        tickers = [x.strip().upper() for x in lines if x and x != "NAN"]
        
        df = pd.DataFrame(index=tickers)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = str(input_path.with_name(f"{input_path.stem}-output_{timestamp}.xlsx"))
        write_in_place = False
        selected_sheet = None
        return df, tickers, output_file, write_in_place, selected_sheet

    else:
        raise ValueError("Only .xlsx and .txt input files are supported")


# =========================================================================
# OVERVIEW BUILDING
# =========================================================================

def build_overviews(df, adj, beginning_date, ending_date, choice, n, indexes: List[str] = None):
    """Build period and total return overview sheets.
    
    Args:
        df: Input DataFrame with ticker metadata (tickers as index)
        adj: DataFrame with adjusted close prices (tickers as columns, dates as index)
        beginning_date: Start date for analysis
        ending_date: End date for analysis
        choice: Period type - 'year', 'month', or 'week'
        n: Number of periods to analyze
        indexes: List of benchmark index symbols (uses DEFAULT_INDEXES if None)
    
    Returns:
        Tuple of (period_sheet_name, total_sheet_name, period_df, total_df, available, missing)
        - period_sheet_name: Name for period overview sheet
        - total_sheet_name: Name for total return overview sheet
        - period_df: DataFrame with rolling period returns and stats
        - total_df: DataFrame with cumulative returns from each period start to end
        - available: List of tickers with data available
        - missing: List of tickers with no data available
    """
    if indexes is None:
        indexes = DEFAULT_INDEXES
    
    delta, label = period_delta(choice)
    tickers = safe_tickers(df.index)

    all_symbols = list(dict.fromkeys(tickers + indexes))
    available = [t for t in all_symbols if t in adj.columns]
    missing = [t for t in all_symbols if t not in adj.columns]

    print(f"  Available: {len(available)}, Missing: {len(missing)}")

    beginning_dt = to_date(beginning_date)
    ending_dt = to_date(ending_date)

    period_returns = {}
    total_returns = {}

    for i in range(n):
        period_start = ending_dt - (delta * (i + 1))
        period_end = ending_dt - (delta * i)

        if period_start < beginning_dt:
            print(f"  Warning: Period {i+1} start {period_start.date()} is before beginning_date {beginning_dt.date()}")
            break

        for ticker in available:
            if ticker not in adj.columns:
                continue

            ticker_adj = adj[[ticker]]
            period_return = make_return_series(ticker_adj, period_start, period_end)
            total_return = make_return_series(ticker_adj, period_start, ending_dt)

            period_key = f"{label}_{i+1}"
            total_key = f"total_{i+1}"

            if not period_return.empty and ticker in period_return.index:
                period_returns.setdefault(ticker, {})[period_key] = period_return[ticker]

            if not total_return.empty and ticker in total_return.index:
                total_returns.setdefault(ticker, {})[total_key] = total_return[ticker]

    period_df = pd.DataFrame.from_dict(period_returns, orient='index')
    total_df = pd.DataFrame.from_dict(total_returns, orient='index')

    # Add statistics
    if not period_df.empty:
        period_df = add_better_worst_stats(period_df, period_df, indexes)
        period_df = add_percentile_bucket_counts(period_df, period_df, indexes)
        period_df = append_index_validation_rows(period_df, period_df, indexes)

    if not total_df.empty:
        total_df = add_better_worst_stats(total_df, total_df, indexes)
        total_df = add_percentile_bucket_counts(total_df, total_df, indexes)
        total_df = append_index_validation_rows(total_df, total_df, indexes)

    return (
        f"{n}-{label}-overview",
        f"Total-{n}-{label}-overview",
        period_df,
        total_df,
        available,
        missing
    )


def _returns_over(adj, tickers: List[str], legs: Dict[str, tuple]) -> pd.DataFrame:
    """Return per ticker for each {column: (start, end)} leg (first close on/after
    start to last close on/before end). Missing history stays blank."""
    rows = {}
    for ticker in tickers:
        if ticker not in adj.columns:
            continue
        prices = adj[[ticker]].dropna()
        for col, (start, end) in legs.items():
            r = make_return_series(prices, to_date(start), to_date(end))
            if ticker in r.index:
                rows.setdefault(ticker, {})[col] = r[ticker]
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=list(legs))


def _with_benchmark_stats(out: pd.DataFrame, indexes: List[str]) -> pd.DataFrame:
    if out.empty:
        return out
    out = add_better_worst_stats(out, out, indexes)
    out = add_percentile_bucket_counts(out, out, indexes)
    return append_index_validation_rows(out, out, indexes)


def build_volatile_period_overview(df, adj, period: Dict, indexes: List[str] = None):
    """Exact returns over a volatile period picked from volatile_config.yaml.

    Columns: decline_return (period start -> end, e.g. S&P high -> low) and,
    when the period has a recovery date, recovery_return (end -> recovery),
    plus the same benchmark/percentile stats as the other sheets and the
    index rows at the bottom.
    """
    if indexes is None:
        indexes = DEFAULT_INDEXES
    tickers = list(dict.fromkeys(safe_tickers(df.index) + indexes))
    legs = {"decline_return": (period["start"], period["end"])}
    if period.get("recovery"):
        legs["recovery_return"] = (period["end"], period["recovery"])
    return _with_benchmark_stats(_returns_over(adj, tickers, legs), indexes)


# =========================================================================
# EXCEL OUTPUT
# =========================================================================

def add_sheet_as_table(ws, df):
    """Add DataFrame to Excel worksheet as a formatted table.
    
    Args:
        ws: Excel worksheet object
        df: DataFrame to write to the worksheet
    
    Returns:
        None (modifies worksheet in place)
    
    Features:
        - Creates Excel table with TableStyleMedium2 style
        - Freezes header row
        - Auto-adjusts column widths
        - Formats percentage columns appropriately
    """
    for j, col in enumerate(df.columns, start=1):
        ws.cell(row=1, column=j, value=col)

    for i, row in enumerate(df.itertuples(index=False), start=2):
        for j, val in enumerate(row, start=1):
            ws.cell(row=i, column=j, value=None if pd.isna(val) else val)

    max_row = ws.max_row
    max_col = ws.max_column
    ref = f"A1:{get_column_letter(max_col)}{max_row}"

    # Excel table names allow only letters, digits and underscores
    tab = Table(displayName="Table_" + re.sub(r"\W", "_", ws.title), ref=ref)
    style = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=True
    )
    tab.tableStyleInfo = style
    ws.add_table(tab)

    ws.freeze_panes = "A2"

    # Auto-adjust column widths
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column].width = adjusted_width

    # Format percentage columns
    pct_cols = [c for c in df.columns if "%" in str(c)]
    return_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["return", "_0_", "_1_", "_2_", "_3_", "_4_", "_5_", "_6_", "_7_", "_8_", "_9_"])]

    for c in range(1, max_col + 1):
        col_name = ws.cell(row=1, column=c).value

        if col_name in pct_cols:
            for r in range(2, max_row + 1):
                ws.cell(r, c).number_format = "0.0%"
        elif col_name in return_cols:
            for r in range(2, max_row + 1):
                ws.cell(r, c).number_format = "0.00%"


def open_or_create_workbook(output_file, write_in_place):
    """Open existing workbook or create new one.
    
    Args:
        output_file: Path to Excel file
        write_in_place: If True, open existing file; if False, create new
    
    Returns:
        openpyxl Workbook object
    """
    # The output file is new for each run (timestamped), so once this run has
    # created it, later choices must add to it -- not start a blank workbook
    # and overwrite the sheets written earlier.
    if Path(output_file).exists():
        return load_workbook(output_file)

    wb = Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)
    return wb


def save_workbook_with_retry(wb, file_path):
    """Save workbook with retry logic for file access errors.
    
    Args:
        wb: openpyxl Workbook object to save
        file_path: Path to save the workbook
    
    Returns:
        None (saves file and prompts user to retry if file is locked)
    
    Features:
        - Handles PermissionError when file is open in another application
        - Prompts user to close file and retry
    """
    while True:
        try:
            wb.save(file_path)
            return
        except PermissionError:
            print(f"\nThe file '{file_path}' is open or locked.")
            ans = input("Please close the file, then type Y to retry or 99 to stop: ").strip().lower()
            if ans == "99":
                raise SystemExit("Stopped by user because the workbook is open.")
            if ans != "y":
                print("Type Y after closing the file, or 99 to stop.")


def write_result_to_excel(output_file, write_in_place, period_sheet, total_sheet, period_out, total_out):
    """Write period and total return sheets to Excel file.
    
    Args:
        output_file: Path to Excel file
        write_in_place: If True, write to existing file; if False, create new
        period_sheet: Name for period overview sheet
        total_sheet: Name for total return overview sheet
        period_out: DataFrame with period overview data
        total_out: DataFrame with total return data
    
    Returns:
        None (writes to Excel file)
    
    Features:
        - Adds new sheets without deleting existing ones (avoids Excel recovery message)
        - If sheet exists, skips it to prevent duplicates
        - Handles file access errors with retry logic
    """
    write_sheets_to_excel(output_file, write_in_place, {period_sheet: period_out, total_sheet: total_out})


def write_sheets_to_excel(output_file, write_in_place, sheets: Dict[str, pd.DataFrame]):
    """Write each {sheet_name: DataFrame} as a table; existing sheets are skipped.

    Handles file access errors with retry logic.
    """
    while True:
        try:
            wb = open_or_create_workbook(output_file, write_in_place)

            for sheet_name, sheet_df in sheets.items():
                if sheet_name not in wb.sheetnames:
                    ws = wb.create_sheet(sheet_name)
                    add_sheet_as_table(ws, sheet_df.reset_index().rename(columns={"index": "Ticker"}))
                else:
                    print(f"  Sheet '{sheet_name}' already exists, skipping")

            save_workbook_with_retry(wb, output_file)
            wb.close()
            return

        except PermissionError:
            print(f"\nThe file '{output_file}' is open or locked.")
            ans = input("Please close the file, then type Y to retry or 99 to stop: ").strip().lower()
            if ans == "99":
                raise SystemExit("Stopped by user because the workbook is open.")
        except Exception as e:
            print(f"\nError while writing sheets: {e}")
            ans = input("Type Y to retry this write, S to skip, or 99 to stop: ").strip().lower()
            if ans == "99":
                raise SystemExit("Stopped by user.")
            if ans == "s":
                return


# =========================================================================
# MAIN ENTRY POINT
# =========================================================================

def main():
    """Main entry point for interactive Yahoo Finance data analysis.
    
    Features:
        - Interactive mode: Download data and analyze returns over custom periods
        - File access error handling with retry logic
    
    User Flow:
        1. Provide input file, dates
        2. Download Yahoo Finance data
        3. Choose analysis periods (year/month/week) and number of periods
        4. Generate Excel reports with performance statistics
    
    Returns:
        None
    
    Note: For yearly history cache management, use yearly_cache_manager.py instead.
    """
    config = DEFAULT_CONFIG
    
    # Interactive mode
    try:
        query_config = config.get("query", {})
        paths_config = config.get("paths", {})
        
        # Get input file with validation
        while True:
            input_file = input("input file (.xlsx or .txt, or press Enter for default): ").strip()
            if input_file:
                break
            # Use the latest screener results if user pressed Enter
            latest = latest_screener_output(config)
            if latest is not None:
                print(f"Will use latest screener results: {latest.name}")
                break
            print("No screener results (results_*.xlsx) found. Please provide a file path.")
        
        # Optionally pick a ready-made volatile period (volatile_config.yaml)
        period = None
        if input("Use a volatile market period from volatile_config.yaml? (y / Enter for no): ").strip().lower() == "y":
            period = pick_period()
        if period:
            beginning_date, ending_date = str(period["start"]), str(period["end"])
            days = (pd.Timestamp(ending_date) - pd.Timestamp(beginning_date)).days
            print(f"Using {period.get('name', period['id'])}: {beginning_date} -> {ending_date} "
                  f"({days} days, about {days // 7} weeks / {days // 30} months)")
            print("A volatile-... sheet with the exact return over this period is added "
                  "automatically; next you can add week/month breakdowns, or type 99 to finish.")

        # Get beginning_date with validation
        while period is None:
            beginning_date = input("beginning_date (yyyy-mm-dd, or press Enter for default): ").strip()
            if beginning_date:
                try:
                    pd.to_datetime(beginning_date)
                    break
                except ValueError:
                    print("Invalid date format. Please use yyyy-mm-dd format.")
            else:
                beginning_date = query_config.get("beginning_date", "2010-01-01")
                print(f"Using default beginning_date: {beginning_date}")
                break
        
        # Get ending_date with validation
        while period is None:
            ending_date = input("ending_date (yyyy-mm-dd, or press Enter for today): ").strip()
            if ending_date:
                try:
                    pd.to_datetime(ending_date)
                    break
                except ValueError:
                    print("Invalid date format. Please use yyyy-mm-dd format.")
            else:
                ending_date = query_config.get("ending_date")
                if ending_date is None:
                    ending_date = datetime.now().strftime("%Y-%m-%d")
                print(f"Using ending_date: {ending_date}")
                break

        # Load input data with retry for file access errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                df, tickers, output_file, write_in_place, selected_sheet = load_input_data(input_file, config)
                break
            except (FileNotFoundError, PermissionError, IOError) as e:
                if attempt < max_retries - 1:
                    print(f"\nError accessing file: {e}")
                    print("This may be because the file is open in another application.")
                    response = input("Close the file and press Enter to retry, or 'q' to quit: ").strip().lower()
                    if response == 'q':
                        return
                else:
                    print(f"\nFailed to access file after {max_retries} attempts: {e}")
                    return

        print(f"Loaded {len(tickers)} tickers")
        if selected_sheet is not None:
            print(f"Using sheet: {selected_sheet}")

        print("Downloading Yahoo data once...")
        indexes = config.get("indexes") or DEFAULT_INDEXES
        download_symbols = list(dict.fromkeys(tickers + indexes))  # benchmarks are needed for better/worst stats
        download_end = pd.Timestamp(period["recovery"]) if period and period.get("recovery") else pd.Timestamp(ending_date)
        download_end = max(download_end, pd.Timestamp(ending_date))
        # yfinance's `end` is exclusive, so add a day to include the last date
        adj = download_adj_close(download_symbols, beginning_date, (download_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), config)

        if adj.empty:
            print("No Yahoo data downloaded. Stop.")
            return

        if period:
            volatile_sheet = f"volatile-{period['start']}"
            volatile_out = build_volatile_period_overview(df, adj, period, indexes)
            write_sheets_to_excel(output_file, write_in_place, {volatile_sheet: volatile_out})
            print(f"Added sheet: {volatile_sheet} (exact return over {period.get('name', period['id'])})")
            print(f"Output file: {output_file}")

        while True:
            current_choice = input("\ncurrent_choice (year / month / week, or 99 to stop): ").strip().lower()
            if current_choice == "99":
                print("Done.")
                break

            if current_choice not in {"year", "month", "week"}:
                print("Invalid choice. Please type 'year', 'month', 'week', or '99' to stop.")
                continue

            while True:
                n_text = input("num_of_year / num_of_month / num_of_weeks: ").strip()
                if n_text == "99":
                    print("Done.")
                    break

                try:
                    n = int(n_text)
                    if n <= 0:
                        print("Please enter a positive integer.")
                        continue
                    break  # Valid input, proceed
                except ValueError:
                    print("Invalid integer. Please enter a number (e.g., 3, 5, 10).")
            
            if n_text == "99":
                break

            try:
                indexes = config.get("indexes")
                period_sheet, total_sheet, period_out, total_out, available, missing = build_overviews(
                    df, adj, beginning_date, ending_date, current_choice, n, indexes
                )

                write_result_to_excel(
                    output_file,
                    write_in_place,
                    period_sheet,
                    total_sheet,
                    period_out,
                    total_out
                )

                print(f"Added/Replaced sheets: {period_sheet}, {total_sheet}")
                print(f"Output file: {output_file}")
                print(f"Available tickers: {len(available)}, Missing: {len(missing)}")


            except Exception as e:
                print(f"\nError while processing choice '{current_choice}' with n={n}: {e}")
                ans = input("Type Y to continue, or 99 to stop: ").strip().lower()
                if ans == "99":
                    break


    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except SystemExit as e:
        print(str(e))
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
