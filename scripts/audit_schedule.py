#!/usr/bin/env python3
"""Read-only cadence evidence. Never dispatches workflows or sends notifications."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import median
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result


def summarize(runs, start, end, source):
    event = "schedule" if source == "native" else "workflow_dispatch"
    selected = sorted((r for r in runs if r["event"] == event
                       and r.get("run_attempt", 1) == 1
                       and start <= timestamp(r["created_at"]) < end
                       and (source == "native" or r.get("display_title", "").endswith(
                           " | external-scheduler"))), key=lambda r: r["created_at"])
    points = [timestamp(r["created_at"]) for r in selected]
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(points, points[1:])]
    # Include the edges: no runs or an outage at the end must not look healthy.
    boundaries = [start, *points, end]
    return {
        "source": source, "window_start": start.isoformat(), "window_end": end.isoformat(),
        "runs": len(selected), "conclusions": dict(Counter(r["conclusion"] for r in selected)),
        "median_gap_minutes": median(gaps) if gaps else None,
        "largest_uncovered_minutes": max((b-a).total_seconds()/60
                                         for a, b in zip(boundaries, boundaries[1:])),
        "run_ids": [r["id"] for r in selected],
        "note": "Compare external runs with scheduler execution history; labels alone do not prove automatic origin."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=timestamp)
    parser.add_argument("--until", type=timestamp, default=datetime.now(timezone.utc))
    parser.add_argument("--source", choices=["native", "external"], default="native")
    parser.add_argument("--runs-json", type=Path, help="Offline API response or list; must cover the whole window")
    args = parser.parse_args()
    if args.until <= args.since:
        parser.error("--until must be later than --since")
    if args.runs_json:
        data = json.loads(args.runs_json.read_text())
        runs = data["workflow_runs"] if isinstance(data, dict) else data
    else:
        runs = []
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "intern-pal-schedule-audit"}
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        for page in range(1, 11):
            query = urlencode({"per_page": 100, "page": page,
                               "created": args.since.isoformat() + ".." + args.until.isoformat()})
            url = "https://api.github.com/repos/azishqureshi/intern-pal/actions/workflows/main.yml/runs?" + query
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                data = json.load(response)
            if data["total_count"] >= 1000:
                raise SystemExit("API window reaches the 1,000-result limit; use a shorter window")
            runs.extend(data["workflow_runs"])
            if len(runs) >= data["total_count"] or not data["workflow_runs"]:
                break
    print(json.dumps(summarize(runs, args.since, args.until, args.source), indent=2))


if __name__ == "__main__":
    main()
