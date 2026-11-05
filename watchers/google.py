"""Google's public server-rendered results and semantic job-detail headings."""
import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from filtering import classify, extract_term
from models import Posting

BASE = 'https://www.google.com/about/careers/applications/'
SEARCH = BASE + 'jobs/results/'
JOB_PATH = re.compile(r'/jobs/results/(\d+)-[^/?]+')


def parse_detail(html, url):
    soup = BeautifulSoup(html, 'lxml')
    minimum = soup.find('h3', string=re.compile(r'^Minimum qualifications:'))
    title = minimum.find_previous('h2') if minimum else None
    responsibilities = soup.find('h3', string='Responsibilities')
    apply = soup.find('a', href=re.compile(r'^\./apply\?jobId='))
    if not minimum or not title or not responsibilities or not apply:
        raise ValueError('Google job detail missing qualifications, responsibilities or application link')
    place = soup.find('i', string='place')
    if not place:
        raise ValueError('Google job location missing')
    location = place.parent.get_text(' ', strip=True).removeprefix('place').strip()
    location = re.sub(r';?\s*\+\d+ more', '', location)
    descriptions = []
    for heading in soup.find_all('h3'):
        if heading.get_text(strip=True) in ('Minimum qualifications:', 'Preferred qualifications:', 'About the job', 'Responsibilities'):
            descriptions.append(heading.parent.get_text(' ', strip=True))
    match = JOB_PATH.search(urlsplit(url).path)
    if not match:
        raise ValueError('Google job ID missing')
    title = title.get_text(' ', strip=True)
    return Posting('google', 'Google', title, location, None, url, match[1], None,
                   '\n'.join(descriptions), '', '', extract_term(title))


def fetch_postings(session=None):
    session = session or requests.Session()
    postings, seen = [], set()
    for page in range(1, 51):
        response = session.get(SEARCH, params={'location': 'Canada', 'employment_type': 'INTERN', 'page': page}, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        count = re.search(r'Showing\s+(\d+)\s+to\s+(\d+)\s+of\s+([\d,]+)\s+rows', soup.get_text(' ', strip=True))
        if not count:
            # Only an explicit empty-result message is evidence of no jobs.
            if 'No jobs matched your search' in soup.get_text(' ', strip=True):
                return []
            raise ValueError('Google search result count missing')
        _, end, total = [int(x.replace(',', '')) for x in count.groups()]
        urls = {urljoin(BASE, a['href']).split('?')[0] for a in soup.select('a[href]')
                if JOB_PATH.search('/' + a['href'].lstrip('./'))}
        if not urls or urls <= seen:
            raise ValueError('Google incomplete/repeated page')
        for url in sorted(urls - seen):
            if urlsplit(url).netloc != 'www.google.com':
                raise ValueError('Google unexpected job URL')
            time.sleep(0.15)
            try:
                detail = session.get(url, timeout=25)
                if detail.status_code in (404, 410):
                    continue
                detail.raise_for_status()
                p = parse_detail(detail.text, url)
                if classify(p).accepted:
                    postings.append(p)
            except (requests.RequestException, ValueError):
                logging.warning('google: detail unavailable (scan incomplete): %s', url)
        seen.update(urls)
        if end >= total:
            return postings
    raise ValueError('Google pagination limit exceeded')
