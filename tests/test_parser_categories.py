from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_database
import codex_update
from codex_database import collect_entries
from codex_parser import (
    CONFIG_SCHEMAS,
    FIELD_LABELS,
    ConfigRow,
    ExtractionContext,
    render_dish_markdown,
    select_category_rows,
)
from codex_update import GameInstallation


TABLE_NAMES = (
    "Config_Item",
    "Config_ItemSubCategory",
    "Config_FoodType",
    "Config_CookingRecipe",
    "Config_Plant",
    "Config_PlantLv",
    "Config_ProductionList",
    "Config_ProductionLv",
    "Config_Furniture",
    "Config_FurnitureFunc",
    "Config_FurnitureCook",
    "Config_FurniturePlant",
    "Config_FurnitureElectrical",
    "Config_FurnitureState",
    "Config_FurnitureTag",
    "Config_FurniturePartner",
    "Config_Achievement",
)


def build_test_context() -> ExtractionContext:
    tables = {table_name: [] for table_name in TABLE_NAMES}
    tables["Config_Item"] = [
        ConfigRow(
            "Config_Item",
            {
                "ID": 10,
                "ItemName": "Item_10",
                "ItemName_Local": "Item 10",
                "Category": 1,
                "InCodex": True,
                "Prey_Rarity": 1,
            },
        ),
        ConfigRow(
            "Config_Item",
            {
                "ID": 11,
                "ItemName": "Item_11",
                "ItemName_Local": "Item 11",
                "Category": 1,
                "InCodex": False,
                "Prey_Rarity": 0,
            },
        ),
        ConfigRow(
            "Config_Item",
            {
                "ID": 12,
                "ItemName": "Item_12",
                "ItemName_Local": "Item 12",
                "Category": 2,
                "InCodex": False,
                "Prey_Rarity": 2,
            },
        ),
        ConfigRow(
            "Config_Item",
            {
                "ID": 13,
                "ItemName": "Item_13",
                "ItemName_Local": "Item 13",
                "Category": 1,
                "InCodex": 1,
                "Prey_Rarity": 3,
            },
        ),
    ]
    tables["Config_ItemSubCategory"] = [
        ConfigRow(
            "Config_ItemSubCategory",
            {"ID": 2, "Name": "Subcategory_2", "Name_Local": "Subcategory 2"},
        )
    ]
    tables["Config_CookingRecipe"] = [
        ConfigRow("Config_CookingRecipe", {"ID": 100, "RecipeName": "Recipe_100"})
    ]
    tables["Config_Plant"] = [
        ConfigRow("Config_Plant", {"ID": 20, "Name": "Plant_20", "InCodex": False}),
        ConfigRow("Config_Plant", {"ID": 21, "Name": "Plant_21", "InCodex": True}),
    ]
    tables["Config_ProductionList"] = [
        ConfigRow(
            "Config_ProductionList",
            {"ID": 30, "ShopName": "Craft_30", "InCodex": False},
        ),
        ConfigRow(
            "Config_ProductionList",
            {"ID": 31, "ShopName": "Craft_31", "InCodex": True},
        ),
    ]
    tables["Config_Furniture"] = [
        ConfigRow("Config_Furniture", {"ID": 40, "Name": "Furniture_40", "InCodex": False}),
        ConfigRow("Config_Furniture", {"ID": 41, "Name": "Furniture_41", "InCodex": True}),
    ]
    return ExtractionContext(
        game_root=Path("test-game"),
        package_version="test-version",
        bundle_name="test-bundle",
        bundle_path=Path("test-bundle.bundle"),
        tables=tables,
    )


class CategorySelectionTests(unittest.TestCase):
    def test_category_selection_uses_final_export_policy(self) -> None:
        selected = select_category_rows(build_test_context())

        self.assertEqual([row.row_id for row in selected["food"]], [10])
        self.assertEqual([row.row_id for row in selected["dish"]], [100])
        self.assertEqual([row.row_id for row in selected["prey"]], [10])
        self.assertEqual([row.row_id for row in selected["plant"]], [21])
        self.assertEqual([row.row_id for row in selected["craft"]], [31])
        self.assertEqual([row.row_id for row in selected["furniture"]], [41])

    def test_database_memberships_share_overlapping_item_entry(self) -> None:
        entries, memberships = collect_entries(build_test_context())

        self.assertEqual(len(entries), 5)
        self.assertEqual(len(memberships), 6)
        self.assertEqual(entries["Config_Item:10"].row_id, 10)
        self.assertEqual(
            {(entry_key, category) for entry_key, category, _ in memberships
             if entry_key == "Config_Item:10"},
            {("Config_Item:10", "food"), ("Config_Item:10", "prey")},
        )


