"""Shopify's server-rendered job list and official internship programme links."""
import logging
import re
from urllib.parse import urljoin, urlsplit
from collections import Counter

import requests
from bs4 import BeautifulSoup

from filtering import STUDENT, classify, extract_term, text
from models import Posting

BASE = 'https://www.shopify.com'
INDEX = BASE + '/careers/jobs'
PROGRAMME = 'https://internships.shopify.com/'
JOB_PATH = re.compile(r'/careers/[^/?]+_([a-f0-9-]{36})$')
LOG = logging.getLogger(__name__)


def internship_location(location, description):
    """Resolve broad Americas metadata from the mandatory intern office section.

    Do not infer eligibility from compensation, a company address, or generic
    Canada mentions elsewhere on the page.
    """
    if text(location) not in ('remote - americas', 'remote'):
        return location
    match = re.search(
        r'as an intern you must be able to work(?: in-person)? from one of our offices'
        r'(.{0,1800}?)(?:onboarding|please note:)', text(description))
    if not match:
        return location
    offices = match[1]
    cities = []
    for city, province in [('montreal', 'quebec'), ('ottawa', 'ontario'), ('toronto', 'ontario')]:
        if re.search(r'\b' + city + r'\b[^.;]{0,100}\b' + province + r'\b', offices):
            cities.append(f'{city.title()}, {province.title()}, Canada')
    return '; '.join(cities) or location


def parse_detail(html, url):
    soup = BeautifulSoup(html, 'lxml')
    title = soup.select_one('main h1')
    marker = soup.select_one('[data-component-name="job-description"]')
    if not title or not marker or not soup.select_one('#apply'):
        raise ValueError('Shopify job detail structure changed')
    header = title.find_parent('header')
    location = header.find('p') if header else None
    # Only the actual role description, excluding generic engineering/culture copy.
    description = marker.find_next_sibling()
    if not location or not description:
        raise ValueError('Shopify job location/description missing')
    match = JOB_PATH.search(urlsplit(url).path)
    if not match:
        raise ValueError('Shopify job identifier missing')
    title = title.get_text(' ', strip=True)
    description = description.get_text(' ', strip=True)
    location = internship_location(location.get_text(' ', strip=True), description)
    return Posting('shopify', 'Shopify', title, location, None,
                   url, match[1], None, description,
                   '', '', extract_term(title))


def fetch_postings(session=None):
    session = session or requests.Session()
    response = session.get(INDEX, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'lxml')
    links = [a for a in soup.select('a[href]') if JOB_PATH.search(urlsplit(a['href']).path)]
    if not links:
        raise ValueError('Shopify job index missing listings; cannot verify empty board')
    # The current public index renders every job, with client-side filters.
    # Detect pagination if Shopify switches to a paginated index.
    if soup.select('a[rel="next"]'):
        raise ValueError('Shopify index now paginated; adapter needs updating')
    urls = {urljoin(BASE, a['href']).split('?')[0] for a in links
            if re.search(STUDENT, a.get_text(' ', strip=True), re.I)}
    programme = session.get(PROGRAMME, timeout=25)
    programme.raise_for_status()
    programme_soup = BeautifulSoup(programme.text, 'lxml')
    if not re.search('internship', programme_soup.get_text(), re.I):
        raise ValueError('Shopify internship programme page changed')
    for a in programme_soup.select('a[href]'):
        url = urljoin(BASE, a['href']).split('?')[0]
        if urlsplit(url).netloc in ('www.shopify.com', 'shopify.com') and JOB_PATH.search(urlsplit(url).path):
            urls.add(BASE + urlsplit(url).path)
    postings = []
    rejected = Counter()
    for url in sorted(urls):
        try:
            detail = session.get(url, timeout=25)
            if detail.status_code in (404, 410):
                continue  # Expired programme links are not open jobs.
            detail.raise_for_status()
            p = parse_detail(detail.text, url)
            decision = classify(p)
            if decision.accepted:
                postings.append(p)
            else:
                rejected[decision.reason] += 1
                LOG.info('shopify: rejected %s: %s', p.title, decision.reason)
        except (requests.RequestException, ValueError):
            logging.warning('shopify: detail unavailable (scan incomplete): %s', url)
    LOG.info('shopify: reviewed %d candidate links; accepted %d; rejection reasons=%s',
             len(urls), len(postings), dict(rejected))
    return postings
