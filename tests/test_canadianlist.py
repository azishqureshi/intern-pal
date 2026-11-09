import contextlib
from dataclasses import replace
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from main import CHANNELS, _build_fields, _posting_matches_channel, process_postings
from tracking import Ledger
from watchers import canadianlist


HEADER = """# Canadian Tech Internships
## Listings
| Company | Role | Location | Apply | Posted |
| --- | --- | --- | --- | --- |
"""


def row(company, role, url, location='Toronto, ON, Canada', date='Nov 7, 2026'):
    return f'| {company} | {role} | {location} | {url} | {date} |\n'


def response(status=302, location=None, content=''):
    result = Mock()
    result.status_code = status
    result.headers = {'Location': location} if location else {}
    result.text = content
    return result


class CanadianListTests(unittest.TestCase):
    def setUp(self):
        clock = patch('watchers.canadianlist.datetime', wraps=datetime)
        mocked = clock.start()
        self.addCleanup(clock.stop)
        mocked.now.return_value = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

    def test_all_terms_disciplines_and_old_dates_are_preserved(self):
        md = HEADER + ''.join(row('Example', title, f'[Apply](https://example.test/jobs/{i})',
                                 date='Jan 1, 2025')
                              for i, title in enumerate([
                                  'Software Intern (Summer 2027)', 'Hardware Co-op (Winter 2027)',
                                  'Product Management Intern (Fall 2027)', 'PhD Research Intern']))
        jobs = canadianlist.parse_readme(md)
        self.assertEqual(len(jobs), 4)
        self.assertEqual([p.term for p in jobs], ['2027-summer', '2027-winter', '2027-fall', ''])
        self.assertTrue(all(p.age is None and p.posted_at == '2025-01-01' for p in jobs))
        self.assertTrue(all(not _posting_matches_channel(p, CHANNELS[0]) for p in jobs))

    def test_date_cutoff_rejects_old_unknown_and_future_dates(self):
        job = canadianlist.parse_readme(HEADER + row('Example', 'Intern',
                    '[Apply](https://example.test/new)'))[0]
        self.assertTrue(_posting_matches_channel(job, CHANNELS[0]))
        for value in ['2026-11-06', '2026-10-15', '2026-09-09', None, '',
                      'invalid', '2026-02-30', '2026-11-08']:
            with self.subTest(value=value):
                self.assertFalse(_posting_matches_channel(replace(job, posted_at=value), CHANNELS[0]))
        self.assertTrue(canadianlist.is_recent(replace(job, posted_at='2026-11-06'), 1))
        self.assertFalse(canadianlist.is_recent(replace(job, posted_at='2026-11-05'), 1))
        self.assertIn({'name': 'Posted (source date)', 'value': '2026-11-07', 'inline': True},
                      _build_fields(job))

    def test_stale_changed_links_never_send_but_fresh_rows_do(self):
        # Matches the board's continuation rows and stale alerts. A fresh row
        # after an old one must still be considered if the board is reordered.
        md = HEADER + row('Qualcomm', 'Digital Design Engineer Intern',
                          '[Apply](https://example.test/new1)')
        md += row('↳', 'RF/Analog Verification Engineer Intern',
                  '[Apply](https://example.test/new2)')
        for company, posted in [('SiTime', 'Oct 15, 2026'), ('Intel', 'Sep 9, 2026'),
                                ('Microsoft', 'Oct 14, 2026')]:
            md += row(company, 'Engineering Intern', f'[Apply](https://example.test/{company}/changed)', date=posted)
        md += row('Fresh Employer', 'Intern', '[Apply](https://example.test/new3)')
        jobs = canadianlist.parse_readme(md)
        self.assertEqual([p.company for p in jobs[:2]], ['Qualcomm', 'Qualcomm'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            ledger = Ledger(path, None)
            ledger.state['_source_baselines'] = {'canadianlist': True}
            with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general'}, clear=True), \
                    patch('main._send_posting') as send:
                process_postings(jobs, ledger)
                self.assertEqual([c.args[0].url for c in send.call_args_list],
                                 ['https://example.test/new1', 'https://example.test/new2', 'https://example.test/new3'])
                process_postings(jobs, Ledger(path, None))
                self.assertEqual(send.call_count, 3)

    def test_company_inheritance_and_closed_missing_foreign_links(self):
        md = HEADER + row('**[Example &amp; Co](https://example.test)**', 'Closed intern',
                          '[Closed 🔒](https://example.test/closed)')
        md += row('↳', 'Developer Intern', '[Apply](https://example.test/open)')
        md += row('Foreign Company', 'Software Intern', '[Apply](https://example.test/us)', 'New York, USA')
        md += row('↳', r'Data \| Software Intern', '[Apply](https://example.test/ca)', 'Vancouver, BC')
        md += row('↳', 'No link', '🔒')
        jobs = canadianlist.parse_readme(md)
        self.assertEqual([p.company for p in jobs], ['Example & Co', 'Foreign Company'])
        self.assertEqual(jobs[1].title, 'Data | Software Intern')
        self.assertEqual([p.url for p in jobs], ['https://example.test/open', 'https://example.test/ca'])

    def test_malformed_table_fails_instead_of_silently_empty(self):
        for md in ['', HEADER, HEADER.replace('Apply', 'Changed') + row('Example', 'Intern', 'none'),
                   HEADER + row('↳', 'Intern', '[Apply](https://example.test/job)'),
                   HEADER + '| Example | Truncated |\n']:
            with self.subTest(md=md), self.assertRaises(ValueError):
                canadianlist.parse_readme(md)

    def test_shortener_resolves_without_fetching_employer_and_deduplicates(self):
        short = 'https://go.vansh.nyc/abc?s=y'
        target = 'https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Role_123?utm_source=list'
        md = HEADER + row('CIBC', 'Developer Co-op (Winter 2027)', f'[Apply]({short})')
        md += row('↳', 'Developer Co-op', f'[Apply]({target})')
        session = Mock()
        session.get.return_value = response(status=200, content=md)
        redirected = response(location=target)
        with patch('watchers.canadianlist.requests.head', return_value=redirected) as head:
            jobs = canadianlist.fetch_postings(session)
        head.assert_called_once_with(short, allow_redirects=False, timeout=10)
        redirected.close.assert_called_once()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].url, target.split('?')[0])

    def test_expired_or_looping_shortener_is_skipped_not_sent_as_new_identity(self):
        short = 'https://go.vansh.nyc/abc'
        with patch('watchers.canadianlist.requests.head', side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout):
                canadianlist._resolve_application(short)
        with patch('watchers.canadianlist.requests.head', return_value=response(status=404)):
            self.assertIsNone(canadianlist._resolve_application(short))
        for target in [short, 'file:///private/example']:
            with patch('watchers.canadianlist.requests.head', return_value=response(location=target)):
                self.assertIsNone(canadianlist._resolve_application(short))
        with patch('watchers.canadianlist.requests.head', return_value=response(status=200)):
            self.assertIsNone(canadianlist._resolve_application(short))

    def test_transient_redirect_failure_prevents_a_partial_first_snapshot(self):
        md = HEADER + row('Example', 'Intern', '[Apply](https://go.vansh.nyc/abc)')
        md += row('↳', 'Other Intern', '[Apply](https://example.test/direct)')
        session = Mock()
        session.get.return_value = response(status=200, content=md)
        with patch('watchers.canadianlist.requests.head', side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout):
                canadianlist.fetch_postings(session)

    def test_general_delivery_and_cross_source_history_survive_restart(self):
        jobs = canadianlist.parse_readme(HEADER + row('CIBC', 'Developer Co-op (Winter 2027)',
                    '[Apply](https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Role_123)'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            ledger = Ledger(path, None)
            # An employer record with another Workday slug/site still matches by requisition.
            prior = replace(jobs[0], source='cibc', job_id='123',
                            url='https://cibc.wd3.myworkdayjobs.com/Other/job/Toronto/Other_123')
            ledger.observe(prior).update(status='sent', channel='general')
            ledger.save()
            with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general'}, clear=True), \
                    patch('main._send_posting') as send:
                process_postings(jobs, Ledger(path, None))
                send.assert_not_called()
                fresh = replace(jobs[0], url=jobs[0].url.replace('_123', '_124'))
                process_postings([fresh], Ledger(path, None))
                send.assert_called_once_with(fresh, 'https://example.test/general')
                process_postings([fresh], Ledger(path, None))
                self.assertEqual(send.call_count, 1)

    def test_new_list_dry_run_does_not_send_or_save_history(self):
        jobs = canadianlist.parse_readme(HEADER + row('Example', 'Hardware Intern (Fall 2027)',
                                                    '[Apply](https://example.test/jobs/1)'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()) as output:
                process_postings(jobs, Ledger(path, None), dry_run=True)
            send.assert_not_called()
            self.assertFalse(path.exists())
            self.assertIn('marked 1 existing entries as seen', output.getvalue())

    def test_first_snapshot_is_silent_and_only_future_additions_send(self):
        existing = canadianlist.parse_readme(HEADER + row('CIBC', 'Developer Co-op',
                    '[Apply](https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Role_123)'))
        fresh = replace(existing[0], url=existing[0].url.replace('_123', '_124'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general'}, clear=True), \
                    patch('main._send_posting') as send:
                process_postings(existing, Ledger(path, None))
                send.assert_not_called()
                restarted = Ledger(path, None)
                self.assertEqual(restarted.jobs[0]['status'], 'seen')
                self.assertEqual(restarted.jobs[0]['channel'], '')
                self.assertTrue(restarted.state['_source_baselines']['canadianlist'])
                alias = replace(existing[0], url=existing[0].url.replace('/campus/', '/Other/'),
                                company='Canadian Imperial Bank of Commerce')
                process_postings([alias, fresh], restarted)
                send.assert_called_once_with(fresh, 'https://example.test/general')
                process_postings([alias, fresh], Ledger(path, None))
                self.assertEqual(send.call_count, 1)

    def test_empty_source_does_not_initialize_or_hide_existing_delivery_status(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'state.json', None)
            self.assertIsNone(ledger.baseline_source('canadianlist', []))
            self.assertNotIn('_source_baselines', ledger.state)
            jobs = canadianlist.parse_readme(HEADER + row('Example', 'Intern',
                            '[Apply](https://example.test/job)'))
            for status in ['sent', 'pending']:
                ledger.observe(jobs[0])['status'] = status
                self.assertEqual(ledger.baseline_source('canadianlist', jobs), 0)
                self.assertEqual(ledger.observe(jobs[0])['status'], status)
                ledger.state['_source_baselines'].clear()


if __name__ == '__main__':
    unittest.main()
