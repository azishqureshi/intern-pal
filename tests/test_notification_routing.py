"""Exercise the real notification pipeline, mocking only sources and HTTP.

No webhook credentials, network requests, or production history are used.
"""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from main import WATCHERS, process_postings, run_all_watchers
from test_filtering import posting
from tracking import Ledger

GENERAL = 'https://example.test/general'
ENV = {
    'DISCORD_WEBHOOK_GENERAL': GENERAL,
    'DISCORD_WEBHOOK_CIBC': 'https://example.test/obsolete-cibc',
    'DISCORD_WEBHOOK_AMD': 'https://example.test/obsolete-amd',
}


class NotificationRoutingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'state.json'
        self.ledger = Ledger(self.path, None)
        self.cibc = posting()
        self.amd = posting(source='amd', company='AMD', location='CA,ON,Markham',
                           job_id='84637', url='https://careers.amd.com/careers-home/jobs/84637',
                           description='')
        env = patch.dict('os.environ', ENV, clear=True)
        env.start()
        self.addCleanup(env.stop)
        http = patch('utils.requests.post')
        self.http = http.start()
        self.addCleanup(http.stop)

    def test_cibc_and_amd_use_general_with_existing_embed_fields(self):
        process_postings([self.cibc, self.amd], self.ledger)
        self.assertEqual(self.http.call_count, 2)
        for call, job in zip(self.http.call_args_list, [self.cibc, self.amd]):
            self.assertEqual(call.args[0], GENERAL)
            self.assertEqual(call.kwargs['params'], {'wait': 'true'})
            embed = call.kwargs['json']['embeds'][0]
            self.assertEqual(embed['title'], 'New Internship: ' + job.company)
            self.assertEqual(embed['url'], job.url)
            self.assertEqual(embed['description'], f'[View posting]({job.url})')
            fields = {field['name']: field['value'] for field in embed['fields']}
            self.assertEqual(fields['Company'], job.company)
            self.assertEqual(fields['Role'], job.title)
            self.assertEqual(fields['Location'], job.location)
            self.assertEqual(fields['Source'], job.source)
            self.assertEqual(fields['Job ID'], job.job_id)
        self.assertTrue(all(j['status'] == 'sent' and j['channel'] == 'general'
                            for j in Ledger(self.path, None).jobs))

    def test_all_sources_share_general_and_duplicates_stay_suppressed_after_restart(self):
        # This test exercises delivery after the new source's first-scan baseline.
        self.ledger.state['_source_baselines'] = {'canadianlist': True, 'internlist': True}
        companies = {'simplifyjobs': 'Example', 'amd': 'AMD', 'cibc': 'CIBC',
                     'rbc': 'RBC', 'bmo': 'BMO', 'td': 'TD', 'scotiabank': 'Scotiabank',
                     'shopify': 'Shopify', 'google': 'Google', 'amazon': 'Amazon',
                     'canadianlist': 'Canadian List Employer', 'internlist': 'Intern List Employer'}
        jobs = [posting(source=source, company=companies[source], job_id=str(2000+i),
                        location='Toronto, ON, Canada', url=f'https://example.test/jobs/{2000+i}',
                        age='0d' if source == 'simplifyjobs' else None,
                        posted_at=datetime.now(timezone.utc).isoformat())
                for i, source in enumerate(WATCHERS)]
        sources = {job.source: (lambda job=job: [job]) for job in jobs}
        duplicates = [replace(job, source='simplifyjobs', age='0d', job_id=None)
                      for job in jobs if job.source in ('cibc', 'amd')]
        with patch('main.WATCHERS', sources):
            discovered = run_all_watchers() + duplicates
        process_postings(discovered, self.ledger)
        self.assertEqual(self.http.call_count, len(WATCHERS))
        self.assertTrue(all(call.args[0] == GENERAL for call in self.http.call_args_list))
        process_postings(discovered, Ledger(self.path, None))
        self.assertEqual(self.http.call_count, len(WATCHERS))

    def test_legacy_dedicated_channel_history_is_not_reposted_to_general(self):
        old = {'general': [], 'cibc': ['123'], 'amd': ['84637']}
        self.path.write_text(json.dumps(old))
        process_postings([self.cibc, self.amd], Ledger(self.path, None))
        self.http.assert_not_called()
        saved = json.loads(self.path.read_text())
        for key, values in old.items():
            self.assertEqual(saved[key], values)
        process_postings([self.cibc, self.amd], Ledger(self.path, None))
        self.http.assert_not_called()

    def test_existing_shared_ledger_keeps_old_delivery_channels(self):
        for job in [self.cibc, self.amd]:
            record = self.ledger.observe(job)
            record.update(status='sent', channel=job.source)
        self.ledger.save()
        process_postings([self.cibc, self.amd], Ledger(self.path, None))
        self.http.assert_not_called()
        self.assertEqual([j['channel'] for j in Ledger(self.path, None).jobs], ['cibc', 'amd'])

    def test_obsolete_webhooks_are_not_used_when_general_is_missing(self):
        with patch.dict('os.environ', {k: v for k, v in ENV.items() if k != 'DISCORD_WEBHOOK_GENERAL'}, clear=True):
            process_postings([self.cibc, self.amd], self.ledger)
        self.http.assert_not_called()
        self.assertTrue(all(j['status'] == 'discovered' for j in Ledger(self.path, None).jobs))


if __name__ == '__main__':
    unittest.main()
