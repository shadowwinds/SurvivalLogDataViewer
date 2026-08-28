# Survival Log 图鉴离线解析说明

## 1. 项目结论

本项目直接读取当前本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，并只读读取用户本机 `HistorySave.bytes` 中的图鉴完成状态。不启动游戏，不修改存档、mod DLL、游戏资源或 Steam Cloud。

当前本地游戏资源版本为 `1.0.15218`，catalog 版本为 `2.3.1`。完整解析生成六份主图鉴和一份辅助配置：

- [survival_log_food.md](./snapshots/survival_log_food.md)
- [survival_log_dish.md](./snapshots/survival_log_dish.md)
- [survival_log_plant.md](./snapshots/survival_log_plant.md)
- [survival_log_prey.md](./snapshots/survival_log_prey.md)
- [survival_log_craft.md](./snapshots/survival_log_craft.md)
- [survival_log_furniture.md](./snapshots/survival_log_furniture.md)
- [survival_log_auxiliary.md](./snapshots/survival_log_auxiliary.md)

当前版本主图鉴配置总量为：食品 174、菜肴 496、植物 38、猎物 19、制造 148、家具 1249。严格按展示规则导出的数量为：食品 174、菜肴 496、植物 34、猎物 19、制造 125、家具 87，六类分类映射合计 `935`。前一组是原始配置总量，后一组是 `InCodex == true` 筛选（菜肴表无该字段）后的图鉴展示基数，不能混用。

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

独立版首次实际使用、首次 API 同步或启动错误时才建立分发目录中的 UTF-8 JSON Lines 日志 `SurvivalLogDataViewer.log`；新打包目录不预置日志，源码版不生成存档同步诊断日志。分发目录不可写时回退到 `%LOCALAPPDATA%\SurvivalLogDataViewer`。日志记录存档签名、解析阶段、图鉴映射 offset、候选评分、分类数量和错误原因，不记录原始存档字节；相同存档签名和错误只记录一次，日志达到 2 MiB 时轮转一个 `.1` 文件。

完成状态由 `HistorySave.bytes` 实时读取，具体完成数量随存档变化。食品和猎物可能引用同一个 `Config_Item`；数据库在 `completion` 中只保存一份主状态，同时在 `category_completion` 中保存按分类的完成状态，使两个分类分别计数。

### 存档可烹饪菜肴

完整的库存来源历史、字段词典、实测证据和后续排查清单见 [`save_inventory_pipeline.md`](./save_inventory_pipeline.md)。

`codex_save.py` 对当前版本的 `HistoryData` 使用严格的 16 成员 schema。`GameSaveData` 的标准 `CurSave` 使用当前 176 成员 schema；同时兼容已验证的 181 成员历史变体（`SaveChildData` 末尾增加 5 个整数）和 183 成员历史变体（末尾增加 6 个整数及一个 `Dictionary<int,string>`），三种形式都必须完整读取到文件末尾。`HistoryList` 中的子存档文件名必须是单层 `Save_*.bytes` 文件名，并在读取前后检查文件大小和修改时间；主文件解析失败时才尝试同名 `.bak`。全局 `HistoryData.CodexUnlocked` 是菜肴图鉴完成状态的唯一来源，因此“未完成菜肴”与具体子存档库存无关，所有 `HistoryList` 子存档共用同一份未完成列表。运行时 `Save_*.bytes` 里的 `CodexUnlocked`、`UnlockedCookingRecipeIds`、`CraftLevel` 和 `CraftUnlockedCookingRecipeIds` 不参与菜肴候选过滤。

子存档按当前 `GameSaveData` 的 `CurSave` 读取。主控 `LeadingRole.ItemList` 始终作为背包来源；先读取 `LeadingRole.Name` 并按已验证名称映射确定角色，再按 `GameSaveData.PlayerSelectId`、`HistoryList.PlayerSelectId`、`LeadingRole.AgentConfigId` 的顺序兼容回退，名称未知、缺失或与数字身份冲突时会保留角色上下文和诊断。储物家具以静态库 `storage_furniture` 表为权威来源，覆盖当前 `Config_Furniture` 中 `FurnitureFunc` 包含 215 或 `ShowStorage > 0` 的全部配置，不受图鉴 `is_current` 可见性影响，也不按本地化名称筛选；旧数据库缺少专用表时才回退到旧的当前图鉴行。家具优先使用 `BagFurnitureConfigId`，否则使用 `AgentConfigId`，同名的多个家具实例均单独保留。容器必须同时有储物行为配置、当前角色槽位和地图证据：先比较主控 `MapConfigIdHome`、`ChapterAgentMap` 地图键与实例 `MapConfigId`，任一地图 ID 不一致始终判定为其他位置；再按当前角色选择槽位，角色 1 使用 `HomeBuildingPos`/`Home_`，角色 2 使用 `NeighborGirlBuildingPos`，角色 3 使用 `WarehousePos`。空槽位不再因地图相同而视为家中，其他角色的已知槽位判定为其他位置，未知槽位判定为未知并跳过库存；位置、实例和角色解析诊断仍保留在后端 `storage_containers`/存档 JSON。`IsDoorBox == true` 仅在地图明确属于当前家中时作为兼容储物容器读取；工作台抽屉 `WorkbenchDrawerItems` 作为家中直接容器读取，车辆后备箱和普通 `ChapterAgentMap` 条目忽略。旧版 `DoorBoxItems`/`DoorBoxItems2` 只对 15000/15001 保留兼容回退，且仅在没有对应实际家具并已解析出已知角色时使用。

