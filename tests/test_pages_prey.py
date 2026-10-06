from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path
from unittest import mock

from codex_parser import ConfigRow, parse_config_table


ROOT = Path(__file__).resolve().parents[1]


def utf8_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<ii", ~len(raw), len(raw)) + raw


def pack_row(member_count: int, body: bytes) -> bytes:
    return struct.pack("<iB", 1, member_count) + body


def trap_row() -> bytes:
    body = struct.pack("<i", 1)
    body += utf8_text("Trap_Name_1") + utf8_text("简易捕鼠夹")
    body += utf8_text("Trap_Description_1") + utf8_text("简陋版本")
    body += struct.pack("<iiii", 1, 800, 200, 57600)
    body += struct.pack("<ii", 1, 1)                                # rooms [1]
    body += struct.pack("<ii", 1, 2501)                             # bait [2501]
    body += struct.pack("<ii", 1, 30000)                            # prey [30000]
    body += struct.pack("<ii", 1, 100)                              # discovery exp [100]
    body += struct.pack("<if", 1, 0.5)                              # base rate [0.5]
    body += struct.pack("<f", 18.0)                                 # empty weight
    body += utf8_text("../../Res/Furniture/UI_Item_Icon_bushujia.png")
    body += utf8_text("Assets/RuntimeAssets/Prefabs/Trap/P_Xianjing01")
    body += utf8_text("Assets/RuntimeAssets/Prefabs/Trap/P_Xianjing02")
    body += struct.pack("<ii", 1803, 1804)                          # remove / look action
    body += struct.pack("<ii", 1, 20004)                            # trap get [20004]
    body += struct.pack("<ii", 0, 0)                                # bait / prey capacity
    return pack_row(23, body)


def bait_row(bait_id: int = 2501) -> bytes:
    body = struct.pack("<i", bait_id)
    body += utf8_text("TrapBait_Name_2501")
    body += struct.pack("<ii", 2, 30000) + struct.pack("<i", 30001)
    body += struct.pack("<if", 2, 10.0) + struct.pack("<f", 2.0)
    body += utf8_text("TrapBait_Effect_Des_2501") + utf8_text("广谱诱饵 · 大多数猎物都会靠近")
    return pack_row(6, body)


def room_bias_row() -> bytes:
    body = struct.pack("<i", 1)
    body += utf8_text("一楼") + utf8_text("MapRoom_Name_1")
    body += struct.pack("<ii", 2, 30000) + struct.pack("<i", 30001)
    body += struct.pack("<if", 2, 1.5) + struct.pack("<f", 0.0)
    body += utf8_text("TrapRoomBias_Effect_Des_1") + utf8_text("对小家鼠具有较强的环境诱捕倾向。")
    return pack_row(7, body)


class TrapSchemaTests(unittest.TestCase):
    def test_trap_table_parses_exact_layout_and_rejects_drift(self) -> None:
        rows = parse_config_table(trap_row(), "Config_Trap")
        self.assertEqual(rows[0].values["Empty_Weight"], 18.0)
        self.assertEqual(rows[0].values["Base_Rate"], [0.5])
        self.assertEqual(rows[0].values["Trap_Get"], [20004])
        self.assertEqual(rows[0].values["Bait_id"], [2501])
        for invalid in (trap_row()[:-1], trap_row() + b"x"):
            with self.assertRaises(ValueError):
                parse_config_table(invalid, "Config_Trap")

    def test_bait_and_room_bias_tables_parse_to_eof(self) -> None:
        bait = parse_config_table(bait_row(), "Config_TrapBait")
        self.assertEqual(bait[0].values["Bait_coefficient"], [10.0, 2.0])
        bias = parse_config_table(room_bias_row(), "Config_TrapRoomBias")
        self.assertEqual(bias[0].values["Room_coefficient"], [1.5, 0.0])
        self.assertEqual(bias[0].values["Des1"], "一楼")
        with self.assertRaises(ValueError):
            parse_config_table(bait_row() + b"\x00", "Config_TrapBait")


