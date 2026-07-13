"""
Data loading: reading, combining, and cleaning the raw Morningstar Excel
exports (structural fields + performance fields) into pandas DataFrames.

NOTE ON THE _x/_y BUG WE DEBUGGED EARLIER:
read_and_concat_excels() below intentionally uses pd.concat() + drop_duplicates()
to combine multiple files -- NEVER pd.merge() -- because pd.merge() is what
introduces _x/_y suffixes when two files share column names. Row-stacking
via concat cannot produce that bug.

It also actively checks each file's real header row against the requested
`usecols` list and prints a warning for any name that doesn't match exactly
(trailing spaces, trademark symbols, naming variants, etc.) -- since pandas'
usecols silently drops non-matching columns instead of raising an error,
which was our leading theory for the empty long-horizon columns.
"""

import os
import glob
from typing import List, Optional, Tuple
import pandas as pd

from config import STRUCT_NEEDED_COLS, PERF_NEEDED_COLS


def resolve_files_in_path(
    path: str,
    file_pattern: str,
    exclude_dir: Optional[str] = None,
) -> List[str]:
    """
    Resolve `path` into a list of file paths to read.

    - If `path` is an existing file, returns [path].
    - If `path` is a directory, globs for files matching the basename of
      `file_pattern` inside that directory (e.g. all files named
      'performance-etfs*.xlsx'), skipping Excel lock files ('~$...') and
      anything located inside `exclude_dir` (e.g. your output/results
      folder), so previously generated output never gets re-ingested as
      input.

    Raises FileNotFoundError if no matching files are found.
    """
    exclude_dir_abs: Optional[str] = os.path.abspath(exclude_dir) if exclude_dir else None

    if os.path.isfile(path):
        candidates: List[str] = [path]
    elif os.path.isdir(path):
        pattern_name: str = os.path.basename(file_pattern)
        # If file_pattern has no wildcard, glob for anything starting with
        # its stem and sharing its extension (handles dated/versioned copies
        # like 'performance-etfs_2026-07-08.xlsx').
        if "*" not in pattern_name and "?" not in pattern_name:
            stem, ext = os.path.splitext(pattern_name)
            pattern_name = f"{stem}*{ext}"
        search_glob: str = os.path.join(path, pattern_name)
        candidates = glob.glob(search_glob)
    else:
        raise FileNotFoundError(f"Path does not exist: {path}")

    resolved: List[str] = []
    for f in candidates:
        basename: str = os.path.basename(f)
        if basename.startswith("~$"):
            continue  # skip Excel temp/lock files
        f_abs: str = os.path.abspath(f)
        if exclude_dir_abs and f_abs.startswith(exclude_dir_abs + os.sep):
            continue  # skip files inside the output/results folder
        resolved.append(f_abs)

    if not resolved:
        raise FileNotFoundError(
            f"No files found for path='{path}', file_pattern='{file_pattern}' "
            f"(exclude_dir='{exclude_dir}')."
        )

    resolved.sort()
    print(f"  Resolved {len(resolved)} file(s): {[os.path.basename(f) for f in resolved]}")
    return resolved


def _check_usecols_against_header(file_path: str, usecols: Optional[List[str]]) -> None:
    """
    Compare the requested `usecols` list against the actual header row of
    `file_path`, and print a warning for any requested column that doesn't
    match exactly. This is the diagnostic we discussed: pandas' usecols
    silently drops non-matching names (extra whitespace, ®/™ symbols,
    naming variants) instead of raising an error, which can look identical
    to "the column loaded but is all empty."
    """
    if not usecols:
        return
    try:
        actual_cols: List[str] = pd.read_excel(file_path, nrows=0).columns.tolist()
    except Exception as e:  # noqa: BLE001
        print(f"  Warning: could not pre-read header of '{file_path}' for usecols check: {e}")
        return

    actual_set = set(actual_cols)
    missing: List[str] = [c for c in usecols if c not in actual_set]
    if missing:
        print(
            f"  Warning: {os.path.basename(file_path)} is missing "
            f"{len(missing)} expected column(s) (usecols will silently "
            f"drop these -- check for whitespace/symbol mismatches):"
        )
        for c in missing:
            # Try to find a near-match to help spot whitespace/symbol issues.
            close = [a for a in actual_cols if a.strip().lower() == c.strip().lower()]
            hint = f" (possible match in file: '{close[0]}')" if close else ""
            print(f"    - '{c}'{hint}")


