"""Reads the latest screener output and delivers only high-signal rows
via Slack webhook and/or email.

The screener pipeline (main.py / profiles/weighted_profile.py) exports a
"Profile <key> Selected Flag" column per profile, e.g. "Profile LT
Selected Flag" (True for rows ranked in the top_n of their category) -- there is no "Decision" column in that output (that
name only exists in the separate standalone_utils/get_yahoo_dta.py Sharpe/Decision CSV
workflow). Alert-worthy rows here are therefore rows where the profile's
Selected Flag column is True. Every enabled input_files/profile_*.yaml
gets its own section, from the newest report that has its columns
(normally one combined results_profile_LT_ST_... file).

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
from pathlib import Path

import pandas as pd
import requests

from input_file import discover_profiles

# Read each profile's output folder from the same YAMLs run_ci.py uses, so
# the alert step always looks where the screener actually wrote its results.
# Set OUTPUT_DIR in the environment to override.
PROFILE_INPUTS = discover_profiles()
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


def build_alert_message(df: pd.DataFrame, profile_name: str) -> tuple[str, pd.DataFrame]:
    selected_flag_col = f"Profile {profile_name} Selected Flag"
    hits = df[df[selected_flag_col].fillna(False).astype(bool)]
    if hits.empty:
        return "", hits

    score_col = next((c for c in df.columns if c == f"Profile {profile_name} Score"), None)
    rank_col = next((c for c in df.columns if c == f"Profile {profile_name} Rank In Category"), None)

    lines = []
    yahoo_issue_hits = 0
    for _, row in hits.iterrows():
        ticker = row.get("Ticker", "?")
        category = row.get("Morningstar Category", "Unknown Category")
        score_text = f" | Score: {row[score_col]:.2f}" if score_col and pd.notna(row.get(score_col)) else ""
        rank_text = f" | Rank in Category: {int(row[rank_col])}" if rank_col and pd.notna(row.get(rank_col)) else ""
        yahoo_note = ""
        if pd.notna(row.get("Yahoo_Fetch_Error")) and str(row.get("Yahoo_Fetch_Error")).strip():
            yahoo_issue_hits += 1
            yahoo_note = " | Yahoo data issue logged"
        lines.append(f"*{ticker}* — Selected ({category}{score_text}{rank_text}{yahoo_note})")

    header = f"*Profile {profile_name}*"
    if yahoo_issue_hits:
        header += f"\n\u26A0\uFE0F Yahoo data issues flagged on {yahoo_issue_hits} selected row(s)."
    message = header + "\n" + "\n".join(lines[:20])
    return message, hits


def send_slack(message: str) -> None:
    if not WEBHOOK_URL:
        print("No SLACK_WEBHOOK_URL set — skipping Slack alert.")
        return
    resp = requests.post(WEBHOOK_URL, json={"text": message})
    resp.raise_for_status()
    print("Alert sent to Slack.")


def send_email(subject: str, body: str, attachment_paths: list[str] | None = None) -> None:
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

    for attachment_path in attachment_paths or []:
        if not (EMAIL_ATTACH_REPORT and os.path.isfile(attachment_path)):
            continue
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
    sections = []
    reports = []
    any_hits = False
    for profile_input in PROFILE_INPUTS:
        profile_name = profile_input.profile_name
        output_dir = os.environ.get("OUTPUT_DIR") or profile_input.out_path
        # Matches the combined report (results_profile_LT_ST_...) and older
        # single-profile ones (results_profile_ST_...).
        latest_xlsx = find_latest_file(output_dir, f"results_profile_*{profile_name}_*.xlsx")
        if not latest_xlsx:
            print(f"No Profile {profile_name} report found in {os.path.abspath(output_dir)}; skipping it.")
            continue
        if latest_xlsx not in reports:  # one combined file serves every profile
            reports.append(latest_xlsx)

        df = pd.read_excel(latest_xlsx)
        if f"Profile {profile_name} Selected Flag" not in df.columns:
            print(f"No 'Profile {profile_name} Selected Flag' column in {latest_xlsx}; skipping it.")
            continue

        message, hits = build_alert_message(df, profile_name)
        if hits.empty:
            message = f"*Profile {profile_name}*\nNo alert-worthy tickers today."
        else:
            any_hits = True
        sections.append(message)

    if not reports:
        print("No profile reports found; skipping alerts.")
        return

    message = "\U0001F4C8 *Daily ETF Screener Alerts*\n\n" + "\n\n".join(sections)
    if not any_hits:
        print("No alert-worthy tickers today.")

    # Slack: only send when there are actual hits (preserves original behavior).
    if any_hits:
        if WEBHOOK_URL:
            send_slack(message)
        else:
            print("No SLACK_WEBHOOK_URL set — printing instead:\n" + message)

    # Email: send a daily report regardless of hits, so it can double as the report delivery.
    send_email(EMAIL_SUBJECT, message, attachment_paths=reports)


if __name__ == "__main__":
    main()
