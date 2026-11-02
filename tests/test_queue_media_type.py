import unittest

from ui.main_window import _resolve_queue_media_type


class QueueMediaTypeTests(unittest.TestCase):
    def test_visible_queue_choice_overrides_saved_audio_snapshot(self):
        media_type = _resolve_queue_media_type(
            "Video (Best)",
            {"media_type": "Audio (Best)"},
            {"media_type": "Audio (Best)"},
        )

        self.assertEqual(media_type, "Video (Best)")

    def test_saved_choice_is_fallback_when_queue_has_no_selection(self):
        media_type = _resolve_queue_media_type(
            None,
            {"media_type": "Video (H.265)"},
            {"media_type": "Audio (Best)"},
        )

        self.assertEqual(media_type, "Video (H.265)")


if __name__ == "__main__":
    unittest.main()
