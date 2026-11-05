import re
import html as html_module
from typing import Optional

import requests
from bs4 import BeautifulSoup


def strip_html_tags(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return BeautifulSoup(text, "lxml").get_text(strip=True)


def normalize_url(url: str) -> str:
    if not isinstance(url, str):
        return ""
    return html_module.unescape(url).strip()


def location_is_canada(location_text: str) -> bool:
    if not location_text:
        return False
    return "canada" in strip_html_tags(location_text).lower()


def location_is_canada_amd(location_text: str) -> bool:
    if not location_text:
        return False
    cleaned = strip_html_tags(location_text).lower()
    if "canada" in cleaned:
        return True
    # AMD uses CA,<province> codes for Canada locations (e.g., CA,ON,...)
    return re.search(r"\bca,(on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)\b", cleaned) is not None


def location_is_canada_cibc(location_text: str) -> bool:
    if not location_text:
        return False
    cleaned = strip_html_tags(location_text).lower()
    if "canada" in cleaned:
        return True
    if re.search(r"\bca[-,\s](on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)\b", cleaned):
        return True
    if re.search(r"(?:,|\()\s*(on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)\s*(?:\)|,|$)", cleaned):
        return True
    if re.search(
        r"\b(ontario|quebec|british columbia|alberta|manitoba|new brunswick|newfoundland|nova scotia|"
        r"northwest territories|nunavut|prince edward island|saskatchewan|yukon)\b",
        cleaned,
    ):
        return True
    return False


def is_age_zero(age_text: Optional[str]) -> bool:
    if not age_text:
        return False
    return re.search(r"\b0\s*d\b|\b0\s*days?\b", age_text.lower()) is not None


def parse_age_days(age_text: Optional[str]) -> Optional[int]:
    if not age_text:
        return None
    m = re.search(r"\b(\d+)\s*d\b|\b(\d+)\s*days?\b", age_text.lower())
    if not m:
        return None
    value = m.group(1) or m.group(2)
    try:
        return int(value)
    except ValueError:
        return None


def is_age_within_days(age_text: Optional[str], max_days: int) -> bool:
    age_days = parse_age_days(age_text)
    if age_days is None:
        return False
    return age_days <= max_days


def send_discord_webhook(
    webhook_url: str,
    title: str,
    description: str,
    url: Optional[str],
    fields: list,
) -> None:
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "url": url or None,
                "fields": fields,
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post(webhook_url, params={"wait": "true"}, json=payload, headers=headers, timeout=10)
    r.raise_for_status()