数据库 schema v8 额外保存全部 `Config_Item` 的烹饪相关字段、按储物功能生成的家具映射和七类烹饪档位阈值及其 `Config_GlobalSetting` 键；旧 v5 数据库会强制重建，旧 v6 源码库会拆分为静态库和 runtime 库。菜肴匹配拆分为两个独立指令：`SpecificItems` 按 `Config_Item.Category == 1 && CanCook == true` 和实际物品 ID 多重集合精确匹配；`TagCombo` 按子分类数量枚举库存组合、使用 `CookingTierResolver` 解析档位并选择同档位配方。两类结果仍互不预留或扣除共享食材，但每个完整食材组合先执行 `SpecificItems` 特色菜肴优先判断，只有未命中特色菜肴时才允许显示 `TagCombo` 通用菜肴；因此菠菜只有在补入后的完整组合没有命中特色菜肴时，才可作为通用菜肴候选。近匹配只在其他槽位和数量全部满足、加入候选食材后确实能得到有效目标通用菜肴且未命中特色菜肴时返回；候选可来自配置上可烹饪但当前尚未拥有的食材，并统一放在 `missing_item_candidates`。

### ChapterAgentMap 外层键判定（当前实现）

实际存档对比表明，`ChapterAgentMap` 的外层键是章节分组键，不是角色 ID，也不是地图 ID；角色 1、2、3 的存档都可能同时出现键 `1` 和键 `2`。当前优先使用 `GameSaveData.InitChapterId` 选择同名外层键，并在存档 JSON 中记录选择来源和诊断。`InitChapterId` 缺失或对应键不存在时，才使用“角色槽位 + `MapConfigIdHome`”找到唯一候选；候选不唯一或无法确认时跳过依赖章节分组的容器。外层键选定后，容器还必须满足储物行为配置、实例 `MapConfigId == MapConfigIdHome` 和当前角色槽位三项条件；因此地图字段负责地图一致性，槽位字段负责角色归属，不能用任一字段替代外层键判定。该规则覆盖本节前文中将 `ChapterAgentMap` 键作为地图证据的旧表述。

当前已验证 `SaveChildData` 的标准 176 成员格式、末尾增加 5 个整数的 181 成员格式，以及末尾增加 6 个整数和一个 `Dictionary<int,string>` 的 183 成员格式；三种形式都必须严格读取到文件末尾。

## 3. 主图鉴分类和关联

食品和猎物使用当前游戏 Codex 字段，两个分类允许重叠：

- 食品：`Config_Item.InCodex == true && Category == 1`，当前展示 174 条。
- 猎物：`Config_Item.InCodex == true && Prey_Rarity > 0`，当前展示 19 条。
- 菜肴：当前 `Config_CookingRecipe` 的全部 496 条配置（该表没有 `InCodex` 字段）。
- 植物：`Config_Plant.InCodex == true`，当前展示 34 条。
- 制造：`Config_ProductionList.InCodex == true`，当前展示 125 条。
- 家具：`Config_Furniture.InCodex == true`，当前展示 87 条。

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
  --database "survival_log_codex.sqlite3" `
  --runtime-database "survival_log_codex_runtime.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

静态库保存主条目、分类映射、关联关系、辅助配置原始行、资源元数据，以及 schema v8 的菜肴物品、按储物功能生成的家具映射和烹饪档位规则；runtime 库保存共享主完成状态、分类完成状态、`save_*` 元数据和持久化缓存。查询通过附加 runtime 库跨库关联。重新导入使用事务和 upsert；存档同步先完整解析，成功后才在 runtime 事务中更新状态，失败不会清空上一次有效状态。菜肴库存不写入 SQLite，网页请求 `/api/recipe-plans` 时根据 `HistorySave.bytes` 列出的子存档重新计算，并附带角色上下文、回退诊断和每个储物容器的位置诊断。没有存档时可以使用 `--no-save-sync` 只构建静态数据库。

源码默认数据库为根目录的 `survival_log_codex.sqlite3`，runtime 文件固定为根目录的 `survival_log_codex_runtime.sqlite3`，源码运行不生成存档同步诊断日志。首次发现旧的 `data/survival_log_codex.sqlite3` 时，工具会先执行 `PRAGMA integrity_check`，校验通过后在临时文件中原子拆分静态和 runtime 数据库，并保留完成状态、存档哈希和已有缓存；存在 WAL/SHM 旁车文件、锁定或目标冲突时会保留旧文件。显式 `--database` 路径不会触发默认迁移。

没有存档时可以使用 `--no-save-sync` 只构建静态数据库，完成状态保持未完成。

### 轻量本地网页

[codex_server.py](./codex_server.py) 使用 Python 标准库启动仅监听 `127.0.0.1` 的本地 HTTP 服务，网页资源位于 `web/`，不依赖 Streamlit。浏览器每 5 秒请求一次状态接口；服务端先比较 `HistorySave.bytes` 和同名 `.bak` 的路径、大小、修改时间，只有签名变化时才解析存档并同步数据库。

```powershell
python "codex_server.py" `
  --database "survival_log_codex.sqlite3" `
  --runtime-database "survival_log_codex_runtime.sqlite3" `
  --save-file "$env:USERPROFILE\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes"
```

