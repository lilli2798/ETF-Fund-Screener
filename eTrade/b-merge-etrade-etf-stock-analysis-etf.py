from pathlib import Path
import pandas as pd


ETRADE_ETF_FILE = Path(
    r"/Users/lihongfeng/Library/CloudStorage/OneDrive-Personal/AA-FundResearchProject/A-Do-Not-Delete-DB/merged/etrade/etrade-etfs.xlsx"
)

STOCK_ANALYSIS_DIR = Path(
    r"/Users/lihongfeng/Library/CloudStorage/OneDrive-Personal/AA-FundResearchProject/A-Do-Not-Delete-DB/merged/StockAnalysis"
)

OUTPUT_FILE = STOCK_ANALYSIS_DIR / "etrade-etf-merged.xlsx"

COLUMNS_TO_REMOVE = {
    "ETF Name",
    "Expense Ratio",
    "1 Yr Return",
    "3 Yr Return",
    "5 Yr Return",
    "10 Yr Return",
}


def validate_paths() -> None:
    if not ETRADE_ETF_FILE.exists():
        raise FileNotFoundError(f"E*TRADE ETF file not found: {ETRADE_ETF_FILE}")

    if not STOCK_ANALYSIS_DIR.exists():
        raise FileNotFoundError(f"StockAnalysis folder not found: {STOCK_ANALYSIS_DIR}")

    if not STOCK_ANALYSIS_DIR.is_dir():
        raise NotADirectoryError(f"StockAnalysis path is not a folder: {STOCK_ANALYSIS_DIR}")


def find_stockanalysis_file(folder: Path, output_file: Path) -> Path:
    xlsx_files = [
        f for f in folder.glob("*.xlsx")
        if f.is_file() and f.resolve() != output_file.resolve()
    ]

    if not xlsx_files:
        raise FileNotFoundError(f"No .xlsx file found in: {folder}")

    newest_file = max(xlsx_files, key=lambda f: f.stat().st_mtime)
    return newest_file


def read_excel_with_symbol_index(file_path: Path) -> pd.DataFrame:
    try:
        df = pd.read_excel(file_path, engine="openpyxl")
    except Exception as e:
        raise RuntimeError(f"Failed to read Excel file: {file_path}\nReason: {e}") from e

    if df.empty:
        raise ValueError(f"Excel file is empty: {file_path}")

    if "Ticker" in df.columns:
        df["Ticker"] = df["Ticker"].astype("string").str.strip()
        df = df[df["Ticker"].notna() & (df["Ticker"] != "")]
        df = df.set_index("Ticker", drop=True)
    else:
        if df.index.name != "Ticker":
            raise ValueError(
                f'File does not contain a "Ticker" column and index name is not "Ticker": {file_path}'
            )
        df.index = df.index.astype("string").str.strip()
        df = df[df.index.notna() & (df.index != "")]

    if df.index.duplicated().any():
        dupes = df.index[df.index.duplicated()].unique().tolist()
        preview = dupes[:10]
        raise ValueError(
            f"Duplicate Ticker values found in {file_path}: {preview}"
            + (" ..." if len(dupes) > 10 else "")
        )

    return df


def merge_files() -> Path:
    validate_paths()

    stockanalysis_file = find_stockanalysis_file(STOCK_ANALYSIS_DIR, OUTPUT_FILE)

    etrade_df = read_excel_with_symbol_index(ETRADE_ETF_FILE)
    stockanalysis_df = read_excel_with_symbol_index(stockanalysis_file)

    common_symbols = etrade_df.index.intersection(stockanalysis_df.index)
    if common_symbols.empty:
        raise ValueError(
            "No matching Symbol values found between the E*TRADE ETF file "
            f"and StockAnalysis file: {stockanalysis_file.name}"
        )

    merged_df = stockanalysis_df.join(
        etrade_df,
        how="left",
        lsuffix="",
        rsuffix="_etrade",
        validate="one_to_one",
    )

    extra_suffix_cols = {c for c in merged_df.columns if c.endswith("_etrade")}
    merged_df = merged_df.drop(
        columns=list(COLUMNS_TO_REMOVE | extra_suffix_cols),
        errors="ignore",
    )

    merged_df.index.name = "Symbol"

    try:
        merged_df.to_excel(OUTPUT_FILE, engine="xlsxwriter")
    except Exception as e:
        raise RuntimeError(f"Failed to write output file: {OUTPUT_FILE}\nReason: {e}") from e

    return OUTPUT_FILE


def main():
    try:
        output_file = merge_files()
        print(f"Created: {output_file}")
    except FileNotFoundError as e:
        print(f"File error: {e}")
    except NotADirectoryError as e:
        print(f"Directory error: {e}")
    except ValueError as e:
        print(f"Validation error: {e}")
    except RuntimeError as e:
        print(f"Runtime error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()