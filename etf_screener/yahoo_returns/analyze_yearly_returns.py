from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font

from benchmark_stats import PERCENTILE_BUCKETS, add_better_worst_stats, add_percentile_bucket_counts
from yahoo_config import DEFAULT_CONFIG, DEFAULT_INDEXES

INDEXES = DEFAULT_INDEXES


def analyze_yearly_returns(csv_file_path, output_file_path=None, db_path=None):
    """
    Analyze yearly ETF returns against index benchmarks and write the full report.
    
    Args:
        csv_file_path: Path to etf_yearly_history.csv
        output_file_path: Path to save the output Excel file (optional, defaults to
            paths.yearly_analysis_path in yahoo_config.py; overwritten each run)
        db_path: Unused; kept for backward compatibility
    """
    if output_file_path is None:
        output_file_path = DEFAULT_CONFIG["paths"]["yearly_analysis_path"]
    Path(output_file_path).parent.mkdir(parents=True, exist_ok=True)

    result_df, etf_df, max_per_year, min_per_year, year_columns = compute_yearly_analysis(csv_file_path)
    save_with_formatting(result_df, etf_df, max_per_year, min_per_year, output_file_path, year_columns)
    return result_df


def compute_yearly_analysis(csv_file_path):
    """Compute the analysis for every ticker in the CSV (no file is written).

    Returns (result_df, etf_df, max_per_year, min_per_year, year_columns).
    Ranks and percentile buckets are always computed against ALL tickers in
    the CSV, so a single ticker's row matches what a full rebuild would give.
    """
    # Read the CSV file
    df = pd.read_csv(csv_file_path, index_col=0)
    
    # Filter to only years (numeric columns)
    year_columns = [col for col in df.columns if col.isdigit()]
    df_years = df[year_columns]
    
    # Get index data
    index_df = df_years.loc[INDEXES]
    
    # Calculate max and min for each year across indexes
    max_per_year = index_df.max(axis=0)
    min_per_year = index_df.min(axis=0)
    
    # Remove indexes from the main dataframe for analysis
    etf_df = df_years.drop(INDEXES, errors='ignore')
    
    # Benchmark comparison + percentile buckets (shared with the
    # user-defined date script so both report identical numbers)
    stats = add_better_worst_stats(pd.DataFrame(index=etf_df.index), df_years, INDEXES)
    stats = add_percentile_bucket_counts(stats, df_years, INDEXES)

    # Yearly rankings (1 = best return that year)
    ranks = pd.DataFrame(
        {f'Yearly_{year}_rank': etf_df[year].rank(ascending=False, method='dense') for year in year_columns},
        index=etf_df.index,
    )

    # Final column order
    metric_columns = [
        'total_columns', 'no_null_columns', 'better', 'worst',
        'better_%', 'worst_%', 'better_worst_diff'
    ]
    result_df = pd.concat([stats[metric_columns], ranks, stats[PERCENTILE_BUCKETS]], axis=1)

    return result_df, etf_df, max_per_year, min_per_year, year_columns


YELLOW_FILL = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')  # beat every index that year
GRAY_FILL = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')    # trailed every index that year
LARGE_FONT = Font(size=15)


