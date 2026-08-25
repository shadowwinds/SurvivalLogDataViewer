# Survival Log 图鉴离线解析说明

## 结论

本项目直接读取当前本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，并只读读取用户本机的 `HistorySave.bytes` 图鉴完成状态；不启动游戏，不修改存档、mod DLL 或游戏资源。

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

元数据中还包含 `IsInCodex`、`GetUnlockedCount`、`GetTotalCount`、`IsEntryUnlocked`、`BuildTotalCache`、`GetEntryName` 和 `GetEntryIcon` 等成员。`CodexManager._unlockedMap` 是运行时映射，`PersistToHistory`/`SaveCodexUnlocked` 将其写入 `HistoryData.CodexUnlocked`；本项目从存档读取这个持久化分类 ID 列表，不读取 `Save_*.bytes` 中只用于界面快照的 `CodexUnlocked` 汇总值。

## 游戏存档完成状态

默认存档路径为：

`%USERPROFILE%\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes`

独立解析器 [图鉴存档解析.py](./图鉴存档解析.py) 按当前 `HistoryData` MemoryPack 字段顺序读取到 `CodexUnlocked`，校验 `HistoryData` 成员数、历史条目成员数、分类 ID、集合长度、重复 ID 和文件读取稳定性。存档正在写入或主文件解析失败时，会只读尝试同名 `.bak`；两者均失败则数据库保留上一次有效完成状态。

当前存档的分类完成数量为食品 61、菜肴 93、植物 14、猎物 15、制造 110、家具 73，分类映射合计 `366/935`。食品和猎物可能引用同一个 `Config_Item`，数据库在 `completion` 中只保存一份主状态，同时在 `category_completion` 中保存按分类的完成状态，使两个分类分别计数。

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
  --database "SurvivalLog图鉴.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

数据库保存主条目、分类映射、共享主完成状态、分类完成状态、关联关系、辅助配置原始行和资源元数据。重新导入使用事务和 upsert；存档同步先完整解析，成功后才在事务中更新状态，失败不会清空上一次有效状态。数据库文件不会写入游戏目录或存档目录。

没有存档时可以使用 `--no-save-sync` 只构建静态数据库，完成状态保持未完成。

## 轻量本地网页

[图鉴前端.py](./图鉴前端.py) 使用 Python 标准库启动仅监听 `127.0.0.1` 的本地 HTTP 服务，网页资源位于 `web/`，不依赖 Streamlit。浏览器每 5 秒请求一次状态接口；服务端先比较 `HistorySave.bytes` 和同名 `.bak` 的路径、大小、修改时间，只有签名变化时才解析存档并同步数据库。

```powershell
python "图鉴前端.py" `
  --database "SurvivalLog图鉴.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

前端提供六类分类、总体进度、搜索、完成状态筛选、全量条目列表、关联数据和配置字段详情。完成状态只读显示游戏存档中的图鉴状态；存档写入中或解析失败时保留上一次有效数据库状态，并在页面提示错误。前端不会写回存档。

### Windows 独立版

使用 [打包图鉴前端.ps1](./打包图鉴前端.ps1) 可以生成不需要用户安装 Python 的 Windows 文件夹版应用。打包内容只包含精简 Python 运行时、标准库服务、网页资源和预生成 SQLite 数据库，不再携带 Streamlit、PyArrow、NumPy、Pandas、Plotly 或 Matplotlib：

```powershell
PowerShell -ExecutionPolicy Bypass -File ".\打包图鉴前端.ps1"
```

分发目录为 `dist/SurvivalLog图鉴/`，其中的 `SurvivalLog图鉴.exe` 可以直接双击运行。必须整体分发该文件夹，不能只复制 exe；构建产物不包含游戏安装目录、bundle、catalog 或原始存档。

独立版直接使用 exe 同目录中的 `SurvivalLog图鉴.sqlite3`，不创建或读取用户目录数据库副本；存档同步后的完成状态直接写回该数据库。普通启动不显示终端，浏览器关闭后连续约 30 秒没有网页心跳时服务自动退出；`--headless` 模式保持后台常驻。程序仍只读读取当前用户的 `HistorySave.bytes`，没有存档时可以浏览静态图鉴但无法同步个人完成状态。

## 已知限制

- 静态解析器不推断完成状态；数据库和前端只读读取 `HistorySave.bytes` 的持久化图鉴列表，不读取存档中的玩家库存或其他运行时动态数据。
- `Config_CodexMilestone` 用于游戏图鉴里程碑，不参与六类主条目数量和完成勾选。
- 条件组、奖励组、动作、房间和掉落组等没有独立解析表的引用保留原始 ID，并以 `ID:xxxx` 标明。
- 参考仓库只用于字段命名和交叉校验，最终数据源始终是当前本地游戏资源。
- 重新运行只覆盖用户指定输出目录中的目标 Markdown 或 SQLite 派生数据，不修改游戏文件、mod DLL、存档、Steam Cloud 或 catalog。
