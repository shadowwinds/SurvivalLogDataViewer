from __future__ import annotations

import json
import sqlite3
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import codex_database
from codex_server import CodexService
from codex_database import get_category_summaries, open_database, sync_game_completion
from codex_save import (
    MAX_DIAGNOSTIC_LOG_BYTES,
    CodexMapCandidate,
    SaveParseError,
    _scan_codex_map_candidates,
    _select_codex_map_candidate,
    build_save_diagnostic,
    parse_codex_save_bytes,
    read_codex_save,
    write_save_diagnostic,
)


ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "test"
DATABASE = ROOT / "data" / "survival_log_codex.sqlite3"


EXPECTED_COUNTS = {
    "HistorySave_test2.bytes": {
        "food": 75,
        "dish": 127,
        "plant": 32,
        "prey": 15,
        "craft": 56,
        "furniture": 50,
    },
    "HistorySave_test3.bytes": {
        "food": 75,
        "dish": 64,
        "plant": 27,
        "prey": 14,
        "craft": 78,
        "furniture": 57,
    },
}


def _pack_map(mapping: dict[int, tuple[int, ...]]) -> bytes:
    return _pack_map_entries(list(mapping.items()))


def _pack_map_entries(entries: list[tuple[int, tuple[int, ...]]]) -> bytes:
    chunks = [struct.pack("<i", len(entries))]
    for category_id, source_ids in entries:
        chunks.append(struct.pack("<i", category_id))
        chunks.append(struct.pack("<i", len(source_ids)))
        chunks.extend(struct.pack("<i", source_id) for source_id in source_ids)
    chunks.extend(struct.pack("<i", 0) for _ in range(3))
    return b"\x00" + b"".join(chunks)


class PublicSaveTests(unittest.TestCase):
    def test_public_save_mappings_are_found_without_fixed_offsets(self) -> None:
        states = {
            name: read_codex_save(FIXTURE_DIR / name)
            for name in EXPECTED_COUNTS
        }

        for name, expected in EXPECTED_COUNTS.items():
            with self.subTest(name=name):
                state = states[name]
                self.assertEqual(state.category_counts, expected)
                self.assertEqual(state.unknown_ids, {})
                self.assertEqual(state.candidate_count, 1)
                self.assertEqual(state.candidate_score[0:2], (3, 6))

        self.assertNotEqual(
            states["HistorySave_test2.bytes"].codex_offset,
            states["HistorySave_test3.bytes"].codex_offset,
        )
        self.assertEqual(states["HistorySave_test3.bytes"].codex_offset % 4, 1)

    def test_database_sync_uses_database_ids_for_scoring(self) -> None:
        if not DATABASE.is_file():
            self.skipTest(f"缺少本地测试数据库：{DATABASE}")

        for name, expected in EXPECTED_COUNTS.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                temp_dir = Path(directory)
                database = temp_dir / "survival_log_codex.sqlite3"
                shutil.copy2(DATABASE, database)
                connection = open_database(database)
                try:
                    result = sync_game_completion(
                        connection,
                        FIXTURE_DIR / name,
                        force=True,
                        log_path=database.with_suffix(".log"),
                    )
                    self.assertEqual(result.status, "ok")
                    self.assertEqual(result.category_counts, expected)
                    self.assertEqual(result.unknown_ids, {})
                    summaries = {
                        row["category"]: int(row["completed"])
                        for row in get_category_summaries(connection)
                    }
                    self.assertEqual(summaries, expected)
                    self.assertTrue(database.with_suffix(".log").is_file())
                finally:
                    connection.close()


class ServiceDiagnosticLogTests(unittest.TestCase):
    def _run_service(self, root: Path, log_path: Path | None) -> Path:
        if not DATABASE.is_file():
            self.skipTest(f"缺少本地测试数据库：{DATABASE}")

        database = root / "survival_log_codex.sqlite3"
        shutil.copy2(DATABASE, database)
        save_file = root / "HistorySave_test2.bytes"
        shutil.copy2(FIXTURE_DIR / "HistorySave_test2.bytes", save_file)
        service = CodexService(database, save_file, log_path=log_path)
        try:
            result = service._ensure_sync()
        finally:
            service.close()
        self.assertEqual(result.status, "ok")
        return database

    def test_source_service_does_not_configure_diagnostic_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self._run_service(Path(directory), None)
            self.assertFalse(database.with_suffix(".log").exists())

    def test_packaged_service_can_configure_diagnostic_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "SurvivalLogDataViewer.log"
            database = self._run_service(root, log_path)
            self.assertTrue(log_path.is_file())
            self.assertFalse(database.with_suffix(".log").exists())
            event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event["event"], "save_sync")


