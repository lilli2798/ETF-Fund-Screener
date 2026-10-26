"""Non-interactive CI entry point. Wraps main.process_data() and runs every
profile YAML in config.PROFILE_INPUT_FILES instead of prompting, so it can
run headless inside GitHub Actions. All profiles go into one report
(results_profile_LT_ST_....xlsx): the rows and concept scores come from
the first profile, and each profile adds its own score/rank/flag columns."""
import sys
from pathlib import Path

# Add parent directory to path so imports work when running scripts directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROFILE_INPUT_FILES
from input_file import load_profile_input
from main import process_data

if __name__ == "__main__":
    first, *extras = [load_profile_input(str(Path(__file__).parent / f)) for f in PROFILE_INPUT_FILES]
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
