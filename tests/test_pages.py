from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from codex_database import CATEGORY_LABELS, DATABASE_SCHEMA_VERSION, STATIC_SCHEMA_SQL
from codex_pages import SOURCE_DIR, build_pages, export_data


class PagesExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "static.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript(STATIC_SCHEMA_SQL)
            connection.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                [
                    ("database_schema_version", str(DATABASE_SCHEMA_VERSION)),
                    ("game_version", "test / catalog test"),
                    ("game_root", "PRIVATE_GAME_PATH"),
                    ("save_path", "PRIVATE_SAVE_PATH"),
                ],
            )
            connection.executemany(
                "INSERT INTO codex_categories VALUES (?, ?, ?)",
                [(key, label, index) for index, (key, label) in enumerate(CATEGORY_LABELS.items())],
            )
            connection.executemany(
                """
                INSERT INTO codex_entries
                VALUES (?, 'Config_Item', ?, ?, '', '', '', ?, ?)
                """,
                [
                    ("Config_Item:1", 1, "食品", '{"ID":1,"price":2,"InCodex":true,"ValueDisplay1":8,"ValueDisplay2":-4,"ValueDisplay3":0,"FoodTag1":4,"FoodTag2":4,"FoodTag3":99,"SubCategory":11,"CanCook":true}', 1),
                    ("Config_Item:2", 2, "旧条目", '{"ID":2}', 0),
                ],
            )
            connection.executemany(
                "INSERT INTO codex_entry_categories VALUES (?, ?, ?)",
                [("Config_Item:1", "food", 1), ("Config_Item:1", "prey", 1), ("Config_Item:2", "food", 2)],
            )
            connection.execute(
                "INSERT INTO entry_relations VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("Config_Item:1", "目标家具", "Config_Furniture", 99999, "ID:99999", 0, ""),
            )
            connection.execute(
                """
                INSERT INTO achievements (
                    achievement_id, sort_order, name, name_key, description, icon_path,
                    category, is_hidden, condition_text, method_text, role_restriction,
                    notes_json, common_notes_json, source_version, raw_json
                ) VALUES (1, 1, '隐藏成就', '', '', '', '剧情', 1, '完成条件',
                          '完成方法', '', '[]', '[]', 'test', '{"ID":1}')
                """
            )
            connection.execute("CREATE TABLE completion (player TEXT)")
            connection.execute("INSERT INTO completion VALUES ('PRIVATE_PLAYER_STATE')")
            connection.executemany(
                "INSERT INTO auxiliary_rows VALUES (?, ?, ?, ?)",
                [("Config_FoodType", 4, "鱼类", "{}"), ("Config_ItemSubCategory", 11, "菌菇", "{}")],
            )
            connection.execute(
                "INSERT INTO codex_entries VALUES (?, 'Config_CookingRecipe', 10, '测试料理', '', '', '', ?, 1)",
                ("Config_CookingRecipe:10", '{"ID":10,"PerfectItemID":101,"GoodItemID":102,"NormalItemID":103,"FailItemID":104}'),
            )
            connection.execute("INSERT INTO codex_entry_categories VALUES ('Config_CookingRecipe:10', 'dish', 10)")
            for item_id, value in ((101, 60), (102, 50), (103, 40)):
                connection.execute(
                    "INSERT INTO recipe_items VALUES (?, ?, 0, 1, 2, '肉类', 0, ?)",
                    (item_id, f"成品{item_id}", json.dumps({"ID": item_id, "ValueDisplay1": value, "ValueDisplay2": -3,
                                                          "ItemDes2_Local": "食用说明", "private": "PRIVATE_UNUSED_FIELD"})),
                )

    def test_export_excludes_personal_metadata_and_runtime_and_keeps_source_read_only(self) -> None:
        before = hashlib.sha256(self.database.read_bytes()).digest()
        payload = export_data(self.database)
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("PRIVATE_", text)
        self.assertNotIn('"completed"', text)
        self.assertEqual(set(payload["metadata"]), {"game_version", "database_schema_version"})
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).digest())

    def test_export_preserves_overlap_unknown_ids_and_hidden_achievements(self) -> None:
        payload = export_data(self.database)
        categories = {item["id"]: item for item in payload["categories"]}
        self.assertEqual([item["id"] for item in categories["food"]["entries"]], [1])
        self.assertEqual(categories["food"]["entries"][0]["key"], categories["prey"]["entries"][0]["key"])
        unknown = categories["food"]["entries"][0]["relations"][0]
        self.assertEqual(unknown["target_name"], "ID:99999")
        self.assertNotIn("link", unknown)
        self.assertTrue(categories["achievements"]["entries"][0]["hidden"])

    def test_build_keeps_unrelated_files_and_generates_relative_assets(self) -> None:
        output = self.root / "output"
        output.mkdir()
        unrelated = output / "keep.txt"
        unrelated.write_text("keep", encoding="utf-8")
        build_pages(self.database, output)
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
        self.assertTrue((output / ".nojekyll").is_file())
        self.assertIn('href="./styles.css"', (output / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((output / "data.json").read_text(encoding="utf-8"))["format_version"], 1)

    def test_food_stats_preserve_negative_zero_missing_and_repeated_tags(self) -> None:
        categories = {item["id"]: item for item in export_data(self.database)["categories"]}
        food = categories["food"]["entries"][0]["food"]
        self.assertEqual([stat["value"] for stat in food["stats"]], [8, -4, 0, None, None])
        self.assertEqual([stat["label"] for stat in food["stats"]], ["饱食", "心态", "精力", "健康", "生命"])
        self.assertEqual(food["tags"], [{"id": 4, "name": "鱼类", "count": 2}, {"id": 99, "name": "ID:99", "count": 1}])
        self.assertEqual(food["sub_category"], "菌菇")
        self.assertTrue(food["cookable"])

    def test_dish_effects_use_referenced_product_quality_and_do_not_guess_missing_item(self) -> None:
        categories = {item["id"]: item for item in export_data(self.database)["categories"]}
        products = categories["dish"]["entries"][0]["products"]
        self.assertEqual([product["quality"] for product in products], ["完美", "良好", "普通", "失败"])
        self.assertEqual([product["stats"][0]["value"] for product in products], [60, 50, 40, None])
        self.assertEqual(products[3]["name"], "ID:104")
        self.assertEqual(products[0]["note"], "食用说明")
        self.assertNotIn("PRIVATE_", json.dumps(products))

    def test_schema_change_fails_before_writing_output(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE metadata SET value='999' WHERE key='database_schema_version'")
        output = self.root / "output"
        with self.assertRaisesRegex(ValueError, "schema"):
            build_pages(self.database, output)
        self.assertFalse(output.exists())

    def test_missing_database_and_source_output_are_rejected(self) -> None:
        with self.assertRaises(FileNotFoundError):
            export_data(self.root / "missing.sqlite3")
        with self.assertRaises(ValueError):
            build_pages(self.database, SOURCE_DIR)
        with self.assertRaises(ValueError):
            build_pages(self.database, self.root)


if __name__ == "__main__":
    unittest.main()
