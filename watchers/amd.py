"""Canadian student openings from the public AMD careers search feed."""
import re

import requests

from models import Posting


API = "https://careers.amd.com/api/jobs"
STUDENT = re.compile(r"\bintern\b|internship|\bco[-\s]?op\b|student", re.I)


def fetch_postings(session=None):
    session = session or requests.Session()
    postings = []
    seen = set()
    for page in range(1, 101):
        response = session.get(API, params={"country": "Canada", "limit": 100, "page": page}, timeout=25)
        response.raise_for_status()
        data = response.json()
        rows, total = data["jobs"], data["totalCount"]
        if not isinstance(rows, list) or not isinstance(total, int) or total < 0:
            raise ValueError("AMD search schema changed")
        previous_count = len(seen)
        for row in rows:
            job = row["data"]
            req = str(job["req_id"])
            if not req.isdigit() or job["country"] != "Canada":
                raise ValueError("AMD returned an unexpected requisition or country")
            if req in seen:
                continue
            seen.add(req)
            categories = " ".join(category["name"] for category in job["categories"])
            if job.get("applyable") is False or not STUDENT.search(f"{job['title']} {categories}"):
                continue
            postings.append(Posting("amd", "AMD", job["title"], job["full_location"], None,
                                    f"https://careers.amd.com/careers-home/jobs/{req}?lang=en-us",
                                    req, job.get("posted_date")))
        if len(seen) >= total:
            print(f"amd: reviewed {len(seen)} Canadian requisitions")
            return postings
        if len(seen) == previous_count:
            raise ValueError("AMD incomplete search results")
    raise ValueError("AMD pagination limit exceeded")
