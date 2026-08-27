# Survival Log 图鉴离线解析说明

## 1. 项目结论

本项目直接读取当前本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，并只读读取用户本机 `HistorySave.bytes` 中的图鉴完成状态。不启动游戏，不修改存档、mod DLL、游戏资源或 Steam Cloud。

当前本地游戏资源版本为 `1.0.15130`，catalog 版本为 `2.3.1`。完整解析生成六份主图鉴和一份辅助配置：

- [survival_log_food.md](./snapshots/survival_log_food.md)
- [survival_log_dish.md](./snapshots/survival_log_dish.md)
- [survival_log_plant.md](./snapshots/survival_log_plant.md)
- [survival_log_prey.md](./snapshots/survival_log_prey.md)
- [survival_log_craft.md](./snapshots/survival_log_craft.md)
- [survival_log_furniture.md](./snapshots/survival_log_furniture.md)
- [survival_log_auxiliary.md](./snapshots/survival_log_auxiliary.md)

当前版本主图鉴全量配置为：食品 174、菜肴 496、植物 38、猎物 19、制造 148、家具 1249；六类分类映射合计 `2124`。实际在游戏图鉴中展示并需要完成的数量为：食品 174、菜肴 496、植物 34、猎物 19、制造 125、家具 87，合计 `935`。前一组是解析配置数量，后一组是运行时图鉴完成基数，不能混用。

## 2. 游戏图鉴和存档

安装目录是 IL2CPP 构建，没有可直接阅读的 C# 源文件；`global-metadata.dat` 保留了编译时源文件路径、类型和方法名。当前版本可以确认：

- `Assets/GameCore/HotUpdate/Battle/Logic/Codex/CodexManager.cs`
- `Assets/GameCore/HotUpdate/Codex/DishCodexGrouping.cs`
- `Assets/GameCore/HotUpdate/ReduxUI/Store/State_Reducer/2_UI/Codex/SR_Web_Codex.cs`
- `Assets/GameCore/HotUpdate/ReduxUI/WebUI/WebUIMsg/WebUI_Codex.cs`
- `Assets/GameCore/HotUpdate/Config/ConfigData/Config_CodexMilestone.cs`

元数据中包含 `IsInCodex`、`GetUnlockedCount`、`GetTotalCount`、`IsEntryUnlocked`、`BuildTotalCache`、`GetEntryName` 和 `GetEntryIcon` 等成员。`CodexManager._unlockedMap` 是运行时映射，`PersistToHistory`/`SaveCodexUnlocked` 将其写入 `HistoryData.CodexUnlocked`。本项目读取这个持久化分类 ID 列表，不读取 `Save_*.bytes` 中只用于界面快照的 `CodexUnlocked` 汇总值。

默认存档路径为：

```text
%USERPROFILE%\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes
```

`codex_save.py` 先校验 `HistoryData` 根对象、历史条目和公共前缀，再从公共前缀之后扫描所有字节 offset 寻找图鉴分类映射，不假设图鉴字段位于固定位置或全局 4 字节对齐。候选必须通过分类 ID、集合边界、正数且不重复的条目 ID，以及后续整数列表链校验；数据库同步时还使用当前六类配置的源 ID 集合参与评分。评分相同但映射相同的候选可以合并，评分相同但映射不同则报告歧义并保留上一次状态。

解析器校验 `HistoryData` 成员数、历史条目成员数、分类 ID、集合长度、重复 ID 和文件读取稳定性。存档正在写入或主文件解析失败时，只读尝试同名 `.bak`；两者均失败则数据库保留上一次有效完成状态。未识别的存档条目 ID 会保留在诊断结果中，不会静默转换为其他条目。

网页服务和数据库同步可以将诊断写入数据库同目录的 UTF-8 JSON Lines 日志。源码数据库对应 `survival_log_codex.log`，独立版对应 `SurvivalLogDataViewer.log`；数据库目录不可写时回退到 `%LOCALAPPDATA%\SurvivalLogDataViewer`。日志记录存档签名、解析阶段、图鉴映射 offset、候选评分、分类数量和错误原因，不记录原始存档字节；相同存档签名和错误只记录一次，日志达到 2 MiB 时轮转一个 `.1` 文件。

