"""Non-interactive CI entry point. Wraps main.process_data() using a
fixed profile input path instead of prompting, so it can run headless
inside GitHub Actions."""
import sys
from input_file import load_profile_input
from main import process_data

PROFILE_INPUT_PATH = "input_files/input_profile_a.yaml"

if __name__ == "__main__":
    profile_input = load_profile_input(PROFILE_INPUT_PATH)
    df, out_path = process_data(
        struct_path=profile_input.struct_path,
        perf_path=profile_input.perf_path,
        out_path=profile_input.out_path,
        profile_name=profile_input.profile_name,
        top_n=profile_input.top_n,
        thresholds=profile_input.thresholds,
    )
    print(f"CI run complete. Output written to: {out_path}")
    sys.exit(0)
