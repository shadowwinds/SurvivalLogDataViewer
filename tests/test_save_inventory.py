import struct
import unittest
from pathlib import Path

from codex_save import (
    SaveFileInfo,
    _SAVE_SCHEMAS,
    _inventory_from_game_save,
    _read_game_save_wire,
)


class SaveWireCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _null_value(type_name: str) -> bytes:
        if type_name == "bool" or type_name == "byte":
            return b"\x00"
        if type_name in {"int", "long", "float"}:
            return b"\x00" * {"int": 4, "long": 8, "float": 4}[type_name]
        if type_name == "Nullable<bool>":
            return b"\x00" * 2
        if type_name.startswith("Nullable<"):
            return b"\x00" * 8
        if type_name == "string":
            return struct.pack("<i", -1)
        if (
            type_name.endswith("[]")
            or type_name.startswith("List<")
            or type_name.startswith("Dictionary<")
        ):
            return struct.pack("<i", -1)
        return b"\xff"

    @staticmethod
    def _utf8_string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<ii", ~len(raw), len(value)) + raw

    @classmethod
    def _v183_game_save(cls) -> bytes:
        root_schema = _SAVE_SCHEMAS["GameSaveData"]
        child_schema = _SAVE_SCHEMAS["SaveChildData"]
        result = [bytes([len(root_schema)])]
        for name, type_name in root_schema:
            if name == "CurSave":
                result.append(bytes([183]))
                result.extend(cls._null_value(field_type) for _, field_type in child_schema)
                result.extend(struct.pack("<i", value) for value in (0, 0, 0, -1, -1, 0))
                result.append(struct.pack("<i", 1))
                result.append(struct.pack("<i", 919))
                result.append(cls._utf8_string("v183-extra"))
            elif name == "ProficiencyData":
                result.extend((bytes([2]), struct.pack("<i", -1), struct.pack("<i", -1)))
            else:
                result.append(cls._null_value(type_name))
        return b"".join(result)

    def test_v183_extra_dictionary_is_skipped_before_proficiency_data(self) -> None:
        parsed = _read_game_save_wire(self._v183_game_save())
        self.assertIsInstance(parsed["CurSave"], dict)
        self.assertIsNone(parsed["CurSave"]["LeadingRole"])


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

    def _read_inventory(
        self,
        root: dict[str, object],
        file_info: SaveFileInfo | None = None,
        **kwargs: object,
    ):
        """Give legacy in-memory fixtures an explicit character identity."""

        leading_role = (root.get("CurSave") or {}).get("LeadingRole")
        if isinstance(leading_role, dict) and "Name" not in leading_role:
            leading_config_id = leading_role.get("AgentConfigId")
            role_names = {
                1: "玩家-打工仔",
                2: "玩家-大学生",
            }
            role_ids = {1: 1, 2: 1002, 3: 1003}
            player_select_id = root.get("PlayerSelectId")
            if not isinstance(player_select_id, int):
                player_select_id = kwargs.get("player_select_id")
            if (
                not isinstance(leading_config_id, int)
                and not isinstance(player_select_id, int)
                and "PlayerSelectId" not in root
            ):
                root["PlayerSelectId"] = 1
                player_select_id = 1
            if not isinstance(leading_config_id, int) and isinstance(player_select_id, int):
                leading_role["AgentConfigId"] = role_ids.get(player_select_id, 1)
                leading_config_id = leading_role["AgentConfigId"]
            if isinstance(leading_config_id, int):
                resolved_id = {1: 1, 1002: 2, 1003: 3}.get(leading_config_id)
                if resolved_id in role_names:
                    leading_role["Name"] = role_names[resolved_id]
        if "PlayerSelectId" not in root and isinstance(kwargs.get("player_select_id"), int):
            root["PlayerSelectId"] = kwargs["player_select_id"]
        return _inventory_from_game_save(root, file_info or self.file_info, **kwargs)

    def test_leading_role_cooking_level_is_carried_with_inventory_state(self) -> None:
        state = self._read_inventory(
            {
                "PlayerSelectId": 2,
                "CurSave": {
                    "LeadingRole": {
                        "AgentConfigId": 1002,
                        "Name": "玩家-大学生",
                        "CookingLevel": 4,
                        "ItemList": [],
                        "MapConfigIdHome": 1,
                    },
                    "ChapterAgentMap": {},
                },
            }
        )

        self.assertEqual(state.cooking_level, 4)

    def test_marked_furniture_uses_config_id_and_wins_over_fallback(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [self._item(2527)], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "BagFurnitureConfigId": 15000,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos04",
                            "SaveInstanceId": 1001,
                            "ItemList": [self._item(2528)],
                        }
                    ]
                },
                "DoorBoxItems": [self._item(2529)],
                "DoorBoxItems2": [],
            }
        }
        state = self._read_inventory(root)

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
        state = self._read_inventory(root)

        self.assertEqual(
            [(item.item_config_id, item.item_count, item.source) for item in state.items],
            [
                (70105, 1, "主控背包"),
                (999999, 1, "主控背包"),
                (2527, 2, "双开门冰箱（兼容字段）"),
                (2528, 1, "冰柜（兼容字段）"),
            ],
        )

    def test_agent_config_id_recognizes_mapped_storage_and_ignores_other_furniture(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [self._item(2527)], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "BagFurnitureConfigId": 0,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2528)],
                        },
                        {
                            "AgentConfigId": 216,
                            "BagFurnitureConfigId": 0,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos02",
                            "ItemList": [self._item(2529)],
                        },
                        {
                            "AgentConfigId": 215,
                            "BagFurnitureConfigId": 217,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos03",
                            "ItemList": [self._item(2530)],
                        },
                        {
                            "AgentConfigId": 9001,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos04",
                            "ItemList": [self._item(2529)],
                        },
                        {
                            "AgentConfigId": 9002,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos05",
                            "ItemList": [self._item(2531)],
                        },
                    ]
                },
                "DoorBoxItems": [self._item(2530)],
                "DoorBoxItems2": [self._item(2531)],
            }
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={
                215: "双门冰箱",
                216: "冰柜",
                217: "双门冰箱",
            },
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527, 2528, 2529, 2530])
        self.assertEqual(state.items[1].source, "双门冰箱")
        self.assertEqual(state.items[2].source, "冰柜")
        self.assertEqual(state.items[3].source, "双门冰箱")
        self.assertEqual(state.container_counts["storage_215"], 1)
        self.assertEqual(state.container_counts["storage_216"], 1)
        self.assertEqual(state.container_counts["storage_217"], 1)
        self.assertNotIn("storage_9001", state.container_counts)
        self.assertNotIn("storage_9002", state.container_counts)

    def test_multiple_storage_configs_with_same_name_are_all_read(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 908,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "SaveInstanceId": 1001,
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 909,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos02",
                            "SaveInstanceId": 1002,
                            "ItemList": [self._item(2528)],
                        },
                    ]
                },
            }
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={908: "冰柜", 909: "冰柜"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527, 2528])
        self.assertEqual([item.source for item in state.items], ["冰柜", "冰柜"])
        self.assertEqual(
            state.container_counts,
            {"主控背包": 0, "storage_908": 1, "storage_909": 1},
        )

    def test_agent_config_is_used_when_bag_config_is_not_storage(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "BagFurnitureConfigId": 9998,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos06",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            }
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "储物家具"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.storage_containers[0].config_id, 215)

    def test_same_named_storage_is_filtered_by_home_location(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos04",
                            "SaveInstanceId": 1001,
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos04",
                            "SaveInstanceId": 1002,
                            "ItemList": [self._item(2528)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1004,
                            "SlotPosPoint": "NEWMaket01_after_29",
                            "SaveInstanceId": 1003,
                            "ItemList": [self._item(2529)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "UnknownBuildingPos04",
                            "SaveInstanceId": 1004,
                            "ItemList": [self._item(2530)],
                        },
                    ]
                },
            }
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "同名储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.container_counts["storage_215"], 1)
        self.assertEqual(
            [(container.instance_id, container.is_home, container.location) for container in state.storage_containers],
            [
                (1001, True, "home"),
                (1002, False, "other"),
                (1003, False, "other"),
                (1004, None, "unknown"),
            ],
        )
        self.assertTrue(any("位置无法确认" in diagnostic for diagnostic in state.diagnostics))

    def test_home_storage_slot_prefix_is_selected_by_player_role(self) -> None:
        cases = (
            (1, 1, "HomeBuildingPos01", "NeighborGirlBuildingPos01"),
            (2, 1002, "NeighborGirlBuildingPos01", "HomeBuildingPos01"),
            (3, 1003, "WarehousePos01", "HomeBuildingPos01"),
        )
        for player_select_id, agent_config_id, home_slot, other_slot in cases:
            with self.subTest(player_select_id=player_select_id):
                root = {
                    "PlayerSelectId": player_select_id,
                    "CurSave": {
                        "LeadingRole": {
                            "AgentConfigId": agent_config_id,
                            "ItemList": [],
                            "MapConfigIdHome": 1,
                        },
                        "ChapterAgentMap": {
                            1: [
                                {
                                    "AgentConfigId": 215,
                                    "MapConfigId": 1,
                                    "SlotPosPoint": home_slot,
                                    "ItemList": [self._item(2527)],
                                },
                                {
                                    "AgentConfigId": 215,
                                    "MapConfigId": 1,
                                    "SlotPosPoint": other_slot,
                                    "ItemList": [self._item(2528)],
                                },
                            ]
                        },
                    },
                }
                state = self._read_inventory(
                    root,
                    self.file_info,
                    storage_furniture={215: "储物容器"},
                )

                self.assertEqual([item.item_config_id for item in state.items], [2527])
                self.assertEqual(
                    {
                        container.slot_pos_point: container.is_home
                        for container in state.storage_containers
                    },
                    {home_slot: True, other_slot: False},
                )

    def test_leading_role_name_is_the_primary_identity(self) -> None:
        root = {
            "PlayerSelectId": 2,
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-大学生",
                    "AgentConfigId": 1002,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            },
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.role_context.role_name, "玩家-大学生")
        self.assertEqual(state.role_context.resolved_player_select_id, 2)
        self.assertEqual(state.role_context.resolution_source, "leading_role_name")

    def test_unknown_role_name_falls_back_to_numeric_identity(self) -> None:
        root = {
            "PlayerSelectId": 2,
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-新角色",
                    "AgentConfigId": 1002,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            },
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.role_context.resolved_player_select_id, 2)
        self.assertEqual(state.role_context.resolution_source, "game_save_player_select_id")
        self.assertTrue(any("未匹配已知角色" in diagnostic for diagnostic in state.role_context.diagnostics))
        self.assertTrue(any("兼容回退" in diagnostic for diagnostic in state.diagnostics))

    def test_missing_role_name_falls_back_to_history_identity(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {
                    "AgentConfigId": 1002,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            }
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
            player_select_id=2,
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertIsNone(state.role_context.role_name)
        self.assertEqual(state.role_context.resolved_player_select_id, 2)
        self.assertEqual(state.role_context.resolution_source, "history_player_select_id")
        self.assertTrue(any("Name 缺失" in diagnostic for diagnostic in state.role_context.diagnostics))
        self.assertTrue(any("Name 缺失" in diagnostic for diagnostic in state.diagnostics))
        self.assertTrue(any("history_player_select_id" in diagnostic for diagnostic in state.diagnostics))

    def test_role_name_conflict_falls_back_to_root_identity(self) -> None:
        root = {
            "PlayerSelectId": 1,
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-大学生",
                    "AgentConfigId": 1002,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2528)],
                        },
                    ]
                },
            },
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.role_context.resolved_player_select_id, 1)
        self.assertEqual(state.role_context.resolution_source, "game_save_player_select_id")
        self.assertTrue(any("数字身份不一致" in diagnostic for diagnostic in state.diagnostics))

    def test_unresolved_role_skips_chapter_storage(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-未知角色",
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            }
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual(state.items, ())
        self.assertIsNone(state.role_context.resolved_player_select_id)
        self.assertEqual(state.role_context.resolution_source, "unresolved")
        self.assertIsNone(state.storage_containers[0].is_home)
        self.assertTrue(any("跳过" in diagnostic for diagnostic in state.diagnostics))

    def test_empty_storage_slot_is_not_assumed_to_be_home(self) -> None:
        root = {
            "PlayerSelectId": 1,
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-打工仔",
                    "AgentConfigId": 1,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "",
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            },
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual(state.items, ())
        self.assertIsNone(state.storage_containers[0].is_home)

    def test_save_player_select_id_overrides_leading_role_and_fallback_uses_leading_role(self) -> None:
        root = {
            "PlayerSelectId": 2,
            "CurSave": {
                "LeadingRole": {
                    "AgentConfigId": 1,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2528)],
                        },
                    ]
                },
            },
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )
        self.assertEqual([item.item_config_id for item in state.items], [2528])

        fallback_root = {
            "CurSave": {
                "LeadingRole": {
                    "AgentConfigId": 1003,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "WarehousePos01",
                            "ItemList": [self._item(2529)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2530)],
                        },
                    ]
                },
            },
        }
        fallback_state = self._read_inventory(
            fallback_root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )
        self.assertEqual([item.item_config_id for item in fallback_state.items], [2529])

    def test_legacy_storage_mapping_reads_role_two_fridge_and_freezer(self) -> None:
        root = {
            "PlayerSelectId": 2,
            "CurSave": {
                "LeadingRole": {"AgentConfigId": 1002, "ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 80062,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos40",
                            "SaveInstanceId": 8006201,
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 15001,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos37",
                            "SaveInstanceId": 1500101,
                            "ItemList": [self._item(2528)],
                        },
                    ]
                },
            },
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={80062: "豪华版双门冰箱", 15001: "冰柜"},
        )

        self.assertEqual(
            sorted(item.item_config_id for item in state.items),
            [2527, 2528],
        )
        self.assertEqual(
            [container.config_id for container in state.storage_containers],
            [15001, 80062],
        )
        self.assertEqual(
            [container.location for container in state.storage_containers],
            ["home", "home"],
        )

    def test_init_chapter_id_selects_group_independently_of_role_id(self) -> None:
        root = {
            "InitChapterId": 1,
            "PlayerSelectId": 3,
            "CurSave": {
                "LeadingRole": {
                    "Name": "玩家-仓库管理员",
                    "AgentConfigId": 1003,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "WarehousePos01",
                            "SaveInstanceId": 1001,
                            "ItemList": [self._item(2527)],
                        }
                    ],
                    3: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "WarehousePos01",
                            "SaveInstanceId": 1003,
                            "ItemList": [self._item(2528)],
                        }
                    ],
                },
            },
        }

        state = _inventory_from_game_save(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.role_context.role_name, "玩家-仓库管理员")
        self.assertEqual(state.role_context.resolved_player_select_id, 3)
        self.assertEqual(state.role_context.resolved_chapter_map_key, 1)
        self.assertEqual(
            state.role_context.chapter_resolution_source,
            "game_save_init_chapter_id",
        )
        self.assertEqual(
            {container.chapter_map_key: container.is_home for container in state.storage_containers},
            {1: True, 3: False},
        )

    def test_chapter_map_key_mismatch_is_other_even_when_agent_map_matches(self) -> None:
        root = {
            "InitChapterId": 1,
            "PlayerSelectId": 2,
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2527)],
                        }
                    ],
                    2: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "NeighborGirlBuildingPos01",
                            "ItemList": [self._item(2528)],
                        }
                    ],
                },
            },
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(
            {
                container.chapter_map_key: container.is_home
                for container in state.storage_containers
            },
            {1: True, 2: False},
        )

    def test_explicit_player_select_id_is_used_when_save_field_is_missing(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {
                    "AgentConfigId": 1,
                    "ItemList": [],
                    "MapConfigIdHome": 1,
                },
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "WarehousePos01",
                            "ItemList": [self._item(2529)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2530)],
                        },
                    ]
                },
            },
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
            player_select_id=3,
        )

        self.assertEqual([item.item_config_id for item in state.items], [2529])

    def test_unknown_player_role_does_not_treat_same_map_or_home_prefix_as_home(self) -> None:
        root = {
            "PlayerSelectId": 99,
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "HomeBuildingPos01",
                            "ItemList": [self._item(2527)],
                        },
                        {
                            "AgentConfigId": 215,
                            "MapConfigId": 1,
                            "SlotPosPoint": "",
                            "ItemList": [self._item(2528)],
                        },
                    ]
                },
            },
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={215: "储物容器"},
        )

        self.assertEqual(state.items, ())
        self.assertEqual(
            {
                container.slot_pos_point: container.is_home
                for container in state.storage_containers
            },
            {"": None, "HomeBuildingPos01": False},
        )

    def test_door_box_flag_is_read_without_a_name_mapping(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {
                    1: [
                        {
                            "AgentConfigId": 1000,
                            "BagFurnitureConfigId": 9999,
                            "IsDoorBox": True,
                            "MapConfigId": 1,
                            "ItemList": [self._item(2527)],
                        }
                    ]
                },
            }
        }
        state = self._read_inventory(
            root,
            self.file_info,
            storage_furniture={},
        )

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.container_counts["storage_9999"], 1)
        self.assertEqual(state.storage_containers[0].name, "ID:9999")

    def test_workbench_drawer_is_included_as_home_storage(self) -> None:
        root = {
            "CurSave": {
                "LeadingRole": {"ItemList": [], "MapConfigIdHome": 1},
                "ChapterAgentMap": {},
                "WorkbenchDrawerItems": [self._item(2527, 2)],
            }
        }
        state = self._read_inventory(root, storage_furniture={})

        self.assertEqual([item.item_config_id for item in state.items], [2527])
        self.assertEqual(state.container_counts["workbench_drawer"], 1)
        self.assertEqual(state.storage_containers[0].name, "工作台抽屉")


if __name__ == "__main__":
    unittest.main()
