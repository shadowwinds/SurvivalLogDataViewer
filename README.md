<!-- BEGIN USER GUIDE -->
# Survival Log Data Viewer

### 在线静态图鉴

本 fork 的在线版：[生存日志在线图鉴](https://shadowwinds.github.io/SurvivalLogDataViewer/)。原项目来自 [tianwaiyan/SurvivalLogDataViewer](https://github.com/tianwaiyan/SurvivalLogDataViewer)。

在线版从仓库已公开的静态 SQLite 生成，使用贴近游戏物品栏的深灰、暖棕边框和金黄色界面。食品按可烹饪与否分为“烹饪食材”和“即食食品”，在图标左下角显示每份可烹饪或食用次数，并列出五项属性、食品标签及烹饪分类。菜肴可以切换普通、良好、完美和失败品质；固定食材配方的图标左下角显示整份可吃次数，属性显示每次食用效果；通用配方的次数显示为“可变”，并提供总饱食分份计算。支持按标签、属性增益筛选及属性排序，也能从食材查询相关配方。页面配有从游戏只读提取的物品图标，缺失图标用分类符号占位。

浏览提示折叠在标题旁，补给计划入口也位于标题旁。桌面分类、条目列表和详情分别滚动，查询工具栏保持可见；手机页面滚动时，查询、筛选和排序工具栏吸附在顶部。

[生存补给计划](https://shadowwinds.github.io/SurvivalLogDataViewer/recommendations/)提供即食囤货、烹饪备料、菜肴和作物推荐。按烹饪 Lv.1／2／3 区分前、中、后期，可切换普通、良好、完美品质，或只看本阶段新增配方；支持名称、食材检索及成本、饱食、时间排序。每个条目公开评分分项、食材用量、整包购买价和每锅摊销价。指数由本站按静态配置计算，通用配方的产量随组合变化，保留条件并单独列出；具体公式与计算边界见页面说明。

六类图鉴及成就仍支持名称/ID 搜索、材料搜索和详情查询。食品标签和烹饪分类分别保留，不用标签替代配方分类；相关配方只是食材用途参考，实际制作仍需满足完整配方与品质要求。数值使用数据库中记录的数据版本，不自动跟随访客本机游戏更新；个人完成状态、存档自动同步和库存菜肴匹配仍由原项目本地版提供。

成就模块在手动导入时读取 `Config_Achievement`，并在侧边栏“成就”中单独展示。完成状态来自全局 `HistoryData.UnlockedAchievementIds`，不按当前选中的子存档区分；隐藏成就也会显示。详情包含完成条件、完成方法、角色限制、数值门槛、排除项、注意事项、配置引用和原始配置字段。

条件说明来自随程序发布的 `achievement_conditions.json`，其中的 `source_version` 仅记录人工整理时参考的资源版本，不参与自动更新判断。自动更新只校验并重建原有六类图鉴，跳过 `Config_Achievement` 和人工条件说明，并保留数据库中已有的成就内容及完成状态；仅在数据库尚无成就数据时，才会在初始化阶段导入当前手工说明。成就同步与其他完成状态共用约 5 秒轮询，主存档和 `.bak` 都无法解析，或旧存档格式无法确认 `UnlockedAchievementIds` 时，保留上一次有效成就状态。

离线读取 Survival Log 本地资源的图鉴查看器。程序不启动游戏，不修改游戏文件、Mod、Steam Cloud 或存档；六类图鉴配置来自本机游戏资源，完成状态只读取 `HistorySave.bytes`，成就条件来自随程序发布的手动维护说明文件。

## 面向用户

### 快速开始

1. 解压完整的 `dist/SurvivalLogDataViewer/` 文件夹，不要只复制 exe 文件。
2. 双击 `生存日志图鉴.exe`。
3. 程序会自动打开浏览器并启动本地图鉴页面。

独立版不要求用户安装 Python。首次启动会从 Steam 的 `libraryfolders.vdf` 查找游戏目录，游戏资源版本变化后会自动重新解析并更新图鉴数据库。

### 启动和更新

程序只在本机启动 HTTP 服务，服务监听地址为 `127.0.0.1`，不会对外提供图鉴页面。Steam 库中找不到游戏时，程序会在常见的 Steam 和 Games 路径中进行有限搜索；仍找不到时会保留现有数据库，静态图鉴仍可打开。

更新数据库时只读取游戏安装目录中的 catalog、资源包和配置。程序不会向游戏目录写入更新文件，也不会替换或删除已有图鉴数据库中的有效内容；更新失败时继续使用上一次有效数据库。

### 存档同步和隐私

发布包中的数据库文件是 `SurvivalLogDataViewer.sqlite3`，完成状态保存在该文件中。首次生成的发布包不包含玩家完成状态；程序启动后会尝试读取默认存档：

```text
%USERPROFILE%\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes
```

默认存档不存在时，程序会弹出文件选择窗口。可以选择其他 `HistorySave.bytes` 文件，程序只读读取所选文件，并在主存档写入期间尝试读取同名 `.bak` 备份。

完成状态同步只读游戏保存的图鉴完成列表；菜肴页面另行只读各子存档的主控背包、工作台抽屉和按当前角色判定位于玩家家中的全部储物容器。子存档先按 `LeadingRole.Name` 解析角色，名称缺失、未知或冲突时按 `GameSaveData.PlayerSelectId`、`HistoryList.PlayerSelectId`、`LeadingRole.AgentConfigId` 顺序兼容回退并显示诊断。储物容器先按 `InitChapterId` 选择 `ChapterAgentMap` 外层章节分组，再按专用配置功能、角色槽位和 `MapConfigIdHome`/实例 `MapConfigId` 证据识别，不按容器名称筛选；外层键不是角色 ID、地图 ID 或“数值越大越新”，角色 1/2/3 分别使用 `HomeBuildingPos`/`Home_`、`NeighborGirlBuildingPos`、`WarehousePos` 槽位，空槽位不因地图相同而视为家中，其他角色槽位和未知位置不会并入食材库存，但每个实例及位置诊断仍会保留。专用储物配置覆盖全部 `FurnitureFunc` 包含 215 或 `ShowStorage > 0` 的家具，因此旧配置 ID `80062` 和其他非当前图鉴家具也可被识别。程序不读取联网数据，也不会写回存档；主存档和备份都无法解析时，页面会保留上一次有效状态并显示同步错误。

当前数据库 schema 为 v9，runtime schema 为 v2。菜肴近匹配只有在精确配方缺一个物品数量，或分类配方只缺一个分类槽位且其余实际库存组合完整时才显示；多个可替代食材仍属于同一个分类槽位。

### 存档章节分组说明

`ChapterAgentMap` 的外层键表示章节分组，不表示角色 ID、地图 ID 或“数值越大越新”。程序优先用 `GameSaveData.InitChapterId` 选择外层键；只有该字段缺失或对应键不存在时，才使用角色槽位和 `MapConfigIdHome` 寻找唯一候选。选定外层键后，仍需同时满足储物行为、实例 `MapConfigId` 与家地图一致、以及当前角色槽位一致，才会把容器内容计入食材库存；无法唯一确认的章节分组会跳过并显示诊断。

### 使用图鉴页面

- 左侧可以切换食品、智能菜肴、植物、猎物、制造和家具；菜肴页面内的结果分为“可烹饪菜肴”和“仅差一个食材”。
- 条目按 ID 从小到大排列，点击整行即可查看右侧详情。
- “成品名称”检索匹配条目名称、名称键和 ID。
- “材料”检索匹配菜肴食材、制造材料和家具制造材料；两个检索条件可以同时使用。
- 可以按完成状态筛选条目。
- 详情顶部显示当前分类的重点信息，其余字段默认折叠。
- 食品和猎物可能包含同一个物品，这是游戏图鉴分类规则导致的正常情况。
- “智能菜肴”使用同一行的存档下拉菜单切换存档，模式/天数显示在文件名右侧，最右侧提供【存档更新】；点击后只重新读取当前选中的子存档。页面为固定双栏布局，两列分别滚动。
- 菜肴结果分为两个独立显示区：`SpecificItems` 精确匹配可烹饪食品，`TagCombo` 按子分类数量和 `CookingTierResolver` 档位参与匹配与优先级判断；页面同时显示特色菜肴和通用菜肴结果。

### 多页面和浏览器行为

同一台电脑上可以打开多个图鉴页面，它们共享同一个本地服务；关闭其中一个页面不会影响其他页面。浏览器切到后台、窗口最小化或切回游戏时，程序不会把这种状态当作关闭。

页面恢复可见后会继续请求最新状态。如果游戏刚刚完成存档写入，等待下一次刷新即可看到新的完成数量；也可以刷新浏览器页面，但不要在服务仍运行时移动或重命名数据库文件。

### 日志、文件和退出

独立版首次实际使用、首次 API 同步或启动错误时才建立 `SurvivalLogDataViewer.log`，打包初始目录不包含日志。源码版不生成存档同步诊断日志。日志只记录解析阶段、文件摘要、图鉴映射位置、候选评分和错误原因，不记录原始存档字节；分发目录不可写时会回退到 `%LOCALAPPDATA%\SurvivalLogDataViewer`。

必须整体保留 `SurvivalLogDataViewer/` 文件夹，其中的 exe、网页资源和 SQLite 数据库缺一不可。需要备份个人完成状态时，关闭图鉴页面后复制 `SurvivalLogDataViewer.sqlite3` 即可。

浏览器切换到后台或切回游戏时，本地服务会继续运行。明确关闭所有图鉴页面后，程序通常会在约 30 秒后自动退出；如果浏览器没有成功打开或页面没有完成加载，服务也会在启动等待时间结束后退出。浏览器崩溃或被强制结束而没有发送关闭通知时，服务会在约 90 秒没有收到网页心跳后自动回收。`--headless` 是开发和自检模式，按设计保持常驻。

### 运行前检查

- 确认 Steam 游戏已经安装，并且当前用户可以读取游戏安装目录。
- 第一次启动时保留完整的发布文件夹结构，不要把网页资源目录改名或移出。
- 如果需要读取另一份进度，提前找到对应的 `HistorySave.bytes`；程序不会从其他存档类型推断图鉴状态。
- 如果暂时没有存档，可以取消文件选择；页面仍可打开，但不会显示个人完成进度。
- 更换电脑或重新解压程序时，使用之前备份的 SQLite 数据库恢复完成状态，并在首次启动前退出其他图鉴实例。

图鉴配置是从本机游戏资源读取后生成的本地数据，不依赖在线账号或远程接口。程序只访问完成工作所需的游戏目录、选定存档、发布包数据库和日志位置，不会上传这些文件。

### 完成状态和备份

页面中的完成数量来自当前选定存档，不是根据条目名称、库存或玩家等级推算出来的。食品和猎物在游戏中可能共享同一个物品，因此同一个物品在两个分类中都显示是正常的；两个分类的完成统计也会分别保留。

程序只在存档签名发生变化时重新读取存档。游戏正在保存时，主文件可能暂时无法读取，程序会尝试同名 `.bak` 文件；如果备份也不可用，不会把页面上的旧完成状态清空。关闭游戏并等待存档写入完成后，页面会在下一次轮询时自动刷新。

独立版的 `SurvivalLogDataViewer.sqlite3` 同时保存图鉴配置和同步后的完成状态。备份前先关闭图鉴页面，再复制整个数据库文件；恢复备份时也应先退出程序，避免 SQLite 文件仍被服务占用。源码运行使用根目录下跟踪的 `survival_log_codex.sqlite3` 静态库，以及未跟踪的 `survival_log_codex_runtime.sqlite3` runtime 库；不要把两种运行方式的数据库混用。

### 游戏更新和文件管理

程序会把数据库记录的游戏资源版本与本机安装目录的 catalog 版本进行比较。版本一致时直接打开已有数据库，版本变化时只重新解析六类图鉴配置，跳过 `Config_Achievement` 和人工成就条件说明；更新过程只读取游戏文件，并通过数据库事务写入新结果，同时保留已有成就内容和完成状态。资源缺失、版本格式异常或 schema 不匹配时会显示错误并保留旧数据库。

发布包必须作为完整文件夹移动或备份。除了 `生存日志图鉴.exe`，网页资源目录和 `SurvivalLogDataViewer.sqlite3` 也是运行所需文件；只复制 exe 会导致页面或数据库缺失。新生成的发布目录不包含日志；程序使用后产生的日志可以一起保留，用于排查存档同步问题，但其中不包含原始存档内容。

### 页面使用建议

需要查找某个物品时，先选择对应分类，再使用“成品名称”检索；该检索支持名称、名称键和 ID，不会把材料名称当作成品匹配。查配方、制造或家具消耗时使用“材料”检索；名称检索和材料检索可以同时缩小结果。

列表中的 ID 是配置中的原始数字。详情中的关联名称来自当前游戏配置，无法解析的关联会显示为 `ID:xxxx`，不代表程序修改了该配置。部分字段属于低层配置，默认收在折叠区域；展开后可查看原始值和已解析的关联值。

### 常见问题

- **页面打不开**：确认是从完整分发文件夹启动 exe，而不是单独复制 exe；默认端口被占用时程序会自动改用空闲端口；仍失败时查看分发目录中的 `SurvivalLogDataViewer.log`。
- **没有完成状态**：确认选择的是包含图鉴进度的 `HistorySave.bytes`，并检查日志中的同步错误。
- **图鉴没有随游戏更新**：确认 Steam 能找到游戏安装目录，再重新启动程序；旧数据库会在更新失败时保留。
- **需要重新选择存档**：默认存档不存在时，在文件选择窗口中选取正确的 `HistorySave.bytes`；也可以使用启动参数 `--save-file` 固定指定路径。

如果 Steam 安装在非标准位置，程序会优先读取 Steam 自己的库配置；仍无法发现游戏时，可以使用带 `--game-root` 的启动方式明确指定游戏目录。指定的目录必须包含 `SurvivalLog_Data\StreamingAssets\PackageManifest`，否则程序会拒绝读取并给出错误。

如果页面显示的是旧数据，先确认数据库目录有写入权限，再查看同目录日志。不要手动编辑数据库、存档或游戏资源；这类修改可能使后续完整性检查或存档解析失败。需要重新生成静态图鉴时，应由开发者使用源码命令并把输出写到指定的项目外目录。

程序的静态图鉴数据始终来自当前本机游戏资源；页面显示的是当前数据库内容和所选存档完成状态。
成就 API 为 `GET /api/achievements?name_search=&completion=all` 和 `GET /api/achievements/{achievement_id}`。前者支持名称、ID、描述和条件文字搜索，以及全部、已解锁、未解锁筛选；后者返回完整条件说明、方法步骤、角色限制、数值门槛、排除项、注意事项、配置引用和配置字段。

<!-- END USER GUIDE -->

<!-- BEGIN DEVELOPER GUIDE -->
## 面向开发者

### GitHub Pages 构建与部署

在线版支持简体中文和 English，右上角切换后会记住语言，保留当前筛选与已选材料。食材名称旁直接显示档位，分类按钮可组合筛选蔬菜、菌菇等分类及档位；菜肴的选材菜单也可按分类和档位挑选。

官方英文文本的本地刷新命令：`python codex_pages_i18n.py --game-root "游戏安装目录" --output-dir pages/locales`。只提取当前公开条目用到的名称和说明；缺失或歧义文本及尚未翻译的手动成就攻略保留中文。CI 使用仓库内的语言文件，不读取游戏。

运行 `python codex_pages.py --output-dir build/pages --site-url https://你的用户名.github.io/SurvivalLogDataViewer/` 构建网页，再运行 `python -m http.server 8502 --bind 127.0.0.1 --directory build`，访问 `http://127.0.0.1:8502/pages/`。构建只读静态库，不附加 runtime 库，也不读取游戏安装目录或存档；输出仅覆盖所选目录中的网页资源、被引用的图标、`data.json`、`.nojekyll`、`sitemap.xml`、`recommendations/` 推荐页和 `guide/` 下的当前图鉴页面，保留其他文件。

`guide/` 提供无需 JavaScript 的分类目录和独立详情页，包含属性、标签、各品质菜肴效果及关联条目。每页生成独立标题、描述、canonical、Open Graph、Twitter 分享信息和 WebPage / CollectionPage / BreadcrumbList 结构化数据；食品与猎物重叠条目共用一个详情地址。游戏菜肴不标注为现实食谱的 Recipe。站点地图列出真实页面地址，不包含 `#` 筛选状态。

`--site-url` 用于所有公开网址，默认指向当前在线版；本地预览可传 `http://127.0.0.1:8502/pages/`。Actions 按当前仓库生成 Pages 网址，绑定自定义域名或使用用户主页仓库时需设置仓库变量 `PAGES_SITE_URL`。可将公开的 `sitemap.xml` 提交到搜索引擎站长平台；GitHub 项目站点不能通过子目录中的 `robots.txt` 控制整个域名，因此构建不生成这种无效的规则文件。

图标提取是独立的本地步骤：安装 UnityPy 后运行 `python codex_pages_icons.py --game-root "游戏安装目录" --output-dir pages/icons`。脚本从 catalog 定位当前图鉴、成就及菜肴成品、植物收获物、普通制造产物引用的图标，复用现有 bundle 解密；缺失引用按同一配置的网页图标字段使用游戏自带 PNG。将缩略图和不含本机路径的版本清单写入指定输出目录，不输出配置全集或修改游戏。Pages 工作流直接使用仓库图标，不需要游戏或 UnityPy；图标验证使用 Pillow。

自己的公开 fork 也可以部署：在仓库 `Settings → Pages → Source` 选择 `GitHub Actions`，然后运行 `Build and deploy online codex` 工作流。后续主分支的相关代码或静态库更新会自动重新构建和发布。

### 项目结构

| 文件或目录 | 用途 |
| --- | --- |
| `codex_parser.py` | 定位 YooAsset、解密 UnityFS 并解析 MemoryPack 配置 |
| `codex_database.py` | 构建、查询和同步 SQLite 数据库 |
| `codex_achievements.py` | 加载并校验手动维护的成就条件说明 |
| `codex_save.py` | 只读解析 `HistorySave.bytes` |
| `codex_server.py` | 标准库本地 HTTP 服务和 API |
| `codex_launcher.py` | 独立版启动、存档选择和自动更新 |
| `codex_update.py` | Steam 游戏发现和资源版本更新 |
| `codex_pages.py` / `codex_pages_seo.py` | 导出公开在线图鉴与可抓取详情、站点地图 |
| `codex_pages_recommendations.py` | 根据公开配置计算补给推荐指数、食材摊销与基础种植产出 |
| `survival_log_codex.spec` | PyInstaller 依赖配置 |
| `web/` | 静态网页资源 |
| `snapshots/` | 七份版本化 Markdown 快照 |
| `survival_log_codex.sqlite3` | 跟踪的源码静态配置库 |
| `survival_log_codex_runtime.sqlite3` | 未跟踪的源码完成状态、存档元数据和 runtime 缓存 |
| `achievement_conditions.json` | 手动维护的全部成就条件、方法和限制 |
| `parser_notes.md` | 资源格式、schema、分类和运行限制 |

### 开发环境和依赖

需要 Python 3.11 或更高版本。UnityPy 默认安装到当前项目目录：

```powershell
Set-Location "D:\Codex\SurvivalLogDataViewer"
python -m pip install --target ".\_vendor_unitypy" UnityPy
```

也可以通过 `SURVIVALLOG_UNITYPY_DIR` 指定其他依赖目录。源码解析器只把项目内 `_vendor_unitypy` 作为默认位置；独立包使用打包进运行文件的 UnityPy。

### 从源码运行

启动本地网页服务：

```powershell
python .\codex_server.py `
  --database .\survival_log_codex.sqlite3 `
  --runtime-database .\survival_log_codex_runtime.sqlite3
```

构建数据库：

```powershell
python .\codex_database.py `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --database .\survival_log_codex.sqlite3 `
  --runtime-database .\survival_log_codex_runtime.sqlite3
```

默认导出全部七份 Markdown 到 `snapshots/`：

```powershell
python .\codex_parser.py `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --output-dir .\snapshots
```

单分类导出支持 `food`、`dish`、`plant`、`prey`、`craft`、`furniture` 和 `auxiliary`；`all` 使用 `--output-dir`，单分类可以使用 `--output`。

### 独立版打包

本地打包脚本会调用 PyInstaller，生成不需要用户安装 Python 的 Windows 文件夹版：

```powershell
PowerShell -ExecutionPolicy Bypass -File .\package_frontend.ps1
```

产物位于 `dist\SurvivalLogDataViewer\`，包含网页资源、预生成 SQLite 数据库和精简的 UnityPy 运行依赖，不包含游戏目录、catalog、bundle 或原始存档。脚本从 README 的用户区标记生成发布包中的 README，因此独立包不会携带开发者说明。

打包脚本会先强制关闭后台的 `生存日志图鉴.exe` 进程，每次从跟踪的静态库生成一个全新的 `SurvivalLogDataViewer.sqlite3`，其中运行时表为空，不读取或合并旧发布数据库。构建完成后再执行首页、状态和配方接口自检；只有自检通过才替换现有发布目录。自检期间产生的日志会删除，并断言最终发布目录没有日志文件。

`package_frontend.ps1` 是当前工作区的本地打包脚本，按项目约定继续被 Git 忽略；从干净克隆构建时需要另行提供该脚本。详细资源格式、数据库结构、完成状态同步和限制见 [`parser_notes.md`](./parser_notes.md)，长期工作规范见 [`AGENTS.md`](./AGENTS.md)。
<!-- END DEVELOPER GUIDE -->
