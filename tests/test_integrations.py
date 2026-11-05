"""Offline contract fixtures for schemas verified against official boards.

Descriptions below are deliberately synthetic, so cases stay stable when live
roles close. tests/fixtures holds small, sanitized real markup samples too.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from filtering import classify
from watchers import amazon, banks, cibc, google, scotiabank, shopify, workday

DESCRIPTION = 'Develop software applications using Python and Java. Write unit tests and review code. Currently enrolled in an undergraduate degree and returning to school.'


def response(data=None, html='', status=200):
    r = Mock()
    r.json.return_value = data
    r.text, r.status_code = html, status
    if status >= 400:
        actual = requests.Response(); actual.status_code = status
        r.raise_for_status.side_effect = requests.HTTPError(response=actual)
    return r


def wd_detail(board, req='123', title='Software Engineering Intern - Summer 2027', **extra):
    info = dict(title=title, jobDescription=DESCRIPTION, jobReqId=req,
                location='Toronto, ON', country={'descriptor': 'Canada'},
                timeType='Full time', canApply=True, posted=True,
                externalUrl=f'{board.base}/{board.site}/job/Toronto/Role_{req}')
    info.update(extra)
    return {'jobPostingInfo': info}


def wd_item(req='123'):
    return {'title': 'Unconventional Name', 'externalPath': '/job/Toronto/Role_'+req, 'locationsText': 'Toronto, ON'}


def scotia_detail(req='273053', title='Software Engineer Internship - Summer 2027'):
    return f'''<html><span itemprop="title">{title}</span>
    <meta itemprop="addressLocality" content="Toronto"><meta itemprop="addressRegion" content="ON">
    <meta itemprop="addressCountry" content="CA"><meta itemprop="datePosted" content="2026-11-01">
    <span itemprop="description">Requisition ID: {req} {DESCRIPTION}</span></html>'''


def scotia_index(start, end, total, path):
    return f'<span class="paginationLabel">Results {start} – {end} of {total}</span><a class="jobTitle-link" href="{path}">Job</a>'


def shopify_detail(title='Software Engineering Intern - Summer 2027', location='Remote - Canada'):
    return f'''<main><header><h1>{title}</h1><p>{location}</p></header>
    <span data-component-name="job-description"></span><section>{DESCRIPTION}</section><section id="apply"></section></main>'''


def google_detail(title='Software Developer Intern, BS, Summer 2027'):
    return f'''<h2>{title}</h2><span><i>place</i>Toronto, ON, Canada</span>
    <a href="./apply?jobId=abc">Apply</a>
    <div><h3>Minimum qualifications:</h3>Enrolled in a bachelor degree. Python programming.</div>
    <div><h3>About the job</h3>Student internship.</div>
    <div><h3>Responsibilities</h3>{DESCRIPTION}</div>'''


def amazon_job(req='10553947', title='Software Development Engineer Intern - Summer 2027 (CAN)'):
    return dict(title=title, id_icims=req, job_path=f'/en/jobs/{req}/software-intern',
                description=DESCRIPTION, basic_qualifications='Enrolled in a bachelor degree.',
                preferred_qualifications='', country_code='CAN', location='CA, BC, Vancouver',
                job_category='Software Development', job_schedule_type='Full-Time', is_intern=None)


class WorkdayTests(unittest.TestCase):
    @patch('watchers.workday.time.sleep')
    def test_each_bank_uses_details_and_filter(self, _sleep):
        for board in (cibc.BOARD, banks.RBC, banks.BMO, banks.TD):
            with self.subTest(board=board.source):
                session = Mock()
                session.post.return_value = response({'total': 2, 'jobPostings': [wd_item(), wd_item('124')]})
                session.get.side_effect = [response(wd_detail(board)), response(wd_detail(board, '124', 'Investment Banking Intern'))]
                result = workday.fetch_board(board, session)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].job_id, '123')
                self.assertTrue(result[0].url.startswith(board.base))
                self.assertEqual(result[0].term, '2027-summer')
                self.assertEqual(session.post.call_args.kwargs['json']['appliedFacets'], board.facets)

    @patch('watchers.workday.time.sleep')
    def test_pagination_and_overlapping_pages(self, _sleep):
        session = Mock()
        session.post.side_effect = [response({'total': 3, 'jobPostings': [wd_item(), wd_item('124')]}),
                                    response({'total': 3, 'jobPostings': [wd_item('125')]})]
        session.get.side_effect = [response(wd_detail(cibc.BOARD, n)) for n in ['123','124','125']]
        self.assertEqual(len(workday.fetch_board(cibc.BOARD, session)), 3)
        self.assertEqual([c.kwargs['json']['offset'] for c in session.post.call_args_list], [0, 2])

    @patch('watchers.workday.time.sleep')
    def test_failed_detail_does_not_emit_unverified_summary(self, _sleep):
        session = Mock()
        session.post.return_value = response({'total': 2, 'jobPostings': [wd_item(), wd_item('124')]})
        session.get.side_effect = [requests.Timeout(), response(wd_detail(cibc.BOARD, '124'))]
        with self.assertLogs('watchers.workday', 'WARNING'):
            result = workday.fetch_board(cibc.BOARD, session)
        self.assertEqual([p.job_id for p in result], ['124'])

    @patch('watchers.workday.time.sleep')
    def test_bad_schema_empty_truncated_and_repeated_page_fail(self, _sleep):
        for data in [{}, {'total': 1, 'jobPostings': []}]:
            session = Mock(); session.post.return_value = response(data)
            with self.assertRaises(ValueError): workday.fetch_board(cibc.BOARD, session)
        session = Mock();session.post.return_value = response({'total': 2, 'jobPostings': [wd_item()]})
        session.get.return_value = response(wd_detail(cibc.BOARD))
        with self.assertRaises(ValueError): workday.fetch_board(cibc.BOARD, session)

    def test_closed_and_untrusted_links(self):
        self.assertIsNone(workday.from_detail(cibc.BOARD, wd_detail(cibc.BOARD, canApply=False)))
        self.assertIsNone(workday.from_detail(cibc.BOARD, wd_detail(cibc.BOARD, endDate='2000-01-01')))
        with self.assertRaises(ValueError):
            workday.from_detail(cibc.BOARD, wd_detail(cibc.BOARD, externalUrl='https://example.test/job/123'))
        with self.assertRaises(ValueError):
            workday.from_detail(cibc.BOARD, wd_detail(cibc.BOARD, externalUrl=cibc.BOARD.base+'/campus/job/Toronto/Different_999'))


class OtherSourceTests(unittest.TestCase):
    @patch('watchers.scotiabank.time.sleep')
    def test_scotiabank_pagination_and_requisition(self, _sleep):
        session = Mock()
        first, second = '/job/Software-Intern/605897917/', '/job/Banking-Intern/605897918/'
        session.get.side_effect = [response(html=scotia_index(1, 1, 2, first)), response(html=scotia_detail()),
                                   response(html=scotia_index(2, 2, 2, second)), response(html=scotia_detail('273054', 'Investment Banking Intern'))]
        results = scotiabank.fetch_postings(session)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].job_id, '273053')
        self.assertEqual(results[0].url, scotiabank.BASE + first)
        self.assertEqual(session.get.call_args_list[2].args[0], scotiabank.SEARCH + '1/')

    @patch('watchers.scotiabank.time.sleep')
    def test_scotiabank_repeated_page(self, _sleep):
        session = Mock()
        page = scotia_index(1, 1, 2, '/job/Role/123/')
        session.get.side_effect = [response(html=page), response(html=scotia_detail()), response(html=page)]
        with self.assertRaises(ValueError): scotiabank.fetch_postings(session)

    def test_shopify_active_and_expired_programme_link(self):
        session = Mock()
        path = '/careers/software-intern_404bb82e-37f3-4a78-b0f3-12923a7c4856'
        index = f'<a href="{path}">Software Engineering Internship</a>'
        session.get.side_effect = [response(html=index), response(html='<h1>Engineering Internship</h1>'), response(html=shopify_detail())]
        result = shopify.fetch_postings(session)
        self.assertEqual(len(result), 1)
        self.assertTrue(classify(result[0]).accepted)
        session.get.side_effect = [response(html=index), response(html=f'<h1>Internships</h1><a href="{shopify.BASE+path}">Apply</a>'), response(status=410)]
        self.assertEqual(shopify.fetch_postings(session), [])
        self.assertFalse(classify(shopify.parse_detail(shopify_detail(location='Remote - Americas'), shopify.BASE+path)).accepted)

    @patch('watchers.google.time.sleep')
    def test_google_pagination_and_undergraduate(self, _sleep):
        def index(start, title):
            return f'Showing {start} to {start} of 2 rows <a href="jobs/results/{start}-{title}">Job</a>'
        session = Mock()
        session.get.side_effect = [response(html=index(1,'software-intern')), response(html=google_detail()),
                                   response(html=index(2,'software-intern-phd')), response(html=google_detail('Software Developer Intern, PhD, Summer 2027'))]
        result = google.fetch_postings(session)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].job_id, '1')
        self.assertEqual(session.get.call_args_list[2].kwargs['params']['page'], 2)

    def test_amazon_pagination_business_filter_and_urls(self):
        session = Mock()
        session.get.side_effect = [response({'hits': 2, 'jobs': [amazon_job()]}),
                                   response({'hits': 2, 'jobs': [amazon_job('123', 'Marketing Intern')]})]
        result = amazon.fetch_postings(session)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].job_id, '10553947')
        self.assertEqual(result[0].url, 'https://www.amazon.jobs/en/jobs/10553947/software-intern')
        self.assertEqual(session.get.call_args_list[1].kwargs['params']['offset'], 1)

    def test_amazon_ignored_country_filter_fails(self):
        session = Mock(); job = amazon_job();job['country_code'] = 'USA'
        session.get.return_value = response({'hits': 1, 'jobs': [job]})
        with self.assertRaises(ValueError): amazon.fetch_postings(session)

    def test_changed_html_fails_closed(self):
        for parser, url in [(scotiabank.parse_detail, 'https://jobs.scotiabank.com/job/role/123/'),
                            (shopify.parse_detail, 'https://www.shopify.com/careers/role_123'),
                            (google.parse_detail, google.SEARCH+'123-role')]:
            with self.assertRaises(ValueError): parser('<html>Temporary outage</html>', url)


class RecordedShapeTests(unittest.TestCase):
    def test_recorded_rbc_unconventional_title(self):
        data = json.loads((Path(__file__).parent/'fixtures/rbc_amplify.json').read_text())
        job = workday.from_detail(banks.RBC, data)
        self.assertTrue(classify(job).accepted)

    def test_recorded_scotiabank_metadata_and_shopify_markup(self):
        root = Path(__file__).parent/'fixtures'
        job = scotiabank.parse_detail((root/'scotiabank.html').read_text(), 'https://jobs.scotiabank.com/job/Toronto-Role/605897917/')
        self.assertEqual(job.job_id, '273053')
        self.assertIn('Canada', job.location)
        job = shopify.parse_detail((root/'shopify.html').read_text(), 'https://www.shopify.com/careers/staff-software-engineer-internal-tools_12490bc5-00b1-4baf-9caa-8f01b4be4dbf')
        self.assertFalse(classify(job).accepted)
