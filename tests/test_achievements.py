from __future__ import annotations

import json
import sqlite3
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import codex_database
from codex_achievements import (
    AchievementConditionError,
    load_achievement_conditions,
    validate_achievement_conditions,
)
from codex_database import (
    get_achievement_summary,
    initialize_database,
    prepare_packaged_database,
    query_achievements,
    sync_game_completion,
)
from codex_save import (
    CODEX_CATEGORY_IDS,
    CodexSaveState,
    SaveFileInfo,
    SaveParseError,
    parse_codex_save_bytes,
    read_codex_save,
    read_history_save,
)
from codex_server import CodexHTTPServer, CodexService
from codex_parser import ConfigRow


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "test"


def _pack_string(value: str | None) -> bytes:
    if value is None:
        return struct.pack("<i", -1)
    raw = value.encode("utf-8")
    return struct.pack("<ii", ~len(raw), len(value)) + raw


def _pack_history(achievement_ids: tuple[int, ...]) -> bytes:
    chunks = [
        b"\x10",
        struct.pack("<i", -1),  # HistoryList
        _pack_string(None),  # LastPlayFileName
        struct.pack("<i", len(achievement_ids)),
        b"".join(struct.pack("<i", value) for value in achievement_ids),
        struct.pack("<i", -1),  # UnlockedPlayerSelectIds
        struct.pack("<i", -1),  # ClearedEndings
        struct.pack("<i", -1),  # GlobalEasterEggFlags
        struct.pack("<i", -1),  # PlayerSelectSaveFileMap
        struct.pack("<i", -1),  # CodexUnlocked
        struct.pack("<i", -1),  # CodexMilestonesClaimed
        struct.pack("<i", -1),  # PendingUnlockNoticeIds
        struct.pack("<i", -1),  # EndlessBestRecords
        b"\x00",  # EndlessModeUnlocked
        struct.pack("<i", -1),  # BestDossierRecords
        struct.pack("<i", 0),  # DataOrigin
        struct.pack("<i", -1),  # EndlessCharUnlockedIds
        struct.pack("<i", -1),  # SeenProloguePlayerSelectIds
    ]
    return b"".join(chunks)


def _mock_state(root: Path, achievement_ids: tuple[int, ...], available: bool = True) -> CodexSaveState:
    return CodexSaveState(
        file_info=SaveFileInfo(root / "HistorySave.bytes", "hash", 1, 1, "now"),
        category_ids={category: () for category in CODEX_CATEGORY_IDS.values()},
        raw_category_ids={},
        codex_offset=0,
        trailing_offset=1,
        codex_end_offset=1,
        schema_profile="historydata-v16",
        candidate_count=1,
        candidate_score=(3, 0, 1000, 0, 0),
        achievement_ids=achievement_ids,
        achievement_status_available=available,
    )


