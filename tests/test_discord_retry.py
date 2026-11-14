import unittest
from unittest.mock import Mock, patch
import requests
from utils import send_discord_webhook


class DiscordRetryTests(unittest.TestCase):
    def send(self):
        send_discord_webhook('https://example.test', 'Title', '', None, [])

    @patch('utils.time.sleep')
    @patch('utils.requests.post')
    def test_explicit_rate_limit_waits_then_retries(self, post, sleep):
        limited = Mock(status_code=429)
        limited.json.return_value = {'retry_after': 1.5}
        post.side_effect = [limited, Mock(status_code=204)]
        self.send()
        sleep.assert_called_once_with(1.6)
        self.assertEqual(post.call_count, 2)

    @patch('utils.time.sleep')
    @patch('utils.requests.post')
    def test_retries_are_bounded(self, post, sleep):
        limited = Mock(status_code=429)
        limited.json.return_value = {'retry_after': 0.5}
        limited.raise_for_status.side_effect = requests.HTTPError()
        post.return_value = limited
        with self.assertRaises(requests.HTTPError):
            self.send()
        self.assertEqual(post.call_count, 4)

    @patch('utils.requests.post', side_effect=requests.Timeout)
    def test_ambiguous_timeout_is_not_retried(self, post):
        with self.assertRaises(requests.Timeout):
            self.send()
        post.assert_called_once()