完成状态由 `HistorySave.bytes` 实时读取，具体完成数量随存档变化。食品和猎物可能引用同一个 `Config_Item`；数据库在 `completion` 中只保存一份主状态，同时在 `category_completion` 中保存按分类的完成状态，使两个分类分别计数。

### 存档可烹饪菜谱

`codex_save.py` 对当前版本的 `HistoryData` 使用严格的 16 成员 schema。`HistoryList` 中的子存档文件名必须是单层 `Save_*.bytes` 文件名，并在读取前后检查文件大小和修改时间；主文件解析失败时才尝试同名 `.bak`。全局 `HistoryData.CodexUnlocked` 是菜肴图鉴完成状态的唯一来源，因此“未完成菜肴”与具体子存档库存无关，所有 `HistoryList` 子存档共用同一份未完成列表。运行时 `Save_*.bytes` 里的 `CodexUnlocked`、`UnlockedCookingRecipeIds`、`CraftLevel` 和 `CraftUnlockedCookingRecipeIds` 不参与菜谱候选过滤。

子存档按当前 `GameSaveData` 的 `CurSave` 读取。主控 `LeadingRole.ItemList` 始终作为背包来源；`ChapterAgentMap` 中标记 `BagFurnitureConfigId` 为 `15000`（双开门冰箱）或 `15001`（冰柜）的家具库存优先使用。没有标记家具时，才回退到 `DoorBoxItems`/`DoorBoxItems2`；标记家具与兼容字段同时存在时保留标记结果并记录诊断。车辆后备箱、工作台抽屉不进入菜谱库存，`Config_Item.CanCook == false` 的物品也会被排除；输出仍保留实际物品 ID、数量、来源、容器、分类、子分类和价格。

数据库 schema v4 额外保存全部 `Config_Item` 的烹饪相关字段和七类烹饪档位阈值及其 `Config_GlobalSetting` 键。`SpecificItems` 按实际物品 ID 多重集合精确匹配；`TagCombo` 只按 `Config_ItemSubCategory` 将配方放入候选组，不单独决定最终菜肴。工具枚举库存中的实际组合，按原生 `CookingTierResolver` 对 Meat、Custard、Fish、Vegetable、Fruit、Seasoning、Mushroom 分别计算 High/Mid/Low，整组取最差档位，再选择同一候选组的 `Tier=1/2/3` 配方。当前静态候选固定为全部 496 道菜谱；同时设置 `SpecificItems` 和 `TagCombo` 的配置会直接报错。

## 3. 主图鉴分类和关联

食品和猎物使用当前游戏 Codex 字段，两个分类允许重叠：

- 食品：`Config_Item.InCodex == true && Category == 1`。
- 猎物：`Config_Item.Prey_Rarity > 0`，不以 `InCodex` 过滤，但保留该原始字段。
- 菜肴：当前 `Config_CookingRecipe` 的全部 496 条配置。
- 植物：当前 `Config_Plant` 的全部 38 条配置。
- 制造：当前 `Config_ProductionList` 的全部 148 条配置。
- 家具：当前 `Config_Furniture` 的全部 1249 条配置。

因此，猎物物品可以同时出现在食品和猎物 Markdown 中；数据库只保存一份完成状态，并通过分类映射分别计数。主 Markdown 只展开主表条目，物品子分类、食品标签、植物等级、制造等级和家具辅助表集中写入 `survival_log_auxiliary.md`。

