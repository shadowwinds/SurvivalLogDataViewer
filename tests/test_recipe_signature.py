import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_refresh_recipe_save_merges_only_selected_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "HistorySave.bytes"
            selected = root / "Save_selected.bytes"
            other = root / "Save_other.bytes"
            history.write_bytes(b"history")
            selected.write_bytes(b"selected")
            other.write_bytes(b"other")

            service = object.__new__(CodexService)
            service.save_file = history
            service.connection = object()
            service._lock = threading.RLock()
            service._last_recipe_signature = service._recipe_signature()
            existing_plan = {
                "status": "ok",
                "history_source": {},
                "saves": [
                    {"file_name": selected.name, "status": "ok", "inventory": ["old-selected"]},
                    {"file_name": other.name, "status": "ok", "inventory": ["other"]},
                ],
            }
            service._last_recipe_plan = existing_plan
            selected.write_bytes(b"selected-updated")
            refreshed_plan = {
                "status": "ok",
                "history_source": {},
                "saves": [
                    {"file_name": selected.name, "status": "ok", "inventory": ["new-selected"]},
                    {"file_name": other.name, "status": "ok", "inventory": ["other"]},
                ],
            }

            with (
                patch("codex_server.build_recipe_plan", return_value=refreshed_plan) as build,
                patch("codex_server.get_metadata", return_value={}),
                patch("codex_server.set_runtime_cache") as set_cache,
            ):
                result = service.refresh_recipe_save(selected.name)

            self.assertEqual(build.call_args.kwargs["refresh_file_name"], selected.name)
            self.assertEqual(
                build.call_args.kwargs["existing_saves"][other.name],
                existing_plan["saves"][1],
            )
            self.assertEqual(result["saves"][0]["inventory"], ["new-selected"])
            self.assertEqual(result["saves"][1], existing_plan["saves"][1])
            set_cache.assert_called_once()

            with self.assertRaisesRegex(ValueError, "不存在选中的存档"):
                service.refresh_recipe_save("Save_missing.bytes")

            failed_plan = {
                "status": "partial",
                "history_source": {},
                "saves": [
                    {
                        "file_name": selected.name,
                        "status": "error",
                        "diagnostics": ["save is being written"],
                    },
                    existing_plan["saves"][1],
                ],
            }
            service._last_recipe_plan = existing_plan
            with patch("codex_server.build_recipe_plan", return_value=failed_plan):
                with self.assertRaisesRegex(ValueError, "存档更新失败"):
                    service.refresh_recipe_save(selected.name)
            self.assertEqual(service._last_recipe_plan, existing_plan)


if __name__ == "__main__":
    unittest.main()
