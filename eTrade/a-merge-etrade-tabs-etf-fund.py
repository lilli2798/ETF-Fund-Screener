"""
E*TRADE ETF/Fund Data Processor

This script processes E*TRADE ETF or Fund data by:
1. Automatically reading all Excel files from source-files directory
2. Merging all tabs from all files into a single DataFrame based on key columns
3. Extracting ticker symbols from the name column (format: "Name (TICKER)")
4. Applying filtering logic:
   - Removes funds with "BOND" in the name (case-insensitive)
   - Filters by inception date (keeps funds >= 1 year old) and/or since inception return (>= 20%)
5. Converting column types (float and percentage columns)
6. Outputting a merged Excel file with formatted columns
7. Creating chunked CSV files (max 500 symbols per file) with Quantity column

Purpose:
The generated CSV files are used to upload ticker symbols to Morningstar to retrieve
detailed analysis data, which is then fed into the ETF screener for further analysis.

Input:
- All Excel files (.xls or .xlsx) in eTrade/source-files directory

Output:
- Merged Excel file (etrade-merged.xlsx)
- Chunked CSV files (filename_ticker_1.csv, filename_ticker_2.csv, etc.) with empty header and Quantity column
"""

from pathlib import Path
from zipfile import BadZipFile
from datetime import datetime, timedelta
import pandas as pd
import glob
import os
import yfinance as yf
import threading
from queue import Queue
import time


FLOAT_COLUMNS = {
    "3-Year Alpha",
    "3-Year Beta vs. Benchmark",
    "3-Year Sharpe Ratio",
    "3-Year R-Squared",
    "Index Corr. 3 Yr S&P 500",
    "Index Corr. 3 Yr Morningstar",
    "Previous Close",
    "Previous Close vs. NAV",
    "Premium Discount",
    "Initial Minimum",
    "IRA Initial Minimum"
}

PERCENT_COLUMNS = {
    "Expense Ratio",
    "1 Yr Return",
    "3 Yr Return",
    "5 Yr Return",
    "10 Yr Return",
    "Since Inception Return",
    "Turnover Ratio",
    "Portfolio Concentration",
    "Avg. Market Cap",
    "Yield",
    "Price/Prospective Earnings",
    "Category Return 10 Yr Return",
    ":Category Return Since Inception",
    "Net Expense Ratio",
    "Max Sales Load",
    "YTD",
    "1 Month",
    "3 Month",
    "6 Month",
    "Distribution Yield",
    "Gross Expense Ratio",
    "Category Return 1 Yr Return",
    "Category Return 3 Yr Return",
    "Category Return 5 Yr Return",
    "Category Return Since Inception"
}


def get_source_files_directory() -> Path:
    """Auto-detect the source-files directory."""
    source_dir = Path(__file__).parent / "source-files"
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    return source_dir


def get_excel_files(source_dir: Path) -> list[Path]:
    """Get all Excel files from the source directory."""
    excel_files = []
    for pattern in ['*.xls', '*.xlsx']:
        excel_files.extend(source_dir.glob(pattern))
    
    # Filter out Excel temp files
    excel_files = [f for f in excel_files if not f.name.startswith('~$')]
    
    if not excel_files:
        raise FileNotFoundError(f"No Excel files found in {source_dir}")
    
    return sorted(excel_files)


def get_config(file_name: str) -> tuple[str, str]:
    if "ETFs" in file_name:
        return "ETF Name", "etrade-etfs.xlsx"
    if "Funds" in file_name:
        return "Fund Name", "etrade-funds.xlsx"
    # Default to ETF Name if not specified
    return "ETF Name", "etrade-etfs.xlsx"


def detect_excel_engine(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return "openpyxl"
    if suffix == ".xls":
        return "xlrd"
    if not suffix:
        # Try to auto-detect by attempting to read with both engines
        try:
            pd.ExcelFile(path, engine="openpyxl")
            return "openpyxl"
        except:
            try:
                pd.ExcelFile(path, engine="xlrd")
                return "xlrd"
            except Exception as e:
                raise ValueError(f"Could not detect Excel format for file without extension: {path.name}. Error: {e}")
    raise ValueError(f"Unsupported Excel extension: {suffix}. Supported formats: .xls, .xlsx")


def clean_missing_markers(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace({"--": pd.NA, "": pd.NA})


def to_float_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "--": pd.NA})
    return pd.Series(pd.to_numeric(cleaned, errors="coerce"), index=cleaned.index)


