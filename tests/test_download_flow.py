import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from core.downloader import MediaDownloader


class SettingsStub:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeYoutubeDL:
    actions = []
    instances = []
    player_clients = []
    download_urls = []
    search_result = {}
    extract_error = None

    def __init__(self, options):
        self.options = options
        type(self).instances.append(self)
        type(self).player_clients.append(
            list(options["extractor_args"]["youtube"]["player_client"])
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def download(self, urls):
        type(self).download_urls.append(list(urls))
        action = type(self).actions.pop(0)
        return action(self, urls)

    def extract_info(self, url, download=False):
        self.extract_info_call = (url, download)
        if type(self).extract_error:
            raise type(self).extract_error
        return type(self).search_result


def make_downloader(output_dir, settings=None):
    downloader = MediaDownloader.__new__(MediaDownloader)
    downloader.output_dir = str(output_dir)
    downloader.settings = settings or SettingsStub()
    downloader.format_compat = None
    downloader.last_error = ""
    downloader.was_skipped = False
    downloader.was_cancelled = False
    return downloader


def finish_with_file(path, info):
    def action(ydl, urls):
        path.write_bytes(b"downloaded media")
        event = {
            "status": "finished",
            "filepath": str(path),
            "filename": str(path),
            "info_dict": {**info, "filepath": str(path)},
        }
        for hook in ydl.options["progress_hooks"]:
            hook(event)
        return 0

    return action


class DownloadFlowTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.actions = []
        FakeYoutubeDL.instances = []
        FakeYoutubeDL.player_clients = []
        FakeYoutubeDL.download_urls = []
        FakeYoutubeDL.search_result = {}
        FakeYoutubeDL.extract_error = None

    def test_interrupted_download_preserves_partial_file_for_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            partial = output_dir / "clip.f401.mp4.part"
            interrupted = False

            def pause_mid_download(ydl, _urls):
                nonlocal interrupted
                partial.write_bytes(b"partial video")
                interrupted = True
                ydl.options["progress_hooks"][0]({"status": "downloading"})
                return 0

            FakeYoutubeDL.actions = [pause_mid_download]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=video-id",
                    media_type="Video (Best)",
                    cancel_check=lambda: interrupted,
                )

            self.assertEqual(result, (False, "", False))
            self.assertTrue(downloader.was_cancelled)
            self.assertTrue(partial.exists())
            self.assertTrue(FakeYoutubeDL.instances[0].options["continuedl"])

    def test_http_416_retries_fresh_without_overwriting_original_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            partial = output_dir / "song.webm.part"
            partial.write_bytes(b"original saved bytes")
            media_path = output_dir / "song.mp3"

            def rejected_resume(ydl, _urls):
                ydl.options["logger"].error(
                    "unable to download video data: HTTP Error 416: Requested range not satisfiable"
                )
                return 1

            FakeYoutubeDL.actions = [
                rejected_resume,
                finish_with_file(media_path, {"id": "abcdefghijk", "title": "Song"}),
            ]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **kwargs: path):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk", media_type="Audio (Best)"
                )

            self.assertEqual(result, (True, "", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 2)
            self.assertTrue(FakeYoutubeDL.instances[0].options["continuedl"])
            retry_options = FakeYoutubeDL.instances[1].options
            self.assertFalse(retry_options["continuedl"])
            self.assertEqual(retry_options["outtmpl"]["default"], FakeYoutubeDL.instances[0].options["outtmpl"])
            self.assertIn(".retry-", retry_options["outtmpl"]["temp"])
            self.assertEqual(partial.read_bytes(), b"original saved bytes")

    def test_http_416_fresh_retry_failure_still_preserves_original_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            partial = output_dir / "song.webm.part"
            partial.write_bytes(b"original saved bytes")

            def fail(ydl, _urls):
                ydl.options["logger"].error("unable to download video data: HTTP Error 416")
                return 1

            FakeYoutubeDL.actions = [fail, fail]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ):
                result = make_downloader(output_dir).download(
                    "https://www.youtube.com/watch?v=abcdefghijk", media_type="Audio (Best)"
                )

            self.assertFalse(result[0])
            self.assertIn("416", result[1])
            self.assertEqual(len(FakeYoutubeDL.instances), 2)
            self.assertEqual(partial.read_bytes(), b"original saved bytes")

    def test_audio_success_builds_expected_options_and_postprocesses_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "downloaded.mp3"
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "abcdefghijk",
                "title": "Extracted Song",
                "artist": "Extracted Artist",
                "album": "Album",
                "release_year": 2020,
                "thumbnail": "https://example.invalid/cover.jpg",
            })]
            progress_events = []

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path) as postprocess, patch(
                "core.downloader.cleanup_orphan_files"
            ) as cleanup:
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk&utm_source=test",
                    media_type="Audio (MP3)",
                    quality="Best",
                    title="Requested Song",
                    author="Requested Artist",
                    speed_limit="1 MB/s",
                    progress_callback=progress_events.append,
                )

            self.assertEqual(result, (True, "", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 1)
            options = FakeYoutubeDL.instances[0].options
            self.assertEqual(options["format"], "bestaudio/best")
            self.assertEqual(options["ratelimit"], 1024 * 1024)
            self.assertEqual(options["postprocessors"], [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }])
            self.assertEqual(progress_events[0]["status"], "finished")
            postprocess.assert_called_once()
            self.assertEqual(postprocess.call_args.args[0], media_path)
            self.assertEqual(postprocess.call_args.kwargs["artist"], "Requested Artist")
            self.assertEqual(postprocess.call_args.kwargs["title"], "Requested Song")
            self.assertEqual(postprocess.call_args.kwargs["album"], "Album")
            self.assertEqual(postprocess.call_args.kwargs["year"], "2020")
            self.assertEqual(
                postprocess.call_args.kwargs["thumbnail_url"],
                "https://example.invalid/cover.jpg",
            )
            cleanup.assert_called_once_with(str(output_dir), is_audio_playlist=False, preserve_partials=True)

    def test_audio_download_does_not_convert_unrelated_video_in_same_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            video_path = output_dir / "existing-video.mp4"
            video_path.write_bytes(b"v" * (500 * 1024))
            media_path = output_dir / "song.mp3"

            def finish_audio(ydl, urls):
                result = finish_with_file(media_path, {"id": "song-id", "title": "Song"})(ydl, urls)
                media_path.write_bytes(b"a" * (500 * 1024))
                return result

            FakeYoutubeDL.actions = [finish_audio]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.ensure_audio_format"
            ) as convert:
                result = make_downloader(output_dir).download(
                    "https://www.youtube.com/watch?v=song-id", media_type="Audio (Best)"
                )

            self.assertEqual(result, (True, "", False))
            self.assertTrue(video_path.exists())
            self.assertTrue(media_path.exists())
            convert.assert_not_called()

    def test_failed_audio_download_does_not_treat_existing_video_as_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            video_path = output_dir / "existing-video.mp4"
            video_path.write_bytes(b"v" * (500 * 1024))

            def fail_download(ydl, _urls):
                ydl.options["logger"].error("Network error")
                return 1

            FakeYoutubeDL.actions = [fail_download for _ in range(4)]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file") as postprocess, patch(
                "core.downloader.time.sleep"
            ), patch("core.downloader.log_failed_download"):
                result = make_downloader(output_dir).download(
                    "https://www.youtube.com/watch?v=song-id", media_type="Audio (Best)"
                )

            self.assertEqual(result, (False, "Network error", False))
            self.assertTrue(video_path.exists())
            postprocess.assert_not_called()

    def test_failed_video_download_does_not_treat_existing_audio_as_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            audio_path = output_dir / "existing-audio.mp3"
            audio_path.write_bytes(b"a" * (500 * 1024))

            def fail_download(ydl, _urls):
                ydl.options["logger"].error("Network error")
                return 1

            FakeYoutubeDL.actions = [fail_download for _ in range(4)]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_video_file") as postprocess, patch(
                "core.downloader.time.sleep"
            ), patch("core.downloader.log_failed_download"):
                result = make_downloader(output_dir).download(
                    "https://www.youtube.com/watch?v=video-id", media_type="Video (Best)"
                )

            self.assertEqual(result, (False, "Network error", False))
            self.assertTrue(audio_path.exists())
            postprocess.assert_not_called()

    def test_video_download_does_not_accept_an_audio_hook_as_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            audio_path = output_dir / "downloaded.mp3"

            def finish_audio_only(ydl, urls):
                result = finish_with_file(audio_path, {"id": "video-id", "title": "Clip"})(ydl, urls)
                audio_path.write_bytes(b"a" * (500 * 1024))
                return result

            FakeYoutubeDL.actions = [finish_audio_only]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_video_file") as postprocess, patch(
                "core.downloader.log_failed_download"
            ):
                result = make_downloader(output_dir).download(
                    "https://www.youtube.com/watch?v=video-id", media_type="Video (Best)"
                )

            self.assertEqual(result, (False, "No video file was found after download.", False))
            self.assertTrue(audio_path.exists())
            postprocess.assert_not_called()

    def test_video_options_include_browser_cookies_subtitles_and_postprocessors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "downloaded.mkv"
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "video-id",
                "title": "Clip",
                "uploader": "Artist",
                "height": 1080,
                "fps": 60,
            })]
            settings = SettingsStub({
                "video_container": "mkv",
                "video_codec": "h264",
                "embed_all_video_metadata": True,
            })

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_video_file", side_effect=lambda path, **_kwargs: path) as postprocess, patch(
                "core.downloader.cleanup_orphan_files"
            ):
                downloader = make_downloader(output_dir, settings)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=video-id",
                    media_type="Video",
                    quality="1080p",
                    cookies={"use": True, "source": "browser", "browser": "firefox"},
                    subtitles={"download": True, "langs": "English (en)"},
                    title="Clip",
                    author="Artist",
                )

            self.assertEqual(result, (True, "", False))
            options = FakeYoutubeDL.instances[0].options
            self.assertEqual(options["cookiesfrombrowser"], ("firefox",))
            self.assertEqual(options["merge_output_format"], "mkv")
            self.assertIn("vcodec^=avc", options["format"])
            self.assertEqual(options["subtitleslangs"], ["en", "en.*", "en-*"])
            self.assertFalse(options["writeautomaticsub"])
            self.assertEqual(
                options["postprocessors"],
                [
                    {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
                    {"key": "EmbedThumbnail"},
                    {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
                ],
            )
            self.assertEqual(postprocess.call_args.args[0], media_path)
            self.assertEqual(postprocess.call_args.kwargs["resolution"], "1080p")
            self.assertEqual(postprocess.call_args.kwargs["fps"], "60")

    def test_video_request_with_audio_only_platform_quality_still_selects_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "downloaded.mp4"
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "video-id",
                "title": "Clip",
                "uploader": "Artist",
            })]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_video_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.cleanup_orphan_files"
            ):
                downloader = make_downloader(output_dir, SettingsStub({"video_codec": "auto"}))
                result = downloader.download(
                    "https://www.youtube.com/watch?v=video-id",
                    media_type="Video (Best)",
                    quality="Audio only (MP3)",
                )

            self.assertEqual(result, (True, "", False))
            self.assertEqual(
                FakeYoutubeDL.instances[0].options["format"],
                "bestvideo+bestaudio/best",
            )

    def test_video_quality_mapping_never_falls_back_to_audio_only(self):
        downloader = MediaDownloader.__new__(MediaDownloader)
        cases = {
            "Best video": "bestvideo+bestaudio/best",
            "Audio only (MP3)": "bestvideo+bestaudio/best",
            "Best Audio": "bestvideo+bestaudio/best",
            "Worst": "worstvideo+worstaudio/worst",
            "Worst Audio": "worstvideo+worstaudio/worst",
            "720p (HD)": "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo+bestaudio/best",
        }

        for quality, expected in cases.items():
            with self.subTest(quality=quality):
                self.assertEqual(downloader._map_quality(quality), expected)

    def test_h265_and_vp9_video_codecs_select_expected_formats_and_containers(self):
        cases = (
            (
                "h265",
                "mp4",
                "bestvideo[vcodec^=hev]+bestaudio/bestvideo[vcodec^=h265]+bestaudio/bestvideo+bestaudio/best",
            ),
            (
                "vp9_av1",
                "mkv",
                "bestvideo[vcodec^=vp9]+bestaudio/bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio/best",
            ),
        )
        for codec, container, expected_format in cases:
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as temp_dir:
                FakeYoutubeDL.actions = []
                FakeYoutubeDL.instances = []
                output_dir = Path(temp_dir) / "downloads"
                output_dir.mkdir()
                app_dir = Path(temp_dir) / "app-data"
                app_dir.mkdir()
                media_path = output_dir / f"video.{container}"
                FakeYoutubeDL.actions = [finish_with_file(media_path, {
                    "id": "video-id", "title": "Clip", "uploader": "Artist",
                })]
                settings = SettingsStub({
                    "video_container": container,
                    "video_codec": codec,
                    "embed_all_video_metadata": False,
                    "video_metadata_tags": {
                        "title_desc": False,
                        "author": False,
                        "chapters": False,
                        "thumbnail": False,
                        "subtitles": False,
                    },
                })

                with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                    "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
                ), patch("core.downloader.postprocess_video_file", side_effect=lambda path, **_kwargs: path), patch(
                    "core.downloader.cleanup_orphan_files"
                ):
                    downloader = make_downloader(output_dir, settings)
                    result = downloader.download(
                        "https://www.youtube.com/watch?v=video-id",
                        media_type="Video",
                    )

                self.assertEqual(result, (True, "", False))
                options = FakeYoutubeDL.instances[0].options
                self.assertEqual(options["format"], expected_format)
                self.assertEqual(options["merge_output_format"], container)

    def test_archive_logger_skip_returns_success_without_processing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()

            def skip_from_archive(ydl, _urls):
                ydl.options["logger"].debug("Video has already been recorded in the archive")
                return 0

            FakeYoutubeDL.actions = [skip_from_archive]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file") as postprocess, patch(
                "core.downloader.cleanup_orphan_files"
            ):
                downloader = make_downloader(output_dir)
                result = downloader.download("https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(result, (True, "", True))
            self.assertTrue(downloader.was_skipped)
            postprocess.assert_not_called()

    def test_spotify_track_is_searched_on_youtube_and_audio_subtitles_are_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "song.mp3"
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "youtube-id",
                "title": "Song",
                "artist": "Artist",
            })]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.cleanup_orphan_files"
            ):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://open.spotify.com/track/spotify-id",
                    media_type="Audio (Best)",
                    title="Song",
                    author="Artist",
                    subtitles={"download": True, "langs": "ru (auto)"},
                )

            self.assertEqual(result, (True, "", False))
            self.assertEqual(FakeYoutubeDL.download_urls, [["ytsearch1:Artist - Song"]])
            options = FakeYoutubeDL.instances[0].options
            self.assertTrue(options["writesubtitles"])
            self.assertTrue(options["writeautomaticsub"])
            self.assertEqual(options["subtitleslangs"], ["ru", "ru.*", "ru-*"])
            self.assertEqual(options["subtitlesformat"], "lrc/srt/best")

    def test_valid_cookie_file_is_passed_to_ytdlp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "song.mp3"
            cookie_file = Path(temp_dir) / "cookies.txt"
            cookie_file.write_text("Netscape cookie fixture", encoding="utf-8")
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "abcdefghijk", "title": "Song", "artist": "Artist",
            })]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.is_valid_netscape_cookies", return_value=True) as validate, patch(
                "core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path
            ), patch("core.downloader.cleanup_orphan_files"):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    cookies={"use": True, "source": "file", "file": str(cookie_file)},
                )

            self.assertEqual(result, (True, "", False))
            validate.assert_called_once_with(str(cookie_file))
            self.assertEqual(FakeYoutubeDL.instances[0].options["cookiefile"], str(cookie_file))

    def test_invalid_existing_cookie_file_is_omitted_from_ytdlp_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "song.mp3"
            cookie_file = Path(temp_dir) / "invalid-cookies.txt"
            cookie_file.write_text("plain text, not Netscape cookies", encoding="utf-8")
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "abcdefghijk", "title": "Song", "artist": "Artist",
            })]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.is_valid_netscape_cookies", return_value=False), patch(
                "core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path
            ), patch("core.downloader.cleanup_orphan_files"), redirect_stderr(io.StringIO()):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    cookies={"use": True, "source": "file", "file": str(cookie_file)},
                )

            self.assertEqual(result, (True, "", False))
            self.assertNotIn("cookiefile", FakeYoutubeDL.instances[0].options)

    def test_existing_playlist_file_is_skipped_without_starting_ytdlp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            progress_events = []

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch(
                "core.downloader.is_file_already_downloaded", return_value=True
            ), patch("core.downloader.cleanup_orphan_files") as cleanup:
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    playlist_index=1,
                    title="Song",
                    author="Artist",
                    progress_callback=progress_events.append,
                )

            self.assertEqual(result, (True, "", True))
            self.assertTrue(downloader.was_skipped)
            self.assertEqual(FakeYoutubeDL.instances, [])
            self.assertEqual(progress_events[0]["status_text"], "Already downloaded (Skipped)")
            cleanup.assert_called_once_with(str(output_dir), is_audio_playlist=False, preserve_partials=True)

    def test_playlist_download_updates_archive_map_order_and_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "playlist"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "downloaded.mp3"
            FakeYoutubeDL.actions = [finish_with_file(media_path, {
                "id": "download-id",
                "title": "Song",
                "artist": "Artist",
            })]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.is_file_already_downloaded", return_value=False), patch(
                "core.downloader.check_and_clean_archive_if_file_missing"
            ), patch("core.downloader.read_playlist_format", return_value=None), patch(
                "core.downloader.update_stem_vid_map"
            ) as update_map, patch("core.downloader.append_playlist_order") as append_order, patch(
                "core.downloader.write_playlist_format"
            ) as write_format, patch(
                "core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path
            ), patch("core.downloader.cleanup_orphan_files"):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=original-id",
                    playlist_index=2,
                    playlist_count=5,
                    title="Song",
                    author="Artist",
                )

            self.assertEqual(result, (True, "", False))
            options = FakeYoutubeDL.instances[0].options
            self.assertEqual(options["download_archive"], str(output_dir / "downloaded_archive.txt"))
            append_order.assert_called_once_with(str(output_dir), media_path.name)
            self.assertEqual(update_map.call_count, 2)
            self.assertEqual(update_map.call_args.kwargs, {
                "vid": "download-id",
                "original_vid": "original-id",
            })
            write_format.assert_called_once_with(str(output_dir), "windows")

    def test_first_client_failure_rotates_to_next_client_and_recovers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "recovered.mp3"

            def fail_first(_ydl, _urls):
                raise RuntimeError("temporary extractor failure")

            FakeYoutubeDL.actions = [
                fail_first,
                finish_with_file(media_path, {"id": "abcdefghijk", "title": "Song", "artist": "Artist"}),
            ]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.cleanup_orphan_files"
            ), patch("core.downloader.time.sleep") as sleep:
                downloader = make_downloader(output_dir)
                result = downloader.download("https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(result, (True, "", False))
            self.assertEqual(FakeYoutubeDL.player_clients[:2], [
                ["android", "web"],
                ["web", "android"],
            ])
            sleep.assert_called_once_with(0.3)

    def test_exhausted_attempts_return_failure_and_log_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            FakeYoutubeDL.actions = [lambda _ydl, _urls: 1 for _ in range(4)]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.time.sleep"), patch(
                "core.downloader.log_failed_download"
            ) as log_failure, patch("core.downloader.cleanup_orphan_files"):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    title="Song",
                    author="Artist",
                )

            self.assertEqual(result, (False, "Unknown error occurred.", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 4)
            log_failure.assert_called_once_with(
                str(output_dir),
                title="Song",
                author="Artist",
                url="https://www.youtube.com/watch?v=abcdefghijk",
                reason="Unknown error occurred.",
            )

    def test_nonzero_ytdlp_code_is_accepted_when_a_valid_media_file_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "partial.mp3"

            def finish_partial(ydl, _urls):
                media_path.write_bytes(b"x" * (500 * 1024))
                event = {
                    "status": "finished",
                    "filepath": str(media_path),
                    "info_dict": {"id": "abcdefghijk", "title": "Song", "artist": "Artist"},
                }
                for hook in ydl.options["progress_hooks"]:
                    hook(event)
                return 1

            FakeYoutubeDL.actions = [finish_partial]

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.cleanup_orphan_files"
            ), patch("core.downloader.log_failed_download") as log_failure:
                downloader = make_downloader(output_dir)
                result = downloader.download("https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(result, (True, "", False))
            self.assertTrue(media_path.exists())
            log_failure.assert_not_called()

    def test_unavailable_audio_searches_for_a_matching_reupload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            replacement = output_dir / "replacement.mp3"

            def fail_as_unavailable(ydl, _urls):
                ydl.options["logger"].error("Video unavailable")
                return 1

            FakeYoutubeDL.actions = [fail_as_unavailable for _ in range(4)] + [
                finish_with_file(replacement, {
                    "id": "replacement-id",
                    "title": "Song",
                    "artist": "Artist",
                })
            ]
            FakeYoutubeDL.search_result = {
                "entries": [{"id": "replacement-id", "title": "Song", "uploader": "Artist"}],
            }

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.match_search_candidate", return_value=True) as match_candidate, patch(
                "core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path
            ), patch("core.downloader.cleanup_orphan_files"), patch(
                "core.downloader.time.sleep"
            ), patch("core.downloader.log_failed_download") as log_failure:
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=original-id",
                    media_type="Audio (Best)",
                    title="Song",
                    author="Artist",
                )

            self.assertEqual(result, (True, "", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 6)
            search_instance = next(
                instance for instance in FakeYoutubeDL.instances
                if hasattr(instance, "extract_info_call")
            )
            self.assertEqual(search_instance.extract_info_call, ("ytsearch5:Artist Song", False))
            match_candidate.assert_called_once_with("Song", "Artist", "Song", "Artist")
            self.assertTrue(replacement.exists())
            log_failure.assert_not_called()

    def test_unavailable_audio_does_not_download_a_rejected_search_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()

            def fail_as_unavailable(ydl, _urls):
                ydl.options["logger"].error("Video unavailable")
                return 1

            FakeYoutubeDL.actions = [fail_as_unavailable for _ in range(4)]
            FakeYoutubeDL.search_result = {
                "entries": [{"id": "wrong-id", "title": "Different Song", "uploader": "Other Artist"}],
            }

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.match_search_candidate", return_value=False) as match_candidate, patch(
                "core.downloader.time.sleep"
            ), patch("core.downloader.cleanup_orphan_files"), patch(
                "core.downloader.log_failed_download"
            ) as log_failure:
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=original-id",
                    title="Song",
                    author="Artist",
                )

            self.assertEqual(result, (False, "Video unavailable", False))
            self.assertEqual(FakeYoutubeDL.download_urls, [["https://www.youtube.com/watch?v=original-id"]] * 4)
            self.assertEqual(len(FakeYoutubeDL.instances), 5)
            match_candidate.assert_called_once_with("Different Song", "Other Artist", "Song", "Artist")
            log_failure.assert_called_once()

    def test_unavailable_audio_fallback_search_error_preserves_download_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()

            def fail_as_unavailable(ydl, _urls):
                ydl.options["logger"].error("Video unavailable")
                return 1

            FakeYoutubeDL.actions = [fail_as_unavailable for _ in range(4)]
            FakeYoutubeDL.extract_error = RuntimeError("search backend unavailable")

            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.time.sleep"), patch(
                "core.downloader.cleanup_orphan_files"
            ), patch("core.downloader.log_failed_download") as log_failure:
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=original-id",
                    title="Song",
                    author="Artist",
                )

            self.assertEqual(result, (False, "Video unavailable", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 5)
            log_failure.assert_called_once()

    def test_unavailable_video_does_not_use_audio_reupload_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()

            def fail_as_unavailable(ydl, _urls):
                ydl.options["logger"].error("Video unavailable")
                return 1

            FakeYoutubeDL.actions = [fail_as_unavailable for _ in range(4)]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.match_search_candidate") as match_candidate, patch(
                "core.downloader.time.sleep"
            ), patch("core.downloader.cleanup_orphan_files"), patch(
                "core.downloader.log_failed_download"
            ):
                downloader = make_downloader(output_dir)
                result = downloader.download(
                    "https://www.youtube.com/watch?v=video-id",
                    media_type="Video",
                    title="Clip",
                    author="Artist",
                )

            self.assertEqual(result, (False, "Video unavailable", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 4)
            match_candidate.assert_not_called()

    def test_recoverable_logger_message_does_not_trigger_client_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "downloads"
            output_dir.mkdir()
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()
            media_path = output_dir / "song.mp3"

            def download_with_recoverable_message(ydl, urls):
                ydl.options["logger"].error("Some Android client HTTPS formats have been skipped")
                return finish_with_file(media_path, {
                    "id": "abcdefghijk", "title": "Song", "artist": "Artist",
                })(ydl, urls)

            FakeYoutubeDL.actions = [download_with_recoverable_message]
            with patch("core.settings.get_app_data_dir", return_value=app_dir), patch(
                "core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL
            ), patch("core.downloader.postprocess_audio_file", side_effect=lambda path, **_kwargs: path), patch(
                "core.downloader.cleanup_orphan_files"
            ), patch("core.downloader.time.sleep") as sleep:
                downloader = make_downloader(output_dir)
                result = downloader.download("https://www.youtube.com/watch?v=abcdefghijk")

            self.assertEqual(result, (True, "", False))
            self.assertEqual(len(FakeYoutubeDL.instances), 1)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
