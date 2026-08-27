import unittest
from pathlib import Path

from codex_save import SaveFileInfo, _inventory_from_game_save


class SaveInventorySourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.file_info = SaveFileInfo(
            path=Path("<memory>"),
            sha256="0" * 64,
            size=0,
            mtime_ns=0,
            read_at="test",
        )

    @staticmethod
    def _item(item_id: int, count: int = 1) -> dict[str, int]:
        return {"ItemConfigId": item_id, "ItemCount": count}

    def test_marked_furniture_uses_config_id_and_wins_over_fallback(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [self._item(2527)]},
                "ChapterAgentMap": {
                    1: [
                        {
                            "BagFurnitureConfigId": 15000,
                            "ItemList": [self._item(2528)],
                        }
                    ]
                },
                "DoorBoxItems": [self._item(2529)],
                "DoorBoxItems2": [],
            }
        }
        state = _inventory_from_game_save(root, self.file_info)

        self.assertEqual([item.item_config_id for item in state.items], [2527, 2528])
        self.assertTrue(any("标记家具" in diagnostic for diagnostic in state.diagnostics))
        self.assertEqual(state.container_counts["fridge_15000"], 1)

    def test_fallback_is_used_only_without_marked_furniture_and_unknown_is_preserved(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [self._item(70105), self._item(999999)]},
                "ChapterAgentMap": {},
                "DoorBoxItems": [self._item(2527, 2)],
                "DoorBoxItems2": [self._item(2528)],
            }
        }
        state = _inventory_from_game_save(root, self.file_info)

        self.assertEqual(
            [(item.item_config_id, item.item_count, item.source) for item in state.items],
            [
                (70105, 1, "主控背包"),
                (999999, 1, "主控背包"),
                (2527, 2, "双开门冰箱（兼容字段）"),
                (2528, 1, "冰柜（兼容字段）"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
