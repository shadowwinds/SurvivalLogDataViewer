from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from codex_database import CATEGORY_LABELS, DATABASE_SCHEMA_VERSION, STATIC_SCHEMA_SQL
from codex_pages import SOURCE_DIR, build_pages, dish_servings, export_data
from codex_pages_seo import browse_categories, normalize_site_url


class PageHTML(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.text: list[str] = []
        self.schemas: list[dict] = []
        self.in_schema = False
        self.feed(text)

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs["href"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "meta":
            self.meta[attrs.get("name") or attrs.get("property") or ""] = attrs.get("content", "")
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.in_schema = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_schema = False

    def handle_data(self, data: str) -> None:
        if self.in_schema:
            self.schemas.append(json.loads(data))
        else:
            self.text.append(data)


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
                [("Config_FoodType", 4, "鱼类", "{}"), ("Config_ItemSubCategory", 11, "菌菇", "{}"),
                 ("FoodTag1", 4, "生食材", "{}"), ("FoodTag2", 4, "绿色食品", "{}")],
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

    def test_planting_export_links_only_current_harvests_and_uses_food_icon(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO recipe_items VALUES (1, '食品', 1, 1, 11, '菌菇', 0, ?)",
                               (json.dumps({"ID": 1, "Category": 1, "Icon": "food-icon", "private": "PRIVATE_UNUSED_FIELD"}),))
            for plant_id, current, gain, perfect, seed in ((20, 1, [1, 1], [1], [101]),
                                                         (21, 0, [1], [], []), (22, 1, [], [], [1])):
                raw = {"ID": plant_id, "Size": 2, "LightNeed": 0, "ColdResistance": 3,
                       "GrowthTime": 86400, "Gain": gain, "Perfect_Gain": perfect, "Gain_Seed": seed}
                connection.execute("INSERT INTO codex_entries VALUES (?, 'Config_Plant', ?, ?, '', '', '', ?, ?)",
                                   (f"Config_Plant:{plant_id}", plant_id, f"植物{plant_id}", json.dumps(raw), current))
                connection.execute("INSERT INTO codex_entry_categories VALUES (?, 'plant', ?)",
                                   (f"Config_Plant:{plant_id}", plant_id))
        with patch("codex_pages.public_icon", side_effect=lambda path: "./icons/00000000000000000000.png" if path == "food-icon" else ""):
            payload = export_data(self.database)
        groups = {category["id"]: category["entries"] for category in payload["categories"]}
        plant = groups["plant"][0]
        self.assertEqual(plant["icon_source"], {"id": 1, "name": "食品"})
        self.assertEqual(plant["icon"], "./icons/00000000000000000000.png")
        self.assertEqual(plant["plant"], {"size": 2, "light_need": 0, "cold_resistance": 3, "growth_seconds": 86400})
        self.assertEqual([(source["category"], source["id"]) for source in groups["food"][0]["sources"]],
                         [("plant", 20), ("prey", 1)])
        self.assertNotIn("PRIVATE_", json.dumps(payload))
        output = self.root / "plant-pages"
        build_pages(self.database, output)
        document = PageHTML((output / "guide/food/1/index.html").read_text(encoding="utf-8"))
        self.assertTrue(any(link.endswith('/guide/plant/20/') for link in document.links))
        self.assertTrue(any(link.endswith('#prey/Config_Item%3A1') for link in document.links))
        plant_document = (output / "guide/plant/20/index.html").read_text(encoding="utf-8")
        self.assertIn("光照需求", plant_document)
        self.assertIn("≥ 0", plant_document)
        self.assertIn("≤ 3", plant_document)

    def test_planters_use_public_furniture_config_and_do_not_export_auxiliary_private_fields(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            for furniture_id, current, config_id in ((30, 1, 17), (31, 0, 18), (32, 1, 999), (33, 1, 0)):
                connection.execute("INSERT INTO codex_entries VALUES (?, 'Config_Furniture', ?, ?, '', '', '', ?, ?)",
                                   (f"Config_Furniture:{furniture_id}", furniture_id, f"花盆{furniture_id}",
                                    json.dumps({"PlantFurnitureID": config_id}), current))
                connection.execute("INSERT INTO codex_entry_categories VALUES (?, 'furniture', ?)",
                                   (f"Config_Furniture:{furniture_id}", furniture_id))
            for config_id in (17, 18, 19):
                connection.execute("INSERT INTO auxiliary_rows VALUES ('Config_FurniturePlant', ?, '', ?)",
                                   (config_id, json.dumps({"Capacity": 2, "AddLight": 0, "AddHeat": 1, "NeedPower": True,
                                                          "ElectricLight": 2, "ElectricHeat": 0,
                                                          "private": "PRIVATE_UNUSED_FIELD"})))
        planters = export_data(self.database)["planters"]
        self.assertEqual([planter["id"] for planter in planters], [30])
        self.assertEqual((planters[0]["capacity"], planters[0]["heat_bonus"], planters[0]["electric_light"]), (2, 1, 2))
        self.assertNotIn("PRIVATE_", json.dumps(planters))

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

    def test_food_stats_preserve_negative_zero_missing_and_separate_tag_namespaces(self) -> None:
        categories = {item["id"]: item for item in export_data(self.database)["categories"]}
        food = categories["food"]["entries"][0]["food"]
        self.assertEqual([stat["value"] for stat in food["stats"]], [8, -4, 0, None, None])
        self.assertEqual([stat["label"] for stat in food["stats"]], ["饱腹", "心态", "精力", "健康", "生命"])
        self.assertEqual(food["tags"], [
            {"id": 4, "field": "FoodTag1", "key": "FoodTag1:4", "name": "生食材", "count": 1},
            {"id": 4, "field": "FoodTag2", "key": "FoodTag2:4", "name": "绿色食品", "count": 1},
        ])
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

    def test_ingredient_export_uses_tier_rules_without_requiring_codex_membership(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO recipe_tier_rules VALUES (11, '菌菇', 15, 6, '', '')")
            for item_id, price, expected in ((201, 5, 3), (202, 6, 2), (203, 15, 1)):
                raw = {"ID": item_id, "Category": 1, "SubCategory": 11, "CanCook": True,
                       "InCodex": False, "price": price, "private": "PRIVATE_UNUSED_FIELD"}
                connection.execute("INSERT INTO recipe_items VALUES (?, ?, 1, 1, 11, '菌菇', 0, ?)",
                                   (item_id, f"菌菇{expected}", json.dumps(raw)))
        ingredients = export_data(self.database)["cooking_ingredients"]
        self.assertEqual([(item["id"], item["tier"]) for item in ingredients], [(201, 3), (202, 2), (203, 1)])
        self.assertNotIn("PRIVATE_", json.dumps(ingredients))

    def test_unknown_food_tags_keep_id_and_do_not_resolve_through_food_type(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE codex_entries SET raw_json=? WHERE source_id=1",
                               (json.dumps({"ID": 1, "FoodTag1": 99, "FoodTag2": 0, "FoodTag3": 4}),))
        food = next(c for c in export_data(self.database)["categories"] if c["id"] == "food")["entries"][0]["food"]
        self.assertEqual(food["tags"][0]["name"], "ID:99")
        self.assertEqual(len(food["tags"]), 1)

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

    def test_sitemap_and_canonicals_cover_real_routes_without_duplicate_food_prey(self) -> None:
        output = self.root / "output"
        base = "https://example.org/fork/"
        build_pages(self.database, output, base)
        tree = ElementTree.parse(output / "sitemap.xml")
        urls = [node.text for node in tree.findall("{*}url/{*}loc")]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertIn(base + "guide/food/1/", urls)
        self.assertNotIn(base + "guide/prey/1/", urls)
        self.assertNotIn(base + "guide/", urls)
        self.assertNotIn(base + "guide/prey/", urls)
        self.assertTrue(all(url.startswith(base) and "#" not in url for url in urls))
        for url in urls:
            source = output / url.removeprefix(base) / "index.html"
            document = PageHTML(source.read_text(encoding="utf-8"))
            self.assertEqual(document.canonicals, [url])
            self.assertEqual(document.meta["og:url"], url)
            self.assertTrue(document.meta["description"])
            self.assertTrue(document.schemas)
            self.assertNotIn("PRIVATE_", source.read_text(encoding="utf-8"))
        prey = PageHTML((output / "guide/prey/index.html").read_text(encoding="utf-8"))
        self.assertIn(base + "#prey/", prey.links)
        self.assertEqual(prey.meta["robots"], "noindex,follow")
        self.assertIn("./guide/food/1/", PageHTML((output / "index.html").read_text(encoding="utf-8")).links)

    def test_static_details_show_stats_tags_and_all_qualities_without_javascript(self) -> None:
        output = self.root / "output"
        build_pages(self.database, output)
        food = " ".join(PageHTML((output / "guide/food/1/index.html").read_text(encoding="utf-8")).text)
        for value in ("+8", "-4", "0", "未提供", "生食材", "绿色食品", "菌菇", "可用于烹饪：是", "ID:99999"):
            self.assertIn(value, food)
        dish = " ".join(PageHTML((output / "guide/dish/10/index.html").read_text(encoding="utf-8")).text)
        for value in ("完美品质", "优良品质", "普通品质", "失败品质", "+60", "+50", "+40", "ID:104", "食用说明", "未提供"):
            self.assertIn(value, dish)
        document = (output / "guide/dish/10/index.html").read_text(encoding="utf-8")
        self.assertIn('../../../i18n.js', document)
        self.assertNotIn('app.js', document)

    def test_game_text_is_escaped_in_html_and_jsonld(self) -> None:
        malicious = '</script><img src=x onerror="alert(1)"> & 食材'
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE codex_entries SET name=?, description=? WHERE source_id=1", (malicious, malicious))
        output = self.root / "output"
        build_pages(self.database, output)
        text = (output / "guide/food/1/index.html").read_text(encoding="utf-8")
        self.assertNotIn(malicious, text)
        self.assertNotIn('<img src=x', text)
        document = PageHTML(text)
        page = document.schemas[0]["@graph"][0]
        self.assertIn(malicious, page["name"])
        self.assertIn(malicious, " ".join(document.text))

    def test_site_url_validation_prevents_invalid_canonical_before_writing(self) -> None:
        self.assertEqual(normalize_site_url("https://example.org/project"), "https://example.org/project/")
        for url in ("/relative/", "javascript:alert(1)", "https://user:pass@example.org/", "https://example.org/?q=x", "https://example.org/#food", "https://example.org/a/../b", "https://example.org/%2e%2e/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                build_pages(self.database, self.root / "invalid", url)
        self.assertFalse((self.root / "invalid").exists())

    def test_nested_output_link_is_rejected_before_overwriting_any_page(self) -> None:
        output = self.root / "output"
        output.mkdir()
        home = output / "index.html"
        home.write_text("keep", encoding="utf-8")
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda path: path == output / "guide" or original(path)):
            with self.assertRaisesRegex(ValueError, "符号链接"):
                build_pages(self.database, output)
        self.assertEqual(home.read_text(encoding="utf-8"), "keep")

    def test_same_names_are_disambiguated_with_category_or_config_id(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            for key, table, item_id, name, category in (
                    ("Config_Item:3", "Config_Item", 3, "食品", "food"),
                    ("Config_ProductionList:1", "Config_ProductionList", 1, "加工木板", "craft"),
                    ("Config_Furniture:1", "Config_Furniture", 1, "加工木板", "furniture")):
                connection.execute("INSERT INTO codex_entries VALUES (?, ?, ?, ?, '', '', '', ?, 1)",
                                   (key, table, item_id, name, json.dumps({"ID": item_id})))
                connection.execute("INSERT INTO codex_entry_categories VALUES (?, ?, ?)", (key, category, item_id))
        output = self.root / "output"
        build_pages(self.database, output)
        for path, qualifier in (("food/1", "（ID:1）"), ("food/3", "（ID:3）"),
                                ("craft/1", "制造图鉴"), ("furniture/1", "家具图鉴")):
            text = (output / "guide" / path / "index.html").read_text(encoding="utf-8")
            title = text.split("<title>", 1)[1].split("</title>", 1)[0]
            self.assertIn(qualifier, title)

    def test_ready_food_view_partitions_food_without_changing_original_memberships_or_urls(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO codex_entries VALUES ('Config_Item:3','Config_Item',3,'即食食品','','','',?,1)",
                               (json.dumps({"ID": 3, "CanCook": False, "UseTimes": 2, "CantUse": False}),))
            connection.execute("INSERT INTO codex_entry_categories VALUES ('Config_Item:3','food',3)")
        payload = export_data(self.database)
        self.assertEqual(next(c for c in payload["categories"] if c["id"] == "food")["entries"][-1]["id"], 3)
        views = {c["id"]: c for c in browse_categories(payload)}
        self.assertEqual([e["id"] for e in views["food"]["entries"]], [1])
        self.assertEqual([e["id"] for e in views["ready-food"]["entries"]], [3])
        self.assertEqual(views["ready-food"]["entries"][0]["food"]["use_times"], 2)
        output = self.root / "output"
        base = "https://example.org/project/"
        build_pages(self.database, output, base)
        index = PageHTML((output / "guide/ready-food/index.html").read_text(encoding="utf-8"))
        self.assertIn(base + "#ready-food/", index.links)
        detail = (output / "guide/food/3/index.html").read_text(encoding="utf-8")
        self.assertIn("每份可食用 2 次", detail)
        self.assertIn('class="icon-uses"', detail)
        self.assertIn('>2次</span>', detail)
        self.assertIn("#ready-food/Config_Item%3A3", detail)

    def test_fixed_dish_servings_follow_native_ceiling_split_and_show_per_use_stats(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            raw = {"ID": 10, "SpecificItems": [1], "SatietyStandard": 40,
                   "PerfectItemID": 101, "GoodItemID": 102, "NormalItemID": 103, "FailItemID": 104}
            connection.execute("UPDATE codex_entries SET raw_json=? WHERE entry_key='Config_CookingRecipe:10'", (json.dumps(raw),))
        products = next(c for c in export_data(self.database)["categories"] if c["id"] == "dish")["entries"][0]["products"]
        self.assertEqual([p["serving_count"] for p in products], [2, 2, 1, None])
        self.assertEqual([p["per_use_stats"][0]["value"] if p["per_use_stats"] else None for p in products], [30, 25, 40, None])
        self.assertEqual(products[0]["stats"][0]["value"], 60)
        self.assertEqual(products[0]["per_use_stats"][1]["value"], -1.5)
        output = self.root / "output"
        build_pages(self.database, output)
        html = (output / "guide/dish/10/index.html").read_text(encoding="utf-8")
        self.assertIn("整份可吃 2 次", html)
        self.assertIn("每次食用属性", html)
        self.assertEqual(html.count('class="icon-uses"'), 4)

    def test_split_boundaries_and_unknown_generic_counts_are_not_fixed_to_config_use_times(self) -> None:
        products = next(c for c in export_data(self.database)["categories"] if c["id"] == "dish")["entries"][0]["products"]
        self.assertTrue(all(p["serving_count"] is None and p["per_use_stats"] is None for p in products))
        for value, expected in ((0, 1), (40, 1), (41, 2), (60, 2), (80, 2), (81, 3), (None, None)):
            profile = {"stats": [{"label": "饱食", "value": value}]}
            with self.subTest(value=value):
                self.assertEqual(dish_servings(profile, 40, True)[0], expected)
        self.assertEqual(dish_servings(products[0], 0, True), (None, None))

    def test_explicit_empty_combo_fallback_uses_configured_product_split(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            raw = {"ID": 10, "TagCombo": [], "SpecificItems": [], "SatietyStandard": 40, "PerfectItemID": 101}
            connection.execute("UPDATE codex_entries SET raw_json=? WHERE entry_key='Config_CookingRecipe:10'", (json.dumps(raw),))
        dish = next(c for c in export_data(self.database)["categories"] if c["id"] == "dish")["entries"][0]
        self.assertEqual(dish["portion_model"]["mode"], "fixed")
        self.assertEqual(dish["products"][0]["serving_count"], 2)


if __name__ == "__main__":
    unittest.main()
