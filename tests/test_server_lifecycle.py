from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from typing import Callable

import codex_server


class TestService:
    def state(self) -> dict[str, object]:
        return {
            "categories": [],
            "overall": {"completed": 0, "total": 0},
            "metadata": {},
            "sync": {
                "status": "ok",
                "message": "测试状态",
                "revision": "test-revision",
                "save_path": "",
            },
        }

    def entries(self, *_args: object) -> dict[str, object]:
        return {"entries": []}


class ServerLifecycleTests(unittest.TestCase):
    def test_bind_failure_keeps_original_socket_error(self) -> None:
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        try:
            with self.assertRaises(OSError):
                codex_server.CodexHTTPServer(
                    ("127.0.0.1", blocker.getsockname()[1]),
                    TestService(),
                    Path(__file__).resolve().parents[1] / "web",
                    auto_exit=False,
                )
        finally:
            blocker.close()

    def setUp(self) -> None:
        self._original_poll_interval = codex_server.POLL_INTERVAL_SECONDS
        self._original_close_grace = codex_server.PAGE_CLOSE_GRACE_SECONDS
        self._original_idle_grace = codex_server.CLIENT_IDLE_GRACE_SECONDS
        codex_server.POLL_INTERVAL_SECONDS = 0.01
        codex_server.PAGE_CLOSE_GRACE_SECONDS = 0.12
        self.server = codex_server.CodexHTTPServer(
            ("127.0.0.1", 0),
            TestService(),
            Path(__file__).resolve().parents[1] / "web",
            auto_exit=True,
        )
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=1)
        self.server.server_close()
        codex_server.POLL_INTERVAL_SECONDS = self._original_poll_interval
        codex_server.PAGE_CLOSE_GRACE_SECONDS = self._original_close_grace
        codex_server.CLIENT_IDLE_GRACE_SECONDS = self._original_idle_grace

    def _wait_until(self, condition: Callable[[], bool], timeout: float = 1) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.01)
        return bool(condition())

    def _close_page(self, client_id: str) -> None:
        request = urllib.request.Request(
            f"{self.url}api/client/closed?client_id={client_id}",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            self.assertEqual(response.status, 200)

    def _request_state(self, client_id: str) -> None:
        request = urllib.request.Request(
            f"{self.url}api/state",
            headers={"X-SurvivalLog-Client": client_id},
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            self.assertEqual(response.status, 200)

    def test_background_idle_does_not_stop_server(self) -> None:
        self.server.note_client_activity("background-page")

        time.sleep(codex_server.PAGE_CLOSE_GRACE_SECONDS * 2)

        self.assertTrue(self.thread.is_alive())

    def test_server_stops_when_no_page_connects(self) -> None:
        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

    def test_anonymous_activity_does_not_cancel_startup_shutdown(self) -> None:
        self.server.note_client_activity()

        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

    def test_server_stops_when_page_disappears_without_close_notification(self) -> None:
        codex_server.CLIENT_IDLE_GRACE_SECONDS = 0.12
        self.server.note_client_activity("lost-page")

        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

    def test_active_page_heartbeat_prevents_idle_shutdown(self) -> None:
        codex_server.CLIENT_IDLE_GRACE_SECONDS = 0.12
        self.server.note_client_activity("active-page")

        for _ in range(4):
            time.sleep(0.05)
            self.server.note_client_activity("active-page")

        self.assertTrue(self.thread.is_alive())

    def test_headless_server_stays_running_without_a_page(self) -> None:
        headless_server = codex_server.CodexHTTPServer(
            ("127.0.0.1", 0),
            TestService(),
            Path(__file__).resolve().parents[1] / "web",
            auto_exit=False,
        )
        headless_thread = threading.Thread(
            target=headless_server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        headless_thread.start()
        try:
            time.sleep(codex_server.PAGE_CLOSE_GRACE_SECONDS * 2)
            self.assertTrue(headless_thread.is_alive())
        finally:
            headless_server.shutdown()
            headless_thread.join(timeout=1)
            headless_server.server_close()

    def test_page_close_stops_server_after_grace_period(self) -> None:
        self.server.note_client_activity("page-to-close")

        self._close_page("page-to-close")

        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

    def test_closing_one_page_does_not_stop_another_page(self) -> None:
        self.server.note_client_activity("page-to-close")
        self.server.note_client_activity("background-page")

        self._close_page("page-to-close")
        time.sleep(codex_server.PAGE_CLOSE_GRACE_SECONDS * 2)

        self.assertTrue(self.thread.is_alive())

    def test_late_request_from_closed_page_does_not_cancel_exit(self) -> None:
        self.server.note_client_activity("page-to-close")
        self._close_page("page-to-close")

        self._request_state("page-to-close")

        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

    def test_new_request_cancels_pending_page_close(self) -> None:
        self.server.note_client_activity("previous-page")
        self._close_page("previous-page")

        self._request_state("replacement-page")
        time.sleep(codex_server.PAGE_CLOSE_GRACE_SECONDS * 2)

        self.assertTrue(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
