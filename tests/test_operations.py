import json
import tempfile
import unittest
from pathlib import Path

from paper_folder.naming import RenamePreview
from paper_folder.operations import apply_renames, undo_last


class OperationTests(unittest.TestCase):
    def test_apply_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "old.pdf"
            old.write_bytes(b"pdf")
            preview = RenamePreview(old, "new.pdf", "preview")
            result = apply_renames([preview], root)
            self.assertEqual(result.changed, 1)
            self.assertTrue((root / "new.pdf").exists())
            self.assertTrue((root / ".paper-folder-history.json").exists())
            undone = undo_last(root)
            self.assertEqual(undone.changed, 1)
            self.assertTrue(old.exists())

    def test_conflict_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "old.pdf"
            target = root / "new.pdf"
            old.touch()
            target.touch()
            with self.assertRaises(FileExistsError):
                apply_renames([RenamePreview(old, target.name, "preview")], root)
            self.assertTrue(old.exists())

    def test_undo_refuses_if_original_name_is_occupied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "old.pdf"
            old.touch()
            apply_renames([RenamePreview(old, "new.pdf", "preview")], root)
            old.touch()
            with self.assertRaises(FileExistsError):
                undo_last(root)
            self.assertTrue((root / "new.pdf").exists())


if __name__ == "__main__":
    unittest.main()
