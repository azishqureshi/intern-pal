import unittest
from unittest.mock import patch
from main import CHANNELS, _posting_matches_channel
from watchers import simplifyjobs

README = '''# Internships
## Software Engineering Internship Roles
| Company | Role | Location | Application | Age |
| --- | --- | --- | --- | --- |
| CIBC | Software Intern | Toronto, Canada | <a href="https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Role_123?utm_source=Simplify">Apply</a> | 0d |
| ↳ | Closed Different Role | Toronto, Canada | 🔒 | 0d |
| RBC | Software Intern | New York, USA | <a href="https://example.test/us">Apply</a> | 0d |
| ↳ | Developer Intern | Vancouver, Canada | <a href="https://example.test/ca">Apply</a> | 0d |
| Shopify | Developer Intern | Remote, Canada | <a href="https://example.test/older">Apply</a> | 2d |
## Other internships
'''


class SimplifyTests(unittest.TestCase):
    def test_existing_filter_and_confirmed_link_company_bugs(self):
        with patch.object(simplifyjobs, 'fetch_readme_raw', return_value=README):
            jobs = simplifyjobs.fetch_postings()
        self.assertEqual(len(jobs), 3)
        self.assertEqual([j.company for j in jobs], ['CIBC', 'RBC', 'Shopify'])
        self.assertEqual(jobs[1].url, 'https://example.test/ca')
        with patch.dict('os.environ', {}, clear=True):
            self.assertTrue(_posting_matches_channel(jobs[0], CHANNELS[0]))
            self.assertFalse(_posting_matches_channel(jobs[2], CHANNELS[0]))

    def test_official_link_preference_unchanged(self):
        cell = '<a href="https://simplify.jobs/p/123">Simplify</a><a href="https://example.test/apply">Apply</a>'
        self.assertEqual(simplifyjobs.extract_link_from_cell(cell), 'https://example.test/apply')
