"""
ETF Fund Screener - Main Entry Point

This script runs the complete ETF analysis pipeline to help you find the best
ETFs based on multiple financial metrics. It's designed to be easy to use:
  1. Just run `python main.py` and it will prompt you for a configuration file
  2. All settings are controlled via YAML files - no code changes needed
  3. Results are exported to Excel with clear rankings and scores

HOW IT WORKS:
  1. Loads structural and performance data from Morningstar Excel files
  2. Merges the datasets and filters to ETFs only (no stocks)
  3. Fetches additional metrics from Yahoo Finance (Sharpe ratios, Z-scores)
  4. Calculates scores across 8 key dimensions (performance, risk, costs, etc.)
  5. Applies your custom filters (expense ratio limits, fund size, etc.)
  6. Ranks funds within each category and selects the top N per category
  7. Exports results to Excel with formatted headers and all details

ADDING NEW INVESTMENT PROFILES:
  To create a new investment strategy (e.g., aggressive growth, income-focused):
  1. Copy profiles/profile_a.py as a template and name it profiles/profile_x.py
  2. Add one line: `import profiles.profile_x`  (see line 55 below)
  3. Create a YAML configuration file for your new profile
  No other code changes needed - the profile self-registers automatically!

CONFIGURATION:
  All settings come from a YAML file (e.g., input_profile_a.yaml):
  - Input file paths (structural data, performance data)
  - Output directory
  - Profile name (which investment strategy to use)
  - Top N funds to select per category
  - Custom thresholds and weights for scoring

TECHNICAL NOTE:
  The composite score uses numeric metrics only (returns, Sharpe, fees, etc.).
  Qualitative fields like Medalist ratings and letter grades are preserved
  in the output for reference but are not part of the numerical score.
"""

from typing import List, Tuple
import pandas as pd
import yaml
import os

from config import (
    DEFAULT_TOP_N_PER_CATEGORY,
    DEFAULT_DATA_PATH,
    DEFAULT_OUT_PATH,
    DEFAULT_PROFILE_NAME,
    DEFAULT_YAHOO_METRICS,
)
from input_file import load_profile_input, ProfileInput
from data_loading import load_data
from merging import apply_fund_filter
from scoring import build_concept_scores, PROFILE_FILTERS, PROFILE_SCORERS
from utils import yahoo_metrics
YahooMetricsConfig = yahoo_metrics.YahooMetricsConfig
get_yahoo_metrics_for_tickers = yahoo_metrics.get_yahoo_metrics_for_tickers

from export import (
    write_excel_with_retry,
    apply_header_formatting,
    format_column_names_for_export,
    build_timestamped_output_path,
    append_to_recorder,
    write_used_weights_report,
    create_sheets_by_category,
)
from database import ETFScreenerDatabase


# Import each profile module once so it self-registers into
# PROFILE_FILTERS / PROFILE_SCORERS. Add new profiles here, one line each.
import profiles.profile_a  # noqa: F401  (registers "A")
# import profiles.profile_b  # noqa: F401  (registers "B" -- future)


def get_profile_input_interactively() -> ProfileInput:
    """
    Repeatedly prompt for a profile input file path until one loads
    successfully. Mirrors the retry pattern already used elsewhere in
    this project for struct/perf file loading -- catches common errors
    (missing file, bad YAML, invalid contents) and lets the user retype
    the path instead of crashing the whole pipeline.
    """
    while True:
        input_file = input("Path to profile input file (e.g. input_profile_a.yaml): ").strip()

        if not input_file:
            print("  Please enter a file path.")
            continue

        try:
            return load_profile_input(input_file)
        except FileNotFoundError:
            print(f"  File not found: {input_file}. Please check the path and try again.")
        except PermissionError:
            print(f"  Permission denied: {input_file}. Close it if it's open elsewhere, then retry.")
        except yaml.YAMLError as e:
            print(f"  Could not parse YAML in {input_file}: {e}")
        except ValueError as e:
            print(f"  Invalid input file contents: {e}")


