from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import codex_launcher


class LauncherErrorTests(unittest.TestCase):
    def test_show_error_logs_when_stderr_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "startup.log"
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(codex_launcher, "_startup_log_paths", return_value=(log_path,))
                )
                stack.enter_context(patch.object(codex_launcher.sys, "platform", "linux"))
                stack.enter_context(patch.object(codex_launcher.sys, "stderr", None))
                codex_launcher.show_error("database startup failed")

            payload = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "startup_error")
            self.assertEqual(payload["message"], "database startup failed")


if __name__ == "__main__":
    unittest.main()
