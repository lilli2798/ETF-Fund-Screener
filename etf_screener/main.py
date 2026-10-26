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
  Profiles LT (long term) and ST (short term) share the logic in
  profiles/weighted_profile.py and differ only in their YAML files.
  To add one, copy a profile_*.yaml in input_files/ and give it a new
  `profile:` key -- nothing else to change. Every enabled profile_*.yaml
  goes into one report (results_profile_LT_ST_...), each with its own
  score/rank columns.

CONFIGURATION:
  All settings come from a YAML file (e.g., input_files/profile_long_term.yaml):
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

import os
from typing import List, Sequence, Tuple

import pandas as pd
import yaml

from config import (
    KEEP_LAST_REPORTS,
    YEARLY_RETURN_YEARS,
    YEARLY_RETURNS_CSV,
)
from data_loading import load_data
from input_file import discover_profiles, load_profile_input, ProfileInput
from merging import apply_fund_filter, attach_yearly_returns
from performance import append_benchmark_rows, attach_volatile_performance, attach_yearly_stats
from extra_reports import split_no_yahoo_data
from scoring import build_concept_scores, PROFILE_FILTERS, PROFILE_PREFILTERS, PROFILE_SCORERS
from utils import yahoo_metrics

YahooMetricsConfig = yahoo_metrics.YahooMetricsConfig
get_yahoo_metrics_for_tickers = yahoo_metrics.get_yahoo_metrics_for_tickers
add_subsector_z_scores = yahoo_metrics.add_subsector_z_scores

from export import (
    add_sheets_to_workbook,
    write_excel_with_retry,
    apply_header_formatting,
    format_column_names_for_export,
    build_timestamped_output_path,
    append_to_recorder,
    write_used_weights_report,
    create_sheets_by_category,
    prune_old_reports,
)


# Profiles with their own logic get a module in profiles/ that registers
# its key when imported; add it here, one line each. Every other profile
# key uses profiles/weighted_profile.py (see _validate_profile_name).
import profiles.weighted_profile

# Yahoo results already fetched in this process, keyed by settings.
_YAHOO_RESULTS: dict = {}


