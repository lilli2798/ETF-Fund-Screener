from __future__ import annotations

import os
from datetime import datetime

from yahoo_metrics import YahooMetricsConfig, get_yahoo_metrics_for_tickers, read_tickers_from_file

INPUT_FILE = "tickers.txt"
OUTPUT_FILE_PREFIX = "yahoo_metrics"


def main() -> None:
    tickers = read_tickers_from_file(INPUT_FILE)
    if not tickers:
        raise SystemExit(f"No tickers found in {INPUT_FILE}.")

    print(f"Loaded {len(tickers)} unique ticker(s) from {INPUT_FILE}.")
    df = get_yahoo_metrics_for_tickers(tickers, cfg=YahooMetricsConfig())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{OUTPUT_FILE_PREFIX}_{timestamp}.csv"
    output_path = os.path.join(os.getcwd(), output_name)
    df.to_csv(output_path, index=False)

    print(f"Saved Yahoo metrics export: {output_path}")
    print(f"Rows exported: {len(df)}")


if __name__ == "__main__":
    main()
