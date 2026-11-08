"""Public Canadian SWE internship feed embedded by intern-list.com.

Read every page of the category used by the website. This is an aggregator,
so its category is discovery evidence, not an employer-verified description.
"""
from datetime import datetime, timedelta, timezone
import logging
import os
import re

import requests

from filtering import BUSINESS_ROLE, DUTIES, SKILLS, canadian_location, extract_term, text
from models import Posting

SEARCH = 'https://jobright.ai/swan/mini-sites/list'
CATEGORY = 'intern:ca:swe'
PAGE_SIZE = 50
LOG = logging.getLogger(__name__)


def software_role(title, qualifications):
    """Check summary evidence without treating a broad aggregator tag as proof.

    Qualifications are truncated, so clear software titles do not require the
    full responsibility paragraphs used by the employer-board classifier.
    """
    title, qualifications = text(title), text(qualifications)
    if re.search(BUSINESS_ROLE, title) or re.search(
            r'\b(?:corporate security|information management|geomatics|future opportunities)\b', title):
        return False
    if re.search(r'\b(?:software|developer|programmer|devops|sdet|firmware|'
                 r'full.stack|back.end|front.end|cybersecurity|browser security|'
                 r'machine learning|data scien(?:ce|tist)|data engineer(?:ing)?)\b', title):
        return True
    # AI/robotics and ambiguous engineering titles need programming evidence.
    if re.search(r'\b(?:ai|artificial intelligence|robotics)\b', title):
        return bool(re.search(SKILLS, qualifications))
    return bool(re.search(SKILLS, qualifications) and
                any(re.search(pattern, qualifications) for pattern in DUTIES))


def is_recent(posting, now=None):
    """Use source time, never discovery time, for a rolling freshness window."""
    try:
        hours = int(os.getenv('INTERNLIST_MAX_AGE_HOURS', '48'))
        posted = datetime.fromisoformat(posting.posted_at or '')
        if hours <= 0 or posted.tzinfo is None:
            return False
    except (ValueError, TypeError):
        return False
    age = (now or datetime.now(timezone.utc)) - posted
    return timedelta(0) <= age <= timedelta(hours=hours)


def _job_id(item):
    if not isinstance(item, dict):
        raise ValueError('Intern List job is not an object')
    identifier = item.get('jobId')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-fA-F0-9]{24}', identifier):
        raise ValueError('Intern List job identifier missing or changed')
    return identifier.lower()


def from_job(item):
    identifier = _job_id(item)
    categories = item.get('tabCategory')
    if not isinstance(categories, list) or CATEGORY not in categories:
        raise ValueError('Intern List returned a job outside the requested Canadian SWE category')
    props = item.get('properties')
    if not isinstance(props, dict) or any(
            not isinstance(props.get(key), str) or not props[key].strip()
            for key in ('title', 'company', 'location')):
        raise ValueError('Intern List job is missing title, company or location')
    qualifications = props.get('qualifications') or ''
    if not isinstance(qualifications, str):
        raise ValueError('Intern List qualifications schema changed')
    # The category can contain bad locations or new-grad entries; check locally.
    if props.get('isNewGrad') is True or not canadian_location(props['location'], qualifications):
        return None
    posted = item.get('postedAt')
    if isinstance(posted, bool) or not isinstance(posted, (int, float)) or posted <= 0:
        raise ValueError('Intern List posting timestamp missing or changed')
    try:
        posted_at = datetime.fromtimestamp(posted / 1000, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError('Intern List posting timestamp invalid') from error
    if not software_role(props['title'], qualifications):
        return None
    return Posting(
        source='internlist', company=props['company'].strip(), title=props['title'].strip(),
        location=props['location'].strip(), age=None,
        url=f'https://jobright.ai/jobs/info/{identifier}',
        # A Jobright ID is NOT an employer requisition ID. Keeping it in the
        # stable URL allows shared metadata matching with employer records.
        job_id=None, posted_at=posted_at, description=qualifications,
        employment_type='Internship', category='Software Engineering',
        term=extract_term(props['title']),
    )


def fetch_postings(session=None):
    session = session or requests.Session()
    postings, seen = [], set()
    offset, expected_total = 0, None
    for _ in range(100):
        response = session.post(
            SEARCH, params={'position': offset, 'count': PAGE_SIZE},
            json={'category': CATEGORY}, headers={'Accept': 'application/json'}, timeout=20,
        )
        response.raise_for_status()
        envelope = response.json()
        if not isinstance(envelope, dict) or envelope.get('success') is not True:
            raise ValueError('Intern List search failed or its response schema changed')
        data = envelope.get('result')
        if not isinstance(data, dict) or not isinstance(data.get('jobList'), list):
            raise ValueError('Intern List result schema changed')
        total, items = data.get('total'), data['jobList']
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError('Intern List total count missing or invalid')
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError('Intern List changed during pagination; retry a complete scan next run')
        if len(items) > PAGE_SIZE or (not items and offset < total):
            raise ValueError('Intern List incomplete or oversized results page')
        ids = [_job_id(item) for item in items]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError('Intern List repeated/overlapping results page')
        for item in items:
            posting = from_job(item)
            if posting:
                postings.append(posting)
        seen.update(ids)
        offset += len(items)
        if offset >= total:
            if offset != total:
                raise ValueError('Intern List rows do not match its total count')
            LOG.info('internlist: reviewed %d Canadian SWE category records; returned %d',
                     len(seen), len(postings))
            return postings
    raise ValueError('Intern List pagination limit exceeded')
