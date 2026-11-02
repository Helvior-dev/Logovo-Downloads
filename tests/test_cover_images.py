import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from core.downloader import (
    crop_to_square,
    fetch_and_crop_cover_jpeg,
    is_pillarboxed,
    process_cover_image,
)


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.data


class CoverImageTests(unittest.TestCase):
    def test_crop_to_square_center_crops_and_resizes_to_standard_dimensions(self):
        image = Image.new("RGB", (200, 100), "blue")
        ImageDraw.Draw(image).rectangle((50, 0, 149, 99), fill="green")

        cropped = crop_to_square(image)

        self.assertEqual(cropped.size, (1000, 1000))
        self.assertEqual(cropped.getpixel((500, 500)), (0, 128, 0))

    def test_pillarbox_detection_distinguishes_dark_bars_from_full_frame(self):
        pillarboxed = Image.new("RGB", (160, 90), "black")
        ImageDraw.Draw(pillarboxed).rectangle((35, 0, 124, 89), fill="red")
        full_frame = Image.new("RGB", (160, 90))
        for y in range(90):
            for x in range(160):
                value = (x * 71 + y * 37) % 256
                full_frame.putpixel((x, y), (value, (value * 3) % 256, (value * 7) % 256))

        self.assertTrue(is_pillarboxed(pillarboxed))
        self.assertFalse(is_pillarboxed(full_frame))
        self.assertTrue(is_pillarboxed(Image.new("RGB", (80, 100), "blue")))

    def test_smart_style_crops_pillarboxed_audio_but_preserves_full_frame_and_video(self):
        pillarboxed = Image.new("RGB", (160, 90), "black")
        ImageDraw.Draw(pillarboxed).rectangle((35, 0, 124, 89), fill="red")
        full_frame = Image.new("RGB", (160, 90))
        for y in range(90):
            for x in range(160):
                value = (x * 71 + y * 37) % 256
                full_frame.putpixel((x, y), (value, (value * 3) % 256, (value * 7) % 256))

        self.assertEqual(process_cover_image(pillarboxed, is_audio=True, cover_style="smart").size, (1000, 1000))
        self.assertEqual(process_cover_image(full_frame, is_audio=True, cover_style="smart").size, (160, 90))
        self.assertEqual(process_cover_image(full_frame, is_audio=False, cover_style="smart").size, (160, 90))

    def test_original_style_preserves_dimensions_and_converts_alpha_to_rgb(self):
        image = Image.new("RGBA", (120, 60), (20, 40, 60, 100))

        processed = process_cover_image(image, cover_style="original")

        self.assertEqual(processed.size, (120, 60))
        self.assertEqual(processed.mode, "RGB")

    def test_fetch_cover_prefers_local_thumbnail_and_removes_it_after_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media_path = root / "Track.mp3"
            thumbnail_path = root / "Track.jpg"
            Image.new("RGB", (320, 180), "purple").save(thumbnail_path, format="JPEG")

            result = fetch_and_crop_cover_jpeg(media_path, cover_style="square")

            self.assertIsNotNone(result)
            self.assertFalse(thumbnail_path.exists())
            with Image.open(io.BytesIO(result)) as cover:
                self.assertEqual(cover.format, "JPEG")
                self.assertEqual(cover.size, (1000, 1000))

    def test_fetch_cover_uses_explicit_url_and_handles_download_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media_path = root / "Track.mp3"
            buffer = io.BytesIO()
            Image.new("RGB", (160, 90), "orange").save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()

            class Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self):
                    return image_bytes

            with patch("core.downloader.urllib.request.urlopen", return_value=Response()) as urlopen:
                result = fetch_and_crop_cover_jpeg(
                    media_path,
                    thumbnail_url="https://example.invalid/cover.jpg",
                    square=False,
                    cover_style="original",
                )

            self.assertIsNotNone(result)
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 8)
            with Image.open(io.BytesIO(result)) as cover:
                self.assertEqual(cover.size, (160, 90))

            with patch("core.downloader.urllib.request.urlopen", side_effect=OSError("offline")) as urlopen:
                failed = fetch_and_crop_cover_jpeg(
                    media_path,
                    thumbnail_url="https://example.invalid/cover.jpg",
                    square=False,
                )

            self.assertIsNone(failed)
            urlopen.assert_called_once()

    def test_fetch_cover_tries_youtube_thumbnail_sizes_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media_path = root / "Track.mp3"
            buffer = io.BytesIO()
            Image.new("RGB", (160, 90), "blue").save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()

            with patch("core.downloader.read_stem_vid_map", return_value={"Track": "video-id"}), patch(
                "core.downloader.urllib.request.urlopen",
                side_effect=[FakeResponse(b"", status=404), FakeResponse(image_bytes)],
            ) as urlopen:
                result = fetch_and_crop_cover_jpeg(
                    media_path,
                    square=False,
                    cover_style="original",
                )

            self.assertIsNotNone(result)
            requested_urls = [call.args[0].full_url for call in urlopen.call_args_list]
            self.assertEqual(requested_urls, [
                "https://i.ytimg.com/vi/video-id/maxresdefault.jpg",
                "https://i.ytimg.com/vi/video-id/hqdefault.jpg",
            ])
            with Image.open(io.BytesIO(result)) as cover:
                self.assertEqual(cover.size, (160, 90))

    def test_fetch_cover_uses_itunes_result_and_requests_high_resolution_artwork(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media_path = root / "Track.mp3"
            buffer = io.BytesIO()
            Image.new("RGB", (160, 90), "orange").save(buffer, format="JPEG")
            image_bytes = buffer.getvalue()
            search_result = json.dumps({
                "results": [{
                    "artworkUrl100": "https://img.example/100x100bb.jpg",
                }],
            }).encode("utf-8")

            with patch("core.downloader.read_stem_vid_map", return_value={}), patch(
                "core.downloader.urllib.request.urlopen",
                side_effect=[FakeResponse(search_result), FakeResponse(image_bytes)],
            ) as urlopen:
                result = fetch_and_crop_cover_jpeg(
                    media_path,
                    artist="Artist",
                    title="Song",
                    cover_style="square",
                )

            self.assertIsNotNone(result)
            self.assertIn("https://itunes.apple.com/search?", urlopen.call_args_list[0].args[0].full_url)
            self.assertEqual(
                urlopen.call_args_list[1].args[0].full_url,
                "https://img.example/1000x1000bb.jpg",
            )
            with Image.open(io.BytesIO(result)) as cover:
                self.assertEqual(cover.size, (1000, 1000))


if __name__ == "__main__":
    unittest.main()