def _validate_profile_name(profile_name: str) -> None:
    """
    Raise a clear, early ValueError if `profile_name` isn't registered in
    both PROFILE_FILTERS and PROFILE_SCORERS -- e.g. a typo like 'a'
    instead of 'A', or a profile module that was never imported.
    """
    known_filter_names = set(PROFILE_FILTERS)
    known_scorer_names = set(PROFILE_SCORERS)
    available: List[str] = sorted(known_filter_names | known_scorer_names)

    if profile_name not in known_filter_names or profile_name not in known_scorer_names:
        raise ValueError(
            f"Unknown profile_name '{profile_name}'. "
            f"Available profiles: {available or '(none registered -- did you forget to `import profiles.profile_x`?)'}"
        )


def ensure_profile_score_numeric(df: pd.DataFrame, profile_name: str) -> pd.DataFrame:
    """
    Stage A export safety: force profile score/rank columns to real floats.

    Ranking logic is unchanged. This only fixes dtype/export issues where
    Excel later shows Model/Profile scores as text (str/object).
    """
    out = df.copy()

    candidates = [
        f"Profile_{profile_name}_Score",
        f"Profile_{profile_name}_Rank_In_Category",
        f"Profile_{profile_name}_Rank_Overall",
        # legacy / alternate names if a profile still emits them
        "Model_Composite_Score",
        "Model_Rank_In_Category",
    ]

    for col in candidates:
        if col not in out.columns:
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce")
        # plain float64 (not pandas nullable Float64) plays better with openpyxl/Excel
        out[col] = out[col].astype("float64")

    # Selected flags stay boolean if present
    for col in (
        f"Profile_{profile_name}_Selected_Flag",
        f"Profile_{profile_name}_Selected_Overall_Flag",
        "Model_Selected_Flag",
    ):
        if col in out.columns:
            out[col] = out[col].astype(bool)

    return out


def print_numeric_score_check(df: pd.DataFrame, profile_name: str) -> None:
    """Quick console proof that score columns are numeric before Excel write."""
    score_col = f"Profile_{profile_name}_Score"
    rank_col = f"Profile_{profile_name}_Rank_In_Category"
    cols = [c for c in (score_col, rank_col, "Model_Composite_Score") if c in df.columns]
    if not cols:
        print("  (No profile/model score columns found for numeric check.)")
        return

    print("  Numeric dtype check (pre-export):")
    print(df[cols].dtypes.to_string())
    print(df[cols].head(5).to_string(index=False))

    for c in cols:
        if str(df[c].dtype) == "object":
            raise TypeError(
                f"{c} is still object/str after ensure_profile_score_numeric(). "
                "Fix the profile scorer to assign numeric Series, not strings."
            )


