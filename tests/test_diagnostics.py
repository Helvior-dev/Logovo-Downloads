import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import diagnostics


class FakeSettings:
    def __init__(self, values, settings_file=None):
        self.values = values
        self.settings_file = settings_file

    def get(self, key, default=None):
        return self.values.get(key, default)


class DiagnosticsTests(unittest.TestCase):
    def test_self_diagnostics_are_local_and_do_not_make_network_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / 'downloads'
            output_dir.mkdir()
            settings = FakeSettings(
                {'download_path': str(output_dir), 'cookies_source': 'none'},
                settings_file=Path(temp_dir) / 'settings.json',
            )

            with patch.object(diagnostics, 'get_installed_ytdlp_version', return_value='2026.01.01'), patch.object(
                diagnostics, 'get_ffmpeg_path', return_value=None
            ), patch.object(diagnostics, 'get_ffprobe_path', return_value=None), patch.object(
                diagnostics.requests, 'get'
            ) as network_get:
                results = diagnostics.run_self_diagnostics(settings)

            network_get.assert_not_called()
            by_name = {result['name']: result for result in results}
            self.assertEqual(by_name['yt-dlp']['status'], 'OK')
            self.assertEqual(by_name['Download folder']['status'], 'OK')
            self.assertEqual(by_name['FFmpeg']['status'], 'WARN')
            self.assertEqual(by_name['Cookies']['status'], 'INFO')

    def test_cookie_diagnostics_never_display_cookie_contents(self):
        settings = FakeSettings({
            'cookies_source': 'file',
            'cookies_file': 'D:/private/cookies.txt',
        })
        with patch.object(diagnostics, 'is_valid_netscape_cookies', return_value=True):
            result = diagnostics._check_cookie_configuration(settings)

        self.assertEqual(result['status'], 'OK')
        self.assertNotIn('D:/private/cookies.txt', result['details'])

    def test_network_diagnostics_probe_each_service_only_when_called(self):
        responses = [Mock(status_code=204), Mock(status_code=200), Mock(status_code=403)]
        with patch.object(diagnostics.requests, 'get', side_effect=responses) as network_get:
            results = diagnostics.run_network_diagnostics(timeout=2)

        self.assertEqual([result['status'] for result in results], ['OK', 'OK', 'WARN'])
        self.assertEqual(network_get.call_count, 3)
        for response in responses:
            response.close.assert_called_once()
        self.assertTrue(all(call.kwargs['stream'] for call in network_get.call_args_list))

    def test_network_failures_are_reported_per_service(self):
        with patch.object(diagnostics.requests, 'get', side_effect=diagnostics.requests.Timeout('timed out')):
            results = diagnostics.run_network_diagnostics(timeout=1)

        self.assertEqual(len(results), 3)
        self.assertTrue(all(result['status'] == 'FAIL' for result in results))


if __name__ == '__main__':
    unittest.main()
