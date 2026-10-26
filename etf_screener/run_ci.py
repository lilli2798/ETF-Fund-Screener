"""Non-interactive CI entry point. Wraps main.process_data() and runs every
enabled input_files/profile_*.yaml instead of prompting, so it can
run headless inside GitHub Actions. All profiles go into one report
(results_profile_LT_ST_....xlsx) with every fund that passed any profile's
rules; each profile adds its own score/rank/flag columns."""
import sys
from pathlib import Path

# Add parent directory to path so imports work when running scripts directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from input_file import discover_profiles
from main import process_data

if __name__ == "__main__":
    first, *extras = discover_profiles()
    print(f"\n===== Profiles {', '.join(p.profile_name for p in (first, *extras))} =====")
    df, out_path = process_data(
        data_path=first.data_path,
        out_path=first.out_path,
        profile_name=first.profile_name,
        top_n=first.top_n_per_category,
        thresholds=first.thresholds,
        extra_profiles=extras,
    )
    print(f"CI run complete. Output written to: {out_path}")
    sys.exit(0)
