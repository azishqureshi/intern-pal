import json
import os
import re
import html as html_module
from typing import Dict, Iterable, Optional, Set

import requests
from bs4 import BeautifulSoup

from models import Posting


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


def is_age_zero(age_text: Optional[str]) -> bool:
    if not age_text:
        return False
    return re.search(r"\b0\s*d\b|\b0\s*days?\b", age_text.lower()) is not None


def make_dedupe_key(posting: Posting) -> str:
    if posting.job_id:
        return normalize_url(posting.job_id)
    if posting.url:
        return normalize_url(posting.url)
    fallback = f"{posting.company}|{posting.title}|{posting.location}"
    return normalize_url(fallback)


def load_state(path: str) -> Dict[str, Set[str]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        state: Dict[str, Set[str]] = {}
        for channel, items in raw.items():
            if isinstance(items, list):
                state[channel] = set(normalize_url(x) for x in items if isinstance(x, str))
        return state
    except Exception:
        return {}


def save_state(state: Dict[str, Iterable[str]], path: str) -> None:
    normalized = {
        channel: sorted(normalize_url(x) for x in items)
        for channel, items in state.items()
    }
    with open(path, "w") as f:
        json.dump(normalized, f, indent=2)


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
    r = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
    r.raise_for_status()
