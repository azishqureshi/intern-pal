"""Amazon's public search JSON includes full descriptions and qualifications."""
from urllib.parse import urljoin

import requests

from filtering import classify, extract_term
from models import Posting

SEARCH = 'https://www.amazon.jobs/en/search.json'


def from_job(job):
    required = ('title', 'id_icims', 'job_path', 'description', 'country_code')
    if any(not job.get(k) for k in required):
        raise ValueError('Amazon job missing required fields')
    path = job['job_path']
    if not path.startswith('/en/jobs/' + str(job['id_icims']) + '/'):
        raise ValueError('Amazon job path does not match job ID')
    locations = [job.get('location', '')]
    for loc in job.get('locations') or []:
        if isinstance(loc, dict):
            locations.append(loc.get('location', '') or ', '.join(filter(None, [loc.get('city'), loc.get('state'), loc.get('country_code')])))
    description = '\n'.join(job.get(k) or '' for k in ('description', 'basic_qualifications', 'preferred_qualifications'))
    return Posting('amazon', 'Amazon', job['title'], '; '.join(dict.fromkeys(filter(None, locations))),
                   None, urljoin('https://www.amazon.jobs', path), str(job['id_icims']), job.get('posted_date'),
                   description, 'Internship' if job.get('is_intern') is True else job.get('job_schedule_type', ''),
                   job.get('job_category', ''), extract_term(job['title']))


def fetch_postings(session=None):
    session = session or requests.Session()
    postings, seen = [], set()
    offset = 0
    for _ in range(40):
        response = session.get(SEARCH, params={'offset': offset, 'result_limit': 100,
                                              'normalized_country_code[]': 'CAN', 'sort': 'recent'}, timeout=25)
        response.raise_for_status()
        data = response.json()
        if data.get('error') or not isinstance(data.get('jobs'), list) or not isinstance(data.get('hits'), int):
            raise ValueError('Amazon search schema/error')
        jobs = data['jobs']
        if not jobs and offset < data['hits']:
            raise ValueError('Amazon incomplete pagination')
        ids = {str(j.get('id_icims')) for j in jobs}
        if jobs and ids <= seen:
            raise ValueError('Amazon repeated page')
        for job in jobs:
            if str(job.get('id_icims')) in seen:
                continue
            if job.get('country_code') != 'CAN':
                raise ValueError('Amazon country filter no longer applied')
            p = from_job(job)
            if classify(p).accepted:
                postings.append(p)
        seen.update(ids)
        offset += len(jobs)
        if offset >= data['hits']:
            return postings
    raise ValueError('Amazon pagination limit exceeded')
