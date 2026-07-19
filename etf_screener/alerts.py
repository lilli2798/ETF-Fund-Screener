"""Reads the latest screener output and delivers only high-signal rows
via Slack webhook and/or email.

The screener pipeline (main.py / profiles/profile_a.py) exports a
"Profile A Selected Flag" column (True for rows ranked in the top_n of
their category) -- there is no "Decision" column in that output (that
name only exists in the separate get_yahoo_dta.py Sharpe/Decision CSV
workflow). Alert-worthy rows here are therefore rows where the profile's
Selected Flag column is True.

Email delivery is enabled by setting SMTP-related environment variables
(see the EMAIL_* variables below). If they are not set, email sending is
skipped and only Slack (or console output) is used, preserving the
original behavior.
"""
import glob
import os
import smtplib
import sys
from email.message import EmailMessage

import pandas as pd
import requests

OUTPUT_DIR = "output"
WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# --- Email configuration (all optional; email is skipped if EMAIL_TO is unset) ---
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USERNAME = os.environ.get("EMAIL_USERNAME")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_FROM = os.environ.get("EMAIL_FROM", EMAIL_USERNAME)
EMAIL_TO = os.environ.get("EMAIL_TO")  # comma-separated list of recipients
EMAIL_SUBJECT = os.environ.get("EMAIL_SUBJECT", "Daily ETF Screener Report")
EMAIL_ATTACH_REPORT = os.environ.get("EMAIL_ATTACH_REPORT", "true").lower() != "false"


def find_latest_file(directory: str, pattern: str) -> str | None:
    files = glob.glob(os.path.join(directory, pattern))
    return max(files, key=os.path.getmtime) if files else None


def build_alert_message(df: pd.DataFrame, selected_flag_col: str) -> tuple[str, pd.DataFrame]:
    hits = df[df[selected_flag_col].fillna(False).astype(bool)]
    if hits.empty:
        return "", hits

    score_col = next((c for c in df.columns if c == "Profile A Score"), None)
    rank_col = next((c for c in df.columns if c == "Profile A Rank In Category"), None)

    lines = []
    for _, row in hits.iterrows():
        ticker = row.get("Ticker", "?")
        category = row.get("Morningstar Category", "Unknown Category")
        score_text = f" | Score: {row[score_col]:.2f}" if score_col and pd.notna(row.get(score_col)) else ""
        rank_text = f" | Rank in Category: {int(row[rank_col])}" if rank_col and pd.notna(row.get(rank_col)) else ""
        lines.append(f"*{ticker}* — Selected ({category}{score_text}{rank_text})")

    message = "\U0001F4C8 *Daily ETF Screener Alerts*\n" + "\n".join(lines[:20])
    return message, hits


def send_slack(message: str) -> None:
    if not WEBHOOK_URL:
        print("No SLACK_WEBHOOK_URL set — skipping Slack alert.")
        return
    resp = requests.post(WEBHOOK_URL, json={"text": message})
    resp.raise_for_status()
    print("Alert sent to Slack.")


def send_email(subject: str, body: str, attachment_path: str | None = None) -> None:
    """Send an email via SMTP. Skips silently if EMAIL_TO is not configured.

    Requires EMAIL_TO plus, for authenticated SMTP servers, EMAIL_USERNAME
    and EMAIL_PASSWORD. EMAIL_FROM defaults to EMAIL_USERNAME if unset.
    """
    if not EMAIL_TO:
        print("No EMAIL_TO set — skipping email delivery.")
        return

    recipients = [addr.strip() for addr in EMAIL_TO.split(",") if addr.strip()]
    if not recipients:
        print("EMAIL_TO is set but contains no valid addresses — skipping email delivery.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    if attachment_path and EMAIL_ATTACH_REPORT and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as f:
            data = f.read()
        filename = os.path.basename(attachment_path)
        msg.add_attachment(
            data,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            if EMAIL_USERNAME and EMAIL_PASSWORD:
                server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to: {', '.join(recipients)}")
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure clearly
        print(f"Failed to send email: {exc}", file=sys.stderr)


def main():
    latest_xlsx = find_latest_file(OUTPUT_DIR, "results_*.xlsx")
    if not latest_xlsx:
        print("No output file found; skipping alerts.")
        return

    df = pd.read_excel(latest_xlsx)
    selected_flag_col = next((c for c in df.columns if c == "Profile A Selected Flag"), None)
    if selected_flag_col is None:
        print("No 'Profile A Selected Flag' column found; skipping alerts.")
        return

    message, hits = build_alert_message(df, selected_flag_col)
    if hits.empty:
        print("No alert-worthy tickers today.")
        message = "No alert-worthy tickers today."

    # Slack: only send when there are actual hits (preserves original behavior).
    if not hits.empty:
        if WEBHOOK_URL:
            send_slack(message)
        else:
            print("No SLACK_WEBHOOK_URL set — printing instead:\n" + message)

    # Email: send a daily report regardless of hits, so it can double as the report delivery.
    email_body = message if message else "No alert-worthy tickers today."
    send_email(EMAIL_SUBJECT, email_body, attachment_path=latest_xlsx)


if __name__ == "__main__":
    main()