class DishRenderingTests(unittest.TestCase):
    def test_dish_snapshot_renders_every_schema_field(self) -> None:
        context = build_test_context()
        dish_values = {field: None for field, _kind in CONFIG_SCHEMAS["Config_CookingRecipe"]}
        dish_values.update(
            {
                "ID": 100,
                "RecipeName": "Recipe_100",
                "RecipeName_Local": "Recipe 100",
                "TagCombo": [2],
                "SpecificItems": [10],
                "PerfectItemID": 10,
                "CookTime": 60,
            }
        )
        content = render_dish_markdown(
            context,
            [ConfigRow("Config_CookingRecipe", dish_values)],
        )

        for field, _kind in CONFIG_SCHEMAS["Config_CookingRecipe"]:
            label = FIELD_LABELS.get(field, field)
            self.assertIn(f"- {label}：", content)
        self.assertIn("Item 10（ID 10）", content)
        self.assertIn("Subcategory 2（ID 2）", content)
        self.assertIn("60 秒（1.0 分钟）", content)


class AchievementSchemaTests(unittest.TestCase):
    def _pack_string(self, value: str) -> bytes:
        import struct

        raw = value.encode("utf-8")
        return struct.pack("<ii", ~len(raw), len(value)) + raw

    def _pack_row(self, achievement_id: int) -> bytes:
        import struct

        values = [
            struct.pack("<ii", achievement_id, 10),
            self._pack_string("Achievement_Name"),
            self._pack_string("成就"),
            self._pack_string("Achievement_Des"),
            self._pack_string("描述"),
            self._pack_string("STEAM_KEY"),
            self._pack_string("icon.png"),
            b"\x00",
            self._pack_string("small.png"),
            struct.pack("<i", 11),
            struct.pack("<if", 2, 1.0) + struct.pack("<f", 0.0),
            struct.pack("<ii", 1, 0),
            self._pack_string("counter"),
            struct.pack("<if", 0, 2.0),
            struct.pack("<i", 0),
            b"\x00",
            self._pack_string("progress"),
            struct.pack("<f", 2.0),
        ]
        return b"\x15" + b"".join(values)

    def test_achievement_schema_reads_float_list_and_eof(self) -> None:
        import struct
        from codex_parser import parse_config_table

        raw = struct.pack("<i", 1) + self._pack_row(1001)
        rows = parse_config_table(raw, "Config_Achievement")
        self.assertEqual(rows[0].row_id, 1001)
        self.assertEqual(rows[0].values["Value"], [1.0, 0.0])
        with self.assertRaises(ValueError):
            parse_config_table(raw + b"x", "Config_Achievement")

    def test_achievement_schema_rejects_wrong_member_count_and_duplicate_id(self) -> None:
        import struct
        from codex_parser import parse_config_table

        with self.assertRaises(ValueError):
            parse_config_table(struct.pack("<i", 1) + b"\x14", "Config_Achievement")
        raw = struct.pack("<i", 2) + self._pack_row(1001) + self._pack_row(1001)
        with self.assertRaisesRegex(ValueError, "重复 ID"):
            parse_config_table(raw, "Config_Achievement")


class DatabaseRefreshTests(unittest.TestCase):
    def _make_metadata_database(self, schema_version: str) -> Path:
        directory = Path(self._temporary_directory.name)
        database = directory / "codex.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("game_version", "1.0.15130 / catalog 2.3.1"),
                    ("database_schema_version", schema_version),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        return database

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_same_game_version_with_old_database_policy_is_rebuilt(self) -> None:
        database = self._make_metadata_database("5")
        game = GameInstallation(
            root=Path("test-game"),
            catalog_path=Path("test-catalog"),
            package_version="1.0.15130 / catalog 2.3.1",
        )

        with patch.object(codex_database, "build_database") as build_database:
            result = codex_update.update_database_if_needed(database, game)

        self.assertEqual(result.status, "updated")
        build_database.assert_called_once_with(game.root, database, sync_save=False)
