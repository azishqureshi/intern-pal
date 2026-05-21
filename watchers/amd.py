import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from models import Posting
from utils import strip_html_tags

AMD_SEARCH_URL = "https://careers.amd.com/jobs?categories=Student%20%2F%20Intern%20%2F%20Temp&country=Canada"
AMD_FALLBACK_URLS = [
    "https://careers.amd.com/careers-home/jobs?page=1&categories=Student%20%2F%20Intern%20%2F%20Temp&country=Canada",
]
AMD_JINA_PREFIX = "https://r.jina.ai/http://"
AMD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_section(text: str, start_kw: str, end_kw: str) -> str:
    start_idx = text.lower().find(start_kw.lower())
    if start_idx == -1:
        return text
    end_idx = text.lower().find(end_kw.lower(), start_idx)
    if end_idx == -1:
        return text[start_idx:]
    return text[start_idx:end_idx]


def _is_internship_role(title: str, categories: str) -> bool:
    blob = f"{title} {categories}".lower()
    return re.search(r"\bintern\b|internship|\bco[-\s]?op\b|student", blob) is not None


def _fetch_search_text(url: str) -> str:
    r = requests.get(url, headers=AMD_HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ", strip=True)
    return _extract_section(text, "Results", "Not ready to apply")


def _fetch_jina_text(url: str) -> str:
    r = requests.get(f"{AMD_JINA_PREFIX}{url}", headers=AMD_HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_postings_from_text(text: str) -> List[Posting]:
    postings: List[Posting] = []

    pattern_full = re.compile(
        r"(?P<title>.*?)\s+Req ID:\s*(?P<reqid>\d+)\s+Location\s+(?P<location>.*?)\s+Categories\s+(?P<categories>.*?)\s+Apply Now\s*:\s*(?P<title2>.*?)\s+(?=Req ID:|Items per page|$)",
        re.IGNORECASE,
    )
    pattern_simple = re.compile(
        r"\[(?P<title>[^\]]+?)\]\((?P<url>https?://[^)]+)\)\s+Req ID:\s*(?P<reqid>\d+)\s+Location\s+(?P<location>.*?)\s+Categories\s+(?P<categories>.*?)(?=\s+\[|\s+Items per page|$)",
        re.IGNORECASE,
    )

    for m in pattern_full.finditer(text):
        title = m.group("title").strip()
        title2 = m.group("title2").strip()
        reqid = m.group("reqid").strip()
        location = strip_html_tags(m.group("location").strip())
        categories = strip_html_tags(m.group("categories").strip())

        if title2 and title2.lower() not in title.lower():
            title = title2

        if re.search(r"\b(united states|usa)\b", location.lower()):
            continue
        if not _is_internship_role(title, categories):
            continue

        postings.append(
            Posting(
                source="amd",
                company="AMD",
                title=title or "Unknown",
                location=location or "Unknown",
                age=None,
                url=f"https://careers.amd.com/careers-home/jobs/{reqid}?lang=en-us",
                job_id=reqid or None,
                posted_at=None,
            )
        )

    if postings:
        return postings

    for m in pattern_simple.finditer(text):
        title = m.group("title").strip()
        url = m.group("url").strip()
        reqid = m.group("reqid").strip()
        location = strip_html_tags(m.group("location").strip())
        categories = strip_html_tags(m.group("categories").strip())

        if re.search(r"\b(united states|usa)\b", location.lower()):
            continue
        if not _is_internship_role(title, categories):
            continue

        postings.append(
            Posting(
                source="amd",
                company="AMD",
                title=title or "Unknown",
                location=location or "Unknown",
                age=None,
                url=url,
                job_id=reqid or None,
                posted_at=None,
            )
        )

    return postings


def fetch_postings(search_url: str = AMD_SEARCH_URL) -> List[Posting]:
    text = _fetch_search_text(search_url)
    if "Req ID" not in text:
        for fallback_url in AMD_FALLBACK_URLS:
            text = _fetch_search_text(fallback_url)
            if "Req ID" in text:
                print(f"amd: using fallback url={fallback_url}")
                break

    if "Req ID" not in text:
        print("amd: primary fetch missing listings, trying jina.ai")
        text = _fetch_jina_text(search_url)

    text = _normalize_text(text)
    print(f"amd: text length={len(text)}")
    if text:
        print(f"amd: text sample={text[:200]}")
    postings = _parse_postings_from_text(text)
    print(f"amd: filtered postings={len(postings)}")
    return postings
