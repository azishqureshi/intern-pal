"""Shared JSON ledger with conservative identities and additive legacy migration."""
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from filtering import extract_term, text
from models import Posting

ALIASES = {
    'cibc': ['cibc', 'canadian imperial bank of commerce', 'canadian imperial bank of commerce cibc'],
    'rbc': ['rbc', 'royal bank of canada', 'rbc royal bank', 'royal bank of canada rbc'],
    'bmo': ['bmo', 'bank of montreal', 'bmo financial group'],
    'td': ['td', 'td bank', 'td bank group', 'toronto dominion bank', 'the toronto dominion bank'],
    'scotiabank': ['scotiabank', 'the bank of nova scotia', 'bank of nova scotia'],
    'shopify': ['shopify'], 'google': ['google', 'google canada'],
    'amazon': ['amazon', 'amazon canada', 'amazon web services', 'aws', 'amazon com'],
    'amd': ['amd', 'advanced micro devices'],
}


def words(value):
    return re.sub(r'[^a-z0-9]+', ' ', text(value)).strip()


def company_name(value):
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value or '')
    cleaned = words(value)
    cleaned = re.sub(r'\s+(?:inc|incorporated|ltd|limited|corp|corporation)$', '', cleaned)
    for canonical, aliases in ALIASES.items():
        if cleaned in aliases:
            return canonical
    return cleaned


def canonical_url(value):
    u = urlsplit((value or '').replace('&amp;', '&').strip())
    if u.scheme not in ('https', 'http') or not u.netloc:
        return ''
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in
             {'ref', 'source', 'src', 'referrer', 'gh_src', 'lang', 'locale', 'trackingid'}]
    path = u.path.rstrip('/')
    if u.netloc.lower() == 'jobs.scotiabank.com':
        match = re.search(r'/job/.*/(\d+)$', path)
        if match:
            path = '/job/' + match[1]
    return urlunsplit(('https', u.netloc.lower(), path, urlencode(sorted(query)), ''))


def company_from_url(value):
    host = urlsplit(value).netloc.lower().removeprefix('www.')
    for name in ALIASES:
        if host.startswith(name + '.wd') and host.endswith('.myworkdayjobs.com'):
            return name
    domains = {'amazon.jobs': 'amazon', 'jobs.scotiabank.com': 'scotiabank',
               'careers.amd.com': 'amd', 'google.com': 'google', 'shopify.com': 'shopify',
               'jobs.rbc.com': 'rbc', 'jobs.bmo.com': 'bmo', 'jobs.td.com': 'td'}
    if host == 'jobs.ashbyhq.com' and urlsplit(value).path.startswith('/shopify/'):
        return 'shopify'
    return domains.get(host, '')


def req_id(value):
    return re.sub(r'[-_\s]', '', (value or '').lower())


def url_req_id(value):
    u = urlsplit(value or '')
    host, path = u.netloc.lower(), unquote(u.path).rstrip('/')
    if host.endswith('.myworkdayjobs.com'):
        m = re.search(r'_((?:R[-_]|JR|REQ|R)?\d[\w-]*?)(?:-\d+)?(?:/apply)?$', path, re.I)
    elif host in ('amazon.jobs', 'www.amazon.jobs'):
        m = re.search(r'/jobs/(\d+)', path)
    elif host == 'careers.amd.com':
        m = re.search(r'/jobs/(\d+)', path)
    elif host == 'jobs.scotiabank.com':
        m = re.search(r'/(\d+)/?$', path)
        # SuccessFactors URL IDs are posting IDs, not requisition IDs.
        return ''
    elif host in ('google.com', 'www.google.com'):
        m = re.search(r'/jobs/results/(\d+)', path)
    elif host in ('shopify.com', 'www.shopify.com'):
        m = re.search(r'_([a-f0-9-]{36})$', path)
        if not m:
            return req_id(dict(parse_qsl(u.query)).get('ashby_jid', ''))
    elif host == 'jobs.ashbyhq.com':
        m = re.search(r'/shopify/([a-f0-9-]{36})', path)
    elif host == 'jobs.rbc.com':
        m = re.search(r'R-?(\d{10})', path, re.I)
        return req_id('R' + m[1]) if m else ''
    elif host == 'jobs.bmo.com':
        m = re.search(r'(R\d{9})', path, re.I)
    else:
        m = None
    return req_id(m[1]) if m else ''


def location_name(value):
    value = words(value)
    for full, short in [('british columbia', 'bc'), ('ontario', 'on'), ('quebec', 'qc'),
                        ('alberta', 'ab'), ('manitoba', 'mb'), ('nova scotia', 'ns')]:
        value = re.sub(r'\b' + full + r'\b', short, value)
    value = re.sub(r'\b(?:canada|can)\b', '', value)
    value = re.sub(r'^ca\s+(?=(?:on|bc|qc|ab|mb|nb|nl|ns|nt|nu|pe|sk|yt)\b)', '', value)
    return ' '.join(value.split())


def role_name(value):
    value = words(value)
    value = re.sub(r'\b(?:winter|spring|summer|fall|autumn)\s+20\d{2}\b|\b20\d{2}\s+(?:winter|spring|summer|fall|autumn)\b', '', value)
    value = re.sub(r'\b(?:internship|intern|co op|coop|student)\b', 'intern', value)
    value = re.sub(r'\b(?:engineering|engineer|development|developer)\b', 'developer', value)
    value = re.sub(r'\b(intern)(?:\s+intern)+\b', r'\1', value)
    return ' '.join(value.split())


