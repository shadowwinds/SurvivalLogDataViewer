"""Public planting requirements and reverse links from harvested food."""

from __future__ import annotations

from typing import Any, Callable


def add_planting_data(categories: list[dict[str, Any]], raw_entries: dict[str, dict[str, Any]],
                      items: dict[int, tuple[str, dict[str, Any]]],
                      planter_configs: dict[int, dict[str, Any]],
                      public_icon: Callable[[str], str]) -> list[dict[str, Any]]:
    groups = {category["id"]: category["entries"] for category in categories}
    foods = {entry["id"]: entry for entry in groups["food"]}
    sources: dict[int, list[dict[str, Any]]] = {}
    for plant in groups["plant"]:
        raw = raw_entries[plant["key"]]
        plant["plant"] = {"size": raw.get("Size"), "light_need": raw.get("LightNeed"),
                          "cold_resistance": raw.get("ColdResistance"), "growth_seconds": raw.get("GrowthTime")}
        harvest_ids = list(dict.fromkeys([*raw.get("Gain", []), *raw.get("Perfect_Gain", [])]))
        for item_id in harvest_ids:
            if item_id in foods:
                sources.setdefault(item_id, []).append({"category": "plant", "key": plant["key"],
                                                        "id": plant["id"], "name": plant["name"]})
        # Plant configs reference 3D models, so use an actual harvested food icon first.
        candidates = [item_id for item_id in harvest_ids if items.get(item_id, ("", {}))[1].get("Category") == 1]
        candidates += [item_id for item_id in harvest_ids if item_id not in candidates]
        for item_id in candidates:
            name, item = items.get(item_id, (f"ID:{item_id}", {}))
            icon = public_icon(item.get("Icon") or item.get("WebIcon") or "")
            if icon:
                plant["icon"] = icon
                plant["icon_source"] = {"id": item_id, "name": name}
                break
    for prey in groups["prey"]:
        if prey["id"] in foods:
            sources.setdefault(prey["id"], []).append({"category": "prey", "key": prey["key"],
                                                     "id": prey["id"], "name": prey["name"]})
    for category in ("food", "prey"):
        for entry in groups[category]:
            entry["sources"] = sources.get(entry["id"], [])
    planters = []
    for furniture in groups["furniture"]:
        config_id = raw_entries[furniture["key"]].get("PlantFurnitureID", 0)
        config = planter_configs.get(config_id)
        if not config:
            continue
        planters.append({"id": furniture["id"], "key": furniture["key"], "name": furniture["name"],
                         "config_id": config_id, "capacity": config.get("Capacity"),
                         "light_bonus": config.get("AddLight"), "heat_bonus": config.get("AddHeat"),
                         "needs_power": config.get("NeedPower"), "electric_light": config.get("ElectricLight"),
                         "electric_heat": config.get("ElectricHeat")})
    return planters
