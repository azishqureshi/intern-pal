import re
from typing import Dict, List, Optional

import requests

from models import Posting
from utils import strip_html_tags

CIBC_BASE_URL = "https://cibc.wd3.myworkdayjobs.com"
CIBC_SITE = "campus"
CIBC_TENANT = "cibc"
CIBC_SEARCH_URL = (
    "https://cibc.wd3.myworkdayjobs.com/en-US/campus"
    "?jobFamilyGroup=4bbe6c74e8a7013edb3931a881012710"
    "&Country=a30a87ed25634629aa6c3958aa2b91ea"
)
CIBC_API_URL = f"{CIBC_BASE_URL}/wday/cxs/{CIBC_TENANT}/{CIBC_SITE}/jobs"
CIBC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}


def _is_internship_role(title: str, categories: str) -> bool:
    blob = f"{title} {categories}".lower()
    return re.search(r"\bintern\b|internship|\bco[-\s]?op\b|student", blob) is not None


def _extract_location(posting: Dict) -> str:
    locations_text = posting.get("locationsText")
    if isinstance(locations_text, str) and locations_text.strip():
        return locations_text.strip()

    locations = posting.get("locations")
    if isinstance(locations, list):
        cleaned = [strip_html_tags(str(loc)) for loc in locations if str(loc).strip()]
        if cleaned:
            return ", ".join(cleaned)

    location = posting.get("location")
    if isinstance(location, str):
        return location.strip()

    return ""


def _build_posting_url(posting: Dict) -> Optional[str]:
    external_path = posting.get("externalPath")
    if isinstance(external_path, str) and external_path.strip():
        path = external_path.strip()
        if path.startswith("/en-US/"):
            return f"{CIBC_BASE_URL}{path}"
        if path.startswith("/job/"):
            slug = path.rsplit("/", 1)[-1]
            return f"{CIBC_BASE_URL}/en-US/{CIBC_SITE}/details/{slug}"
        if path.startswith("/details/"):
            return f"{CIBC_BASE_URL}/en-US/{CIBC_SITE}{path}"
        if path.startswith("/"):
            return f"{CIBC_BASE_URL}{path}"
        return path

    return None


def _fetch_page(offset: int, limit: int) -> Dict:
    params = {
        "offset": offset,
        "limit": limit,
    }
    r = requests.get(CIBC_API_URL, headers=CIBC_HEADERS, params=params, timeout=20)
    if r.status_code != 400:
        r.raise_for_status()
        return r.json()

    payload = {
        "appliedFacets": {
            "jobFamilyGroup": ["4bbe6c74e8a7013edb3931a881012710"],
            "country": ["a30a87ed25634629aa6c3958aa2b91ea"],
        },
        "offset": offset,
        "limit": limit,
    }
    r = requests.post(CIBC_API_URL, headers=CIBC_HEADERS, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_postings() -> List[Posting]:
    postings: List[Posting] = []
    offset = 0
    limit = 20
    total = None
    max_pages = 50
    pages = 0

    while pages < max_pages:
        data = _fetch_page(offset, limit)
        if total is None:
            total = data.get("total") if isinstance(data, dict) else None
        raw_postings = data.get("jobPostings", []) if isinstance(data, dict) else []
        if not isinstance(raw_postings, list) or not raw_postings:
            break

        for item in raw_postings:
            if not isinstance(item, dict):
                continue

            title = strip_html_tags(str(item.get("title", ""))).strip()
            categories = strip_html_tags(str(item.get("jobFamily", ""))).strip()
            location = _extract_location(item)
            job_id = str(item.get("jobRequisitionId") or item.get("id") or "").strip() or None
            url = _build_posting_url(item)

            if not _is_internship_role(title, categories):
                continue

            postings.append(
                Posting(
                    source="cibc",
                    company="CIBC",
                    title=title or "Unknown",
                    location=location or "Unknown",
                    age=None,
                    url=url,
                    job_id=job_id,
                    posted_at=None,
                )
            )

        offset += limit
        pages += 1
        if total is not None and offset >= int(total):
            break

    print(f"cibc: total postings={len(postings)}")
    return postings