def process_data(
    data_path: str = DEFAULT_DATA_PATH,
    out_path: str = DEFAULT_OUT_PATH,
    profile_name: str = DEFAULT_PROFILE_NAME,
    top_n: int = DEFAULT_TOP_N_PER_CATEGORY,
    thresholds: dict = None,
) -> Tuple[pd.DataFrame, str]:
    """
    Run the full pipeline end-to-end for a single profile:
      load -> ETF-only filter -> concept scores ->
      profile eligibility filter -> profile scoring/ranking ->
      numeric score enforcement ->
      format for export -> save -> style header row.

    `thresholds` comes from the profile input YAML file (ProfileInput.thresholds)
    and is passed through to both the registered filter and scorer functions
    for `profile_name`, so eligibility gates and weights are configurable
    without editing code. Defaults to an empty dict if not provided, so
    each profile module's own `thresholds.get(key, default)` calls fall
    back safely.

    Stage A: ranking/selection logic remains entirely inside PROFILE_SCORERS.
    This function does not add quality/risk gates on qualitative fields.
    """
    if thresholds is None:
        thresholds = {}

    _validate_profile_name(profile_name)

    print("Loading data (performance + structural combined)...")
    df: pd.DataFrame = load_data(data_path, exclude_dir=out_path)
    print(f"After load: {len(df)} rows")

    print("Filtering to ETFs and mutual funds (excluding stocks)...")
    df = apply_fund_filter(df)
    print(f"After fund filter: {len(df)} rows")

    print("Fetching Yahoo Finance metrics (sub-sector, Sharpe, Z-scores)...")
    yahoo_cfg = YahooMetricsConfig(**thresholds.get("yahoo_metrics", {}))
    df_yahoo: pd.DataFrame = get_yahoo_metrics_for_tickers(df["Ticker"], cfg=yahoo_cfg)

    # TEMP DEBUG (per user request 2026-07-19): print raw Yahoo results
    # before merging into the Morningstar dataframe, for validation.
    # Remove this print once satisfied the Yahoo fetch is trustworthy.
    # print("\n[DEBUG] Raw Yahoo metrics before merge:")
    # print(df_yahoo.to_string(index=False))
    # print()

    df = pd.merge(df, df_yahoo, on="Ticker", how="left")

    if "Inception Date" in df.columns:
        three_years_ago = pd.Timestamp.now() - pd.Timedelta(days=3 * 365)
        is_established: pd.Series = df["Inception Date"].notna() & (df["Inception Date"] <= three_years_ago)
        yahoo_metric_cols = [c for c in ["Sharpe_3Y", "Z_Score_3Y"] if c in df.columns]
        yahoo_missing: pd.Series = df[yahoo_metric_cols].isna().any(axis=1) if yahoo_metric_cols else pd.Series(False, index=df.index)
        df["Yahoo_Data_Suspect"] = is_established & yahoo_missing

        suspect_count = int(df["Yahoo_Data_Suspect"].sum())
        if suspect_count > 0:
            print(f"  Yahoo_Data_Suspect: {suspect_count} ETF(s) have 3y+ inception history but missing Yahoo Sharpe/Z-score data.")
    else:
        print("  Note: 'Inception Date' column not found -- skipping Yahoo_Data_Suspect check.")
        df["Yahoo_Data_Suspect"] = False

    print("Building concept scores...")
    df = build_concept_scores(df, concept_weights=thresholds.get("concept_weights"))

    print("Adding return rankings for all periods...")
    from scoring import calculate_return_rankings
    df = calculate_return_rankings(df)

    print(f"Applying Profile {profile_name} eligibility filters...")
    df_eligible: pd.DataFrame = PROFILE_FILTERS[profile_name](df, thresholds)

    print(f"Computing Profile {profile_name} composite score and rankings...")
    df_ranked: pd.DataFrame = PROFILE_SCORERS[profile_name](df_eligible, top_n, thresholds)

    # --- Stage A addition: numeric enforcement only (no logic change) ---
    print("Enforcing numeric dtypes on profile score/rank columns...")
    df_ranked = ensure_profile_score_numeric(df_ranked, profile_name=profile_name)
    print_numeric_score_check(df_ranked, profile_name=profile_name)

    print("Formatting column names for export...")
    df_export: pd.DataFrame = format_column_names_for_export(df_ranked)

    # Re-apply numeric cast after any export renaming (names may change)
    df_export = ensure_profile_score_numeric(df_export, profile_name=profile_name)
    # Also catch human-readable renamed headers if export renames them
    for pretty in (
        "Profile A Score",
        f"Profile {profile_name} Score",
        "Composite Score",
        "Model Composite Score",
        "Rank In Category",
        "Rank Overall",
    ):
        if pretty in df_export.columns:
            df_export[pretty] = pd.to_numeric(df_export[pretty], errors="coerce").astype("float64")

    final_out_path: str = build_timestamped_output_path(out_path, prefix=f"results_profile_{profile_name}")
    print(f"Output will be saved to: {final_out_path}")

    # Generate sheet name with current date in monthdayyear-overview format
    from datetime import datetime
    current_date = datetime.now()
    sheet_name = f"{current_date.strftime('%m%d%Y')}-overview"

    print("Saving results...")
    write_excel_with_retry(df_export, final_out_path, sheet_name=sheet_name)

    print("Formatting header row...")
    apply_header_formatting(final_out_path)

    print("Updating run recorder...")
    append_to_recorder(
        output_dir=out_path,
        output_filename=os.path.basename(final_out_path),
        thresholds=thresholds,
    )

    print("Writing used-weights report for this run...")
    used_weights_path = write_used_weights_report(
        out_path=out_path,
        result_filename=os.path.basename(final_out_path),
        profile_name=profile_name,
        top_n=top_n,
        thresholds=thresholds,
    )
    print(f"Used-weights report saved to: {used_weights_path}")

    # Create separate files by category if columns exist
    category_columns = ["Asset Class", "Morningstar Category", "Equity Style Box (Funds)"]
    
    # Create a subdirectory for category files with timestamp matching the results file
    base_filename_no_ext = os.path.splitext(os.path.basename(final_out_path))[0]
    category_output_dir = os.path.join(out_path, f"{base_filename_no_ext}_by_category")
    os.makedirs(category_output_dir, exist_ok=True)
    
    for category_col in category_columns:
        if category_col in df_export.columns:
            create_sheets_by_category(df_export, category_col, category_output_dir)

    # Save results to SQLite database
    print("Saving results to SQLite database...")
    db = ETFScreenerDatabase()
    run_id = db.save_results(
        df=df_export,
        profile_name=profile_name,
        weights=thresholds
    )

    # Save complete dataset (raw data + all computed results) to morningstar table
    print("Saving complete dataset to morningstar table...")
    db.save_morningstar_data(df_export)

    db.close()
    print(f"Results saved to database with run_id: {run_id}")

    return df_ranked, final_out_path