def _insert_achievement(connection: sqlite3.Connection, achievement_id: int, name: str) -> None:
    connection.execute(
        """
        INSERT INTO achievements(
            achievement_id, sort_order, name, name_key, description, icon_path,
            category, is_hidden, condition_text, method_text, role_restriction,
            notes_json, common_notes_json, source_version, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            achievement_id,
            achievement_id,
            name,
            f"Achievement_Name_{achievement_id}",
            "描述",
            "icon.png",
            "测试",
            1 if achievement_id == 1002 else 0,
            "完成条件文本",
            "完成方法文本",
            "角色限制文本",
            json.dumps(["注意事项"], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            "test-version",
            json.dumps({"ID": achievement_id, "IsHidden": achievement_id == 1002}),
        ),
    )


class AchievementConditionTests(unittest.TestCase):
    def test_condition_catalog_covers_current_ids_and_ignores_resource_version(self) -> None:
        source_version, _common_notes, conditions = load_achievement_conditions()
        self.assertEqual(source_version, "1.0.15704 / catalog 2.3.1")
        self.assertEqual(len(conditions), 93)
        rows = [
            ConfigRow(
                "Config_Achievement",
                {"ID": achievement_id, "Name_Local": condition.name, "IsHidden": condition.hidden_in_text},
            )
            for achievement_id, condition in conditions.items()
        ]
        validate_achievement_conditions(rows, "new-game-version", conditions, source_version)
        self.assertTrue(conditions[1102].hidden_in_text)
        self.assertTrue(conditions[1102].role_restriction)
        self.assertEqual(conditions[9004].value_parameters, ())
        self.assertIn("Config_Achievement.ConditionSetId:32144", conditions[9004].config_references)
        self.assertIn("ach.taboo.overspend", conditions[3003].exclusions)
        self.assertEqual(conditions[9001].numeric_threshold, 12.0)
        self.assertIn("Config_Achievement.Threshold:12.0", conditions[9001].config_references)

    def test_condition_catalog_rejects_unknown_schema_version(self) -> None:
        payload = json.loads((ROOT / "achievement_conditions.json").read_text(encoding="utf-8"))
        payload["schema_version"] = 999
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conditions.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(AchievementConditionError):
                load_achievement_conditions(path)


class AchievementSaveTests(unittest.TestCase):
    def test_strict_history_reads_global_unlocked_achievement_ids(self) -> None:
        state = parse_codex_save_bytes(_pack_history((1001, 9006)))
        self.assertEqual(state.achievement_ids, (1001, 9006))
        self.assertTrue(state.achievement_status_available)
        self.assertEqual(state.schema_profile, "historydata-v16")

    def test_duplicate_strict_achievement_ids_are_rejected(self) -> None:
        with self.assertRaises(SaveParseError):
            parse_codex_save_bytes(_pack_history((1001, 1001)))

    def test_history_reader_falls_back_to_bak_for_achievement_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HistorySave.bytes"
            path.write_bytes(b"invalid")
            Path(f"{path}.bak").write_bytes(_pack_history((1001,)))
            state = read_history_save(path)
            self.assertTrue(state.file_info.used_backup)
            self.assertEqual(state.achievement_ids, (1001,))

    def test_legacy_structural_scan_marks_achievement_state_unavailable(self) -> None:
        state = read_codex_save(FIXTURE_DIR / "HistorySave_test2.bytes")
        self.assertTrue(state.achievement_status_available)
        self.assertGreater(len(state.achievement_ids), 0)

    def test_structural_scan_marks_unconfirmed_achievement_state_unavailable(self) -> None:
        chunks = [b"\x00", struct.pack("<i", 6)]
        for category_id in range(1, 7):
            chunks.extend((struct.pack("<i", category_id), struct.pack("<i", 0)))
        chunks.extend(struct.pack("<i", 0) for _ in range(3))
        state = parse_codex_save_bytes(b"".join(chunks))
        self.assertFalse(state.achievement_status_available)
        self.assertEqual(state.achievement_ids, ())


class AchievementDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.connection = sqlite3.connect(self.root / "database.sqlite3")
        self.connection.row_factory = sqlite3.Row
        initialize_database(self.connection)
        _insert_achievement(self.connection, 1001, "成就一")
        _insert_achievement(self.connection, 1002, "成就二")
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.close()
        self._temporary_directory.cleanup()

    def test_sync_marks_known_ids_and_reports_unknown_ids(self) -> None:
        state = _mock_state(self.root, (1001, 9999))
        with patch.object(codex_database, "read_codex_save", return_value=state):
            result = sync_game_completion(self.connection, self.root / "HistorySave.bytes", force=True)
        self.assertEqual(result.achievement_count, 1)
        self.assertEqual(result.unknown_achievement_ids, (9999,))
        self.assertEqual(get_achievement_summary(self.connection), {"total": 2, "completed": 1})
        self.assertEqual(
            [row["achievement_id"] for row in query_achievements(self.connection, completion_filter="completed")],
            [1001],
        )
        self.assertEqual(
            [row["achievement_id"] for row in query_achievements(self.connection, name_search="条件")],
            [1001, 1002],
        )

    def test_unavailable_legacy_state_does_not_clear_previous_achievement_status(self) -> None:
        available = _mock_state(self.root, (1001,))
        unavailable = _mock_state(self.root, (), available=False)
        with patch.object(codex_database, "read_codex_save", side_effect=[available, unavailable]):
            sync_game_completion(self.connection, self.root / "HistorySave.bytes", force=True)
            result = sync_game_completion(self.connection, self.root / "HistorySave.bytes", force=True)
        self.assertFalse(result.achievement_status_available)
        self.assertEqual(get_achievement_summary(self.connection), {"total": 2, "completed": 1})

    def test_sync_error_does_not_clear_previous_achievement_status(self) -> None:
        available = _mock_state(self.root, (1001,))
        with patch.object(codex_database, "read_codex_save", return_value=available):
            sync_game_completion(self.connection, self.root / "HistorySave.bytes", force=True)
        with patch.object(
            codex_database,
            "read_codex_save",
            side_effect=SaveParseError("parse failed"),
        ):
            result = sync_game_completion(self.connection, self.root / "HistorySave.bytes", force=True)
        self.assertEqual(result.status, "error")
        self.assertEqual(get_achievement_summary(self.connection), {"total": 2, "completed": 1})

    def test_packaged_database_clears_achievement_runtime_rows(self) -> None:
        self.connection.execute(
            "INSERT INTO achievement_completion(achievement_id, completed, updated_at) VALUES (1001, 1, 'test')"
        )
        self.connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('save_sha256', 'test')"
        )
        self.connection.commit()
        packaged = self.root / "packaged.sqlite3"
        prepare_packaged_database(self.root / "database.sqlite3", packaged)
        connection = sqlite3.connect(packaged)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM achievement_completion").fetchone()[0], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM metadata WHERE key LIKE 'save_%'").fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_resource_refresh_preserves_manual_achievement_data_and_status(self) -> None:
        database = self.root / "refresh.sqlite3"
        connection = sqlite3.connect(database)
        initialize_database(connection)
        _insert_achievement(connection, 1001, "manual achievement")
        connection.execute(
            "UPDATE achievements SET condition_text = 'manual-condition' WHERE achievement_id = 1001"
        )
        connection.execute(
            "INSERT INTO achievement_completion(achievement_id, completed, updated_at) VALUES (1001, 1, 'manual')"
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('achievement_condition_version', 'manual-version')"
        )
        connection.commit()
        connection.close()

        context = SimpleNamespace(
            package_version="new-game-version",
            bundle_name="new-bundle",
            bundle_path=Path("new-bundle.bytes"),
            tables={table_name: [] for table_name, _title in codex_database.AUXILIARY_TABLES},
        )
        selected_rows = {category: [] for category in codex_database.CATEGORY_ORDER}
        recipe_counts = {
            "recipe_items": 0,
            "recipe_tier_rules": 0,
            "storage_furniture": 0,
        }
        with (
            patch.object(codex_database, "build_extraction_context", return_value=context) as build_context,
            patch.object(
                codex_database,
                "load_achievement_conditions",
                side_effect=AssertionError("automatic refresh must not load manual conditions"),
            ),
            patch.object(
                codex_database,
                "load_recipe_static_data",
                return_value=([], [object()] * 496, []),
            ),
            patch.object(codex_database, "storage_furniture_specs_from_rows", return_value=[]),
            patch.object(codex_database, "collect_entries", return_value=({}, [])),
            patch.object(codex_database, "build_relations", return_value=[]),
            patch.object(codex_database, "select_category_rows", return_value=selected_rows),
            patch.object(codex_database, "populate_recipe_tables", return_value=recipe_counts),
        ):
            result = codex_database.build_database(
                Path("test-game"),
                database,
                sync_save=False,
                single_file=True,
                refresh_achievements=False,
            )

        self.assertFalse(build_context.call_args.kwargs["include_achievement"])
        self.assertEqual(result["achievements"], 1)
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT name, condition_text FROM achievements WHERE achievement_id = 1001"
                ).fetchone(),
                ("manual achievement", "manual-condition"),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT completed FROM achievement_completion WHERE achievement_id = 1001"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM metadata WHERE key = 'achievement_condition_version'"
                ).fetchone()[0],
                "manual-version",
            )
        finally:
            connection.close()

    def test_v9_achievement_condition_columns_migrate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-v9.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE achievements(
                    achievement_id INTEGER PRIMARY KEY,
                    sort_order INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    description TEXT NOT NULL,
                    icon_path TEXT NOT NULL,
                    category TEXT NOT NULL,
                    is_hidden INTEGER NOT NULL,
                    condition_text TEXT NOT NULL,
                    method_text TEXT NOT NULL,
                    role_restriction TEXT NOT NULL,
                    notes_json TEXT NOT NULL,
                    common_notes_json TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            initialize_database(connection)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(achievements)")
            }
            self.assertTrue(
                {
                    "numeric_threshold",
                    "value_parameters_json",
                    "exclusions_json",
                    "config_references_json",
                }.issubset(columns)
            )
            connection.close()


class AchievementHTTPTests(unittest.TestCase):
    def test_achievement_list_detail_and_unknown_id_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "database.sqlite3"
            connection = sqlite3.connect(database)
            initialize_database(connection)
            _insert_achievement(connection, 1001, "成就一")
            connection.commit()
            connection.close()

            service = CodexService(database, root / "missing-HistorySave.bytes")
            server = CodexHTTPServer(("127.0.0.1", 0), service, ROOT / "web", auto_exit=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(f"{base}/api/achievements", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["total"], 1)
                self.assertEqual(payload["entries"][0]["achievement_id"], 1001)
                with urllib.request.urlopen(f"{base}/api/achievements/1001", timeout=5) as response:
                    detail = json.loads(response.read().decode("utf-8"))
                self.assertIn("conditions", detail)
                self.assertIn("config_fields", detail)
                self.assertIn("exclusions", detail["conditions"])
                self.assertIn("config_references", detail["conditions"])
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(f"{base}/api/achievements/9999", timeout=5)
                error.exception.close()
                self.assertEqual(error.exception.code, 404)
                with urllib.request.urlopen(f"{base}/api/state", timeout=5) as response:
                    state = json.loads(response.read().decode("utf-8"))
                achievement_categories = [
                    item for item in state["categories"] if item["category"] == "achievements"
                ]
                self.assertEqual(achievement_categories[0]["total"], 1)
                self.assertNotIn("achievements", state["overall"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                service.close()


if __name__ == "__main__":
    unittest.main()
