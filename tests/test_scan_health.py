import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
import main
from test_filtering import posting
from tracking import Ledger


class ScanHealthTests(unittest.TestCase):
    def test_failed_source_fails_run_after_successful_deliveries_are_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            state = str(Path(directory) / 'state.json')
            Ledger(state, None).save()
            watchers = {'cibc': Mock(return_value=[posting()]),
                        'bmo': Mock(side_effect=requests.HTTPError('429 rate limited'))}
            with patch('main.STATE_FILE', state), patch('main.WATCHERS', watchers), \
                    patch.dict('os.environ', {'DISCORD_WEBHOOK_GENERAL': 'https://example.test', 'DRY_RUN': '0'}), \
                    patch('main._send_posting') as send, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'failed sources: bmo'):
                    main.main()
                send.assert_called_once()
                self.assertEqual([j['status'] for j in Ledger(state, None).jobs if j['company']=='cibc'], ['sent'])
                # The subsequent scan must not resend successful notifications.
                with self.assertRaises(RuntimeError):
                    main.main()
                self.assertEqual(send.call_count, 1)

    def test_successful_empty_board_is_not_a_fetch_failure(self):
        failures = []
        with patch('main.WATCHERS', {'shopify': Mock(return_value=[])}):
            self.assertEqual(main.run_all_watchers(failures), [])
        self.assertEqual(failures, [])
