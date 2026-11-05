"""Scotiabank's public Student & New Grad category (SuccessFactors HTML)."""
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from filtering import classify, extract_term
from models import Posting

BASE = 'https://jobs.scotiabank.com'
SEARCH = BASE + '/go/Student-&-New-Grad-Jobs/2298417/'


def parse_detail(html, url):
    soup = BeautifulSoup(html, 'lxml')
    title, desc = soup.select_one('[itemprop="title"]'), soup.select_one('[itemprop="description"]')
    if not title or not desc:
        raise ValueError('Scotiabank missing job microdata')
    def prop(name):
        tag = soup.select_one(f'[itemprop="{name}"]')
        return tag.get('content', tag.get_text(' ', strip=True)) if tag else ''
    expires = prop('validThrough')[:10]
    if expires and expires < datetime.now(timezone.utc).date().isoformat():
        return None
    description = desc.get_text(' ', strip=True)
    req = re.search(r'Requisition ID:\s*(\d+)', description, re.I)
    if not req:
        raise ValueError('Scotiabank missing requisition ID')
    country = prop('addressCountry')
    if country == 'CA':
        country = 'Canada'
    location = ', '.join(filter(None, [prop('addressLocality'), prop('addressRegion'), country]))
    title = title.get_text(' ', strip=True)
    # Industry tags mix several disciplines and are not primary job categories.
    return Posting('scotiabank', 'Scotiabank', title, location, None, url, req[1],
                   prop('datePosted'), description, '', '', extract_term(title))


def fetch_postings(session=None):
    session = session or requests.Session()
    postings, seen = [], set()
    offset = 0
    for _ in range(40):
        response = session.get(SEARCH + (f'{offset}/' if offset else ''), timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        label = soup.select_one('.paginationLabel')
        match = re.search(r'Results\s+([\d,]+)\s*[–-]\s*([\d,]+)\s+of\s+([\d,]+)', label.get_text(' ', strip=True) if label else '')
        if not match:
            if 'There are currently no open positions' in soup.get_text(' ', strip=True):
                return []
            raise ValueError('Scotiabank missing pagination count')
        start, end, total = [int(v.replace(',', '')) for v in match.groups()]
        paths = {a['href'] for a in soup.select('a.jobTitle-link[href]')}
        if not paths or paths <= seen or start != offset + 1:
            raise ValueError('Scotiabank incomplete/repeated search page')
        foreign = set()
        for row in soup.select('tr.data-row'):
            location = row.select_one('.colLocation')
            link = row.select_one('a.jobTitle-link[href]')
            if location and link and re.search(r',\s*(?:US|MX|GB|CO|PE|CL)\b', location.get_text(' ', strip=True)):
                foreign.add(link['href'])
        for path in sorted(paths - seen - foreign):
            if not path.startswith('/job/'):
                raise ValueError('Scotiabank unexpected job path')
            url = urljoin(BASE, path)
            time.sleep(0.15)
            try:
                detail = session.get(url, timeout=25)
                if detail.status_code in (404, 410):
                    continue
                detail.raise_for_status()
                p = parse_detail(detail.text, url)
                if p and classify(p).accepted:
                    postings.append(p)
            except (requests.RequestException, ValueError):
                logging.warning('scotiabank: detail unavailable (scan incomplete): %s', path)
        seen.update(paths)
        if end >= total:
            return postings
        offset = end
    raise ValueError('Scotiabank pagination limit exceeded')