def identity(posting):
    url = canonical_url(posting.url)
    company = company_name(posting.company)
    ids = set()
    if posting.job_id:
        ids.add(req_id(posting.job_id))
    # Only trust identifiers from the matching employer's URL.
    if company_from_url(url) == company:
        found = url_req_id(url)
        if found:
            ids.add(found)
    term = posting.term or extract_term(posting.title)
    signature = [role_name(posting.title), location_name(posting.location), term]
    return {'company': company, 'ids': sorted(ids), 'urls': [url] if url else [],
            'signatures': [signature] if all(signature) and signature[1] not in ('unknown', 'remote') else []}


def same_job(a, b):
    if a['company'] and b['company'] and a['company'] != b['company']:
        return False
    # Explicitly different requisitions must never be merged by title or URL.
    if a['ids'] and b['ids'] and not set(a['ids']) & set(b['ids']):
        return False
    if set(a['urls']) & set(b['urls']):
        return True
    if a['company'] and a['company'] == b['company']:
        if set(a['ids']) & set(b['ids']):
            return True
        return any(s in b['signatures'] for s in a['signatures'])
    return False


def merge_identity(target, incoming):
    if not target['company']:
        target['company'] = incoming['company']
    for key in ('ids', 'urls', 'signatures'):
        for item in incoming[key]:
            if item not in target[key]:
                target[key].append(item)


class Ledger:
    def __init__(self, path='state.json', legacy_path='notified.json'):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if not isinstance(self.state, dict):
            raise ValueError('Invalid state; refusing to discard notification history')
        if ('_version' in self.state or '_jobs' in self.state) and self.state.get('_version') != 2:
            raise ValueError('Unsupported state version')
        if '_jobs' not in self.state:
            if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v)
                   for v in self.state.values()):
                raise ValueError('Invalid legacy notification history')
            self.state['_jobs'] = []
            self._migrate(legacy_path)
            self.state['_version'] = 2
        self.jobs = self.state['_jobs']
        if not isinstance(self.jobs, list):
            raise ValueError('Invalid job ledger')
        baselines = self.state.get('_source_baselines', {})
        if not isinstance(baselines, dict) or any(
                not isinstance(k, str) or v is not True for k, v in baselines.items()):
            raise ValueError('Invalid source baseline history')
        for job in self.jobs:
            if not isinstance(job, dict) or job.get('status') not in ('discovered', 'pending', 'sent', 'seen'):
                raise ValueError('Invalid ledger record')
            if not isinstance(job.get('company'), str) or not isinstance(job.get('channel'), str):
                raise ValueError('Invalid ledger identity')
            for key in ('ids', 'urls', 'sources'):
                if not isinstance(job.get(key), list) or any(not isinstance(v, str) for v in job[key]):
                    raise ValueError('Invalid ledger aliases/sources')
            if not isinstance(job.get('signatures'), list) or any(
                    not isinstance(v, list) or len(v) != 3 or any(not isinstance(x, str) for x in v)
                    for v in job['signatures']):
                raise ValueError('Invalid ledger signature')

    def _migrate(self, legacy_path):
        historical = []
        for channel, values in self.state.items():
            if channel.startswith('_'):
                continue
            for value in values:
                historical.append((channel, value))
        if legacy_path and Path(legacy_path).exists():
            old = json.loads(Path(legacy_path).read_text())
            if not isinstance(old, list) or any(not isinstance(x, str) for x in old):
                raise ValueError('Invalid notified.json history')
            historical.extend(('', v) for v in old)
        for channel, value in historical:
            url = canonical_url(value)
            company = company_from_url(url) if url else (channel if channel in ('amd', 'cibc') else '')
            # Bare general-channel IDs have no company context. Dedicated
            # channel copies supply that context without guessing globally.
            if not url and not company:
                continue
            p = Posting('legacy', company, '', '', None, url or None,
                        None if url else value, None)
            data = identity(p)
            existing = next((j for j in self.state['_jobs'] if same_job(j, data)), None)
            if existing:
                merge_identity(existing, data)
            else:
                self.state['_jobs'].append(dict(data, status='sent', channel=channel, sources=['legacy']))

    def observe(self, posting):
        data = identity(posting)
        matches = [j for j in self.jobs if same_job(j, data)]
        exact = [j for j in matches if (set(j['ids']) & set(data['ids'])) or
                 (set(j['urls']) & set(data['urls']))]
        if exact:
            # An exact alias always wins over ambiguous metadata. Prefer an
            # existing delivery record if old data contains redundant aliases.
            matches = [min(exact, key=lambda j: {'sent': 0, 'pending': 1, 'seen': 2, 'discovered': 3}[j['status']])]
        # A missing-ID listing matching multiple different requisitions is
        # ambiguous, so don't silently join those jobs together.
        if len(matches) == 1:
            record = matches[0]
            merge_identity(record, data)
        else:
            record = dict(data, status='discovered', channel='', sources=[])
            self.jobs.append(record)
        if posting.source not in record['sources']:
            record['sources'].append(posting.source)
        return record

    def baseline_source(self, source, postings):
        """Remember an initial source snapshot without claiming Discord delivery.

        This changes memory only; the caller saves it before sending anything.
        An absent/failed source must not initialize its baseline.
        """
        baselines = self.state.get('_source_baselines', {})
        if baselines.get(source):
            return None
        initial = [p for p in postings if p.source == source and p.url]
        if not initial:
            return None
        remembered = 0
        for posting in initial:
            record = self.observe(posting)
            if record['status'] == 'discovered':
                record['status'] = 'seen'
                remembered += 1
        self.state.setdefault('_source_baselines', {})[source] = True
        return remembered

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


@contextmanager
def state_lock(path):
    # Both the existing GitHub runner and local macOS support flock.
    import fcntl
    with open(str(path) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
