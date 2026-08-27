import tempfile
import unittest
from pathlib import Path

from codex_server import CodexService


class RecipeSignatureTests(unittest.TestCase):
    def test_only_direct_child_save_files_invalidate_recipe_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "HistorySave.bytes"
            child = root / "Save_demo.bytes"
            history.write_bytes(b"history")
            child.write_bytes(b"child")

            service = object.__new__(CodexService)
            service.save_file = history
            initial = service._recipe_signature()

            (root / "Save_demo.snap0.bytes").write_bytes(b"snapshot")
            (root / "Save_demo.round.bytes").write_bytes(b"round")
            self.assertEqual(service._recipe_signature(), initial)

            child.write_bytes(b"changed")
            self.assertNotEqual(service._recipe_signature(), initial)


if __name__ == "__main__":
    unittest.main()
