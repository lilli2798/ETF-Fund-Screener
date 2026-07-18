"""
Compare N ETF result files (exported .xlsx outputs from main.py) side
by side: weights/thresholds used for each run, per-ticker
selection-flag differences, and a full score/rank matrix.

Updated after the scoring.py refactor:
  - The old "Norm_*" columns no longer exist -- they were replaced by
    8 named concept-score columns (Performance Score, Risk Adjusted
    Score, Volatility Score, Tracking Score, Liquidity Size Score,
    Quality Valuation Score, Costs Score, Tax Income Score).
  - Exported column headers are SPACE-separated, not underscore --
    format_column_names_for_export() in export.py converts internal
    names like "Profile_A_Score" to "Profile A Score" before writing
    the .xlsx file. The old version of this script filtered on
    underscore-style names, which never matched the actual exported
    headers (a pre-existing bug, independent of the scoring refactor).
  - Profile A now also produces an overall (cross-category) rank and
    selected-flag, in addition to the per-category ones -- both are
    now captured here too.
"""

import pandas as pd
import yaml
import os
import argparse
from itertools import combinations
from typing import Dict, Any, List

# Exact exported (space-separated) column-name prefixes to pull in for
# comparison. Matches the output of export.format_column_names_for_export().
SCORE_AND_RANK_PREFIXES = (
    # Per-concept scores (0-100, category-relative)
    "Performance Score",
    "Risk Adjusted Score",
    "Volatility Score",
    "Tracking Score",
    "Liquidity Size Score",
    "Quality Valuation Score",
    "Costs Score",
    "Tax Income Score",
    # Profile A composite score, ranks, and selection flags
    "Profile A Score",
    "Profile A Rank In Category",
    "Profile A Selected Flag",
    "Profile A Rank Overall",
    "Profile A Selected Overall Flag",
)


def load_recorder(output_dir: str) -> dict:
    recorder_path = os.path.join(output_dir, "run_recorder.yaml")
    with open(recorder_path, "r") as f:
        return yaml.safe_load(f) or {}


def build_file_ticker_map(output_dir: str, filename: str, recorder: dict, ticker_col: str = "Ticker") -> Dict[str, Any]:
    df = pd.read_excel(os.path.join(output_dir, filename))
    relevant_cols = [c for c in df.columns if c.startswith(SCORE_AND_RANK_PREFIXES)]
    tickers = {}
    for _, row in df.iterrows():
        tickers[row[ticker_col]] = {col: row[col] for col in relevant_cols}
    entry = recorder.get(filename, {})
    return {
        "thresholds": entry.get("thresholds", entry),  # recorder stores the full thresholds dict
        "weights": entry.get("weights", {}),
        "concept_weights": entry.get("concept_weights", {}),
        "tickers": tickers,
    }


def build_comparison_map(output_dir: str, filenames: List[str]) -> Dict[str, Any]:
    recorder = load_recorder(output_dir)
    return {fn: build_file_ticker_map(output_dir, fn, recorder) for fn in filenames}


