"""Non-interactive CI entry point. Wraps main.process_data() using a
fixed profile input path instead of prompting, so it can run headless
inside GitHub Actions."""
import sys
from pathlib import Path

# Add parent directory to path so imports work when running scripts directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from input_file import load_profile_input
from main import process_data

PROFILE_INPUT_PATH = str(Path(__file__).parent / "input_files" / "input_profile_a.yaml")

if __name__ == "__main__":
    profile_input = load_profile_input(PROFILE_INPUT_PATH)
    df, out_path = process_data(
        data_path=profile_input.data_path,
        out_path=profile_input.out_path,
        profile_name=profile_input.profile_name,
        top_n=profile_input.top_n_per_category,
        thresholds=profile_input.thresholds,
    )
    print(f"CI run complete. Output written to: {out_path}")
    sys.exit(0)