def print_summary(df_ranked: pd.DataFrame, profile_name: str, top_n: int) -> None:
    """
    Print the per-category and overall top selections for quick review
    in the console. Uses the internal (pre-export) column names, since
    this runs on df_ranked before format_column_names_for_export().
    """
    score_col = f"Profile_{profile_name}_Score"
    rank_in_cat_col = f"Profile_{profile_name}_Rank_In_Category"
    selected_flag_col = f"Profile_{profile_name}_Selected_Flag"
    rank_overall_col = f"Profile_{profile_name}_Rank_Overall"
    selected_overall_col = f"Profile_{profile_name}_Selected_Overall_Flag"

    display_cols: List[str] = [
        "Ticker", "Name", "Morningstar Category",
        score_col, rank_in_cat_col, selected_flag_col,
        rank_overall_col, selected_overall_col,
    ]
    display_cols = [c for c in display_cols if c in df_ranked.columns]

    if selected_flag_col in df_ranked.columns and rank_in_cat_col in df_ranked.columns:
        selected_by_category = df_ranked[df_ranked[selected_flag_col]].sort_values(
            ["Morningstar Category", rank_in_cat_col]
        )
        print(f"\n{len(selected_by_category)} ETFs selected across all categories "
              f"(top {top_n} per category).")
        print(selected_by_category[display_cols].head(50).to_string(index=False))
    else:
        print(f"\n(Skipping per-category summary -- '{selected_flag_col}' or "
              f"'{rank_in_cat_col}' not found on ranked results.)")

    if selected_overall_col in df_ranked.columns and rank_overall_col in df_ranked.columns:
        selected_overall = df_ranked[df_ranked[selected_overall_col]].sort_values(
            rank_overall_col
        )
        print(f"\nTop {top_n} ETFs overall (regardless of category):")
        print(selected_overall[display_cols].head(top_n).to_string(index=False))
    else:
        print(f"\n(Skipping overall summary -- '{selected_overall_col}' or "
              f"'{rank_overall_col}' not found on ranked results.)")


def main() -> None:
    profile_input = get_profile_input_interactively()

    df_ranked, final_out_path = process_data(
        data_path=profile_input.data_path,
        out_path=profile_input.out_path,
        profile_name=profile_input.profile_name,
        top_n=profile_input.top_n_per_category,
        thresholds=profile_input.thresholds,
    )

    print_summary(df_ranked, profile_name=profile_input.profile_name, top_n=profile_input.top_n_per_category)


if __name__ == "__main__":
    main()
