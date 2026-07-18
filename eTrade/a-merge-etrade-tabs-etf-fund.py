from pathlib import Path
from zipfile import BadZipFile
import pandas as pd


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


def validate_input_file(input_file: str) -> Path:
    input_path = Path(input_file).expanduser().resolve()
    file_name = input_path.name

    if "ETFs" not in file_name and "Funds" not in file_name:
        raise ValueError('Input file name must contain "ETFs" or "Funds".')

    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    return input_path


def get_valid_input_file() -> Path:
    while True:
        try:
            user_input = input("Enter full file path: ").strip()
            return validate_input_file(user_input)
        except (ValueError, FileNotFoundError) as e:
            print(f"Error: {e}")
            print("Please try again.\n")


def get_config(file_name: str) -> tuple[str, str]:
    if "ETFs" in file_name:
        return "ETF Name", "etrade-etfs.xlsx"
    if "Funds" in file_name:
        return "Fund Name", "etrade-funds.xlsx"
    raise ValueError('Input file name must contain "ETFs" or "Funds".')


def detect_excel_engine(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return "openpyxl"
    if suffix == ".xls":
        return "xlrd"
    raise ValueError(f"Unsupported Excel extension: {suffix}")


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
    return pd.to_numeric(cleaned, errors="coerce")


def percent_to_float_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "--": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce") / 100.0


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


def merge_etrade_workbook(input_path: Path) -> Path:
    key_col, output_name = get_config(input_path.name)
    engine = detect_excel_engine(input_path)

    xls = pd.ExcelFile(input_path, engine=engine)
    if not xls.sheet_names:
        raise ValueError("No sheets found in the workbook.")

    merged_df = None
    existing_cols = set()

    for sheet_name in xls.sheet_names:
        df = pd.read_excel(
            xls,
            sheet_name=sheet_name,
            dtype={key_col: "string"},
            engine=engine,
        )

        df = prepare_sheet(df, key_col, sheet_name)
        if df.empty:
            continue

        if merged_df is None:
            merged_df = df
            existing_cols = set(merged_df.columns)
            continue

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
        existing_cols = set(merged_df.columns)

    if merged_df is None or merged_df.empty:
        raise ValueError("No usable sheets found after cleaning.")

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

    output_path = input_path.parent / output_name
    write_output_excel(merged_df, output_path)

    return output_path


def main():
    while True:
        try:
            input_path = get_valid_input_file()
            output_file = merge_etrade_workbook(input_path)
            print(f"Created: {output_file}")
            break
        except BadZipFile:
            print(
                "Error: The file looks like a non-standard or corrupted .xlsx.\n"
                "If it is actually .xls, ensure the extension is .xls; "
                "otherwise open and re-save as .xlsx in Excel.\n"
            )
        except ValueError as e:
            print(f"Error: {e}")
            print("Please fix the file or choose another file, then try again.\n")
        except Exception as e:
            print(f"Unexpected error: {e}")
            print("Please try again with a valid workbook.\n")


if __name__ == "__main__":
    main()