def find_flag_differences_pair(comparison_map: Dict[str, Any], file_a: str, file_b: str) -> pd.DataFrame:
    tickers_a = comparison_map[file_a]["tickers"]
    tickers_b = comparison_map[file_b]["tickers"]
    all_tickers = sorted(set(tickers_a) | set(tickers_b))
    rows = []
    for ticker in all_tickers:
        flag_a = tickers_a.get(ticker, {}).get("Profile A Selected Flag")
        flag_b = tickers_b.get(ticker, {}).get("Profile A Selected Flag")
        overall_flag_a = tickers_a.get(ticker, {}).get("Profile A Selected Overall Flag")
        overall_flag_b = tickers_b.get(ticker, {}).get("Profile A Selected Overall Flag")
        if flag_a != flag_b or overall_flag_a != overall_flag_b:
            rows.append({
                "Ticker": ticker,
                "file_a": file_a,
                "file_b": file_b,
                "Flag_In_Category_file_a": flag_a,
                "Flag_In_Category_file_b": flag_b,
                "Flag_Overall_file_a": overall_flag_a,
                "Flag_Overall_file_b": overall_flag_b,
                "Score_file_a": tickers_a.get(ticker, {}).get("Profile A Score"),
                "Score_file_b": tickers_b.get(ticker, {}).get("Profile A Score"),
                "Rank_In_Category_file_a": tickers_a.get(ticker, {}).get("Profile A Rank In Category"),
                "Rank_In_Category_file_b": tickers_b.get(ticker, {}).get("Profile A Rank In Category"),
                "Rank_Overall_file_a": tickers_a.get(ticker, {}).get("Profile A Rank Overall"),
                "Rank_Overall_file_b": tickers_b.get(ticker, {}).get("Profile A Rank Overall"),
            })
    return pd.DataFrame(rows)


def find_all_flag_differences(comparison_map: Dict[str, Any], filenames: List[str]) -> pd.DataFrame:
    all_diffs = []
    for file_a, file_b in combinations(filenames, 2):
        diff_df = find_flag_differences_pair(comparison_map, file_a, file_b)
        if not diff_df.empty:
            all_diffs.append(diff_df)
    if not all_diffs:
        return pd.DataFrame()
    return pd.concat(all_diffs, ignore_index=True)


def build_ticker_matrix(comparison_map: Dict[str, Any], filenames: List[str]) -> pd.DataFrame:
    """
    One row per ticker, with every concept score, the composite score,
    both ranks, and both selection flags -- per file, so you can eyeball
    how a single ETF's full scoring breakdown shifted between runs
    (e.g. after tweaking concept_weights.performance.return_3y).
    """
    all_tickers = sorted(set().union(*[comparison_map[fn]["tickers"].keys() for fn in filenames]))
    rows = []
    for ticker in all_tickers:
        row = {"Ticker": ticker}
        for fn in filenames:
            info = comparison_map[fn]["tickers"].get(ticker, {})
            for col in SCORE_AND_RANK_PREFIXES:
                row[f"{fn}::{col}"] = info.get(col)
        rows.append(row)
    return pd.DataFrame(rows)


def load_filenames_from_list_file(list_file_path: str) -> List[str]:
    with open(list_file_path, "r") as f:
        lines = [line.strip() for line in f.readlines()]
    return [line for line in lines if line and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser(description="Compare N ETF result files listed in a text file.")
    parser.add_argument("list_file", help="Path to a text file containing one result .xlsx filename per line")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    filenames = load_filenames_from_list_file(args.list_file)
    if len(filenames) < 2:
        raise ValueError("Need at least 2 filenames in the list file to compare.")

    comparison_map = build_comparison_map(args.output_dir, filenames)

    print("=== Weights / Thresholds per file ===")
    for fn in filenames:
        print(f"\n{fn}")
        print("  thresholds:", comparison_map[fn]["thresholds"])
        print("  weights (profile-level):", comparison_map[fn]["weights"])
        print("  concept_weights (column-level):", comparison_map[fn]["concept_weights"])

    flag_diff_df = find_all_flag_differences(comparison_map, filenames)
    print("\n=== All pairwise Profile A Selected Flag differences (category + overall) ===")
    print(flag_diff_df.to_string(index=False) if not flag_diff_df.empty else "No differences across any pair.")

    matrix_df = build_ticker_matrix(comparison_map, filenames)

    diff_out_path = os.path.join(args.output_dir, "compare_results_report.xlsx")
    with pd.ExcelWriter(diff_out_path) as writer:
        flag_diff_df.to_excel(writer, sheet_name="flag_diffs", index=False)
        matrix_df.to_excel(writer, sheet_name="ticker_matrix", index=False)

    print(f"\nReport written to {diff_out_path}")


if __name__ == "__main__":
    main()
