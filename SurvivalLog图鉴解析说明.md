# Survival Log 图鉴离线解析说明

## 结论

本项目直接读取当前本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，不启动游戏，不读取或修改存档、mod DLL 或游戏资源。

当前本地游戏资源版本为 `1.0.14956`，catalog 版本为 `2.3.1`。一次完整解析会生成六份主图鉴 Markdown 和一份辅助配置 Markdown：

- [SurvivalLog食品.md](./SurvivalLog食品.md)
- [SurvivalLog菜肴.md](./SurvivalLog菜肴.md)
- [SurvivalLog植物.md](./SurvivalLog植物.md)
- [SurvivalLog猎物.md](./SurvivalLog猎物.md)
- [SurvivalLog制造.md](./SurvivalLog制造.md)
- [SurvivalLog家具.md](./SurvivalLog家具.md)
- [SurvivalLog图鉴辅助配置.md](./SurvivalLog图鉴辅助配置.md)

当前版本主图鉴数量为：食品 174、菜肴 496、植物 34、猎物 19、制造 125、家具 87。参考图片中的完成进度为食品 61、菜肴 93、植物 14、猎物 15、制造 110、家具 73，合计 `366/935`，约为 39%。这些完成数量只用于验收和前端参考，离线解析器不会据此伪造具体完成 ID。

## 游戏图鉴运行时

安装目录是 IL2CPP 构建，没有可直接阅读的 C# 源文件；`global-metadata.dat` 保留了编译时源文件路径、类型和方法名。当前版本可以确认：

- `Assets/GameCore/HotUpdate/Battle/Logic/Codex/CodexManager.cs`
- `Assets/GameCore/HotUpdate/Codex/DishCodexGrouping.cs`
- `Assets/GameCore/HotUpdate/ReduxUI/Store/State_Reducer/2_UI/Codex/SR_Web_Codex.cs`
- `Assets/GameCore/HotUpdate/ReduxUI/WebUI/WebUIMsg/WebUI_Codex.cs`
- `Assets/GameCore/HotUpdate/Config/ConfigData/Config_CodexMilestone.cs`

元数据中还包含 `IsInCodex`、`GetUnlockedCount`、`GetTotalCount`、`IsEntryUnlocked`、`BuildTotalCache`、`GetEntryName` 和 `GetEntryIcon` 等成员。网页界面由运行时发送分类列表和条目列表；存档解锁状态属于运行时数据，解析器不模拟它。

## 主图鉴分类规则

食品和猎物使用当前游戏 Codex 字段，两个分类允许重叠：

- 食品：`Config_Item.InCodex == true && Category == 1`。
- 猎物：`Config_Item.InCodex == true && Prey_Rarity > 0`。
- 菜肴：当前 `Config_CookingRecipe` 的全部 496 条配置。
- 植物：`Config_Plant.InCodex == true`。
- 制造：`Config_ProductionList.InCodex == true`。
- 家具：`Config_Furniture.InCodex == true`。

因此，猎物物品可以同时出现在食品和猎物 Markdown 中；数据库只保存一份完成状态，并通过分类映射分别计数。

主表和关联表如下：

| 输出 | 主表 | 主要关联表 |
| --- | --- | --- |
| 食品 | `Config_Item` | `Config_ItemSubCategory`、`Config_FoodType` |
| 菜肴 | `Config_CookingRecipe` | `Config_Item`、`Config_ItemSubCategory` |
| 植物 | `Config_Plant` | `Config_PlantLv`、`Config_Item` |
| 猎物 | `Config_Item` | 猎物字段位于物品表中 |
| 制造 | `Config_ProductionList` | `Config_ProductionLv`、`Config_Item` |
| 家具 | `Config_Furniture` | `Config_FurnitureFunc`、`Config_FurnitureCook`、`Config_FurniturePlant`、`Config_FurnitureElectrical`、`Config_FurnitureState`、`Config_FurnitureTag`、`Config_FurniturePartner` |

主 Markdown 只展开主表条目。物品子分类、食品标签、植物等级、制造等级和家具辅助表集中写入 `SurvivalLog图鉴辅助配置.md`。

所有关联字段保留原始数字并尽量解析名称。无法解析的 ID 显示为 `ID:xxxx`；空值和游戏使用的 0 哨兵显示为“无”。本地化名称按本地化字段、非本地化配置键、ID 顺序回退。

## 资源包和 MemoryPack

相关配置位于 YooAsset catalog 指向的 MemoryPack TextAsset 中，当前主要位于：

`mainpackage_assets_runtimeassets_config_memorypack.bundle`

当前 bundle 解密算法为：

```text
Salt = SL_BundleCrypto_v1_9f3d7a1c
key  = MD5(Salt + BundleName) + MD5(BundleName + Salt)
data[i] ^= key[i % 32]
```

工具会验证 catalog 读取到末尾、每张表的对象数量和字段数量、每行字段完整读取，以及数据游标到达原始数据末尾。schema 变化会返回表名、行号、字段数量或 offset 等错误，不会静默按旧格式猜测。

## 命令行

解析脚本为 [图鉴解析工具.py](./图鉴解析工具.py)。默认生成全部七份 Markdown：

```powershell
python "图鉴解析工具.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --output-dir "."
```

单独导出菜肴：

```powershell
python "图鉴解析工具.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --category dish `
  --output "SurvivalLog菜肴.md"
```

可用分类为 `food|dish|plant|prey|craft|furniture|auxiliary`。`all` 模式使用 `--output-dir`，单分类模式可以使用 `--output`。输出路径不能位于游戏安装目录中。

## SQLite 数据库

[图鉴数据库.py](./图鉴数据库.py) 复用解析器读取上下文并构建 SQLite 数据库：

```powershell
python "图鉴数据库.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --database "SurvivalLog图鉴.sqlite3"
```

数据库保存主条目、分类映射、共享完成状态、关联关系、辅助配置原始行和资源元数据。重新导入使用事务和 upsert，不重置已有完成状态；数据库文件不会写入游戏目录。

## Streamlit 前端

[图鉴前端.py](./图鉴前端.py) 读取 SQLite 并提供分类、搜索、完成状态筛选、条目网格、详情和手动完成勾选：

```powershell
streamlit run "图鉴前端.py" -- --database "SurvivalLog图鉴.sqlite3"
```

前端显示静态总数，不复现游戏网页在部分分类中以 `???` 隐藏总数的行为。前端勾选是本地数据库中的用户记录，不代表存档解锁状态。

## 已知限制

- 解析的是当前安装版本的静态配置，不包含存档解锁、玩家库存或运行时动态修改。
- `Config_CodexMilestone` 用于游戏图鉴里程碑，不参与六类主条目数量和完成勾选。
- 条件组、奖励组、动作、房间和掉落组等没有独立解析表的引用保留原始 ID，并以 `ID:xxxx` 标明。
- 参考仓库只用于字段命名和交叉校验，最终数据源始终是当前本地游戏资源。
- 重新运行只覆盖用户指定输出目录中的目标 Markdown 或数据库，不修改游戏文件、mod DLL、存档或 catalog。