前端提供六类主图鉴分类和“智能菜肴”栏目、成品名称检索、材料检索、完成状态筛选、全量条目列表、关联数据和配置字段详情。菜肴栏目按 `HistoryData.LastPlayFileName` 默认选中存档，下拉切换后只展示该存档；页面采用固定视口高度，左侧拥有食材、右侧可烹饪菜肴和仅差一个食材结果分别滚动。菜肴轮询比较 payload revision，内容未变化时不重建列表，变化时恢复两个滚动列的位置，切换存档则回到顶部。结果卡片严格保持单行，限定食材和大类食材分别显示“特色菜肴”和“通用菜肴”，每个食材使用独立高亮标签；近匹配把“缺少：”和“当前：”放在同一行，通用缺口的全部明确候选名称在同一个高亮标签内用“|”分隔。存档下拉菜单、文件名、模式/天数和状态合并在同一行，前端不会写回存档。

## 6. 独立版运行和打包

独立版启动器会先读取 Steam 的 `steamapps/libraryfolders.vdf`，检查每个库中的 `steamapps/common/Survival Log`，再使用 `SurvivalLog_Data/StreamingAssets/PackageManifest` 和 catalog 校验游戏目录。Steam 库未找到有效目录时，会在本机各磁盘的常见 Steam/Games 路径做有限备用搜索。只有游戏资源版本与数据库 metadata 中的 `game_version` 不同，才会重新解析配置并导入 SQLite；更新失败时保留原数据库。

使用 [package_frontend.ps1](./package_frontend.ps1) 可以生成不需要用户安装 Python 的 Windows 文件夹版应用。打包内容包含精简 Python 运行时、标准库服务、网页资源、自动更新所需的 UnityPy 核心导入图和预生成 SQLite 数据库，不再携带 UnityPy 的导出/CLI 工具、缓存和调试符号，也不携带 Streamlit、PyArrow、NumPy、Pandas、Plotly 或 Matplotlib：

```powershell
PowerShell -ExecutionPolicy Bypass -File ".\package_frontend.ps1"
```

分发目录为 `dist\SurvivalLogDataViewer\`，其中的 `生存日志图鉴.exe` 可以直接双击运行。必须整体分发该文件夹，不能只复制 exe。打包内容包含精简 Python 运行时、标准库服务、网页资源、自动更新所需的 UnityPy 核心导入图和预生成 SQLite 数据库，不包含 UnityPy 导出/CLI 工具、缓存、调试符号、Streamlit、PyArrow、NumPy、Pandas、Plotly 或 Matplotlib，也不包含游戏安装目录、bundle、catalog 或原始存档。

独立版直接使用 exe 同目录中的 `SurvivalLogDataViewer.sqlite3`，在同一文件中保存静态配置和使用后的运行时状态，不创建第二个 runtime 文件。普通启动不显示终端；图鉴页面明确关闭后服务约 30 秒自动退出，启动后没有网页成功建立 API 心跳也会在约 30 秒后退出，浏览器异常结束且关闭通知丢失时会在约 90 秒没有心跳后回收。后台标签页或切回游戏时，只要网页仍能按轮询发送心跳就不会触发退出，页面恢复可见时会立即刷新。`--headless` 模式保持常驻。默认端口 `8501` 被其他图鉴实例占用时会自动选择空闲端口；显式指定的其他端口冲突则返回错误。打包脚本每次从静态库生成空运行时表的独立数据库，不读取旧发布数据库或保留旧完成状态；自检日志结束时删除，并断言发布目录没有日志。打包脚本从 README 的用户区标记生成独立包 README，因此发布包只保留面向用户的说明。

## 7. 已知限制

- 静态解析器不推断完成状态；数据库和前端只读读取 `HistorySave.bytes` 的持久化图鉴列表。
- 可烹饪菜肴视图只读取当前版本已知的严格 `HistoryData`、`GameSaveData` schema；版本变化会显示 schema 诊断，不会用旧字段偏移猜测库存。
- `Config_CodexMilestone` 用于游戏图鉴里程碑，不参与六类主条目数量和完成勾选。
- 条件组、奖励组、动作、房间和掉落组等没有独立解析表的引用保留原始 ID，并以 `ID:xxxx` 标明。
- 参考仓库只用于字段命名和交叉校验，最终数据源始终是当前本地游戏资源。
- 重新运行只覆盖用户指定输出目录中的目标 Markdown 或 SQLite 派生数据，不修改游戏文件、mod DLL、存档、Steam Cloud 或 catalog。
