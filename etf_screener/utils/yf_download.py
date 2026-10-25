"""yf.download() with retries for Yahoo rate limiting.

When Yahoo rate-limits a request, yf.download() does not raise: it returns
empty (NaN) columns for the affected tickers and only logs the error
("['AAA', 'BBB']: YFRateLimitError(...)") to the "yfinance" logger.
Treating those blanks as "no data" would cache good funds as empty, so this
helper reads those log lines, retries the rate-limited tickers after a
pause, and reports any that still failed, for the caller to leave uncached.
"""
from __future__ import annotations

import ast
import logging
import time
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf


def is_rate_limit_error(error: object) -> bool:
    text = str(error or "")
    return "RateLimit" in text or "Too Many Requests" in text


class _ErrorCollector(logging.Handler):
    """Collects {ticker: error} from yf.download()'s "[tickers]: error" log lines."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.errors: Dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage().strip()
        if not msg.startswith("[") or "]: " not in msg:
            return
        tickers, error = msg.split("]: ", 1)
        try:
            for t in ast.literal_eval(tickers + "]"):
                self.errors[str(t)] = error
        except (ValueError, SyntaxError):
            pass


def download_prices(
    tickers: List[str],
    field: str,
    retries: int = 3,
    wait_seconds: float = 30.0,
    **kwargs,
) -> Tuple[pd.DataFrame, List[str]]:
    """Download one price field (e.g. "Close") for `tickers`.

    Returns (prices with tickers as columns, tickers that could not be
    downloaded because of rate limiting or a failed request). Tickers Yahoo
    simply has no data for (delisted, too new) are NOT in the failed list.
    """
    pending = list(dict.fromkeys(tickers))
    frames: List[pd.DataFrame] = []

    for attempt in range(retries + 1):
        collector = _ErrorCollector()
        yf_logger = logging.getLogger("yfinance")
        yf_logger.addHandler(collector)
        try:
            data = yf.download(pending, progress=False, multi_level_index=True, **kwargs)
            failed = [t for t in pending if is_rate_limit_error(collector.errors.get(t))]
        except Exception as exc:  # network error: retry the whole request
            print(f"    Yahoo download failed ({exc}).")
            data, failed = pd.DataFrame(), pending
        finally:
            yf_logger.removeHandler(collector)

        if not data.empty and field in data.columns.get_level_values(0):
            prices = data[field]
            frames.append(prices.drop(columns=[t for t in failed if t in prices.columns]))

        # stop when a retry recovers nothing: Yahoo also answers some unknown
        # symbols with "rate limited", and waiting longer won't help those
        no_progress = attempt > 0 and set(failed) == set(pending)
        pending = failed
        if not pending or attempt == retries or no_progress:
            break
        wait = wait_seconds * (attempt + 1)
        print(f"    Yahoo rate limit: {len(pending)} ticker(s), retrying in {wait:.0f}s...")
        time.sleep(wait)

    prices = pd.concat(frames, axis=1) if frames else pd.DataFrame()
    prices = prices.loc[:, ~prices.columns.duplicated()]
    return prices, pending
