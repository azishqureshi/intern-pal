import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import requests

from main import process_postings, run_all_watchers
from tracking import Ledger, identity, same_job, url_req_id, state_lock
from test_filtering import posting


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.ledger = Ledger(self.path, None)
        self.official = posting()
        self.simplify = replace(self.official, source='simplifyjobs', job_id=None,
                                company='Canadian Imperial Bank of Commerce', age='0d',
                                location='Toronto, Ontario, Canada', title='Software Developer Co-op',
                                url='https://cibc.wd3.myworkdayjobs.com/en-US/CIBC_EX_Career_Site/job/Toronto/Different-title_123?utm_source=Simplify')
        self.env = patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general',
                                           'DISCORD_WEBHOOK_CIBC': 'https://example.test/cibc'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_cross_source_one_notification_official_url(self):
        with patch('main._send_posting') as send:
            process_postings([self.simplify, self.official, self.official], self.ledger)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0].url, self.official.url)
            self.assertEqual(send.call_args.args[1], 'https://example.test/general')

    def test_restart_and_later_source(self):
        with patch('main._send_posting') as send:
            process_postings([self.simplify], self.ledger)
            restarted = Ledger(self.path, None)
            process_postings([self.official], restarted)
            process_postings([self.simplify], restarted)
            self.assertEqual(send.call_count, 1)

    def test_different_requisitions(self):
        other = replace(self.official, job_id='124', url=self.official.url.replace('_123','_124'))
        with patch('main._send_posting') as send:
            process_postings([self.official, other], self.ledger)
            self.assertEqual(send.call_count, 2)

    def test_strong_fallback_and_distinct_team_location_term(self):
        a = replace(self.official, job_id=None, url='https://example.test/one')
        b = replace(a, url='https://example.test/two', title='Software Development Co-op - Summer 2027', location='Toronto, Ontario, Canada')
        self.assertTrue(same_job(identity(a), identity(b)))
        for change in [dict(title=a.title+' - Payments'), dict(location='Vancouver, BC'),
                       dict(title=a.title.replace('2027', '2028')),
                       dict(title='Software Engineering Intern', term='')]:
            self.assertFalse(same_job(identity(a), identity(replace(b, **change))), change)
        # No term evidence: don't join recurring generic titles.
        a = replace(a, title='Software Intern')
        self.assertFalse(same_job(identity(a), identity(replace(a, url='https://example.test/three'))))

    def test_ambiguous_metadata_does_not_repeat_on_restart(self):
        a = self.ledger.observe(self.official)
        b = self.ledger.observe(replace(self.official, job_id='124', url='https://example.test/124'))
        a['status'] = b['status'] = 'sent'
        unknown = replace(self.official, job_id=None, url='https://example.test/unknown')
        with patch('main._send_posting') as send:
            process_postings([unknown], self.ledger)
            process_postings([unknown], Ledger(self.path, None))
            self.assertEqual(send.call_count, 1)

    def test_official_ids_across_other_employers(self):
        cases = [
            ('RBC', 'Royal Bank of Canada', 'R-0000187114',
             'https://rbc.wd3.myworkdayjobs.com/rbcglobal1/job/Toronto/Developer_R-0000187114-1'),
            ('BMO', 'Bank of Montreal', 'R260026951',
             'https://jobs.bmo.com/global/en/job/BOMOGLOBALR260026951EXTERNALENCA/Role'),
            ('TD', 'TD Bank', 'R_1510256',
             'https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/Toronto/Role_R_1510256'),
            ('Amazon', 'AWS', '10553947',
             'https://amazon.jobs/en/jobs/10553947/role?utm_source=Simplify'),
            ('Google', 'Google Canada', '123456',
             'https://www.google.com/about/careers/applications/jobs/results/123456-role'),
            ('Shopify', 'Shopify', '404bb82e-37f3-4a78-b0f3-12923a7c4856',
             'https://jobs.ashbyhq.com/shopify/404bb82e-37f3-4a78-b0f3-12923a7c4856/application'),
        ]
        for company, alias, req, url in cases:
            a = replace(self.official, company=company, job_id=req, url='https://example.test/official')
            b = replace(a, company=alias, job_id=None, url=url, title='Different title')
            self.assertTrue(same_job(identity(a), identity(b)), company)
        a = replace(self.official, company='Scotiabank', job_id='273053',
                    url='https://jobs.scotiabank.com/job/Toronto-Role/605897917/')
        b = replace(a, job_id=None, url='https://jobs.scotiabank.com/job/Different-slug/605897917/?utm_source=Simplify')
        self.assertTrue(same_job(identity(a), identity(b)))

    def test_no_delivery_when_state_cannot_be_reserved(self):
        with patch.object(self.ledger, 'save', side_effect=OSError('Disk full')), patch('main._send_posting') as send:
            with self.assertRaises(OSError): process_postings([self.official], self.ledger)
            send.assert_not_called()

    def test_general_destination_and_missing_webhook(self):
        with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general'}, clear=True):
            with patch('main._send_posting') as send:
                process_postings([self.official], self.ledger)
                self.assertEqual(send.call_args.args[1], 'https://example.test/general')
        fresh = replace(self.official, job_id='999', url='https://example.test/999')
        with patch.dict('os.environ', {}, clear=True), patch('main._send_posting') as send:
            process_postings([fresh], self.ledger)
            send.assert_not_called()
            self.assertEqual(self.ledger.observe(fresh)['status'], 'discovered')

    def test_company_scoped_ids(self):
        self.assertFalse(same_job(identity(self.official), identity(replace(self.official, company='RBC', url='https://example.test/rbc'))))

    def test_workday_ids(self):
        for slug, expected in [('Role_R-00001234-1', 'r00001234'), ('Role_R_1510256', 'r1510256'),
                               ('Role_2611289-1', '2611289'), ('Role_R26_109', 'r26109')]:
            self.assertEqual(url_req_id('https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/'+slug), expected)

    def test_history_preserved_and_imported(self):
        old = {'general': [self.simplify.url, '123'], 'amd': ['123'], 'cibc': []}
        self.path.write_text(json.dumps(old))
        ledger = Ledger(self.path, None)
        with patch('main._send_posting') as send:
            process_postings([self.official], ledger)
            send.assert_not_called()
        saved = json.loads(self.path.read_text())
        for key in old:
            self.assertEqual(saved[key], old[key])
        self.assertEqual(ledger.observe(replace(self.official, company='AMD', url=None))['status'], 'sent')
        legacy = Path(self.tmp.name)/'notified.json'
        legacy.write_text(json.dumps([self.simplify.url]))
        self.assertEqual(Ledger(Path(self.tmp.name)/'new.json', legacy).observe(self.official)['status'], 'sent')

    def test_corrupt_state_fails_closed(self):
        for raw in ['{', '[]', '{"general": "oops"}', '{"_version": 3}']:
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                Ledger(self.path, None)

    def test_ambiguous_delivery_not_retried(self):
        with patch('main._send_posting', side_effect=requests.Timeout) as send:
            process_postings([self.official], self.ledger)
            process_postings([self.official], Ledger(self.path, None))
            self.assertEqual(send.call_count, 1)
            self.assertEqual(Ledger(self.path, None).jobs[0]['status'], 'pending')

    def test_rejected_delivery_is_retryable(self):
        response = requests.Response(); response.status_code = 429
        with patch('main._send_posting', side_effect=requests.HTTPError(response=response)):
            process_postings([self.official], self.ledger)
        with patch('main._send_posting') as send:
            process_postings([self.official], Ledger(self.path, None))
            send.assert_called_once()

    def test_local_lock_prevents_overlapping_sends(self):
        with state_lock(self.path):
            with self.assertRaises(BlockingIOError):
                with state_lock(self.path):
                    self.fail('Second notifier acquired the same lock')

    def test_dry_run_no_writes_or_messages(self):
        with patch('main._send_posting') as send:
            process_postings([self.official], self.ledger, dry_run=True)
            send.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_failed_watcher_does_not_stop_others(self):
        def fail(): raise requests.Timeout()
        with patch('main.WATCHERS', {'bad': fail, 'good': lambda: [self.official]}):
            self.assertEqual(run_all_watchers(), [self.official])


if __name__ == '__main__': unittest.main()