| 输出 | 主表 | 主要关联表 |
| --- | --- | --- |
| 食品 | `Config_Item` | `Config_ItemSubCategory`、`Config_FoodType` |
| 菜肴 | `Config_CookingRecipe` | `Config_Item`、`Config_ItemSubCategory` |
| 植物 | `Config_Plant` | `Config_PlantLv`、`Config_Item` |
| 猎物 | `Config_Item` | 猎物字段位于物品表中 |
| 制造 | `Config_ProductionList` | `Config_ProductionLv`、`Config_Item` |
| 家具 | `Config_Furniture` | `Config_FurnitureFunc`、`Config_FurnitureCook`、`Config_FurniturePlant`、`Config_FurnitureElectrical`、`Config_FurnitureState`、`Config_FurnitureTag`、`Config_FurniturePartner` |

家具字段必须按语义解析：功能 ID 对应 `Config_FurnitureFunc`，种植、烹饪和电力配置 ID 对应各自关联表，包裹、材料、产物、种子和燃料 ID 对应 `Config_Item`，允许菜肴 ID 对应 `Config_CookingRecipe`，伙伴触发家具和伙伴配置 ID 对应 `Config_Furniture`。没有独立配置表的条件组、奖励组、动作、房间和掉落组等引用保留原始 ID。

所有关联字段保留原始数字并尽量解析名称。无法解析的 ID 显示为 `ID:xxxx`；空值和游戏使用的 0 哨兵显示为“无”。本地化名称按本地化字段、非本地化配置键、ID 顺序回退。

## 4. 资源包、依赖和 MemoryPack

相关配置位于 YooAsset catalog 指向的 MemoryPack TextAsset 中，当前主要位于：

`mainpackage_assets_runtimeassets_config_memorypack.bundle`

当前 bundle 解密算法为：

```text
Salt = SL_BundleCrypto_v1_9f3d7a1c
key  = MD5(Salt + BundleName) + MD5(BundleName + Salt)
data[i] ^= key[i % 32]
```

解析器会验证 catalog 读取到末尾、每张表的对象数量和字段数量、每行字段完整读取，以及数据游标到达原始数据末尾。schema 变化会返回表名、行号、字段数量或 offset 等错误，不会静默按旧格式猜测。

源码运行需要 Python 3.11 或更高版本。UnityPy 默认安装在当前项目目录：

```powershell
python -m pip install --target "D:\Codex\SurvivalLogDataViewer\_vendor_unitypy" UnityPy
```

也可以设置 `SURVIVALLOG_UNITYPY_DIR` 覆盖默认依赖目录。独立包不复制 `_vendor_unitypy` 源码目录，而是通过 PyInstaller 打包解析所需的 UnityPy 导入图和运行数据。

## 5. 命令行、数据库和网页服务

解析脚本为 [codex_parser.py](./codex_parser.py)。默认生成全部七份 Markdown 到 `snapshots/`：

```powershell
python "codex_parser.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --output-dir "snapshots"
```

单独导出分类：

```powershell
python "codex_parser.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --category dish `
  --output "snapshots\survival_log_dish.md"
