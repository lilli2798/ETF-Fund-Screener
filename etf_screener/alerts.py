"""Reads the latest screener output and posts only high-signal rows
(e.g. STRONG BUY / TACTICAL BUY) to a Slack webhook."""
import glob
import os
import sys
import pandas as pd
import requests

OUTPUT_DIR = "output"
ALERT_DECISIONS = {"STRONG BUY", "TACTICAL BUY", "BUY THE DIP"}
WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def find_latest_file(directory: str, pattern: str) -> str | None:
    files = glob.glob(os.path.join(directory, pattern))
    return max(files, key=os.path.getmtime) if files else None

def main():
    latest_xlsx = find_latest_file(OUTPUT_DIR, "results_*.xlsx")
    if not latest_xlsx:
        print("No output file found; skipping alerts.")
        return

    df = pd.read_excel(latest_xlsx)
    decision_col = next((c for c in df.columns if "Decision" in c), None)
    if decision_col is None:
        print("No Decision column found; skipping alerts.")
        return

    hits = df[df[decision_col].str.contains("|".join(ALERT_DECISIONS), na=False)]
    if hits.empty:
        print("No alert-worthy tickers today.")
        return

    lines = [f"*{row.get('Ticker','?')}* — {row[decision_col]}" for _, row in hits.iterrows()]
    message = "📈 *Daily ETF Screener Alerts*\n" + "\n".join(lines[:20])

    if WEBHOOK_URL:
        resp = requests.post(WEBHOOK_URL, json={"text": message})
        resp.raise_for_status()
        print("Alert sent to Slack.")
    else:
        print("No SLACK_WEBHOOK_URL set — printing instead:\n" + message)

if __name__ == "__main__":
    main()
