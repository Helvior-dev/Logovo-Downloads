import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.settings import SettingsManager
from ui.styles import (
    THEME_PALETTES,
    get_stylesheet,
    get_theme_colors,
    normalize_theme,
    theme_stylesheet,
)


class UiThemeTests(unittest.TestCase):
    def test_available_palettes_are_complete_and_distinct(self):
        self.assertEqual(set(THEME_PALETTES), {
            "green", "blue", "pink", "red", "amber", "cyan", "violet",
        })
        role_sets = [set(palette) for palette in THEME_PALETTES.values()]
        self.assertTrue(all(roles == role_sets[0] for roles in role_sets))
        self.assertEqual(len({palette["accent"] for palette in THEME_PALETTES.values()}), 7)
        color_roles = {}
        for palette in THEME_PALETTES.values():
            for role, color in palette.items():
                previous = color_roles.setdefault(color.lower(), role)
                self.assertEqual(previous, role, f"{color} maps to both {previous} and {role}")

    def test_unknown_theme_falls_back_to_green(self):
        self.assertEqual(normalize_theme("unknown"), "green")
        self.assertEqual(get_theme_colors(None), THEME_PALETTES["green"])

    def test_stylesheets_use_requested_palette_and_fallback(self):
        self.assertIn(THEME_PALETTES["blue"]["accent"], get_stylesheet("blue"))
        self.assertEqual(get_stylesheet("invalid"), get_stylesheet("green"))
        local_qss = "QLabel { color: #91e5a3; background: #0b120d; }"
        self.assertIn(THEME_PALETTES["pink"]["accent"], theme_stylesheet(local_qss, "pink"))
        self.assertIn(THEME_PALETTES["pink"]["card_bg"], theme_stylesheet(local_qss, "pink"))
        for theme in ("amber", "cyan", "violet"):
            with self.subTest(theme=theme):
                self.assertIn(THEME_PALETTES[theme]["accent"], get_stylesheet(theme))
                self.assertIn(THEME_PALETTES[theme]["card_bg"], theme_stylesheet(local_qss, theme))

    def test_selected_theme_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            with patch("core.settings.get_app_data_dir", return_value=app_dir):
                settings = SettingsManager()
                self.assertEqual(settings.get("ui_theme"), "green")
                settings.set("ui_theme", "violet")

                reloaded = SettingsManager()

            self.assertEqual(reloaded.get("ui_theme"), "violet")


if __name__ == "__main__":
    unittest.main()
