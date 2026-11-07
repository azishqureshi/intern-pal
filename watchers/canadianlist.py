"""Read the complete Canadian Internship List across all terms and disciplines.

Like SimplifyJobs, this is a curated list, not an employer-detail adapter.
Posting dates are metadata, never an age cutoff for this source.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import logging
import re
from urllib.parse import urljoin, urlsplit

import requests

from filtering import canadian_location, extract_term
from models import Posting
from tracking import canonical_url
from utils import strip_html_tags
from watchers.simplifyjobs import extract_link_from_cell

README_URL = "https://raw.githubusercontent.com/Bobwillrule/Canadian-Internship-List/main/README.md"
HEADERS = ("company", "role", "location", "apply", "posted")
SHORT_HOST = "go.vansh.nyc"
LOG = logging.getLogger(__name__)


def _cells(line):
    return [value.strip().replace(r"\|", "|")
            for value in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _plain(value):
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    return strip_html_tags(value).strip().strip("*").strip()


def parse_readme(markdown):
    lines = markdown.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.lstrip().startswith("|")
                  and tuple(_plain(cell).lower() for cell in _cells(line)) == HEADERS), None)
    if start is None or start + 1 >= len(lines):
        raise ValueError("Canadian Internship List table/header missing")
    separator = _cells(lines[start + 1])
    if len(separator) != len(HEADERS) or not all(re.fullmatch(r":?-{3,}:?", c) for c in separator):
        raise ValueError("Canadian Internship List table separator changed")

    postings, previous_company, rows = [], None, 0
    for line in lines[start + 2:]:
        if not line.strip():
            break
        if not line.lstrip().startswith("|") or not line.rstrip().endswith("|"):
            raise ValueError("Canadian Internship List table is truncated or malformed")
        cells = _cells(line)
        if len(cells) != len(HEADERS):
            raise ValueError("Canadian Internship List row has unexpected columns")
        rows += 1
        company, title, location, application, posted = cells
        company, title, location = [_plain(v) for v in (company, title, location)]
        if company == "↳":
            if not previous_company:
                raise ValueError("Canadian Internship List continuation has no company")
            company = previous_company
        elif company:
            previous_company = company
        else:
            raise ValueError("Canadian Internship List company missing")
        if not title or not location:
            raise ValueError("Canadian Internship List title/location missing")
        # Resolve company inheritance before skipping a closed/foreign parent.
        if "🔒" in application or re.search(r"\bclosed\b", _plain(application), re.I):
            continue
        url = extract_link_from_cell(application)
        if not url or not canadian_location(location):
            continue
        posted = _plain(posted)
        posted_at = None
        if posted not in ("", "—", "-"):
            try:
                posted_at = datetime.strptime(posted, "%b %d, %Y").date().isoformat()
            except ValueError:
                LOG.warning("canadianlist: unrecognized posting date %r", posted)
        postings.append(Posting("canadianlist", company, title, location, None,
                                canonical_url(url), None, posted_at,
                                term=extract_term(title)))
    if not rows:
        raise ValueError("Canadian Internship List table unexpectedly empty")
    return postings


def _resolve_application(url):
    """Follow only the shortener, without fetching hundreds of employer pages."""
    try:
        seen = set()
        while urlsplit(url).hostname == SHORT_HOST:
            if url in seen or len(seen) >= 5:
                raise ValueError("Short application link has a redirect loop")
            seen.add(url)
            response = requests.head(url, allow_redirects=False, timeout=10)
            try:
                if response.status_code in (404, 410):
                    return None
                response.raise_for_status()
                location = response.headers.get("Location")
                if response.status_code not in (301, 302, 303, 307, 308) or not location:
                    raise ValueError("Short application link has no redirect")
                url = urljoin(url, location)
            finally:
                response.close()
            if urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("Application redirect is not an HTTP URL")
        return canonical_url(url) or None
    except ValueError:
        return None


def fetch_postings(session=None):
    session = session or requests.Session()
    response = session.get(README_URL, timeout=20)
    response.raise_for_status()
    postings = parse_readme(response.text)
    urls = list(dict.fromkeys(p.url for p in postings))
    # Bounded parallelism keeps redirect resolution within the workflow timeout.
    with ThreadPoolExecutor(max_workers=4) as executor:
        resolved = dict(zip(urls, executor.map(_resolve_application, urls)))
    missing = sum(not resolved[p.url] for p in postings)
    if missing:
        LOG.warning("canadianlist: %d expired or invalid application links skipped", missing)
    results, seen = [], set()
    for posting in postings:
        url = resolved[posting.url]
        key = (posting.company, url)
        if url and key not in seen:
            results.append(replace(posting, url=url))
            seen.add(key)
    LOG.info("canadianlist: read %d Canadian linked entries; returned %d across all terms",
             len(postings), len(results))
    return results
