import os
from typing import Dict, List

from models import Posting
from utils import (
    is_age_within_days,
    load_state,
    location_is_canada,
    make_dedupe_key,
    save_state,
    send_discord_webhook,
)
from watchers import amd, simplifyjobs

STATE_FILE = "state.json"

WATCHERS = {
    "simplifyjobs": simplifyjobs.fetch_postings,
    "amd": amd.fetch_postings,
}

CHANNELS = [
    {
        "name": "general",
        "webhook_env": "DISCORD_WEBHOOK_GENERAL",
        "sources": None,
        "company_filters": None,
        "max_age_days_env": "MAX_AGE_DAYS_GENERAL",
        "max_age_days_default": 0,
    },
    {
        "name": "amd",
        "webhook_env": "DISCORD_WEBHOOK_AMD",
        "sources": ["amd"],
        "company_filters": ["AMD", "Advanced Micro Devices"],
    },
]


def _company_matches(company: str, filters: List[str]) -> bool:
    company_lower = (company or "").lower()
    return any(f.lower() in company_lower for f in filters)


def _get_max_age_days(channel: Dict) -> Optional[int]:
    env_name = channel.get("max_age_days_env")
    if not env_name:
        return channel.get("max_age_days")
    raw = os.getenv(env_name, "")
    if raw == "":
        return channel.get("max_age_days_default")
    try:
        return int(raw)
    except ValueError:
        return channel.get("max_age_days_default")


def _posting_matches_channel(posting: Posting, channel: Dict) -> bool:
    sources = channel.get("sources")
    if sources and posting.source not in sources:
        return False

    if not location_is_canada(posting.location):
        return False

    company_filters = channel.get("company_filters")
    if company_filters and not _company_matches(posting.company, company_filters):
        return False

    max_age_days = _get_max_age_days(channel)
    if max_age_days is not None and posting.age is not None:
        if not is_age_within_days(posting.age, max_age_days):
            return False

    return True


def _build_fields(posting: Posting) -> List[Dict[str, str]]:
    fields = [
        {"name": "Company", "value": posting.company or "—", "inline": True},
        {"name": "Role", "value": posting.title or "—", "inline": True},
        {"name": "Location", "value": posting.location or "—", "inline": True},
        {"name": "Source", "value": posting.source or "—", "inline": True},
    ]

    if posting.age:
        fields.append({"name": "Age", "value": posting.age or "—", "inline": True})
    if posting.job_id:
        fields.append({"name": "Job ID", "value": posting.job_id or "—", "inline": True})

    return fields


def _send_posting(posting: Posting, webhook_url: str) -> None:
    title = f"New Canada Internship — {posting.company or 'Unknown'}"
    description = f"[View posting]({posting.url})" if posting.url else "Posting link not found."
    fields = _build_fields(posting)
    send_discord_webhook(webhook_url, title=title, description=description, url=posting.url, fields=fields)


def run_all_watchers() -> List[Posting]:
    postings: List[Posting] = []
    for name, fetcher in WATCHERS.items():
        try:
            watcher_postings = fetcher()
            postings.extend(watcher_postings)
            print(f"{name}: {len(watcher_postings)} postings")
        except Exception as e:
            print(f"{name}: failed to fetch postings: {e}")
    return postings


def main() -> None:
    state = load_state(STATE_FILE)
    all_postings = run_all_watchers()

    for channel in CHANNELS:
        channel_name = channel["name"]
        webhook_env = channel["webhook_env"]
        webhook_url = os.getenv(webhook_env)
        if not webhook_url:
            print(f"{channel_name}: missing {webhook_env}, skipping")
            continue

        channel_state = state.get(channel_name, set())

        for posting in all_postings:
            if not _posting_matches_channel(posting, channel):
                continue

            key = make_dedupe_key(posting)
            if key in channel_state:
                continue

            try:
                _send_posting(posting, webhook_url)
                channel_state.add(key)
                state[channel_name] = channel_state
                save_state(state, STATE_FILE)
                print(f"{channel_name}: sent {posting.company} - {posting.title}")
            except Exception as e:
                print(f"{channel_name}: failed to send {posting.company} - {posting.title}: {e}")


if __name__ == "__main__":
    main()