class DatabasePathTests(unittest.TestCase):
    def test_legacy_database_is_migrated_after_integrity_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "survival_log_codex.sqlite3"
            target = root / "data" / "survival_log_codex.sqlite3"
            connection = sqlite3.connect(legacy)
            try:
                connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
                connection.execute("INSERT INTO marker VALUES ('legacy')")
                connection.commit()
            finally:
                connection.close()

            with patch.object(codex_database, "LEGACY_DATABASE_PATH", legacy), patch.object(
                codex_database, "DEFAULT_DATABASE_PATH", target
            ):
                resolved = codex_database.resolve_default_database_path()

            self.assertEqual(resolved, target)
            self.assertTrue(target.is_file())
            self.assertFalse(legacy.exists())
            migrated = sqlite3.connect(target)
            try:
                self.assertEqual(migrated.execute("SELECT value FROM marker").fetchone()[0], "legacy")
                self.assertEqual(migrated.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                migrated.close()

    def test_legacy_database_with_wal_sidecar_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "survival_log_codex.sqlite3"
            target = root / "data" / "survival_log_codex.sqlite3"
            legacy.write_bytes(b"legacy")
            Path(f"{legacy}-wal").write_bytes(b"wal")

            with patch.object(codex_database, "LEGACY_DATABASE_PATH", legacy), patch.object(
                codex_database, "DEFAULT_DATABASE_PATH", target
            ):
                resolved = codex_database.resolve_default_database_path()

            self.assertEqual(resolved, legacy)
            self.assertTrue(legacy.is_file())
            self.assertFalse(target.exists())

    def test_legacy_log_moves_with_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "survival_log_codex.sqlite3"
            target = root / "data" / "survival_log_codex.sqlite3"
            connection = sqlite3.connect(legacy)
            try:
                connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
                connection.commit()
            finally:
                connection.close()
            legacy_log = legacy.with_suffix(".log")
            legacy_log.write_text("legacy log\n", encoding="utf-8")

            with patch.object(codex_database, "LEGACY_DATABASE_PATH", legacy), patch.object(
                codex_database, "DEFAULT_DATABASE_PATH", target
            ):
                resolved = codex_database.resolve_default_database_path()

            self.assertEqual(resolved, target)
            self.assertEqual(target.with_suffix(".log").read_text(encoding="utf-8"), "legacy log\n")
            self.assertFalse(legacy_log.exists())

    def test_existing_target_wins_without_overwriting_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "survival_log_codex.sqlite3"
            target = root / "data" / "survival_log_codex.sqlite3"
            target.parent.mkdir()
            legacy.write_bytes(b"legacy")
            target.write_bytes(b"target")

            with patch.object(codex_database, "LEGACY_DATABASE_PATH", legacy), patch.object(
                codex_database, "DEFAULT_DATABASE_PATH", target
            ):
                resolved = codex_database.resolve_default_database_path()

            self.assertEqual(resolved, target)
            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual(target.read_bytes(), b"target")

    def test_migration_function_refuses_target_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "survival_log_codex.sqlite3"
            target = root / "data" / "survival_log_codex.sqlite3"
            legacy.write_bytes(b"legacy")
            target.parent.mkdir()
            target.write_bytes(b"target")

            with self.assertRaisesRegex(FileExistsError, "目标数据库已存在"):
                codex_database._migrate_legacy_database(legacy, target)

            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual(target.read_bytes(), b"target")

    def test_invalid_candidate_shapes_are_rejected(self) -> None:
        duplicate_category = _pack_map_entries([(1, (100,)), (1, (101,))])
        duplicate_id = _pack_map({1: (100, 100)})
        truncated = b"\x00" + struct.pack("<i", 6) + struct.pack("<i", 1)

        for data in (b"\x00" + b"\xff" * 64, duplicate_category, duplicate_id, truncated):
            with self.subTest(data=data):
                self.assertEqual(_scan_codex_map_candidates(data, 1), [])

        with self.assertRaisesRegex(SaveParseError, "未找到有效的图鉴映射"):
            parse_codex_save_bytes(b"\x00" + b"\xff" * 64)

    def test_ambiguous_different_mappings_raise(self) -> None:
        first = CodexMapCandidate(
            offset=10,
            end_offset=20,
            raw_category_ids={1: (100,)},
            post_map_end_offset=32,
            tail_list_count=3,
            known_id_count=1,
            unknown_ids={},
            score=(3, 1, 1000, 1, 0),
            layout="scanned-tail-3",
        )
        second = CodexMapCandidate(
            offset=40,
            end_offset=50,
            raw_category_ids={1: (101,)},
            post_map_end_offset=62,
            tail_list_count=3,
            known_id_count=1,
            unknown_ids={},
            score=(3, 1, 1000, 1, 0),
            layout="scanned-tail-3",
        )

        with self.assertRaisesRegex(SaveParseError, "图鉴映射存在歧义"):
            _select_codex_map_candidate(
                [first, second],
                file_size=100,
                search_start=1,
            )

    def test_ambiguous_same_mapping_is_accepted(self) -> None:
        mapping = {1: (100,)}
        candidates = [
            CodexMapCandidate(
                offset=10 + index * 10,
                end_offset=20 + index * 10,
                raw_category_ids=mapping,
                post_map_end_offset=32 + index * 10,
                tail_list_count=3,
                known_id_count=1,
                unknown_ids={},
                score=(3, 1, 1000, 1, 0),
                layout="scanned-tail-3",
            )
            for index in range(2)
        ]

        selected = _select_codex_map_candidate(
            candidates,
            file_size=100,
            search_start=1,
        )
        self.assertEqual(selected.raw_category_ids, mapping)
        self.assertEqual(selected.offset, 10)

    def test_diagnostic_log_is_redacted_deduplicated_and_rotated(self) -> None:
        requested = Path.home() / "AppData" / "LocalLow" / "LLS" / "SLGame" / "Saves" / "HistorySave.bytes"
        error = SaveParseError(
            f"读取失败：{requested}",
            code="test_error",
            stage="test",
            offset=12,
        )
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "SurvivalLogDataViewer.log"
            payload = build_save_diagnostic(requested, status="error", error=error)
            write_save_diagnostic(log_path, payload)
            write_save_diagnostic(log_path, payload)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertIn("%USERPROFILE%", event["requested_path"])
            self.assertNotIn(str(Path.home()), lines[0])

            log_path.write_bytes(b"x" * MAX_DIAGNOSTIC_LOG_BYTES)
            write_save_diagnostic(
                log_path,
                {"event": "rotation", "value": "unique"},
            )
            self.assertTrue(Path(f"{log_path}.1").is_file())
            self.assertLess(log_path.stat().st_size, MAX_DIAGNOSTIC_LOG_BYTES)


if __name__ == "__main__":
    unittest.main()
