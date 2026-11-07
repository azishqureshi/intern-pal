import contextlib
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from main import CHANNELS, _posting_matches_channel, process_postings
from tracking import Ledger
from watchers import internlist


def job(number=1, **changes):
    result = {
        'jobId': f'{number:024x}', 'tabCategory': ['intern:ca:swe'],
        'postedAt': 1794041244000,
        'properties': {
            'title': 'Software Engineering Intern - Summer 2027', 'company': 'CIBC',
            'location': 'Toronto, ON', 'qualifications': 'Students with Python experience.',
            'isNewGrad': False, 'hireTime': '2027-May',
        },
    }
    result['properties'].update(changes)
    return result


def page(items, total=None):
    response = Mock()
    response.json.return_value = {'success': True, 'result': {
        'jobList': items, 'total': len(items) if total is None else total,
    }}
    return response


class InternListTests(unittest.TestCase):
    def test_all_pages_are_retrieved_and_filtered_to_canadian_interns(self):
        session = Mock()
        first = [job(i) for i in range(1, 51)]
        last = [job(51, location='Vancouver, BC'), job(52, location='San Francisco, CA'),
                job(53, isNewGrad=True)]
        session.post.side_effect = [page(first, 53), page(last, 53)]
        jobs = internlist.fetch_postings(session)
        self.assertEqual(len(jobs), 51)
        self.assertEqual([c.kwargs['params']['position'] for c in session.post.call_args_list], [0, 50])
        for call in session.post.call_args_list:
            self.assertEqual(call.args[0], internlist.SEARCH)
            self.assertEqual(call.kwargs['json'], {'category': 'intern:ca:swe'})
            self.assertEqual(call.kwargs['params']['count'], 50)
        self.assertTrue(all(_posting_matches_channel(p, CHANNELS[0]) for p in jobs))

    def test_stable_url_is_used_without_mislabeling_aggregator_id_as_employer_id(self):
        result = internlist.from_job(job())
        self.assertEqual(result.url, 'https://jobright.ai/jobs/info/000000000000000000000001')
        self.assertIsNone(result.job_id)
        self.assertIsNone(result.age)
        self.assertEqual(result.posted_at, '2026-11-07T08:47:24+00:00')
        self.assertEqual(result.term, '2027-summer')

    def test_winter_and_old_listings_are_not_subject_to_age_or_summer_filters(self):
        item = job(title='Software Developer Co-op - Winter 2027')
        item['postedAt'] = 1700000000000
        result = internlist.from_job(item)
        self.assertEqual(result.term, '2027-winter')
        self.assertTrue(_posting_matches_channel(result, CHANNELS[0]))

    def test_location_is_verified_instead_of_assuming_category_means_canada(self):
        self.assertIsNone(internlist.from_job(job(location='Remote')))
        self.assertIsNone(internlist.from_job(job(location='San Jose, CA')))
        self.assertIsNotNone(internlist.from_job(job(location='Remote',
                               qualifications='Work remote from Canada.')))

    def test_category_or_required_fields_changing_fails_closed(self):
        cases = []
        for key in ['jobId', 'tabCategory', 'properties', 'postedAt']:
            item = job(); del item[key]; cases.append(item)
        for value in [True, 'today', -1, float('inf')]:
            item = job(); item['postedAt'] = value; cases.append(item)
        for key in ['company', 'title', 'location']:
            item = job(); item['properties'][key] = ''; cases.append(item)
        item = job(); item['tabCategory'] = ['intern:us:swe']; cases.append(item)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                internlist.from_job(item)

    def test_errors_and_incomplete_pagination_never_return_a_partial_snapshot(self):
        first = page([job(1)], 2)
        errors = [
            [first, page([], 2)],
            [first, page([job(1)], 2)],
            [first, page([job(2)], 3)],
            [page([job(1), job(1)], 2)],
            [page([job(1)], 0)],
        ]
        malformed = Mock(); malformed.json.return_value = {'success': False, 'errorCode': 401}
        errors.append([malformed])
        malformed = Mock(); malformed.json.return_value = {'success': True, 'result': {'jobList': [], 'total': True}}
        errors.append([malformed])
        for responses in errors:
            session = Mock(); session.post.side_effect = responses
            with self.subTest(responses=responses), self.assertRaises(ValueError):
                internlist.fetch_postings(session)

    def test_explicitly_empty_category_is_a_successful_fetch(self):
        session = Mock(); session.post.return_value = page([], 0)
        self.assertEqual(internlist.fetch_postings(session), [])

    def test_first_scan_is_silent_then_new_entries_send_once_across_restarts(self):
        existing, fresh = [internlist.from_job(job(i)) for i in (1, 2)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test/general'}, clear=True), \
                    patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()):
                process_postings([existing], Ledger(path, None))
                send.assert_not_called()
                restarted = Ledger(path, None)
                self.assertEqual(restarted.jobs[0]['status'], 'seen')
                # A real new job has its own identity, not just a new aggregator ID.
                fresh = replace(fresh, title='Cloud Engineering Intern - Summer 2027')
                process_postings([existing, fresh], restarted)
                send.assert_called_once_with(fresh, 'https://example.test/general')
                process_postings([existing, fresh], Ledger(path, None))
                self.assertEqual(send.call_count, 1)

    def test_shared_employer_history_suppresses_unambiguous_matching_roles(self):
        result = internlist.from_job(job())
        official = replace(result, source='cibc', job_id='123',
                           url='https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Role_123')
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'state.json', None)
            ledger.state['_source_baselines'] = {'internlist': True}
            ledger.observe(official).update(status='sent', channel='general')
            with patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()):
                process_postings([result], ledger)
                send.assert_not_called()
            self.assertEqual(len(ledger.jobs), 1)
            self.assertIn(result.url, ledger.jobs[0]['urls'])

    def test_dry_run_never_sends_or_writes_initial_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()) as output:
                process_postings([internlist.from_job(job())], Ledger(path, None), dry_run=True)
                send.assert_not_called()
            self.assertFalse(path.exists())
            self.assertIn('internlist: marked 1 existing entries as seen', output.getvalue())


if __name__ == '__main__':
    unittest.main()
