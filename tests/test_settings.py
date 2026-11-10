import json
import tempfile
import unittest
from pathlib import Path

from paper_folder.settings import AppSettings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            save_settings(
                AppSettings(
                    email="reader@example.com",
                    recursive=False,
                    online=False,
                    naming_fields=["journal", "year", "title"],
                    onboarding_complete=True,
                ),
                path,
            )
            loaded = load_settings(path)
            self.assertEqual(loaded.naming_fields, ["journal", "year", "title"])
            self.assertTrue(loaded.onboarding_complete)
            self.assertFalse(loaded.online)

    def test_invalid_fields_fall_back_to_legacy_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"naming_fields": ["publisher"]}), encoding="utf-8")
            self.assertEqual(load_settings(path).naming_fields, ["year", "title"])

    def test_broken_json_does_not_block_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_settings(path).naming_fields, ["year", "title"])


if __name__ == "__main__":
    unittest.main()
