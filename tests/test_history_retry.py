import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.history import (
    HistoryManager,
    get_retryable_error_entries,
    snapshot_download_settings,
)
from ui.main_window import MainWindow
from ui.workers import DownloadSettingsOverlay


class HistoryRetryTests(unittest.TestCase):
    def test_new_history_entry_keeps_retry_settings_but_never_cookies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('core.history.get_app_data_dir', return_value=Path(temp_dir)):
                history = HistoryManager()
                history.add_entry(
                    'Track',
                    'Artist',
                    status='Error: network failure',
                    url='https://example.com/video',
                    media_type='Audio (FLAC)',
                    download_options={
                        'source_url': 'https://example.com/video',
                        'output_dir': 'D:/Music',
                        'media_type': 'Audio (FLAC)',
                        'quality': 'Best Audio',
                        'subtitles': {'download': False, 'langs': 'none'},
                        'settings': {
                            'audio_metadata_tags': {'artist': True, 'title': False},
                            'video_codec': 'h265',
                            'cookies_file': 'D:/private/cookies.txt',
                        },
                        'cookies': {'file': 'D:/private/cookies.txt'},
                    },
                )

                stored = history.get_all()[0]
                options = stored['download_options']
                self.assertEqual(options['quality'], 'Best Audio')
                self.assertEqual(options['subtitles'], {'download': False, 'langs': 'none'})
                self.assertEqual(options['settings']['audio_metadata_tags'], {'artist': True, 'title': False})
                self.assertNotIn('cookies', options)
                self.assertNotIn('cookies_file', options['settings'])

                reloaded = HistoryManager()
                self.assertEqual(reloaded.get_all()[0]['download_options'], options)

    def test_retryable_history_contains_only_errors_with_urls(self):
        entries = [
            {'status': 'Unavailable', 'url': 'https://example.com/resolved', 'type': 'Audio (Best)'},
            {'status': 'Error: older failure', 'url': 'https://example.com/resolved', 'type': 'Audio'},
            {'status': 'Error: failed', 'url': 'https://example.com/1'},
            {'status': 'Deleted from platform', 'url': 'https://example.com/2'},
            {'status': 'Completed', 'url': 'https://example.com/3'},
            {'status': 'Error: missing URL'},
        ]

        self.assertEqual(get_retryable_error_entries(entries), [entries[2]])

    def test_settings_snapshot_excludes_cookie_configuration_and_overlay_falls_back(self):
        class Settings:
            values = {
                'video_codec': 'h265',
                'cookies_source': 'file',
                'cookies_file': 'D:/private/cookies.txt',
                'max_concurrent_downloads': 4,
            }

            def get(self, key, default=None):
                return self.values.get(key, default)

        current = Settings()
        snapshot = snapshot_download_settings(current)
        self.assertEqual(snapshot['video_codec'], 'h265')
        self.assertNotIn('cookies_source', snapshot)
        self.assertNotIn('cookies_file', snapshot)
        self.assertNotIn('max_concurrent_downloads', snapshot)

        overlay = DownloadSettingsOverlay(current, {'video_codec': 'h264'})
        self.assertEqual(overlay.get('video_codec'), 'h264')
        self.assertEqual(overlay.get('max_concurrent_downloads'), 4)

    def test_retry_uses_visible_media_type_saved_options_and_current_cookie_source(self):
        class Settings:
            values = {
                'cookies_source': 'file',
                'cookies_file': 'D:/current/cookies.txt',
                'speed_limit': '20 MB/s',
                'download_path': 'D:/current/downloads',
                'filename_compat': 'windows',
            }

            def get(self, key, default=None):
                return self.values.get(key, default)

            def get_quality(self, platform):
                return 'Current quality'

        class Signal:
            def connect(self, callback):
                pass

        class FakeWorker:
            def __init__(self):
                self.progress_signal = Signal()
                self.finished_signal = Signal()
                self.finished = Signal()

            def start(self):
                pass

        class Widget:
            set_status = Mock()
            item_data = {
                'url': 'https://www.youtube.com/watch?v=video-id',
                'title': 'Saved title',
                'uploader': 'Saved artist',
                'media_type': 'Video (H.265)',
                'media_type_category': 'Video',
                'format_compat': 'unix/win',
                'download_options': {
                    'source_url': 'https://www.youtube.com/watch?v=video-id',
                    'output_dir': 'D:/saved/location',
                    'media_type': 'Video (H.265)',
                    'media_type_category': 'Video',
                    'quality': 'Saved quality',
                    'subtitles': {'download': True, 'langs': 'uk'},
                    'speed_limit': '3 MB/s',
                    'naming_pattern': 'saved-{title}',
                    'format_compat': 'unix/win',
                    'playlist_index': 4,
                    'playlist_count': 10,
                    'settings': {'video_codec': 'h265', 'video_container': 'mkv'},
                },
            }

            class FormatCombo:
                def currentText(self):
                    return 'Video (Best)'

            format_combo = FormatCombo()

        class Window:
            settings = Settings()
            widget_start_times = {}
            active_workers = {}

            def update_queue_ui(self):
                pass

            def _save_queue(self):
                pass

        window = Window()
        widget = Widget()
        fake_worker = FakeWorker()
        captured = {}

        def create_worker(**kwargs):
            captured.update(kwargs)
            return fake_worker

        with patch('ui.main_window.WorkerThread', side_effect=create_worker):
            MainWindow.start_worker_for_widget(window, widget)

        self.assertEqual(captured['url'], 'https://www.youtube.com/watch?v=video-id')
        self.assertEqual(captured['output_dir'], 'D:/saved/location')
        self.assertEqual(captured['media_type'], 'Video (Best)')
        widget.set_status.assert_called_once_with('Starting download...', 'Downloading')
        self.assertEqual(widget.item_data['download_options']['media_type'], 'Video (Best)')
        self.assertEqual(captured['quality'], 'Saved quality')
        self.assertEqual(captured['subtitles'], {'download': True, 'langs': 'uk'})
        self.assertEqual(captured['speed_limit'], '3 MB/s')
        self.assertEqual(captured['naming_pattern'], 'saved-{title}')
        self.assertEqual(captured['format_compat'], 'unix/win')
        self.assertEqual(captured['cookies'], {
            'use': True,
            'source': 'file',
            'file': 'D:/current/cookies.txt',
        })
        self.assertEqual(captured['settings'].get('video_codec'), 'h265')
        self.assertEqual(captured['settings'].get('video_container'), 'mkv')


if __name__ == '__main__':
    unittest.main()
