"""
Thin orchestrator for the ETF screener pipeline.

All reusable logic lives in dedicated modules (data_loading, merging,
scoring, export, input_file). Profile-specific logic lives in profiles/*.py
and self-registers via decorators in scoring.py -- so adding a new profile
never requires editing this file's core logic, only:
  1. Create profiles/profile_x.py (copy profiles/profile_a.py as a template)
  2. Add one `import profiles.profile_x` line below

Run configuration (paths, profile name, top_n, thresholds) always comes
from a profile input YAML file (e.g. input_profile_a.yaml) -- the script
prompts for its path and retries on any load error, rather than accepting
CLI flags or asking for each setting individually.
"""

from typing import List, Tuple
import pandas as pd
import yaml
import os

from config import (
    DEFAULT_TOP_N_PER_CATEGORY,
    DEFAULT_STRUCT_PATH,
    DEFAULT_PERF_PATH,
    DEFAULT_OUT_PATH,
    DEFAULT_PROFILE_NAME,
    DEFAULT_YAHOO_METRICS,
)
from input_file import load_profile_input, ProfileInput
from data_loading import load_structural_data, load_performance_data
from merging import merge_datasets, apply_etf_only_filter
from scoring import build_concept_scores, PROFILE_FILTERS, PROFILE_SCORERS
from utils.yahoo_metrics import YahooMetricsConfig, get_yahoo_metrics_for_tickers

from export import (
    write_excel_with_retry,
    apply_header_formatting,
    format_column_names_for_export,
    build_timestamped_output_path,
    append_to_recorder,   # NEW
    write_used_weights_report,   # NEW
)


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


def process_data(
    struct_path: str = DEFAULT_STRUCT_PATH,
    perf_path: str = DEFAULT_PERF_PATH,
    out_path: str = DEFAULT_OUT_PATH,
    profile_name: str = DEFAULT_PROFILE_NAME,
    top_n: int = DEFAULT_TOP_N_PER_CATEGORY,
    thresholds: dict = None,
) -> Tuple[pd.DataFrame, str]:
    """
    Run the full pipeline end-to-end for a single profile:
      load -> merge -> ETF-only filter -> concept scores ->
      profile eligibility filter -> profile scoring/ranking ->
      format for export -> save -> style header row.

    `thresholds` comes from the profile input YAML file (ProfileInput.thresholds)
    and is passed through to both the registered filter and scorer functions
    for `profile_name`, so eligibility gates and weights are configurable
    without editing code. Defaults to an empty dict if not provided, so
    each profile module's own `thresholds.get(key, default)` calls fall
    back safely.
    """
    if thresholds is None:
        thresholds = {}

    _validate_profile_name(profile_name)

    print("Loading structural data...")
    df_struct: pd.DataFrame = load_structural_data(struct_path, exclude_dir=out_path)

    print("Loading performance data...")
    df_perf: pd.DataFrame = load_performance_data(perf_path, exclude_dir=out_path)

    print("Merging datasets on Ticker...")
    df: pd.DataFrame = merge_datasets(df_struct, df_perf)

    print("Filtering to ETFs only (excluding stocks)...")
    df = apply_etf_only_filter(df)

    print("Fetching Yahoo Finance metrics (sub-sector, Sharpe, Z-scores)...")
    yahoo_cfg = YahooMetricsConfig(**thresholds.get("yahoo_metrics", {}))
    df_yahoo: pd.DataFrame = get_yahoo_metrics_for_tickers(df["Ticker"], cfg=yahoo_cfg)

    # TEMP DEBUG (per user request 2026-07-19): print raw Yahoo results
    # before merging into the Morningstar dataframe, for validation.
    # Remove this print once satisfied the Yahoo fetch is trustworthy.
    print("\n[DEBUG] Raw Yahoo metrics before merge:")
    print(df_yahoo.to_string(index=False))
    print()

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

    print(f"Applying Profile {profile_name} eligibility filters...")
    df_eligible: pd.DataFrame = PROFILE_FILTERS[profile_name](df, thresholds)

    print(f"Computing Profile {profile_name} composite score and rankings...")
    df_ranked: pd.DataFrame = PROFILE_SCORERS[profile_name](df_eligible, top_n, thresholds)

    print("Formatting column names for export...")
    df_export: pd.DataFrame = format_column_names_for_export(df_ranked)

    final_out_path: str = build_timestamped_output_path(out_path, prefix=f"results_profile_{profile_name}")
    print(f"Output will be saved to: {final_out_path}")

    print("Saving results...")
    write_excel_with_retry(df_export, final_out_path)

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
        struct_path=profile_input.struct_path,
        perf_path=profile_input.perf_path,
        out_path=profile_input.out_path,
        profile_name=profile_input.profile_name,
        top_n=profile_input.top_n_per_category,
        thresholds=profile_input.thresholds,
    )

    print_summary(df_ranked, profile_name=profile_input.profile_name, top_n=profile_input.top_n_per_category)


if __name__ == "__main__":
    main()
