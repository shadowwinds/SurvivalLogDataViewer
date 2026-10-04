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


if __name__ == "__main__":
    unittest.main()