def rows_from_bytes() -> dict[str, list[ConfigRow]]:
    return {
        "Config_Trap": [ConfigRow("Config_Trap", parse_config_table(trap_row(), "Config_Trap")[0].values)],
        "Config_TrapBait": [ConfigRow("Config_TrapBait", parse_config_table(bait_row(), "Config_TrapBait")[0].values),
                            ConfigRow("Config_TrapBait", {**parse_config_table(bait_row(), "Config_TrapBait")[0].values,
                                                          "ID": 2000})],
        "Config_TrapLv": [ConfigRow("Config_TrapLv", {
            "Lv": 1, "EXP": 280, "Info": "TrapLv_Info_1", "Info_Local": "见习猎手",
            "required_condition": [], "empty_weight_reduction": 0.1, "rare_prey_bonus": 0.0,
            "capture_cost_reduction": 0, "interval_reduction": 0.0, "unlock_recipes": []})],
        "Config_TrapRoomBias": [ConfigRow("Config_TrapRoomBias",
                                          parse_config_table(room_bias_row(), "Config_TrapRoomBias")[0].values)],
        "Config_TrapSlot": [ConfigRow("Config_TrapSlot", {
            "ID": 1, "Map_Id": 1, "Room_Id": 1, "Position": "HomeBuildingPos25"})],
        "Config_Item": [
            ConfigRow("Config_Item", {"ID": 30000, "ItemName_Local": "小家鼠", "Prey_Rarity": 1,
                                      "InCodex": True, "Icon": "Assets/RuntimeAssets/Texture/Food/mouse"}),
            ConfigRow("Config_Item", {"ID": 2501, "ItemName_Local": "意面",
                                      "Icon": "Assets/RuntimeAssets/Texture/Food/pasta"}),
            ConfigRow("Config_Item", {"ID": 2000, "ItemName_Local": "【开发者】之证"}),
            ConfigRow("Config_Item", {"ID": 25001, "ItemName_Local": "简易捕鼠夹", "Trap": 1,
                                      "Icon": "Assets/RuntimeAssets/Texture/Furniture/trap"}),
            ConfigRow("Config_Item", {"ID": 20004, "ItemName_Local": "铁皮"}),
            ConfigRow("Config_Item", {"ID": 14029, "ItemName_Local": "小型老鼠笼包裹",
                                      "TargetFurnitureID": 42010}),
        ],
        "Config_ProductionList": [ConfigRow("Config_ProductionList", {
            "ID": 201, "ShopName_Local": "简易捕鼠夹", "ProductID": [25001]}),
            ConfigRow("Config_ProductionList", {
                "ID": 327, "ShopName_Local": "小型老鼠笼包裹", "ProductID": [14029]})],
        "Config_Furniture": [ConfigRow("Config_Furniture", {
            "ID": cage_id, "Name_Local": cage_name, "Des_Local": cage_name + "。",
            "FurniturePrice": 50, "InstallTime": 200, "FurnitureHPMax": 1000,
            "ElectricalFurnitureID": 12, "BagId": 5007, "ICON": "../../Res/Furniture/cage.png"})
            for cage_id, cage_name in ((42009, "超大型老鼠笼"), (42010, "小型老鼠笼"),
                                       (42011, "中型老鼠笼"), (42012, "大型老鼠笼"))],
        "Config_FurnitureElectrical": [ConfigRow("Config_FurnitureElectrical", {
            "ID": 12, "ElectricalType": 6, "BasePower": 6.0, "FuelRate": 0.0868, "Capacity": 2.0})],
        "Config_Bag": [ConfigRow("Config_Bag", {
            "ID": 5007, "Name_Local": "老鼠笼饲料仓", "Size": [5, 2], "Burden": 0, "UseOwnerName": 0})],
    }


def fake_loader(rows: dict[str, list[ConfigRow]]):
    def loader(game_root: Path, name: str):
        return rows[name], "icons.bundle", "test", Path("bundle")
    return loader


class PreyModelTests(unittest.TestCase):
    def test_extract_prey_model_builds_rankings_and_cages(self) -> None:
        import codex_pages_prey
        rows = rows_from_bytes()
        with mock.patch.object(codex_pages_prey, "load_config_table", fake_loader(rows)):
            model = codex_pages_prey.extract_prey_model(Path("game"))
        self.assertEqual(model["game_version"], "test")
        self.assertEqual(model["prey"][0]["name"], "小家鼠")
        self.assertEqual(model["prey"][0]["traps"][0]["base_rate"], 0.5)
        # 只有可放置诱饵进入排行；TrapBait 里没有对应物品的特殊行与开发物品被排除。
        self.assertEqual(model["prey"][0]["top_baits"], [[2501, 10.0]])
        self.assertEqual([bait["id"] for bait in model["baits"]], [2501])
        self.assertEqual(model["baits"][0]["top"], [[30000, 10.0]])
        self.assertEqual(model["rooms"][0]["name"], "一楼")
        self.assertEqual(model["slots"], [{"room_id": 1, "name": "一楼", "count": 1}])
        self.assertEqual(model["trap_levels"][0]["info"], "见习猎手")
        cage_model = next(cage for cage in model["cages"] if cage["id"] == 42010)
        self.assertEqual(cage_model["capacity_mice"], 2.0)
        self.assertEqual(cage_model["power_per_mouse"], 6.0)
        self.assertEqual(cage_model["fuel_rate"], 0.0868)
        self.assertEqual(cage_model["bag_slots"], 10)
        self.assertEqual(cage_model["craft_key"], "Config_ProductionList:327")
        self.assertEqual(model["traps"][0]["craft_key"], "Config_ProductionList:201")
        self.assertEqual(model["traps"][0]["trap_get"], ["铁皮"])


class VersionedModelTests(unittest.TestCase):
    def test_prey_and_books_models_match_repository_version(self) -> None:
        from codex_pages import load_versioned_model
        model = load_versioned_model("books-model.json", "1.1.18293 / catalog 2.3.1")
        self.assertIsNotNone(model)
        self.assertEqual(len(model["books"]), 49)
        self.assertEqual(model["books"][0]["id"], 4)
        self.assertIsNone(load_versioned_model("books-model.json", "other / catalog other"))
        prey = load_versioned_model("prey-model.json", "1.1.18293 / catalog 2.3.1")
        self.assertIsNotNone(prey)
        self.assertEqual(len(prey["traps"]), 5)
        self.assertEqual(len(prey["baits"]), 2215)
        self.assertIsNone(load_versioned_model("prey-model.json", "other / catalog other"))


if __name__ == "__main__":
    unittest.main()