```

可用分类为 `food|dish|plant|prey|craft|furniture|auxiliary`。`all` 模式使用 `--output-dir`，单分类模式可以使用 `--output`。输出路径不能位于游戏安装目录中。

`codex_database.py` 复用解析器读取上下文并构建 SQLite：

```powershell
python "codex_database.py" `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --database "data\survival_log_codex.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

数据库保存主条目、分类映射、共享主完成状态、分类完成状态、关联关系、辅助配置原始行、资源元数据，以及 schema v4 的菜谱物品和烹饪档位规则。重新导入使用事务和 upsert；存档同步先完整解析，成功后才在事务中更新状态，失败不会清空上一次有效状态。菜谱库存不写入 SQLite，网页请求 `/api/recipe-plans` 时根据 `HistorySave.bytes` 列出的子存档重新计算。没有存档时可以使用 `--no-save-sync` 只构建静态数据库。

源码默认数据库为 `data/survival_log_codex.sqlite3`，诊断日志写在同一目录。首次发现旧的根目录数据库时，工具会先复制到临时文件并执行 `PRAGMA integrity_check`，校验通过后原子迁移；存在 WAL/SHM 旁车文件、锁定或冲突时会保留旧文件并继续使用它。显式 `--database` 路径不会触发迁移。

没有存档时可以使用 `--no-save-sync` 只构建静态数据库，完成状态保持未完成。

### 轻量本地网页

[codex_server.py](./codex_server.py) 使用 Python 标准库启动仅监听 `127.0.0.1` 的本地 HTTP 服务，网页资源位于 `web/`，不依赖 Streamlit。浏览器每 5 秒请求一次状态接口；服务端先比较 `HistorySave.bytes` 和同名 `.bak` 的路径、大小、修改时间，只有签名变化时才解析存档并同步数据库。

```powershell
python "codex_server.py" `
  --database "data\survival_log_codex.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

前端提供六类主图鉴分类和“可烹饪菜谱”栏目、成品名称检索、材料检索、完成状态筛选、全量条目列表、关联数据和配置字段详情。菜谱栏目按 `HistorySave` 的全局未完成菜肴状态展示所有子存档的实时库存、实际食材组合、候选组、解析档位和最终 Tier 配方；前端不会写回存档。

## 6. 独立版运行和打包

独立版启动器会先读取 Steam 的 `steamapps/libraryfolders.vdf`，检查每个库中的 `steamapps/common/Survival Log`，再使用 `SurvivalLog_Data/StreamingAssets/PackageManifest` 和 catalog 校验游戏目录。Steam 库未找到有效目录时，会在本机各磁盘的常见 Steam/Games 路径做有限备用搜索。只有游戏资源版本与数据库 metadata 中的 `game_version` 不同，才会重新解析配置并导入 SQLite；更新失败时保留原数据库。

使用 [package_frontend.ps1](./package_frontend.ps1) 可以生成不需要用户安装 Python 的 Windows 文件夹版应用。打包内容包含精简 Python 运行时、标准库服务、网页资源、自动更新所需的 UnityPy 核心导入图和预生成 SQLite 数据库，不再携带 UnityPy 的导出/CLI 工具、缓存和调试符号，也不携带 Streamlit、PyArrow、NumPy、Pandas、Plotly 或 Matplotlib：

```powershell
PowerShell -ExecutionPolicy Bypass -File ".\package_frontend.ps1"
```

分发目录为 `dist\SurvivalLogDataViewer\`，其中的 `生存日志图鉴.exe` 可以直接双击运行。必须整体分发该文件夹，不能只复制 exe。打包内容包含精简 Python 运行时、标准库服务、网页资源、自动更新所需的 UnityPy 核心导入图和预生成 SQLite 数据库，不包含 UnityPy 导出/CLI 工具、缓存、调试符号、Streamlit、PyArrow、NumPy、Pandas、Plotly 或 Matplotlib，也不包含游戏安装目录、bundle、catalog 或原始存档。

独立版直接使用 exe 同目录中的 `SurvivalLogDataViewer.sqlite3`，不创建或读取用户目录数据库副本。普通启动不显示终端；图鉴页面明确关闭后服务约 30 秒自动退出，后台标签页或切回游戏不会触发退出，页面恢复可见时会立即刷新。`--headless` 模式保持常驻。打包脚本从 README 的用户区标记生成独立包 README，因此发布包只保留面向用户的说明。

## 7. 已知限制

- 静态解析器不推断完成状态；数据库和前端只读读取 `HistorySave.bytes` 的持久化图鉴列表。
- 可烹饪菜谱视图只读取当前版本已知的严格 `HistoryData`、`GameSaveData` schema；版本变化会显示 schema 诊断，不会用旧字段偏移猜测库存。
- `Config_CodexMilestone` 用于游戏图鉴里程碑，不参与六类主条目数量和完成勾选。
- 条件组、奖励组、动作、房间和掉落组等没有独立解析表的引用保留原始 ID，并以 `ID:xxxx` 标明。
- 参考仓库只用于字段命名和交叉校验，最终数据源始终是当前本地游戏资源。
- 重新运行只覆盖用户指定输出目录中的目标 Markdown 或 SQLite 派生数据，不修改游戏文件、mod DLL、存档、Steam Cloud 或 catalog。
