import os
import logging
import requests
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from models import Posting
from filtering import canadian_location, classify
from tracking import Ledger, state_lock
from utils import (
    is_age_within_days,
    location_is_canada,
    location_is_canada_amd,
    send_discord_webhook,
)
from watchers import amd, amazon, banks, canadianlist, cibc, google, internlist, scotiabank, shopify, simplifyjobs

STATE_FILE = "state.json"

WATCHERS = {
    "simplifyjobs": simplifyjobs.fetch_postings,
    "amd": amd.fetch_postings,
    "cibc": cibc.fetch_postings,
    "rbc": banks.fetch_rbc,
    "bmo": banks.fetch_bmo,
    "td": banks.fetch_td,
    "scotiabank": scotiabank.fetch_postings,
    "shopify": shopify.fetch_postings,
    "google": google.fetch_postings,
    "amazon": amazon.fetch_postings,
    "canadianlist": canadianlist.fetch_postings,
    "internlist": internlist.fetch_postings,
}

# Curated lists provide summary rows; full-description checks apply to employer
# adapters. AMD retains its original source-specific checks.
CURATED_SOURCES = {"simplifyjobs", "canadianlist", "internlist"}

CHANNELS = [
    {
        "name": "general",
        "webhook_env": "DISCORD_WEBHOOK_GENERAL",
        "sources": None,
        "company_filters": None,
        "max_age_days_env": "MAX_AGE_DAYS_GENERAL",
        "max_age_days_default": 0,
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
    if posting.source == 'internlist' and not internlist.is_recent(posting):
        return False
    sources = channel.get("sources")
    if sources and posting.source not in sources:
        return False

    if posting.source == "amd":
        if not location_is_canada_amd(posting.location):
            return False
    elif posting.source == "simplifyjobs":
        if not location_is_canada(posting.location):
            return False
    elif not canadian_location(posting.location, posting.description):
        return False

    company_filters = channel.get("company_filters")
    if company_filters and not _company_matches(posting.company, company_filters):
        return False

    max_age_days = _get_max_age_days(channel)
    if posting.source == 'canadianlist' and not canadianlist.is_recent(posting, max_age_days):
        return False
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

    if posting.term:
        fields.append({"name": "Term", "value": posting.term, "inline": True})
    if posting.age:
        fields.append({"name": "Age", "value": posting.age or "—", "inline": True})
    if posting.source == 'internlist' and posting.posted_at:
        fields.append({"name": "Posted (UTC)", "value": posting.posted_at, "inline": True})
    if posting.source == 'canadianlist' and posting.posted_at:
        fields.append({"name": "Posted (source date)", "value": posting.posted_at, "inline": True})
    if posting.job_id:
        fields.append({"name": "Job ID", "value": posting.job_id or "—", "inline": True})

    return fields


def _send_posting(posting: Posting, webhook_url: str) -> None:
    title = f"New Internship: {posting.company or 'Unknown'}"
    description = f"[View posting]({posting.url})" if posting.url else "Posting link not found."
    fields = _build_fields(posting)
    send_discord_webhook(webhook_url, title=title, description=description, url=posting.url, fields=fields)


def run_all_watchers(failures=None, rate_limited=None) -> List[Posting]:
    postings: List[Posting] = []
    for name, fetcher in WATCHERS.items():
        try:
            watcher_postings = fetcher()
            postings.extend(watcher_postings)
            print(f"{name}: {len(watcher_postings)} postings")
        except Exception as e:
            print(f"{name}: failed to fetch postings: {e}")
            if (rate_limited is not None and isinstance(e, requests.HTTPError)
                    and e.response is not None and e.response.status_code == 429):
                rate_limited.append(name)
            elif failures is not None:
                failures.append(name)
    return postings


def process_postings(all_postings, ledger, dry_run=False):
    """Group first so a verified official listing can supply the application URL."""
    internlist_initialized = ledger.state.get('_source_baselines', {}).get('internlist', False)
    for source in ('canadianlist', 'internlist'):
        remembered = ledger.baseline_source(source, all_postings)
        if remembered is not None:
            prefix = 'DRY RUN ' if dry_run else ''
            print(f"{prefix}{source}: marked {remembered} existing entries as seen; notifying future additions only")
    groups = {}
    # Employer records first let curated-list copies share their verified URL.
    for posting in sorted(all_postings, key=lambda p: p.source in CURATED_SOURCES):
        if posting.source not in CURATED_SOURCES | {"amd"} and not classify(posting).accepted:
            continue
        if not posting.url:
            continue
        record = ledger.observe(posting)
        groups.setdefault(id(record), (record, []))[1].append(posting)
    if internlist_initialized:
        for record, members in groups.values():
            if record['status'] == 'seen' and any(
                    p.source == 'internlist' and _posting_matches_channel(p, channel)
                    for p in members for channel in CHANNELS):
                # Baseline is not delivery. Allow a recent, never-sent job once;
                # sent and pending records retain their duplicate protection.
                record['status'] = 'discovered'
    if not dry_run:
        ledger.save()

    # Count unique ledger records per source, rather than raw duplicate rows.
    # A refreshed aggregator timestamp does not make an old job a new identity.
    summaries = defaultdict(Counter)
    for record, members in groups.values():
        for source in {p.source for p in members}:
            eligible = any(_posting_matches_channel(p, channel)
                           for p in members if p.source == source
                           for channel in CHANNELS)
            reason = record['status']
            if reason == 'seen' and eligible:
                reason = 'baseline_seen_recent'
            elif reason == 'discovered':
                reason = 'eligible' if eligible else 'filtered'
            summaries[source][reason] += 1
    for source, counts in sorted(summaries.items()):
        print(f"{source}: scan decisions: " + ', '.join(
            f'{reason}={count}' for reason, count in sorted(counts.items())))

    for record, members in groups.values():
        if record["status"] != "discovered":
            continue
        candidates = []
        for channel in CHANNELS:
            webhook = os.getenv(channel["webhook_env"])
            if not webhook and not dry_run:
                continue
            eligible = [p for p in members if _posting_matches_channel(p, channel)]
            if eligible:
                candidates.append((channel, webhook, eligible[0]))
        if not candidates:
            continue
        # All sources share the general destination and the same delivery ledger.
        channel, webhook, posting = candidates[0]
        if dry_run:
            print(f"DRY RUN {channel['name']}: {posting.company} - {posting.title} | {posting.url}")
            continue
        # Discord webhooks have no idempotency key. Reserve durably BEFORE the
        # request: a timeout/crash may mean Discord already accepted the message.
        # Never automatically retry ambiguous delivery and risk a duplicate.
        record.update(status="pending", channel=channel["name"])
        ledger.save()
        try:
            _send_posting(posting, webhook)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status is not None and 400 <= status < 500 and status != 408:
                record["status"] = "discovered"  # Explicit rejection, safe next-scan retry.
            print(f"{channel['name']}: notification rejected/uncertain (HTTP {status}); status={record['status']}")
            ledger.save()
        except Exception as error:
            print(f"{channel['name']}: delivery uncertain ({type(error).__name__}); pending record retained")
        else:
            record["status"] = "sent"
            ledger.save()
            print(f"{channel['name']}: sent {posting.company} - {posting.title}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    dry_run = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
    with state_lock(STATE_FILE):
        ledger = Ledger(STATE_FILE)
        if not dry_run:
            for channel in CHANNELS:
                if not os.getenv(channel["webhook_env"]):
                    print(f"{channel['name']}: missing {channel['webhook_env']}, channel unavailable")
        failures = []
        rate_limited = []
        all_postings = run_all_watchers(failures, rate_limited)
        process_postings(all_postings, ledger, dry_run=dry_run)
        if rate_limited:
            message = 'Rate limited until a future scan: ' + ', '.join(rate_limited)
            if os.getenv('GITHUB_ACTIONS') == 'true':
                print('::warning::' + message)
            else:
                logging.warning(message)
        if failures or len(rate_limited) == len(WATCHERS):
            raise RuntimeError('Incomplete scan; failed sources: ' + ', '.join(failures + rate_limited))


if __name__ == "__main__":
    main()
