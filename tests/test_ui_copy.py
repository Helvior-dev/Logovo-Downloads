import ast
import unittest
from pathlib import Path


class UiCopyTests(unittest.TestCase):
    def test_ui_string_literals_do_not_contain_emoji(self):
        ui_dir = Path(__file__).resolve().parent.parent / "ui"
        for path in sorted(ui_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                with self.subTest(file=path.name, line=node.lineno):
                    self.assertFalse(any(
                        ord(char) >= 0x1F000
                        or 0x2600 <= ord(char) <= 0x27BF
                        or ord(char) in (0x23F3, 0xFE0F, 0x20E3)
                        for char in node.value
                    ), node.value)

    def test_ui_copy_does_not_include_promotional_claims(self):
        ui_dir = Path(__file__).resolve().parent.parent / "ui"
        phrases = ("awesome", "100% reliable", "modern, high-speed", "without bans or interruptions")
        for path in sorted(ui_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertFalse(any(phrase in node.value.lower() for phrase in phrases))


if __name__ == "__main__":
    unittest.main()
