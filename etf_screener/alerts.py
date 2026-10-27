"""Reads the latest screener report and delivers only high-signal rows
via Slack webhook and/or email.

A fund is alerted when EVERY flag in ALERT_FLAGS below is 1 in the newest
results_profile_*.xlsx -- by default, selected in its category AND in the
overall top list by both the long-term (LT) and short-term (ST) profiles.
Edit ALERT_FLAGS to change the condition.

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

from input_file import discover_profiles

# A fund is alerted only when ALL of these report columns are 1 (True).
ALERT_FLAGS = [
    "Profile LT Selected Flag",          # top top_n_per_category of its category (LT)
    "Profile LT Selected Overall Flag",  # top top_n_overall across all funds (LT)
    "Profile ST Selected Flag",          # top top_n_per_category of its category (ST)
    "Profile ST Selected Overall Flag",  # top top_n_overall across all funds (ST)
]
MAX_LINES = 50  # longer lists are cut in the message; the attached report has all

# The report folder comes from the profile YAMLs run_ci.py uses, so the alert
# step looks where the screener wrote its results. OUTPUT_DIR overrides it.
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


def build_alert_message(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Rows where every ALERT_FLAGS column is 1, best LT overall rank first."""
    hits = df
    for col in ALERT_FLAGS:
        hits = hits[hits[col].fillna(False).astype(bool)]
    hits = hits.sort_values("Profile LT Rank Overall")
    if hits.empty:
        return "", hits

    lines = []
    for _, row in hits.head(MAX_LINES).iterrows():
        parts = [f"*{row.get('Ticker', '?')}* {row.get('Name', '')}", str(row.get("Morningstar Category", ""))]
        for key in ("LT", "ST"):
            score, rank = row.get(f"Profile {key} Score"), row.get(f"Profile {key} Rank Overall")
            if pd.notna(score) and pd.notna(rank):
                parts.append(f"{key} {score:.1f} (#{int(rank)} overall)")
        if pd.notna(row.get("Yahoo Fetch Error")) and str(row.get("Yahoo Fetch Error")).strip():
            parts.append("Yahoo data issue")
        lines.append(" | ".join(parts))
    if len(hits) > MAX_LINES:
        lines.append(f"... and {len(hits) - MAX_LINES} more in the attached report")

    header = f"*{len(hits)} fund(s) meet all of: {', '.join(ALERT_FLAGS)}*"
    return header + "\n" + "\n".join(lines), hits


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
    output_dir = os.environ.get("OUTPUT_DIR") or PROFILE_INPUTS[0].out_path
    report = find_latest_file(output_dir, "results_profile_*.xlsx")
    if not report:
        print(f"No results_profile_*.xlsx in {os.path.abspath(output_dir)}; skipping alerts.")
        return

    df = pd.read_excel(report)  # first sheet: the overview
    missing = [c for c in ALERT_FLAGS if c not in df.columns]
    if missing:
        print(f"{os.path.basename(report)} has no {missing} column(s); skipping alerts.")
        return

    message, hits = build_alert_message(df)
    if hits.empty:
        message = "No fund meets all alert conditions today."
        print(message)
    message = "\U0001F4C8 *Daily ETF Screener Alerts*\n\n" + message

    # Slack: only when there are hits.
    if not hits.empty:
        if WEBHOOK_URL:
            send_slack(message)
        else:
            print("No SLACK_WEBHOOK_URL set — printing instead:\n" + message)

    # Email: every day, with the report attached, so it doubles as the report delivery.
    send_email(EMAIL_SUBJECT, message, attachment_paths=[report])


if __name__ == "__main__":
    main()
