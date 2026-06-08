#!/usr/bin/env python3
import argparse
import io
import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import fitz  # pymupdf

PDF_BASE_URL = "https://greybullvalleyid.com/wp-content/uploads"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
MOUNTAIN_TZ = ZoneInfo("America/Denver")
CARRYOVER_LOOKBACK_DAYS = 2


def build_pdf_url(report_date: date) -> str:
    return (
        f"{PDF_BASE_URL}/{report_date.year}/{report_date.month:02d}"
        f"/{report_date.month}-{report_date.day}.pdf"
    )


def fetch_pdf_bytes(url: str, timeout: int = 30) -> Optional[bytes]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f"Unable to fetch report PDF from {url}: HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"Unable to fetch report PDF from {url}: {error}") from error


def extract_pdf_text(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


def parse_sandstone_orders(text: str) -> List[Dict[str, str]]:
    # pymupdf extracts each table cell on its own line; within the Sandstone*
    # lateral section the pattern is: *Sandstone / acct_num / name / cfs
    section_match = re.search(r"Sandstone\*\n(.*?)Total Cfs \(Sandstone\)", text, re.DOTALL)
    if not section_match:
        return []

    lines = [l.strip() for l in section_match.group(1).splitlines() if l.strip()]
    orders = []
    i = 0
    while i < len(lines):
        if re.match(r"^\*?Sandstone", lines[i], re.IGNORECASE):
            if (
                i + 3 < len(lines)
                and re.match(r"^\d+$", lines[i + 1])
                and re.match(r"^[\d.]+$", lines[i + 3])
            ):
                orders.append({
                    "acct_num": lines[i + 1],
                    "ditch_gate": "Sandstone",
                    "name": lines[i + 2],
                    "cfs": lines[i + 3],
                })
                i += 4
                continue
        i += 1
    return orders


def save_daily_orders(data_dir: Path, report_date: date, orders: List[Dict[str, str]], source_url: str) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / f"{report_date.isoformat()}.json"
    payload = {
        "date": report_date.isoformat(),
        "source_url": source_url,
        "sandstone_orders": orders,
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_daily_orders(data_dir: Path, report_date: date) -> List[Dict[str, str]]:
    target = data_dir / f"{report_date.isoformat()}.json"
    if not target.exists():
        return []
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload.get("sandstone_orders", [])


@dataclass
class Digest:
    active_today: List[str]
    previous_order_flow: List[str]
    body: str


def build_digest(report_date: date, todays_orders: List[Dict[str, str]], prior_two_days_orders: List[Dict[str, str]]) -> Digest:
    active_today = sorted({o["name"] for o in todays_orders})
    prior_members = sorted({o["name"] for o in prior_two_days_orders})
    previous_order_flow = sorted(set(prior_members) - set(active_today))

    today_by_name = {o["name"]: o for o in todays_orders}

    lines = [
        f"Sandstone Canal Water Report - {report_date.isoformat()}",
        "",
        "Active water orders today:",
    ]
    lines.extend(
        [f"- {name} ({today_by_name[name]['cfs']} cfs)" for name in active_today]
        or ["- None found"]
    )
    lines.extend(["", "Still receiving water from orders placed in the previous two days:"])
    lines.extend([f"- {member}" for member in previous_order_flow] or ["- None identified"])

    return Digest(active_today=active_today, previous_order_flow=previous_order_flow, body="\n".join(lines))


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, default)
    if value is None:
        return None
    return value.strip() or None


def send_digest_email(digest_text: str) -> bool:
    smtp_host = _env("SMTP_HOST")
    if not smtp_host:
        return False

    smtp_port = int(_env("SMTP_PORT", "587") or "587")
    smtp_user = _env("SMTP_USERNAME")
    smtp_password = _env("SMTP_PASSWORD")
    from_addr = _env("EMAIL_FROM", smtp_user or "noreply@example.com")
    to_addr = _env("EMAIL_TO", "info@heritageharvestranch.com")

    message = EmailMessage()
    message["Subject"] = "Sandstone Canal Daily Water Digest"
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(digest_text)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(context=context)
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(message)
    return True


def run_report(report_date: date, data_dir: Path) -> Optional[Digest]:
    url = build_pdf_url(report_date)
    pdf_bytes = fetch_pdf_bytes(url)
    if pdf_bytes is None:
        return None

    text = extract_pdf_text(pdf_bytes)
    todays_orders = parse_sandstone_orders(text)
    save_daily_orders(data_dir, report_date, todays_orders, url)

    prior_orders: List[Dict[str, str]] = []
    for offset in range(1, CARRYOVER_LOOKBACK_DAYS + 1):
        prior_orders.extend(load_daily_orders(data_dir, report_date - timedelta(days=offset)))

    return build_digest(report_date, todays_orders, prior_orders)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily Sandstone canal water order digest")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format. Defaults to current Mountain date.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory where daily JSON files are stored.")
    parser.add_argument(
        "--enforce-mountain-9am",
        action="store_true",
        help="Exit successfully unless current America/Denver local hour is 9.",
    )
    args = parser.parse_args()

    now_mt = datetime.now(MOUNTAIN_TZ)
    if args.enforce_mountain_9am and now_mt.hour != 9:
        print(f"Skipping run at {now_mt.isoformat()} (not 9am Mountain Time).")
        return 0

    report_date = date.fromisoformat(args.date) if args.date else now_mt.date()

    if report_date.weekday() == 6:
        print(f"Skipping {report_date.isoformat()} — no report published on Sundays.")
        return 0

    digest = run_report(report_date=report_date, data_dir=Path(args.data_dir))
    if digest is None:
        print(f"No report available for {report_date.isoformat()} (PDF not found).")
        return 0

    print(digest.body)

    if send_digest_email(digest.body):
        print("Digest email sent.")
    else:
        print("Digest email not sent (SMTP_HOST not configured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