def read_and_concat_excels(
    files: List[str],
    usecols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Read one or more Excel files and combine them into a single DataFrame,
    deduplicated on Ticker.

    Uses pd.concat() (row-stacking) + drop_duplicates(subset='Ticker'),
    NOT pd.merge() -- this avoids the _x/_y suffix bug entirely, since
    merge is only appropriate for combining different *columns* about the
    same tickers (structural + performance), not for combining multiple
    files that share the *same* columns (e.g. two dated exports of the
    same performance file).

    When there are duplicate Tickers across files (e.g. an older export
    and a newer export both containing AVUV), the LAST file in `files`
    wins for that ticker, on the assumption files are passed/sorted
    oldest-to-newest. Adjust `keep="last"` below if your convention differs.

    Before reading each file, checks the real header row against `usecols`
    and prints a warning for any silently-dropped column name.
    """
    if not files:
        raise ValueError("read_and_concat_excels() received an empty file list.")

    frames: List[pd.DataFrame] = []
    for f in files:
        _check_usecols_against_header(f, usecols)
        try:
            df_part: pd.DataFrame = pd.read_excel(f, usecols=usecols)
        except ValueError as e:
            # pandas raises ValueError if usecols references a column that
            # doesn't exist AND engine strictness catches it -- fall back to
            # reading all columns so we don't hard-fail the whole pipeline,
            # then trim to whatever overlap exists.
            print(f"  Warning: strict usecols read failed for '{f}' ({e}); "
                  f"reading all columns instead and filtering after the fact.")
            df_part = pd.read_excel(f)
            if usecols:
                keep = [c for c in usecols if c in df_part.columns]
                df_part = df_part[keep]
        df_part["__source_file"] = os.path.basename(f)
        frames.append(df_part)

    combined: pd.DataFrame = pd.concat(frames, ignore_index=True, sort=False)

    if "Ticker" in combined.columns:
        before: int = len(combined)
        combined = combined.drop_duplicates(subset="Ticker", keep="last")
        removed: int = before - len(combined)
        if removed > 0:
            print(f"  Deduplicated on Ticker: removed {removed} duplicate row(s) "
                  f"(kept the version from the last-read file per ticker).")

    combined = combined.drop(columns=["__source_file"], errors="ignore")
    return combined


def clean_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize dtypes across loaded columns:
      - Strip whitespace from string/object columns.
      - Coerce columns that look numeric (but got read as text/object due
        to stray characters like '%', ',' or footnote markers) into floats
        where possible, leaving genuinely non-numeric text columns alone.
      - Leave known categorical/text columns (Ticker, Name, Category,
        Exchange, ratings-as-labels, etc.) untouched.
    """
    cleaned: pd.DataFrame = df.copy()

    text_like_cols = {
        "Ticker", "Name", "Morningstar Category", "Exchange", "Exchange Country",
        "Primary Benchmark", "Portfolio Risk Score", "Portfolio Growth Grade",
        "Portfolio Financial Health Grade", "Economic Moat", "Capital Allocation",
        "Fund Managers", "Longest Tenured Manager", "Management Style",
        "Medalist Rating (Overall)", "Trading Status", "Strategic Beta Group",
        "Share Class Type", "Index Fund", "No Load Fund", "Leveraged Fund",
        "Interval Fund", "Fund of Funds", "Investment Status", "Tender Offer",
        "__source_file",
    }

    for col in cleaned.columns:
        is_text_dtype: bool = (
            cleaned[col].dtype == object
            or pd.api.types.is_string_dtype(cleaned[col])
        )
        if is_text_dtype:
            cleaned[col] = cleaned[col].apply(
                lambda v: v.strip() if isinstance(v, str) else v
            )
            if col in text_like_cols or col == "Inception Date":
                continue
            # Attempt numeric coercion for everything else that's text-typed
            # (e.g. a return column that picked up a stray '%' or blank cell).
            stripped = cleaned[col].astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
            coerced: pd.Series = pd.to_numeric(stripped, errors="coerce")
            # Only replace if coercion actually recovered a meaningful amount
            # of numeric data (avoids turning a genuinely textual column into
            # all-NaN silently). Explicit pd.Series annotation above resolves
            # the 'Unresolved attribute .notna() for ndarray' type-checker
            # warning, since pd.to_numeric()'s return type is ambiguous
            # (Series/ndarray/Index) without it.
            non_null_before: int = cleaned[col].notna().sum()
            non_null_after: int = coerced.notna().sum()
            if non_null_before > 0 and non_null_after >= non_null_before * 0.5:
                cleaned[col] = coerced

    if "Inception Date" in cleaned.columns:
        cleaned["Inception Date"] = pd.to_datetime(cleaned["Inception Date"], errors="coerce")

    return cleaned


def parse_portfolio_risk_score(val) -> Tuple[Optional[str], Optional[float]]:
    """
    Parse a 'Portfolio Risk Score' string like 'Very Aggressive (87)' into
    (label, numeric_score) e.g. ('Very Aggressive', 87.0).

    Returns (None, None) if `val` is missing or doesn't match the expected
    'Label (number)' pattern.
    """
    if pd.isna(val):
        return (None, None)

    text: str = str(val).strip()
    if "(" not in text or ")" not in text:
        return (text if text else None, None)

    label_part, _, rest = text.partition("(")
    number_part: str = rest.rstrip(")").strip()
    label: str = label_part.strip()

    try:
        score: Optional[float] = float(number_part)
    except ValueError:
        score = None

    return (label if label else None, score)


def load_structural_data(
    path: str,
    file_pattern: str = None,
    exclude_dir: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load python-etfs.xlsx (structural/fundamental fields only).

    `path` can be:
      - a single file path, or
      - a directory containing one or more files matching `file_pattern`
        (all matches are read and combined, deduplicated on Ticker).

    `exclude_dir`, if provided, skips any files located inside that
    directory (e.g. your output/results folder) so previously generated
    output files never get re-ingested as input.

    Raises ValueError if required identifier columns are missing after load.
    """
    file_pattern = file_pattern or path
    files: List[str] = resolve_files_in_path(path, file_pattern, exclude_dir=exclude_dir)
    df: pd.DataFrame = read_and_concat_excels(files, usecols=STRUCT_NEEDED_COLS)

    required: List[str] = ["Ticker", "Morningstar Category"]
    missing: List[str] = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Structural data is missing required columns: {missing}")

    df = clean_dtypes(df)

    if "Portfolio Risk Score" in df.columns:
        parsed = df["Portfolio Risk Score"].apply(parse_portfolio_risk_score)
        df["Risk_Label"] = parsed.apply(lambda t: t[0])
        df["Risk_Score_Numeric"] = parsed.apply(lambda t: t[1])

    return df


def load_performance_data(
    path: str,
    file_pattern: str = None,
    exclude_dir: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load performance-etfs.xlsx (returns, ranks, risk, capture, drawdowns).

    `path` can be a single file or a directory containing one or more files
    matching `file_pattern` (all matches are read and combined, deduplicated
    on Ticker).

    `exclude_dir`, if provided, skips any files located inside that
    directory (e.g. your output/results folder).

    Raises ValueError if the 'Ticker' join key is missing after load.
    """
    file_pattern = file_pattern or path
    files: List[str] = resolve_files_in_path(path, file_pattern, exclude_dir=exclude_dir)
    df: pd.DataFrame = read_and_concat_excels(files, usecols=PERF_NEEDED_COLS)

    if "Ticker" not in df.columns:
        raise ValueError("Performance data is missing the required 'Ticker' column.")

    return clean_dtypes(df)
