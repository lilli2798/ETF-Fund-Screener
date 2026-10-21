"""
Find the most volatile S&P 500 periods of the last N years and save them to
volatile_config.yaml, so user_defined_by_date_yahoo_analize.py can offer them
as ready-made date ranges.

Usage:
    python volatile_periods.py            # last 50 years (default)
    python volatile_periods.py 30         # last 30 years

Three kinds of periods are found from ^GSPC daily closes:
  - bear_market: decline of >= 15% from an all-time high; `recovery` is the
    first close back at that high.
  - decline_leg: decline of >= 15% from a swing high (zigzag). Catches the
    separate waves inside a long bear market (e.g. 2001, 2002, 2008) and
    drops that happened while still below an old high (2010, 2011).
  - volatility_spike: 21-day annualized volatility above 35% (median is
    ~13%) that does not overlap a decline above.

Re-running keeps any `name` you edited and any entry you added yourself
with `source: manual`.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "volatile_config.yaml"

BENCHMARK = "^GSPC"
DECLINE_THRESHOLD = 0.15
VOL_WINDOW = 21
VOL_THRESHOLD = 0.35
SPIKE_MERGE_DAYS = 45      # merge spikes closer than this
SPIKE_OVERLAP_DAYS = 60    # spike counted as part of a decline if it starts within this many days after its low

# Historical names, keyed by the S&P 500 high (or spike start) that begins
# the period. Periods not listed get a generic name.
KNOWN_NAMES: Dict[str, str] = {
    "1976-09-21": "1976-78 bear market (inflation, rising rates)",
    "1980-02-13": "1980 credit-controls crash (Volcker rate shock)",
    "1980-11-28": "1980-82 bear market (Volcker tightening, double-dip recession)",
    "1987-08-25": "1987 crash (Black Monday)",
    "1988-01-08": "January 1988 post-crash aftershock",
    "1990-07-16": "1990 Gulf War / savings-and-loan recession",
    "1997-10-03": "1997 Asian financial crisis (Oct 27 mini-crash)",
    "1998-07-17": "1998 Russia default / LTCM",
    "2000-03-24": "2000-02 dot-com bust",
    "2001-05-21": "2001 recession and 9/11",
    "2002-01-04": "2002 accounting scandals (Enron, WorldCom)",
    "2002-08-22": "2002 final dot-com low",
    "2007-10-09": "2007-09 global financial crisis",
    "2008-11-04": "2008 post-Lehman November leg",
    "2009-01-06": "2009 final GFC leg to March low",
    "2010-04-23": "2010 flash crash / euro debt crisis",
    "2011-04-29": "2011 US downgrade / euro crisis",
    "2018-09-20": "2018 Q4 sell-off (Fed tightening, trade war)",
    "2020-02-19": "2020 COVID-19 crash",
    "2022-01-03": "2022 inflation / rate-hike bear market",
    "2022-08-16": "2022 second leg to October low",
    "2025-02-19": "2025 tariff shock",
}
# Legs that start on the same high as a bear market but end earlier
KNOWN_LEG_NAMES: Dict[str, str] = {
    "2000-03-24": "2000-01 dot-com bust, first leg",
    "2007-10-09": "2007-08 GFC, first leg to Oct 2008",
    "2022-01-03": "2022 first leg to June low",
}


def _d(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


def download_closes(years: int) -> pd.Series:
    start = f"{date.today().year - years}-01-01"
    px = yf.download(BENCHMARK, start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    return px.dropna()


def find_bear_markets(px: pd.Series) -> List[dict]:
    """Declines >= threshold measured from the running all-time high."""
    peak = px.cummax()
    drawdown = px / peak - 1
    out, start = [], None
    for d, v in drawdown.items():
        if start is None and v < 0:
            start = px.loc[:d][px.loc[:d] == peak[d]].index[-1]
        elif start is not None and v == 0:
            seg = drawdown.loc[start:d]
            out.append((start, seg.idxmin(), d, seg.min()))
            start = None
    if start is not None:
        seg = drawdown.loc[start:]
        out.append((start, seg.idxmin(), None, seg.min()))
    return [
        {"type": "bear_market", "start": _d(s), "end": _d(t),
         "recovery": _d(r) if r is not None else None, "sp500_change_pct": round(float(m) * 100, 1)}
        for s, t, r, m in out if m <= -DECLINE_THRESHOLD
    ]


def find_decline_legs(px: pd.Series) -> List[dict]:
    """Zigzag: each swing high -> low that falls >= threshold, reset by a >= threshold rally."""
    hi_d, hi_v = px.index[0], px.iloc[0]
    lo_d, lo_v = hi_d, hi_v
    falling, legs = False, []
    for d, v in px.items():
        if not falling:
            if v > hi_v:
                hi_d, hi_v = d, v
            elif v <= hi_v * (1 - DECLINE_THRESHOLD):
                falling, lo_d, lo_v = True, d, v
        else:
            if v < lo_v:
                lo_d, lo_v = d, v
            elif v >= lo_v * (1 + DECLINE_THRESHOLD):
                legs.append((hi_d, hi_v, lo_d, lo_v))
                falling, hi_d, hi_v = False, d, v
    if falling:
        legs.append((hi_d, hi_v, lo_d, lo_v))
    return [
        {"type": "decline_leg", "start": _d(h), "end": _d(l), "sp500_change_pct": round(float(lv / hv - 1) * 100, 1)}
        for h, hv, l, lv in legs
    ]


def find_volatility_spikes(vol: pd.Series) -> List[dict]:
    high = vol > VOL_THRESHOLD
    groups = (high != high.shift()).cumsum()[high]
    spikes = []
    for _, idx in groups.groupby(groups).groups.items():
        s, e = idx[0], idx[-1]
        if spikes and (s - spikes[-1][1]).days < SPIKE_MERGE_DAYS:
            spikes[-1] = (spikes[-1][0], e)
        else:
            spikes.append((s, e))
    # 21-day volatility measures the PREVIOUS 21 days, so start the period
    # where that window begins -- otherwise the shock itself is left out.
    def window_start(d: pd.Timestamp) -> pd.Timestamp:
        return vol.index[max(vol.index.get_loc(d) - VOL_WINDOW, 0)]

    return [{"type": "volatility_spike", "start": _d(window_start(s)), "end": _d(e)} for s, e in spikes]


def build_periods(years: int) -> List[dict]:
    px = download_closes(years)
    vol = np.log(px).diff().rolling(VOL_WINDOW).std() * np.sqrt(252)

    bears = find_bear_markets(px)
    legs = [leg for leg in find_decline_legs(px)
            if not any(b["start"] == leg["start"] and b["end"] == leg["end"] for b in bears)]
    declines = bears + legs

    def overlaps_decline(spike: dict) -> bool:
        s, e = pd.Timestamp(spike["start"]), pd.Timestamp(spike["end"])
        return any(s <= pd.Timestamp(p["end"]) + pd.Timedelta(days=SPIKE_OVERLAP_DAYS) and e >= pd.Timestamp(p["start"])
                   for p in declines)

    spikes = []
    for spike in find_volatility_spikes(vol):
        if not overlaps_decline(spike):
            window = px.loc[spike["start"]:spike["end"]]
            spike["sp500_change_pct"] = round(float(window.iloc[-1] / window.iloc[0] - 1) * 100, 1)
            spikes.append(spike)

    periods = declines + spikes
    for p in periods:
        window = vol.loc[p["start"]:p["end"]]
        p["peak_21d_vol_pct"] = int(round(window.max() * 100)) if window.notna().any() else None
        p["trading_days"] = int(len(px.loc[p["start"]:p["end"]]))
        if p["type"] == "decline_leg" and p["start"] in KNOWN_LEG_NAMES:
            p["name"] = KNOWN_LEG_NAMES[p["start"]]
        else:
            p["name"] = KNOWN_NAMES.get(p["start"], f"S&P 500 {p['type'].replace('_', ' ')} {p['start'][:7]}")
        p["id"] = f"{p['start']}_{p['type']}"
        p["source"] = "generated"

    periods.sort(key=lambda p: (p["start"], p["type"] != "bear_market"))
    return periods


def load_periods(path: Path = CONFIG_PATH) -> List[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("periods", [])


def save_periods(periods: List[dict], years: int, path: Path = CONFIG_PATH) -> None:
    previous = {p.get("id"): p for p in load_periods(path)}
    for p in periods:
        old = previous.get(p["id"])
        if old and old.get("name"):
            p["name"] = old["name"]  # keep names edited by hand
    manual = [p for p in previous.values() if p.get("source") == "manual"]
    all_periods = sorted(periods + manual, key=lambda p: str(p.get("start")))

    keys = ["id", "name", "type", "start", "end", "recovery", "sp500_change_pct",
            "peak_21d_vol_pct", "trading_days", "source"]
    ordered = [{k: p[k] for k in keys if k in p and p[k] is not None} for p in all_periods]

    header = (
        f"# Most volatile S&P 500 ({BENCHMARK}) periods, generated by volatile_periods.py\n"
        f"# on {date.today()} from daily closes over the last {years} years.\n"
        "#   bear_market      : >= 15% fall from an all-time high (start = high, end = low)\n"
        "#   decline_leg      : >= 15% fall from a swing high, e.g. waves inside a long bear market\n"
        "#   volatility_spike : 21-day annualized volatility > 35% not already covered above\n"
        "# Edit `name` freely. Add your own periods with `source: manual`; both survive re-runs.\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump({"periods": ordered}, f, sort_keys=False, allow_unicode=True)


def pick_period(periods: Optional[List[dict]] = None) -> Optional[dict]:
    """Print the periods and let the user choose one by number (Enter = none)."""
    periods = periods if periods is not None else load_periods()
    if not periods:
        print(f"No volatile periods found in {CONFIG_PATH.name}. Run: python volatile_periods.py")
        return None
    print(f"\n{'#':>3}  {'start':10}  {'end':10}  {'S&P':>7}  {'vol':>4}  name")
    for i, p in enumerate(periods, 1):
        chg = f"{p['sp500_change_pct']:+.1f}%" if p.get("sp500_change_pct") is not None else ""
        vol = f"{p['peak_21d_vol_pct']}%" if p.get("peak_21d_vol_pct") is not None else ""
        print(f"{i:>3}  {p['start']:10}  {p['end']:10}  {chg:>7}  {vol:>4}  {p.get('name', '')}")
    while True:
        choice = input("Pick a period number (or press Enter to type dates instead): ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1]
        print(f"Please enter a number from 1 to {len(periods)}.")


if __name__ == "__main__":
    n_years = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    found = build_periods(n_years)
    save_periods(found, n_years)
    print(f"Saved {len(found)} periods to {CONFIG_PATH}")
    for p in load_periods():
        print(f"  {p['start']} -> {p['end']}  {p.get('sp500_change_pct', ''):>6}%  {p['name']}")