def get_profile_input_interactively() -> List[ProfileInput]:
    """
    Repeatedly prompt for a profile input file path until one loads
    successfully. Pressing Enter without a path loads every enabled
    input_files/profile_*.yaml (one combined report). Mirrors the retry pattern already used elsewhere in
    this project for struct/perf file loading -- catches common errors
    (missing file, bad YAML, invalid contents) and lets the user retype
    the path instead of crashing the whole pipeline.
    """
    while True:
        input_file = input(
            "Path to profile input file (e.g. input_files/profile_long_term.yaml),\n"
            "or press Enter for all profiles in one report: "
        ).strip()

        try:
            if not input_file:
                return discover_profiles()
            return [load_profile_input(input_file)]
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
    Make sure `profile_name` has a filter and scorer. A key no profile
    module registered itself uses profiles/weighted_profile.py, so a new
    YAML needs no code change.
    """
    if profile_name not in PROFILE_FILTERS or profile_name not in PROFILE_SCORERS:
        profiles.weighted_profile.register(profile_name)


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


def profile_columns(profile_name: str) -> List[str]:
    """The score/rank/flag columns a profile scorer adds (internal names)."""
    return [
        f"Profile_{profile_name}_Score",
        f"Profile_{profile_name}_Rank_In_Category",
        f"Profile_{profile_name}_Selected_Flag",
        f"Profile_{profile_name}_Rank_Overall",
        f"Profile_{profile_name}_Selected_Overall_Flag",
    ]


def add_profile_columns(df_ranked: pd.DataFrame, df_other: pd.DataFrame, profile_name: str) -> pd.DataFrame:
    """
    Merge another profile's score/rank/flag columns onto `df_ranked` by
    Ticker. Funds the other profile filtered out (e.g. leveraged funds in
    ST) get a blank score and False flags.
    """
    cols = [c for c in profile_columns(profile_name) if c in df_other.columns]
    other = df_other[["Ticker", *cols]].drop_duplicates("Ticker")
    not_in_base = len(set(other["Ticker"]) - set(df_ranked["Ticker"]))
    if not_in_base:
        print(f"  Note: {not_in_base} fund(s) passed Profile {profile_name} but not the base "
              f"profile's filters, so they are not in the combined report.")
    merged = df_ranked.merge(other, on="Ticker", how="left")
    for col in cols:
        if col.endswith("_Flag"):
            merged[col] = merged[col].fillna(False).astype(bool)
    return merged


def score_profile(
    data_path: str,
    out_path: str,
    profile_name: str,
    top_n: int,
    thresholds: dict,
) -> Tuple[pd.DataFrame, dict]:
    """
    Load, filter and score the data for one profile. Returns the ranked
    DataFrame (internal column names) and the missing-data reports for
    the run recorder.
    """
    _validate_profile_name(profile_name)

    print("Loading data (performance + structural combined)...")
    df: pd.DataFrame = load_data(data_path, exclude_dir=out_path)
    print(f"After load: {len(df)} rows")

    print("Filtering to ETFs and mutual funds (excluding stocks)...")
    df = apply_fund_filter(df)
    print(f"After fund filter: {len(df)} rows")

    if profile_name in PROFILE_PREFILTERS:
        print(f"Applying Profile {profile_name} eligibility filters (Morningstar rules)...")
        df = PROFILE_PREFILTERS[profile_name](df, thresholds)

    print("Fetching Yahoo Finance metrics (sub-sector, Sharpe, Z-scores)...")
    yahoo_cfg = YahooMetricsConfig.from_thresholds(thresholds)
    # run_ci.py runs several profiles in one process. Funds an earlier
    # profile already fetched (with the same settings) are reused; only new
    # ones are downloaded. Z-scores compare each fund with its sub-sector
    # peers, so they're recomputed on this profile's own fund list.
    tickers = {str(t).strip().upper() for t in df["Ticker"].dropna() if str(t).strip()}
    fetched = _YAHOO_RESULTS.get(repr(yahoo_cfg))
    if fetched is None:
        fetched = get_yahoo_metrics_for_tickers(df["Ticker"], cfg=yahoo_cfg)
    else:
        missing = sorted(tickers - set(fetched["Ticker"]))
        print(f"  Reusing Yahoo metrics fetched earlier in this run; {len(missing)} new fund(s) to fetch.")
        if missing:
            fetched = pd.concat([fetched, get_yahoo_metrics_for_tickers(missing, cfg=yahoo_cfg)], ignore_index=True)
    _YAHOO_RESULTS[repr(yahoo_cfg)] = fetched
    df_yahoo: pd.DataFrame = add_subsector_z_scores(fetched[fetched["Ticker"].isin(tickers)])

    # TEMP DEBUG (per user request 2026-07-19): print raw Yahoo results
    # before merging into the Morningstar dataframe, for validation.
    # Remove this print once satisfied the Yahoo fetch is trustworthy.
    # print("\n[DEBUG] Raw Yahoo metrics before merge:")
    # print(df_yahoo.to_string(index=False))
    # print()

    df = pd.merge(df, df_yahoo, on="Ticker", how="left")

    print(f"Attaching last {YEARLY_RETURN_YEARS} calendar-year returns...")
    df, yearly_missing_report = attach_yearly_returns(df, YEARLY_RETURNS_CSV, n_years=YEARLY_RETURN_YEARS)
    df = attach_yearly_stats(df, YEARLY_RETURNS_CSV, n_years=YEARLY_RETURN_YEARS)

    print("Attaching performance in volatile market periods...")
    df, volatile_report = attach_volatile_performance(df)

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

    print(f"Applying Profile {profile_name} benchmark filter...")
    df_eligible: pd.DataFrame = PROFILE_FILTERS[profile_name](df, thresholds)

    print(f"Computing Profile {profile_name} composite score and rankings...")
    df_ranked: pd.DataFrame = PROFILE_SCORERS[profile_name](df_eligible, top_n, thresholds)

    # --- Stage A addition: numeric enforcement only (no logic change) ---
    print("Enforcing numeric dtypes on profile score/rank columns...")
    df_ranked = ensure_profile_score_numeric(df_ranked, profile_name=profile_name)
    print_numeric_score_check(df_ranked, profile_name=profile_name)

    reports = {"yearly_returns_missing": yearly_missing_report, "volatile_performance": volatile_report}
    return df_ranked, reports


def process_data(
    data_path: str,
    out_path: str,
    profile_name: str,
    top_n: int,
    thresholds: dict,
    extra_profiles: Sequence[ProfileInput] = (),
) -> Tuple[pd.DataFrame, str]:
    """
    Run the full pipeline end-to-end:
      load -> ETF-only filter -> concept scores ->
      profile eligibility filter -> profile scoring/ranking ->
      numeric score enforcement ->
      format for export -> save -> style header row.

    `thresholds` comes from the profile input YAML file (ProfileInput.thresholds)
    and is passed through to both the registered filter and scorer functions
    for `profile_name`, so eligibility gates and weights are configurable
    without editing code.

    `extra_profiles` are scored the same way, each with its own YAML, and
    their score/rank/flag columns are added to this report (e.g. Profile
    ST next to Profile LT). The rows, concept scores and other columns
    come from the first profile (`profile_name`).

    Stage A: ranking/selection logic remains entirely inside PROFILE_SCORERS.
    This function does not add quality/risk gates on qualitative fields.
    """
    df_ranked, reports = score_profile(data_path, out_path, profile_name, top_n, thresholds)

    all_profiles = [(profile_name, top_n, thresholds)]
    for extra in extra_profiles:
        print(f"\n===== Profile {extra.profile_name}: scoring to add its columns to the report =====")
        df_extra, _ = score_profile(data_path, out_path, extra.profile_name, extra.top_n_per_category, extra.thresholds)
        df_ranked = add_profile_columns(df_ranked, df_extra, extra.profile_name)
        df_ranked = ensure_profile_score_numeric(df_ranked, profile_name=extra.profile_name)
        all_profiles.append((extra.profile_name, extra.top_n_per_category, extra.thresholds))
    profile_names = [name for name, _, _ in all_profiles]

    print("Formatting column names for export...")
    df_export: pd.DataFrame = format_column_names_for_export(df_ranked, profile_names)

    # Re-apply numeric cast after any export renaming (names may change)
    for name in profile_names:
        df_export = ensure_profile_score_numeric(df_export, profile_name=name)
    # Also catch human-readable renamed headers if export renames them
    for pretty in (
        *(f"Profile {name} Score" for name in profile_names),
        "Composite Score",
        "Model Composite Score",
        "Rank In Category",
        "Rank Overall",
    ):
        if pretty in df_export.columns:
            df_export[pretty] = pd.to_numeric(df_export[pretty], errors="coerce").astype("float64")

    final_out_path: str = build_timestamped_output_path(out_path, prefix="results_profile_" + "_".join(profile_names))
    print(f"Output will be saved to: {final_out_path}")

    # Generate sheet name with current date in monthdayyear-overview format
    from datetime import datetime
    current_date = datetime.now()
    sheet_name = f"{current_date.strftime('%m%d%Y')}-overview"

    print("Saving results...")
    # Benchmark index rows (^GSPC, ^DJI, ^IXIC) go at the bottom of the main
    # report only -- not into the per-category files.
    # Funds Yahoo has no price history for get their own tab instead.
    df_overview, no_yahoo_tab = split_no_yahoo_data(df_export)
    write_excel_with_retry(append_benchmark_rows(df_overview, YEARLY_RETURNS_CSV), final_out_path, sheet_name=sheet_name)

    add_sheets_to_workbook(final_out_path, no_yahoo_tab)

    print("Formatting header row...")
    apply_header_formatting(final_out_path)

    print("Updating run recorder...")
    append_to_recorder(
        output_dir=out_path,
        output_filename=os.path.basename(final_out_path),
        thresholds={"top_n_per_category": top_n, **thresholds},
        # a combined report also records the other profiles' settings
        extra={**reports, **({"other_profiles": {name: {"top_n_per_category": n, **t} for name, n, t in all_profiles[1:]}}
                             if len(all_profiles) > 1 else {})},
    )

    print("Writing used-weights report for this run...")
    for name, profile_top_n, profile_thresholds in all_profiles:
        used_weights_path = write_used_weights_report(
            out_path=out_path,
            result_filename=os.path.basename(final_out_path),
            profile_name=name,
            top_n=profile_top_n,
            thresholds=profile_thresholds,
            # one file per profile when the report holds several
            name_suffix=f"_{name}" if len(all_profiles) > 1 else "",
        )
        print(f"Used-weights report saved to: {used_weights_path}")

    # Create separate files by category if columns exist
    # {subfolder: column}. Each split gets its own subfolder, since some
    # names repeat across columns (e.g. "Large Blend" is both a Morningstar
    # Category and a Style Box) and would overwrite each other.
    category_columns = {
        "Asset_Class": "Asset Class",
        "Morningstar_Category": "Morningstar Category",
        "Yahoo_Subsector": "Yahoo Subsector",
        "Style_Box": "Equity Style Box (Funds)",
    }

    # Create a subdirectory for category files with timestamp matching the results file
    base_filename_no_ext = os.path.splitext(os.path.basename(final_out_path))[0]
    category_output_dir = os.path.join(out_path, f"{base_filename_no_ext}_by_category")

    for folder, category_col in category_columns.items():
        if category_col in df_export.columns:
            split_dir = os.path.join(category_output_dir, folder)
            os.makedirs(split_dir, exist_ok=True)
            create_sheets_by_category(df_export, category_col, split_dir, sheet_name=sheet_name)

    removed = prune_old_reports(out_path, KEEP_LAST_REPORTS)
    if removed:
        print(f"Deleted {len(removed)} old report(s); keeping the newest {KEEP_LAST_REPORTS}.")

    return df_ranked, final_out_path


def print_summary(df_ranked: pd.DataFrame, profile_name: str, top_n: int, top_n_overall: int = None) -> None:
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
        top_n_overall = top_n_overall or top_n
        print(f"\nTop {top_n_overall} ETFs overall (regardless of category):")
        print(selected_overall[display_cols].head(top_n_overall).to_string(index=False))
    else:
        print(f"\n(Skipping overall summary -- '{selected_overall_col}' or "
              f"'{rank_overall_col}' not found on ranked results.)")


def main() -> None:
    profile_input, *extra_profiles = get_profile_input_interactively()

    df_ranked, final_out_path = process_data(
        data_path=profile_input.data_path,
        out_path=profile_input.out_path,
        profile_name=profile_input.profile_name,
        top_n=profile_input.top_n_per_category,
        thresholds=profile_input.thresholds,
        extra_profiles=extra_profiles,
    )

    for p in (profile_input, *extra_profiles):
        print(f"\n===== Profile {p.profile_name} summary =====")
        print_summary(df_ranked, profile_name=p.profile_name, top_n=p.top_n_per_category,
                      top_n_overall=p.thresholds.get("top_n_overall"))


if __name__ == "__main__":
    main()