def add_tickers_to_analysis(csv_file_path, tickers, output_file_path=None):
    """Add (or update) rows for `tickers` in an existing analysis report.

    Other rows are left untouched, so their ranks / percentile buckets are
    not re-computed. If the report doesn't exist yet, or its year columns
    differ from the CSV (e.g. a new year was added), the full report is
    rebuilt instead. Returns the number of tickers written.
    """
    if output_file_path is None:
        output_file_path = DEFAULT_CONFIG["paths"]["yearly_analysis_path"]

    result_df, etf_df, max_per_year, min_per_year, year_columns = compute_yearly_analysis(csv_file_path)
    tickers = [t for t in tickers if t in result_df.index]
    if not tickers:
        return 0

    if not Path(output_file_path).exists():
        print("  No existing report -- building the full report.")
        save_with_formatting(result_df, etf_df, max_per_year, min_per_year, output_file_path, year_columns)
        return len(tickers)

    wb = load_workbook(output_file_path)
    ws_raw, ws_analysis = wb['Sheet1'], wb['analysis_result']
    raw_header = [c.value for c in ws_raw[1]]
    if [h for h in raw_header[1:] if h is not None] != list(year_columns):
        wb.close()
        print("  Report years differ from the CSV -- rebuilding the full report.")
        save_with_formatting(result_df, etf_df, max_per_year, min_per_year, output_file_path, year_columns)
        return len(tickers)

    def write_row(ws, ticker, values_by_header):
        header = [c.value for c in ws[1]]
        rows = {ws.cell(row=r, column=1).value: r for r in range(2, ws.max_row + 1)}
        r = rows.get(ticker, ws.max_row + 1)  # update a refilled row in place, else append
        ws.cell(row=r, column=1, value=ticker).font = LARGE_FONT
        for c, name in enumerate(header[1:], start=2):
            val = values_by_header.get(name)
            cell = ws.cell(row=r, column=c, value=None if pd.isna(val) else val)
            cell.font = LARGE_FONT
            cell.fill = PatternFill()
        return r

    for t in tickers:
        r = write_row(ws_raw, t, etf_df.loc[t].to_dict())
        for c, year in enumerate(raw_header[1:], start=2):
            val = etf_df.at[t, year]
            if pd.notna(val):
                if val > max_per_year[year]:
                    ws_raw.cell(row=r, column=c).fill = YELLOW_FILL
                elif val < min_per_year[year]:
                    ws_raw.cell(row=r, column=c).fill = GRAY_FILL
        write_row(ws_analysis, t, result_df.loc[t].to_dict())

    wb.save(output_file_path)
    print(f"Added/updated {len(tickers)} ticker(s) in {output_file_path}: {', '.join(tickers)}")
    return len(tickers)


def save_with_formatting(result_df, etf_df, max_per_year, min_per_year, output_file_path, year_columns):
    """
    Save dataframe to Excel with conditional formatting.
    
    Args:
        result_df: The analysis results dataframe
        etf_df: Original ETF returns dataframe
        max_per_year: Series with max index returns per year
        min_per_year: Series with min index returns per year
        output_file_path: Path to save the Excel file
        year_columns: List of year column names
    """
    # Create Excel file with both sheets (CSV cannot have multiple sheets)
    with pd.ExcelWriter(output_file_path, engine='openpyxl') as writer:
        etf_df.to_excel(writer, sheet_name='Sheet1', index=True)
        result_df.to_excel(writer, sheet_name='analysis_result', index=True)
    
    # Apply formatting to Sheet1 (raw data)
    wb = load_workbook(output_file_path)
    ws = wb['Sheet1']
    
    # Define fills and fonts
    yellow_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
    gray_fill = PatternFill(start_color='D3D3D3', end_color='D3D3D3', fill_type='solid')
    large_font = Font(size=15)  # 150% larger than default 10pt
    
    # Apply larger font to all cells
    for row in ws.iter_rows():
        for cell in row:
            cell.font = large_font
    
    # Get year column indices (columns B onwards, since A is ticker)
    # Map year to column letter
    header_row = 1
    year_col_map = {}
    for col_idx, cell in enumerate(ws[header_row], 1):
        if cell.value and cell.value in year_columns:
            year_col_map[cell.value] = col_idx
    
    # Iterate through each row (starting from row 2, after header)
    for row_idx in range(2, ws.max_row + 1):
        ticker_cell = ws.cell(row=row_idx, column=1)
        ticker = ticker_cell.value
        
        if ticker and ticker in etf_df.index:
            for year in year_columns:
                if year in year_col_map:
                    col_idx = year_col_map[year]
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell_value = cell.value
                    
                    if pd.notna(cell_value):
                        # Better than max (yellow)
                        if cell_value > max_per_year[year]:
                            cell.fill = yellow_fill
                        # Worse than min (gray)
                        elif cell_value < min_per_year[year]:
                            cell.fill = gray_fill
    
    # Apply larger font to analysis_result sheet as well
    ws_analysis = wb['analysis_result']
    for row in ws_analysis.iter_rows():
        for cell in row:
            cell.font = large_font
    
    wb.save(output_file_path)
    print(f"Analysis saved to {output_file_path} with formatting")


if __name__ == "__main__":
    import sys

    from yahoo_config import DEFAULT_CONFIG

    # Usage: python analyze_yearly_returns.py [csv_path] [output_xlsx_path]
    # Defaults to sources/etf_yearly_history.csv next to this script and the
    # single report at paths.yearly_analysis_path (overwritten each run).
    csv_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "sources" / "etf_yearly_history.csv")
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Get database path from config
    cache_config = DEFAULT_CONFIG.get("caching", {})
    db_path = cache_config.get("yearly_returns_db_path", None)

    result = analyze_yearly_returns(csv_path, output_file_path=output_path, db_path=db_path)
    print("Analysis complete!")
    print(result.head())
