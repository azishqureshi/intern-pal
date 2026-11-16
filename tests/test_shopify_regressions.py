"""Actual Summer 2027 descriptions, plus rejection and delivery regressions."""
import contextlib
from dataclasses import replace
import html
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from filtering import classify
from main import CHANNELS, _posting_matches_channel, process_postings
from models import Posting
from tracking import Ledger
from watchers import shopify
from test_integrations import response


class ShopifyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.samples = json.loads((Path(__file__).parent / 'fixtures/shopify_internships.json').read_text())

    def detail(self, sample):
        return ('<main><header><h1>' + html.escape(sample['title']) + '</h1><p>' +
                html.escape(sample['location']) + '</p></header>' +
                '<span data-component-name="job-description"></span><section>' +
                html.escape(sample['description']) + '</section><section id="apply"></section></main>')

    def test_real_swe_ml_and_data_descriptions_pass_end_to_end(self):
        for sample in self.samples:
            with self.subTest(title=sample['title']):
                p = shopify.parse_detail(self.detail(sample), sample['url'])
                self.assertTrue(classify(p).accepted)
                self.assertTrue(_posting_matches_channel(p, CHANNELS[0]))
                self.assertIn('Toronto, Ontario, Canada', p.location)

    def test_generic_canada_mentions_do_not_establish_office_eligibility(self):
        for desc in ['Our headquarters are in Canada. Develop software in Python.',
                     'Compensation: CAD $80,000 for Canada.',
                     'As an Intern you must be able to work from one of our offices: '
                     'New York, USA. Please note: our headquarters are Toronto, Ontario.',
                     'As an Intern you must be able to work from one of our offices: '
                     'New York, USA. Onboarding. Toronto, Ontario.']:
            self.assertEqual(shopify.internship_location('Remote - Americas', desc), 'Remote - Americas')
        self.assertEqual(shopify.internship_location('Remote - United States', self.samples[0]['description']),
                         'Remote - United States')

    def test_programme_bare_domain_is_discovered_and_canonicalized(self):
        sample = self.samples[1]
        session = Mock()
        index = '<a href="/careers/engineer_00000000-0000-0000-0000-000000000000">Engineer</a>'
        programme = '<h1>Internships</h1><a href="' + sample['url'].replace('www.', '') + '">Apply</a>'
        session.get.side_effect = [response(html=index), response(html=programme), response(html=self.detail(sample))]
        postings = shopify.fetch_postings(session)
        self.assertEqual(len(postings), 1)
        self.assertEqual(postings[0].url, sample['url'])

    def test_official_copy_wins_same_scan_and_already_sent_copy_is_not_replayed(self):
        sample = self.samples[1]
        official = shopify.parse_detail(self.detail(sample), sample['url'])
        curated = replace(official, source='simplifyjobs', title='Software Engineer Intern',
                          job_id=None, description='', age='0d', term='',
                          url=official.url+'?utm_source=Simplify&ref=Simplify')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test'}), \
                    patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()):
                process_postings([curated, official], Ledger(path, None))
                send.assert_called_once_with(official, 'https://example.test')
                process_postings([official, curated], Ledger(path, None))
                self.assertEqual(send.call_count, 1)
                # Reproduce production: the first alert came from SimplifyJobs.
                path.unlink()
                process_postings([curated], Ledger(path, None))
                process_postings([official, curated], Ledger(path, None))
                self.assertEqual(send.call_count, 2)

    def test_business_closed_senior_and_graduate_roles_stay_rejected(self):
        p = Posting(**self.samples[1])
        p = replace(p, location='Canada')
        for changes in [dict(title='Marketing Intern'), dict(title='Senior Software Engineer Intern'),
                        dict(title='Software Engineer Intern PhD'),
                        dict(description=p.description+' Applications are currently closed.')]:
            self.assertFalse(classify(replace(p, **changes)).accepted)
