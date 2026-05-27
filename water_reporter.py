#!/usr/bin/env python3
import argparse
import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import urlopen
from zoneinfo import ZoneInfo

SOURCE_URL = "https://greybullvalleyid.com/water-orders/"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
MOUNTAIN_TZ = ZoneInfo("America/Denver")


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text: List[str] = []
        self._current_row: List[str] = []
        self._current_table: List[List[str]] = []
        self.tables: List[List[List[str]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_cell and tag in {"td", "th"}:
            self._in_cell = False
            self._current_row.append(_normalize_text("".join(self._cell_text)))
        elif self._in_row and tag == "tr":
            self._in_row = False
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
        elif self._in_table and tag == "table":
            self._in_table = False
            if self._current_table:
                self.tables.append(self._current_table)


def fetch_water_orders_html(url: str = SOURCE_URL, timeout: int = 30) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _extract_rows(html: str) -> List[Dict[str, str]]:
    parser = TableParser()
    parser.feed(html)
    extracted: List[Dict[str, str]] = []
    for table in parser.tables:
        headers = table[0]
        data_rows = table[1:] if len(table) > 1 else []
        if data_rows and len(set(headers)) > 1:
            mapped_headers = [header or f"column_{i + 1}" for i, header in enumerate(headers)]
        else:
            mapped_headers = [f"column_{i + 1}" for i in range(len(headers))]
            data_rows = table

        for row in data_rows:
            row_values = row + [""] * (len(mapped_headers) - len(row))
            extracted.append(
                {mapped_headers[i]: _normalize_text(value) for i, value in enumerate(row_values[: len(mapped_headers)])}
            )
    return extracted


def parse_sandstone_orders(html: str) -> List[Dict[str, str]]:
    rows = _extract_rows(html)
    sandstone_orders = []
    for row in rows:
        if any("sandstone" in value.lower() for value in row.values() if value):
            sandstone_orders.append(row)
    return sandstone_orders


def _extract_member_name(order: Dict[str, str]) -> str:
    preferred_keys = ("name", "member", "customer", "patron", "user")
    for key, value in order.items():
        if any(marker in key.lower() for marker in preferred_keys) and value:
            return value
    for value in order.values():
        if value and "sandstone" not in value.lower():
            return value
    return "Unknown Member"


def save_daily_orders(data_dir: Path, report_date: date, orders: List[Dict[str, str]]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / f"{report_date.isoformat()}.json"
    payload = {
        "date": report_date.isoformat(),
        "source_url": SOURCE_URL,
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
    active_today = sorted({_extract_member_name(order) for order in todays_orders})
    prior_members = sorted({_extract_member_name(order) for order in prior_two_days_orders})
    previous_order_flow = sorted(set(prior_members) - set(active_today))

    lines = [
        f"Sandstone Canal Water Report - {report_date.isoformat()}",
        "",
        "Active water orders today:",
    ]
    lines.extend([f"- {member}" for member in active_today] or ["- None found"])
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


def run_report(report_date: date, data_dir: Path) -> Digest:
    html = fetch_water_orders_html()
    todays_orders = parse_sandstone_orders(html)
    save_daily_orders(data_dir, report_date, todays_orders)

    prior_orders: List[Dict[str, str]] = []
    for offset in (1, 2):
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
    digest = run_report(report_date=report_date, data_dir=Path(args.data_dir))
    print(digest.body)

    if send_digest_email(digest.body):
        print("Digest email sent.")
    else:
        print("Digest email not sent (SMTP_HOST not configured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
