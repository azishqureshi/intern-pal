import unittest
from scripts.audit_schedule import summarize, timestamp


class ScheduleAuditTests(unittest.TestCase):
    def test_empty_window_exposes_outage(self):
        result = summarize([], timestamp('2026-11-08T00:00:00Z'),
                           timestamp('2026-11-09T00:00:00Z'), 'external')
        self.assertEqual(result['largest_uncovered_minutes'], 1440)
        self.assertIsNone(result['median_gap_minutes'])

    def test_manual_and_rerun_cannot_mask_external_outage(self):
        runs = [dict(id=i, event='workflow_dispatch', run_attempt=attempt,
                     created_at='2026-11-08T00:30:00Z', conclusion='success',
                     display_title='Notify Canada Internships | workflow_dispatch | ' + label)
                for i, attempt, label in [(1, 1, 'manual'), (2, 2, 'external-scheduler'),
                                          (3, 1, 'external-scheduler')]]
        result = summarize(runs, timestamp('2026-11-08T00:00:00Z'),
                           timestamp('2026-11-08T02:00:00Z'), 'external')
        self.assertEqual(result['run_ids'], [3])
        self.assertEqual(result['largest_uncovered_minutes'], 90)

    def test_requires_explicit_timezone(self):
        with self.assertRaises(ValueError):
            timestamp('2026-11-08T00:00:00')