def percent_to_float_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "--": pd.NA})
    return (pd.Series(pd.to_numeric(cleaned, errors="coerce"), index=cleaned.index) / 100.0).round(4)


def convert_column_types(df: pd.DataFrame) -> pd.DataFrame:
    if "Inception Date" in df.columns:
        df["Inception Date"] = pd.to_datetime(
            df["Inception Date"], errors="coerce"
        ).dt.date

    existing_float_cols = df.columns.intersection(FLOAT_COLUMNS)
    existing_percent_cols = df.columns.intersection(PERCENT_COLUMNS)

    for col in existing_float_cols:
        df[col] = to_float_series(df[col])

    for col in existing_percent_cols:
        df[col] = percent_to_float_series(df[col])

    return df


def prepare_sheet(df: pd.DataFrame, key_col: str, sheet_name: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    df = df.dropna(how="all").copy()
    df = df.loc[:, ~df.columns.duplicated()]
    df = clean_missing_markers(df)

    if key_col not in df.columns:
        raise ValueError(
            f'Sheet "{sheet_name}" does not contain required column "{key_col}".'
        )

    df[key_col] = df[key_col].astype("string").str.strip()
    df = df[df[key_col].notna() & (df[key_col] != "")]

    if df.empty:
        return pd.DataFrame()

    df = df.drop_duplicates(subset=[key_col], keep="first")
    df = convert_column_types(df)

    return df


def filter_funds(df: pd.DataFrame) -> pd.DataFrame:
    one_year_ago = datetime.now().date() - timedelta(days=365)

    has_inception_date = "Inception Date" in df.columns
    has_return = "Since Inception Return" in df.columns

    if has_inception_date and has_return:
        # Keep if: (>= 1 year old) OR (return >= 20%)
        # Remove if: (< 1 year old) AND (return is blank OR < 20%)
        df = df[
            (df["Inception Date"].isna() | (df["Inception Date"] <= one_year_ago))
            | (df["Since Inception Return"].notna() & (df["Since Inception Return"] >= 0.20))
        ].copy()
    elif has_inception_date:
        df = df[df["Inception Date"].isna() | (df["Inception Date"] <= one_year_ago)].copy()
    elif has_return:
        df = df[
            df["Since Inception Return"].isna() | (df["Since Inception Return"] >= 0.20)
        ].copy()

    # Filter out funds with "BOND" in name (case-insensitive)
    for col in ["ETF Name", "Fund Group"]:
        if col in df.columns:
            df = df[~df[col].astype("string").str.contains("BOND", case=False, na=False)].copy()

    return pd.DataFrame(df)


def fetch_price_worker(symbol_queue: Queue, result_dict: dict, lock: threading.Lock):
    """Worker function to fetch prices from queue."""
    while True:
        symbol = symbol_queue.get()
        if symbol is None:  # Sentinel value to stop worker
            break
        
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty and 'Close' in hist.columns:
                price = hist['Close'].iloc[-1]
                if pd.notna(price):
                    with lock:
                        result_dict[symbol] = round(float(price), 2)
            else:
                # Fallback to info
                try:
                    info = ticker.info
                    if 'currentPrice' in info:
                        with lock:
                            result_dict[symbol] = round(float(info['currentPrice']), 2)
                    elif 'regularMarketPrice' in info:
                        with lock:
                            result_dict[symbol] = round(float(info['regularMarketPrice']), 2)
                    else:
                        with lock:
                            result_dict[symbol] = 1.0
                except:
                    with lock:
                        result_dict[symbol] = 1.0
        except Exception as e:
            with lock:
                result_dict[symbol] = 1.0
        
        symbol_queue.task_done()


def get_current_prices_parallel(symbols: list[str], num_workers: int = 5) -> dict[str, float]:
    """Get current prices from Yahoo Finance using parallel workers."""
    prices = {}
    
    # Filter out empty symbols
    valid_symbols = [s for s in symbols if pd.notna(s) and s != ""]
    
    if not valid_symbols:
        return prices
    
    print(f"  Fetching prices for {len(valid_symbols)} symbols using {num_workers} workers...")
    
    # Create queue and lock
    symbol_queue = Queue()
    result_dict = {}
    lock = threading.Lock()
    
    # Add symbols to queue
    for symbol in valid_symbols:
        symbol_queue.put(symbol)
    
    # Start worker threads
    workers = []
    for _ in range(num_workers):
        worker = threading.Thread(target=fetch_price_worker, args=(symbol_queue, result_dict, lock))
        worker.start()
        workers.append(worker)
    
    # Wait for queue to be processed
    symbol_queue.join()
    
    # Stop workers
    for _ in range(num_workers):
        symbol_queue.put(None)
    
    for worker in workers:
        worker.join()
    
    successful = sum(1 for v in result_dict.values() if v != 1.0)
    print(f"  Successfully retrieved {successful}/{len(valid_symbols)} prices.")
    
    return result_dict


def write_ticker_files(df: pd.DataFrame, output_path: Path, base_filename: str) -> None:
    symbols = df.index.tolist()
    symbols = [s for s in symbols if pd.notna(s) and s != ""]

    if not symbols:
        print("  Warning: No symbols to write to CSV files.")
        return

    chunk_size = 250
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        
        print(f"  Processing chunk {chunk_num} ({len(chunk)} symbols)...")
        
        # Fetch prices for this chunk in parallel
        prices = get_current_prices_parallel(chunk, num_workers=5)
        
        ticker_file = output_path.parent / f"{base_filename}_ticker_{chunk_num}.csv"
        
        # Write CSV manually with space as first column header
        with open(ticker_file, 'w') as f:
            # Write header: space, Quantity, Cost Basis
            f.write(" ,Quantity,Cost Basis\n")
            # Write data rows
            for symbol in chunk:
                cost_basis = prices.get(symbol, 1.0)
                f.write(f"{symbol},1,{cost_basis}\n")
        print(f"  Created: {ticker_file.name}")


def write_output_excel(df: pd.DataFrame, output_path: Path) -> None:
    df = df.replace(to_replace=[r"^\s*--\s*$"], value=pd.NA, regex=True)

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Merged", na_rep="")

        workbook = writer.book
        worksheet = writer.sheets["Merged"]

        header_format = workbook.add_format({"bold": True, "border": 1})
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
        float_format = workbook.add_format({"num_format": "0.##"})

        output_df = df.reset_index()
        output_columns = list(output_df.columns)

        for col_num, col_name in enumerate(output_columns):
            worksheet.write(0, col_num, col_name, header_format)

        for idx, col_name in enumerate(output_columns):
            if col_name == "Symbol":
                worksheet.set_column(idx, idx, 12)
            elif col_name in {"ETF Name", "Fund Name"}:
                worksheet.set_column(idx, idx, 32)
            elif col_name == "Inception Date":
                worksheet.set_column(idx, idx, 14, date_format)
            elif col_name in FLOAT_COLUMNS or col_name in PERCENT_COLUMNS:
                worksheet.set_column(idx, idx, 18, float_format)
            else:
                worksheet.set_column(idx, idx, 18)

        worksheet.freeze_panes(1, 1)
        worksheet.set_zoom(150)

    write_ticker_files(df, output_path, output_path.stem)


def merge_all_workbooks(source_dir: Path) -> Path:
    """Merge all Excel files from source directory into a single DataFrame."""
    excel_files = get_excel_files(source_dir)
    print(f"Found {len(excel_files)} Excel files to process:")
    for f in excel_files:
        print(f"  - {f.name}")
    
    all_merged_dfs = []
    
    for file_path in excel_files:
        print(f"\nProcessing: {file_path.name}")
        key_col = get_config(file_path.name)[0]
        engine = detect_excel_engine(file_path)
        
        xls = pd.ExcelFile(file_path, engine=engine)
        if not xls.sheet_names:
            print(f"  Warning: No sheets found in {file_path.name}, skipping.")
            continue
        
        file_merged_df = None
        existing_cols = set()
        
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(
                xls,
                sheet_name=sheet_name,
                dtype={key_col: "string"},
            )
            
            df = prepare_sheet(df, key_col, sheet_name)
            if df.empty:
                continue
            
            if file_merged_df is None:
                file_merged_df = df
                existing_cols = set(file_merged_df.columns)
                continue
            
            cols_to_add = [key_col] + [c for c in df.columns if c not in existing_cols]
            df = df.loc[:, cols_to_add]
            
            file_merged_df = file_merged_df.merge(
                df,
                on=key_col,
                how="outer",
                sort=False,
                suffixes=("", "_dup"),
            )
            
            file_merged_df = file_merged_df.loc[:, ~file_merged_df.columns.str.endswith("_dup")]
            existing_cols = set(file_merged_df.columns)
        
        if file_merged_df is not None and not file_merged_df.empty:
            all_merged_dfs.append(file_merged_df)
            print(f"  Merged {len(file_merged_df)} rows from {file_path.name}")
    
    if not all_merged_dfs:
        raise ValueError("No usable data found in any Excel files.")
    
    # Merge all file DataFrames together
    print(f"\nMerging data from {len(all_merged_dfs)} files...")
    merged_df = all_merged_dfs[0]
    key_col = "ETF Name" if "ETF Name" in merged_df.columns else "Fund Name"
    
    for df in all_merged_dfs[1:]:
        # Ensure consistent key column name
        if "ETF Name" in df.columns and "Fund Name" not in df.columns:
            df = df.rename(columns={"ETF Name": key_col})
        elif "Fund Name" in df.columns and "ETF Name" not in df.columns:
            df = df.rename(columns={"Fund Name": key_col})
        
        existing_cols = set(merged_df.columns)
        cols_to_add = [key_col] + [c for c in df.columns if c not in existing_cols]
        df = df.loc[:, cols_to_add]
        
        merged_df = merged_df.merge(
            df,
            on=key_col,
            how="outer",
            sort=False,
            suffixes=("", "_dup"),
        )
        
        merged_df = merged_df.loc[:, ~merged_df.columns.str.endswith("_dup")]
    
    if merged_df is None or merged_df.empty:
        raise ValueError("No usable data found after merging.")
    
    print(f"Total merged rows: {len(merged_df)}")
    
    merged_df["Symbol"] = (
        merged_df[key_col]
        .astype("string")
        .str.extract(r"\(([^()]*)\)\s*$", expand=False)
        .str.strip()
    )
    
    merged_df = merged_df.replace(to_replace=[r"^\s*--\s*$"], value=pd.NA, regex=True)
    merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]
    
    ordered_cols = ["Symbol", key_col] + [
        c for c in merged_df.columns if c not in {"Symbol", key_col}
    ]
    merged_df = merged_df[ordered_cols]
    merged_df = merged_df.set_index("Symbol", drop=True)
    
    merged_df = filter_funds(merged_df)
    print(f"Rows after filtering: {len(merged_df)}")
    
    # Use centralized output directory
    output_dir = Path(__file__).parent.parent / "output" / "etrade"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "etrade-merged.xlsx"
    write_output_excel(merged_df, output_path)
    
    return output_path


def main() -> None:
    try:
        source_dir = get_source_files_directory()
        print(f"Using source directory: {source_dir}")
        output_file = merge_all_workbooks(source_dir)
        print(f"\nCreated: {output_file}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please ensure the eTrade/source-files directory exists and contains Excel files.")
    except BadZipFile:
        print(
            "Error: One of the files looks like a non-standard or corrupted .xlsx.\n"
                "If it is actually .xls, ensure the extension is .xls; "
                "otherwise open and re-save as .xlsx in Excel.\n"
            )
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()