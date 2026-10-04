from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from codex_pages import icon_filename
from codex_pages_icons import extract_icons, web_icon_source


class PagesIconTests(unittest.TestCase):
    def test_null_bundle_reference_uses_configured_web_icon_only(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, output, database = root / "game", root / "icons", root / "codex.sqlite3"
            resources = game / "SurvivalLog_Data/StreamingAssets/WebUI/Res/Food"
            resources.mkdir(parents=True)
            Image.new("RGBA", (256, 128), (40, 80, 20, 100)).save(resources / "pheasant.png")
            icon = "Assets/RuntimeAssets/Texture/Food/pheasant"
            absent = "Assets/RuntimeAssets/Texture/Food/absent"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE codex_entries(source_table TEXT, raw_json TEXT, is_current INTEGER)")
                connection.execute("CREATE TABLE recipe_items(item_id INTEGER, raw_json TEXT)")
                connection.execute("CREATE TABLE achievements(raw_json TEXT)")
                for path, web in ((icon, "../../Res/Food/pheasant.png"), (absent, "../../Res/Food/absent.png")):
                    connection.execute("INSERT INTO codex_entries VALUES ('Config_Item', ?, 1)",
                                       (json.dumps({"Icon": path, "WebIcon": web}),))
                connection.execute("INSERT INTO codex_entries VALUES ('Config_Item', ?, 0)",
                                   (json.dumps({"Icon": "PRIVATE_ICON", "WebIcon": "../../Res/Food/pheasant.png"}),))
                connection.commit()
            bundle = SimpleNamespace(file_hash="bundle", name="icons", encrypted=True)
            environment = SimpleNamespace(container={icon + ".png": None})
            with patch("codex_pages_icons.find_catalog", return_value=game / "catalog"), \
                 patch("codex_pages_icons.parse_catalog", return_value=({icon + ".png": 0}, [bundle], "test")), \
                 patch("codex_pages_icons.decrypt_bundle", return_value=b"bundle"), \
                 patch("codex_pages_icons.load_unitypy", return_value=SimpleNamespace(load=lambda _: environment)):
                extract_icons(database, game, output)
            with Image.open(output / icon_filename(icon)) as image:
                self.assertEqual(image.size, (192, 96))
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getpixel((0, 0))[3], 100)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["icons"], [icon_filename(icon)])
            self.assertEqual(manifest["web_ui_icons"], [icon_filename(icon)])
            self.assertEqual(manifest["missing"], [icon_filename(absent)])
            self.assertNotIn(str(game), json.dumps(manifest))
            self.assertIsNone(web_icon_source(game, "../../Res/Food/../pheasant.png"))
            self.assertIsNone(web_icon_source(game, "https://example.com/pheasant.png"))
            self.assertIsNone(web_icon_source(game, "../../Res/Other/pheasant.png"))

    def test_other_categories_extract_only_current_configured_and_product_icons(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, output, database = root / "game", root / "icons", root / "codex.sqlite3"
            refs = ["../../Res/Food/flower.png", "../../Res/Food/flower_seeds.png",
                    "../../Res/Material/paper.png", "../../Res/Furniture/planter.png", "../../Res/icon/trophy.png"]
            for ref in refs:
                file = game / "SurvivalLog_Data/StreamingAssets/WebUI" / ref.removeprefix("../../")
                file.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 24), (20, 30, 40)).save(file)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("CREATE TABLE codex_entries(source_table TEXT, raw_json TEXT, is_current INTEGER)")
                connection.execute("CREATE TABLE recipe_items(item_id INTEGER, raw_json TEXT)")
                connection.execute("CREATE TABLE achievements(raw_json TEXT)")
                for table, raw, current in (("Config_Plant", {"Gain": [20, 20], "Perfect_Gain": [20, 21]}, 1),
                                            ("Config_ProductionList", {"ProductID": [30], "FailedID": [31], "perfect_item_id": [32]}, 1),
                                            ("Config_Furniture", {"ICON": refs[3]}, 1),
                                            ("Config_ProductionList", {"ProductID": [40]}, 0)):
                    connection.execute("INSERT INTO codex_entries VALUES (?, ?, ?)", (table, json.dumps(raw), current))
                for item_id, ref in ((20, refs[0]), (21, refs[1]), (30, refs[2]), (31, "FAILED_ICON"),
                                     (32, "PERFECT_ICON"), (40, "PRIVATE_UNUSED_ICON")):
                    connection.execute("INSERT INTO recipe_items VALUES (?, ?)", (item_id, json.dumps({"WebIcon": ref})))
                connection.execute("INSERT INTO achievements VALUES (?)", (json.dumps({"WebIcon": refs[4]}),))
            with patch("codex_pages_icons.find_catalog", return_value=game / "catalog"), \
                 patch("codex_pages_icons.parse_catalog", return_value=({}, [], "test")), \
                 patch("codex_pages_icons.load_unitypy", return_value=SimpleNamespace()):
                extract_icons(database, game, output)
            manifest = json.loads((output / "manifest.json").read_text())
            expected = sorted(icon_filename(ref) for ref in refs)
            self.assertEqual(manifest["icons"], expected)
            self.assertEqual(manifest["web_ui_icons"], expected)
            self.assertEqual(manifest["missing"], [])
            for filename in expected:
                with Image.open(output / filename) as image:
                    self.assertEqual(image.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
