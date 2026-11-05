import unittest
from dataclasses import replace
from filtering import classify, extract_term
from models import Posting


def posting(**kwargs):
    base = Posting('cibc', 'CIBC', 'Software Engineering Intern - Summer 2027',
                   'Toronto, ON', None, 'https://cibc.wd3.myworkdayjobs.com/campus/job/Toronto/Intern_123',
                   '123', None, 'Develop software applications in Python. Write unit tests and review code.',
                   'Temporary (Fixed Term)', 'Technology')
    return replace(base, **kwargs)


class FilteringTests(unittest.TestCase):
    def test_software_intern(self):
        self.assertTrue(classify(posting()).accepted)

    def test_business_and_insufficient_evidence(self):
        for title in ['Investment Banking Intern', 'Marketing Intern', 'Business Analyst Co-op',
                      'Human Resources Student', 'Senior Software Engineer Intern',
                      'Software Engineering Intern Talent Pool', 'Software Internship Notifications']:
            with self.subTest(title=title):
                self.assertFalse(classify(posting(title=title)).accepted)
        for desc in ['', 'Join our technology team. Computer science students welcome.',
                     'Use Excel and SQL to report revenue and support developers.']:
            self.assertFalse(classify(posting(description=desc)).accepted)

    def test_unconventional_title(self):
        self.assertTrue(classify(posting(title='Digital Builder Co-op')).accepted)
        self.assertTrue(classify(posting(title='Innovation Fellow', employment_type='Student/Coop (Fixed Term)')).accepted)

    def test_employment_and_location(self):
        for changes in [dict(title='Software Engineer', employment_type='Regular'),
                        dict(title='Software Engineer', employment_type='Full time'),
                        dict(employment_type='Permanent'), dict(location='Remote'),
                        dict(location='San Francisco, CA'), dict(location='London, UK'),
                        dict(title='Software Engineering Intern, PhD')]:
            self.assertFalse(classify(posting(**changes)).accepted, changes)
        self.assertTrue(classify(posting(employment_type='Full time')).accepted)
        self.assertTrue(classify(posting(location='Remote - Canada')).accepted)
        self.assertTrue(classify(posting(location='Toronto, ON, CAN')).accepted)
        self.assertTrue(classify(posting(location='Remote', description=posting().description + ' Work remote from Canada.')).accepted)

    def test_supported_technical_disciplines(self):
        cases = [
            ('Data Engineering Intern', 'Build data pipelines with Python and SQL.'),
            ('Cloud Engineering Intern', 'Provision cloud infrastructure using Terraform and AWS.'),
            ('Cybersecurity Intern', 'Conduct vulnerability assessments and penetration testing.'),
            ('SDET Intern', 'Develop automated test suites using Java.'),
            ('Embedded Software Intern', 'Implement firmware in Rust.'),
            ('Frontend Developer Co-op', 'Develop web applications using React and TypeScript.'),
        ]
        for title, description in cases:
            self.assertTrue(classify(posting(title=title, description=description)).accepted, title)

    def test_technology_in_business_title_is_not_enough(self):
        for title in ['Technology Business Analyst Intern', 'Technology Marketing Co-op', 'UX/UI Designer Intern']:
            self.assertFalse(classify(posting(title=title)).accepted)
        self.assertFalse(classify(posting(title='Software Engineer - Student Services')).accepted)

    def test_terms(self):
        self.assertEqual(extract_term('2027 Summer - Developer'), '2027-summer')
        self.assertEqual(extract_term('Fall 2027'), '2027-fall')


if __name__ == '__main__':
    unittest.main()
