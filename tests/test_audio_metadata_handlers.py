import base64
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from core.downloader import (
    fix_flac_cover,
    fix_flac_tags,
    fix_m4a_cover,
    fix_m4a_tags,
    fix_mp3_cover,
    fix_mp3_tags,
    fix_opus_cover,
    fix_opus_tags,
)


class FakeAudio(dict):
    def __init__(self, values=None, pictures=None):
        super().__init__(values or {})
        self.pictures = list(pictures or [])
        self.added_pictures = []
        self.save_count = 0
        self.saved_args = None

    def add_picture(self, picture):
        self.added_pictures.append(picture)

    def clear_pictures(self):
        self.pictures.clear()

    def save(self, *args, **kwargs):
        self.save_count += 1
        self.saved_args = (args, kwargs)


class FakePicture:
    def __init__(self, data=b""):
        self.data = data

    def write(self):
        return b"serialized-picture"


class FakeProcessedImage:
    width = 1000
    height = 1000

    def save(self, output, format, quality):
        output.write(b"processed-jpeg")


class AudioMetadataHandlerTests(unittest.TestCase):
    def test_mp3_tags_write_requested_frames_and_save_as_id3v23(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.mp3"
            tags = FakeAudio()
            frame_types = ("TPE1", "TIT2", "TRCK", "TALB", "TYER", "TDRC", "USLT")
            with patch("core.downloader.ID3", return_value=tags), ExitStack() as stack:
                for name in frame_types:
                    stack.enter_context(
                        patch(f"core.downloader.{name}", side_effect=lambda **fields: fields)
                    )
                fix_mp3_tags(
                    path,
                    track_num=3,
                    total_tracks=12,
                    album="Album",
                    artist=" Artist ",
                    title=" Song ",
                    year="2024-05-01",
                    lyrics="Lyrics",
                )

            self.assertEqual(tags["TPE1"]["text"], ["Artist"])
            self.assertEqual(tags["TIT2"]["text"], ["Song"])
            self.assertEqual(tags["TRCK"]["text"], ["3/12"])
            self.assertEqual(tags["TALB"]["text"], ["Album"])
            self.assertEqual(tags["TYER"]["text"], ["2024"])
            self.assertEqual(tags["TDRC"]["text"], ["2024"])
            self.assertEqual(tags["USLT"]["text"], "Lyrics")
            self.assertEqual(tags.saved_args, ((str(path),), {"v2_version": 3}))

    def test_flac_and_opus_tags_normalize_fields_and_preserve_existing_album(self):
        cases = (
            ("FLAC", fix_flac_tags),
            ("OggOpus", fix_opus_tags),
        )
        for audio_class, update_tags in cases:
            with self.subTest(audio_class=audio_class), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "track.audio"
                audio = FakeAudio({"albumartist": ["Fallback Artist"], "album": ["Existing Album"]})
                with patch(f"core.downloader.{audio_class}", return_value=audio):
                    update_tags(
                        path,
                        track_num=2,
                        total_tracks=9,
                        album="New Album",
                        title=" Song ",
                        year="2023-10-01",
                        lyrics="Lyrics",
                    )

                self.assertEqual(audio["artist"], ["Fallback Artist"])
                self.assertEqual(audio["title"], ["Song"])
                self.assertEqual(audio["tracknumber"], ["2/9"])
                self.assertEqual(audio["album"], ["Existing Album"])
                self.assertEqual(audio["date"], ["2023"])
                self.assertEqual(audio["lyrics"], ["Lyrics"])
                self.assertEqual(audio.save_count, 1)

    def test_m4a_tags_write_mp4_atoms_and_track_tuple(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.m4a"
            audio = FakeAudio({"\xa9alb": ["Existing Album"]})
            with patch("core.downloader.MP4", return_value=audio):
                fix_m4a_tags(
                    path,
                    track_num=4,
                    total_tracks=11,
                    album="New Album",
                    artist=" Artist ",
                    title=" Song ",
                    year="2022-01-01",
                    lyrics="Lyrics",
                )

            self.assertEqual(audio["\xa9ART"], ["Artist"])
            self.assertEqual(audio["\xa9nam"], ["Song"])
            self.assertEqual(audio["trkn"], [(4, 11)])
            self.assertEqual(audio["\xa9alb"], ["Existing Album"])
            self.assertEqual(audio["\xa9day"], ["2022"])
            self.assertEqual(audio["\xa9lyr"], ["Lyrics"])
            self.assertEqual(audio.save_count, 1)

    def test_mp3_cover_embeds_downloaded_or_cached_jpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.mp3"
            tags = FakeAudio()
            apic = Mock(return_value="embedded-cover")
            with patch("core.downloader.ID3", return_value=tags), patch(
                "core.downloader.APIC", apic
            ), patch("core.downloader.fetch_and_crop_cover_jpeg", return_value=b"jpeg") as fetch:
                fix_mp3_cover(path, thumbnail_url="cover-url", artist="Artist", title="Title")

            fetch.assert_called_once_with(path, thumbnail_url="cover-url", artist="Artist", title="Title")
            self.assertEqual(tags["APIC:Cover"], "embedded-cover")
            apic.assert_called_once_with(
                encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"jpeg"
            )
            self.assertEqual(tags.saved_args, ((str(path),), {"v2_version": 3}))

    def test_flac_cover_embeds_picture_when_none_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.flac"
            audio = FakeAudio()
            picture_factory = Mock(return_value=FakePicture())
            with patch("core.downloader.FLAC", return_value=audio), patch(
                "core.downloader.Picture", picture_factory
            ), patch("core.downloader.fetch_and_crop_cover_jpeg", return_value=b"jpeg"):
                fix_flac_cover(path, thumbnail_url="cover-url")

            self.assertEqual(len(audio.added_pictures), 1)
            self.assertEqual(audio.added_pictures[0].data, b"jpeg")
            self.assertEqual(audio.added_pictures[0].mime, "image/jpeg")
            self.assertEqual(audio.added_pictures[0].type, 3)
            self.assertEqual(audio.save_count, 1)

    def test_opus_cover_embeds_base64_metadata_picture_when_none_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.opus"
            audio = FakeAudio()
            with patch("core.downloader.OggOpus", return_value=audio), patch(
                "core.downloader.Picture", return_value=FakePicture()
            ), patch("core.downloader.fetch_and_crop_cover_jpeg", return_value=b"jpeg"):
                fix_opus_cover(path, thumbnail_url="cover-url")

            self.assertEqual(
                audio["metadata_block_picture"],
                [base64.b64encode(b"serialized-picture").decode("ascii")],
            )
            self.assertEqual(audio.save_count, 1)

    def test_m4a_cover_embeds_jpeg_when_none_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.m4a"
            audio = FakeAudio()
            cover_factory = Mock(return_value="mp4-cover")
            cover_factory.FORMAT_JPEG = "jpeg"
            with patch("core.downloader.MP4", return_value=audio), patch(
                "core.downloader.MP4Cover", cover_factory
            ), patch("core.downloader.fetch_and_crop_cover_jpeg", return_value=b"jpeg"):
                fix_m4a_cover(path, thumbnail_url="cover-url")

            cover_factory.assert_called_once_with(b"jpeg", imageformat="jpeg")
            self.assertEqual(audio["covr"], ["mp4-cover"])
            self.assertEqual(audio.save_count, 1)

    def test_mp3_cover_replaces_existing_apic_frame(self):
        class ExistingApic:
            data = b"old-image"
            desc = "Existing cover"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.mp3"
            tags = FakeAudio({"APIC:Cover": ExistingApic()})
            with patch("core.downloader.ID3", return_value=tags), patch(
                "core.downloader.Image.open", return_value=object()
            ), patch("core.downloader.process_cover_image", return_value=FakeProcessedImage()), patch(
                "core.downloader.APIC", return_value="processed-apic"
            ) as apic:
                fix_mp3_cover(path)

            self.assertEqual(tags["APIC:Cover"], "processed-apic")
            apic.assert_called_once_with(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Existing cover",
                data=b"processed-jpeg",
            )
            self.assertEqual(tags.saved_args, ((str(path),), {"v2_version": 3}))

    def test_flac_cover_replaces_existing_picture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.flac"
            audio = FakeAudio(pictures=[FakePicture(b"old-image")])
            with patch("core.downloader.FLAC", return_value=audio), patch(
                "core.downloader.Image.open", return_value=object()
            ), patch("core.downloader.process_cover_image", return_value=FakeProcessedImage()), patch(
                "core.downloader.Picture", return_value=FakePicture()
            ):
                fix_flac_cover(path)

            self.assertEqual(len(audio.added_pictures), 1)
            picture = audio.added_pictures[0]
            self.assertEqual(picture.data, b"processed-jpeg")
            self.assertEqual(picture.mime, "image/jpeg")
            self.assertEqual((picture.width, picture.height), (1000, 1000))
            self.assertEqual(picture.desc, "Cover")
            self.assertEqual(audio.save_count, 1)

    def test_opus_cover_replaces_existing_metadata_picture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.opus"
            source_picture = base64.b64encode(b"old-picture").decode("ascii")
            audio = FakeAudio({"metadata_block_picture": [source_picture]})
            with patch("core.downloader.OggOpus", return_value=audio), patch(
                "core.downloader.Picture", side_effect=lambda data: FakePicture(data)
            ), patch("core.downloader.Image.open", return_value=object()), patch(
                "core.downloader.process_cover_image", return_value=FakeProcessedImage()
            ):
                fix_opus_cover(path)

            self.assertEqual(
                audio["metadata_block_picture"],
                [base64.b64encode(b"serialized-picture").decode("ascii")],
            )
            self.assertEqual(audio.save_count, 1)

    def test_m4a_cover_replaces_existing_cover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "track.m4a"
            audio = FakeAudio({"covr": [b"old-image"]})
            cover_factory = Mock(return_value="processed-cover")
            cover_factory.FORMAT_JPEG = "jpeg"
            with patch("core.downloader.MP4", return_value=audio), patch(
                "core.downloader.MP4Cover", cover_factory
            ), patch("core.downloader.Image.open", return_value=object()), patch(
                "core.downloader.process_cover_image", return_value=FakeProcessedImage()
            ):
                fix_m4a_cover(path)

            cover_factory.assert_called_once_with(b"processed-jpeg", imageformat="jpeg")
            self.assertEqual(audio["covr"], ["processed-cover"])
            self.assertEqual(audio.save_count, 1)


if __name__ == "__main__":
    unittest.main()
