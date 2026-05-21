import re
from typing import List

import requests
from bs4 import BeautifulSoup

from models import Posting
from utils import location_is_canada, strip_html_tags

AMD_SEARCH_URL = "https://careers.amd.com/careers-home/jobs?page=1&categories=Student%20%2F%20Intern%20%2F%20Temp"


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


def fetch_postings(search_url: str = AMD_SEARCH_URL) -> List[Posting]:
    r = requests.get(search_url, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ", strip=True)
    text = _extract_section(text, "Results", "Not ready to apply")
    print(f"amd: text length={len(text)}")
    if text:
        print(f"amd: text sample={text[:200]}")

    pattern = re.compile(
        r"(?P<title>.*?)\s+Req ID:\s*(?P<reqid>\d+)\s+Location\s+(?P<location>.*?)\s+Categories\s+(?P<categories>.*?)\s+Apply Now\s*:\s*(?P<title2>.*?)\s+(?=Req ID:|Items per page|$)",
        re.IGNORECASE,
    )

    postings: List[Posting] = []
    match_count = 0
    for m in pattern.finditer(text):
        match_count += 1
        title = m.group("title").strip()
        title2 = m.group("title2").strip()
        reqid = m.group("reqid").strip()
        location = strip_html_tags(m.group("location").strip())
        categories = strip_html_tags(m.group("categories").strip())

        if title2 and title2.lower() not in title.lower():
            title = title2

        if not location_is_canada(location):
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
                url=f"https://careers.amd.com/jobs/{reqid}",
                job_id=reqid or None,
                posted_at=None,
            )
        )

    print(f"amd: regex matches={match_count} filtered postings={len(postings)}")
    return postings
