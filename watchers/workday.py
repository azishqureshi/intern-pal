"""Public Workday CXS search and detail endpoints; shared by the bank boards."""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import Counter
from typing import Dict, Tuple
from urllib.parse import unquote, urlparse

import requests

from filtering import classify, extract_term, text
from models import Posting

LOG = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@dataclass(frozen=True)
class Board:
    source: str
    company: str
    tenant: str
    site: str
    facets: Dict = field(default_factory=dict)
    searches: Tuple[str, ...] = ("",)

    @property
    def base(self):
        return f"https://{self.tenant}.wd3.myworkdayjobs.com"

    @property
    def api(self):
        return f"{self.base}/wday/cxs/{self.tenant}/{self.site}"


def from_detail(board, data):
    info = data.get("jobPostingInfo")
    if not isinstance(info, dict) or not info.get("jobReqId"):
        raise ValueError("Workday detail missing jobPostingInfo/jobReqId")
    if info.get("canApply") is False or info.get("posted") is False:
        return None
    if info.get("endDate", "9999")[:10] < datetime.now(timezone.utc).date().isoformat():
        return None
    url = info.get("externalUrl", "")
    if urlparse(url).netloc != urlparse(board.base).netloc or not re.search(r"/(?:job|details)/", url):
        raise ValueError("Workday detail missing official application URL")
    if not re.search(r"_" + re.escape(str(info["jobReqId"])) + r"(?:-\d+)?(?:/apply)?$", unquote(urlparse(url).path).rstrip("/"), re.I):
        raise ValueError("Workday application URL does not match requisition ID")
    locations = [info.get("location", "")]
    for loc in info.get("additionalLocations", []):
        locations.append(loc if isinstance(loc, str) else loc.get("descriptor", ""))
    country = info.get("country", {}).get("descriptor", "")
    if country and not any(country.lower() in loc.lower() or re.search(r"\bCAN\b", loc) for loc in locations):
        locations.append(country)
    desc = info.get("jobDescription", "")
    # Full time describes weekly hours, not whether a job is permanent.
    kind = info.get("workerSubType", "")
    if isinstance(kind, dict):
        kind = kind.get("descriptor", "")
    if not kind:
        kind_match = re.search(r"(?:job type|employment type)\s*:?\s*(student/coop(?: \(fixed term\))?|regular|permanent|temporary(?: \(fixed term\))?)", text(desc))
        if kind_match:
            kind = kind_match[1]
    category = info.get("jobFamily", "") or info.get("jobFamilyGroup", "")
    if isinstance(category, dict):
        category = category.get("descriptor", "")
    title = info.get("title", "")
    return Posting(board.source, board.company, title, "; ".join(filter(None, locations)),
                   None, url, info["jobReqId"], info.get("startDate"), desc,
                   kind or info.get("timeType", ""), category,
                   extract_term(title) or extract_term(desc))


def fetch_board(board, session=None):
    session = session or requests.Session()
    results, seen = [], set()
    rejected = Counter()
    for query in board.searches:
        offset = 0
        query_seen = set()
        for _ in range(100):
            response = session.post(board.api + "/jobs", headers=HEADERS, timeout=25,
                                    json={"appliedFacets": board.facets, "limit": 20,
                                          "offset": offset, "searchText": query})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list) or not isinstance(data.get("total"), int):
                raise ValueError(f"{board.source}: unexpected Workday search schema")
            items = data["jobPostings"]
            if not items and offset < data["total"]:
                raise ValueError(f"{board.source}: incomplete Workday pagination")
            page_paths = set()
            for item in items:
                path = item.get("externalPath", "")
                if not path.startswith("/job/"):
                    raise ValueError(f"{board.source}: missing detail path")
                page_paths.add(path)
                if path in seen:
                    continue
                # Only skip explicitly foreign single-location summaries; full
                # details establish location and student/technical eligibility.
                location = text(item.get("locationsText", ""))
                if re.search(r"\b(?:united states|usa)\b", location) and "canada" not in location:
                    continue
                time.sleep(0.15)
                try:
                    detail = session.get(board.api + path, headers=HEADERS, timeout=25)
                    detail.raise_for_status()
                    posting = from_detail(board, detail.json())
                    if posting:
                        decision = classify(posting)
                        if decision.accepted:
                            results.append(posting)
                        else:
                            rejected[decision.reason] += 1
                except (requests.RequestException, ValueError, TypeError, KeyError):
                    LOG.warning("%s: detail unavailable; skipped %s (scan incomplete)", board.source, path)
            if items and page_paths <= query_seen:
                raise ValueError(f"{board.source}: repeated Workday page")
            query_seen.update(page_paths)
            seen.update(page_paths)
            offset += len(items)
            if offset >= data["total"]:
                break
        else:
            raise ValueError(f"{board.source}: Workday pagination limit exceeded")
    LOG.info("%s: reviewed %d listings; accepted %d; rejection reasons=%s", board.source, len(seen), len(results), dict(rejected))
    return results
