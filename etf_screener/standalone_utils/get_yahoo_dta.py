from __future__ import annotations

import os
import sys
from datetime import datetime

# This script lives in etf_screener/standalone_utils; yahoo_metrics.py is in etf_screener/utils.
HERE = os.path.dirname(os.path.abspath(__file__))
UTILS_DIR = os.path.join(HERE, "..", "utils")
sys.path.insert(0, UTILS_DIR)
from yahoo_metrics import YahooMetricsConfig, get_yahoo_metrics_for_tickers, read_tickers_from_file  # noqa: E402

INPUT_FILE = os.path.join(HERE, "tickers.txt")
OUTPUT_DIR = os.path.join(HERE, "..", "..", "output", "yahoo_screen")  # not in git
OUTPUT_FILE_PREFIX = "yahoo_metrics"


def main() -> None:
    tickers = read_tickers_from_file(INPUT_FILE)
    if not tickers:
        raise SystemExit(f"No tickers found in {INPUT_FILE}.")

    print(f"Loaded {len(tickers)} unique ticker(s) from {INPUT_FILE}.")
    # Share the screener's sub-sector cache instead of creating a new one here
    cfg = YahooMetricsConfig(subsector_cache_path=os.path.join(UTILS_DIR, "sector_cache.json"))
    df = get_yahoo_metrics_for_tickers(tickers, cfg=cfg)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{OUTPUT_FILE_PREFIX}_{timestamp}.csv"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, output_name)
    df.to_csv(output_path, index=False)

    print(f"Saved Yahoo metrics export: {output_path}")
    print(f"Rows exported: {len(df)}")


if __name__ == "__main__":
    main()
