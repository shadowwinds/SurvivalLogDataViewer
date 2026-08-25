# Survival Log 图鉴离线解析说明

## 结论

可以不进入游戏，直接读取本地安装目录中的静态配置，生成六类图鉴 Markdown。工具不会启动游戏，也不会读取或修改存档、mod DLL 和游戏资源。

当前本地游戏资源版本为 `1.0.14956`，catalog 版本为 `2.3.1`。一次完整运行会生成：

- [SurvivalLog食品.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog食品.md)
- [SurvivalLog菜谱.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog菜谱.md)
- [SurvivalLog植物.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog植物.md)
- [SurvivalLog猎物.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog猎物.md)
- [SurvivalLog制造.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog制造.md)
- [SurvivalLog家具.md](D:/Codex/000/SurvivalLogDataViewer/SurvivalLog家具.md)

本次本地版本的主配置数量为：菜谱 496 条、植物 38 条、制造 148 条、家具 1,249 条、食品 155 条、猎物 19 条。家具文件的头部数量只统计 `Config_Furniture` 主条目；文件后面还附带家具功能、烹饪、种植、电力、状态、标签和伙伴关联表，所以 Markdown 标题总数会更大。

## mod 的查询方式

这个 mod 不是联网查询，也没有单独保存一份菜谱数据库。主要调用链是：

1. `ViewerUI.RefreshRecipes()` 调用 `GameApi.DumpAllCookingRecipes(filter, searchKey)`。
2. `GameApi` 取得游戏 `ConfigManager` 单例。
3. 从 `ConfigManager._Config_CookingRecipe_Dict` 遍历全部 `Config_CookingRecipe` 对象。
4. 使用 `_Config_Item_Dict` 将 `SpecificItems` 中的物品 ID 转为 `ItemName_Local`。
5. 如果 `SpecificItems` 为空，则把 `TagCombo` 中的 ID 转为 `Config_ItemSubCategory` 本地化名称。
6. 每条菜谱显示名称、做法、烹饪经验、时间和等级等字段。

菜谱是否已解锁由存档中的 `CodexManager.IsEntryUnlocked(..., recipeId)` 判断。离线工具因此导出全部静态菜谱，不模拟某个存档的解锁状态。

## 数据来源

配置资源位于 YooAsset catalog 指向的 MemoryPack TextAsset 中。当前相关配置都在逻辑 bundle：

`mainpackage_assets_runtimeassets_config_memorypack.bundle`

导出的六类数据使用以下表：

| 输出 | 主表 | 关联表 |
| --- | --- | --- |
| 食品 | `Config_Item` | `Config_ItemSubCategory`、`Config_FoodType` |
| 菜谱 | `Config_CookingRecipe` | `Config_Item`、`Config_ItemSubCategory` |
| 植物 | `Config_Plant` | `Config_PlantLv`、`Config_Item` |
| 猎物 | `Config_Item` | 无独立 `Config_Prey`；使用物品表中的猎物字段 |
| 制造 | `Config_ProductionList` | `Config_ProductionLv`、`Config_Item` |
| 家具 | `Config_Furniture` | `Config_FurnitureFunc`、`Config_FurnitureCook`、`Config_FurniturePlant`、`Config_FurnitureElectrical`、`Config_FurnitureState`、`Config_FurnitureTag`、`Config_FurniturePartner` |

## 分类规则

食品和猎物严格按当前游戏配置和 Codex 字段处理，不照搬参考网页的物品分类：

- 先要求 `Config_Item.InCodex == true`。
- `Prey_Rarity > 0` 的物品归入猎物；当前版本没有独立的 `Config_Prey` 表。
- 其余 `Category == 1` 的物品归入食品。
- `Prey_Rarity`、`CaptureExp`、`IT_Discovery_Exp` 和 `InCodex` 会原样写入食品/猎物文件，便于复核分类。

植物、制造和家具文件读取当前版本的完整静态表，不按存档解锁状态过滤。家具关联配置按字段类型解析：功能 ID 对应 `Config_FurnitureFunc`，种植/烹饪/电力配置 ID 对应各自关联表，包裹、材料、产物、种子和燃料 ID 对应 `Config_Item`，允许菜谱 ID 对应 `Config_CookingRecipe`，伙伴触发家具和伙伴配置 ID 对应 `Config_Furniture`。

每个条目同时保留原始 ID 和解析后的名称。没有名称或关联表中不存在的 ID 会显示为 `ID:xxxx`；空值或游戏使用的 0 哨兵显示为“无”。空本地化名称会回退到配置键或 ID。

## 资源包和 MemoryPack

游戏通过 `GameCore.Scripts.BundleDecryption` 解密 bundle。当前版本的密钥算法是：

```text
Salt = SL_BundleCrypto_v1_9f3d7a1c
key  = MD5(Salt + BundleName) + MD5(BundleName + Salt)
data[i] ^= key[i % 32]
```

解密后是标准 UnityFS bundle，配置 TextAsset 使用 MemoryPack。工具会检查每张表的对象数量、对象字段数和读取位置，解析必须到达数据末尾；资源版本、bundle 和物理文件路径会写入每份 Markdown 的头部。MemoryPack 读取遵循其[官方二进制格式说明](https://github.com/Cysharp/MemoryPack#binary-wire-format-specification)。

## 命令行

脚本：[菜谱解析工具.py](D:/Codex/000/SurvivalLogDataViewer/菜谱解析工具.py)

默认生成六份文件：

```powershell
python "D:\Codex\000\SurvivalLogDataViewer\菜谱解析工具.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --output-dir "D:\Codex\000\SurvivalLogDataViewer"
```

如需单独导出某一类，显式指定分类；下面以菜谱分类为例：

```powershell
python "D:\Codex\000\SurvivalLogDataViewer\菜谱解析工具.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --category dish `
  --output "D:\Codex\000\SurvivalLogDataViewer\SurvivalLog菜谱.md"
```

单独导出某一类时使用 `--category food|dish|plant|prey|craft|furniture`，并可用 `--output` 指定该分类的文件路径。省略 `--category` 或显式使用 `--category all` 时始终生成全部六类，此时使用 `--output-dir` 指定目录。六类分类和导出流程一致，不对菜谱设置专用兼容路径。

## 已知限制

- 解析的是当前安装版本的静态配置，不包含存档解锁、玩家库存或运行时动态修改。
- 条件组、奖励组、动作、房间和掉落组等当前未加载独立配置表的引用会保留原始 ID，并以 `ID:xxxx` 标明，不能凭空推断名称。
- 参考仓库 `AssassinLYB/STEAM-SurvivalLog-wiki` 用于字段命名和交叉校验；最终数据源始终是本地游戏资源。参考仓库标记的版本是 `v1.0.14911`，本地版本可能包含新增物品。
- 重新运行只覆盖输出目录中对应的 Markdown 文件，不写入游戏安装目录。
