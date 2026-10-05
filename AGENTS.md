# SurvivalLogDataViewer 工作规范

本文件是项目唯一的长期工作规范。当前任务状态、长期决定和操作限制统一写在这里，不再生成重复的规则文件。

规则冲突优先级为：用户当前要求、本文、实际代码与配置、项目说明文档、历史记录。文档与代码行为冲突时，以代码和本地游戏资源为事实，并修正文档；不能为了符合旧文档修改已验证的本地数据。

## 1. 项目事实

- 本项目是 Survival Log 的离线图鉴数据解析工具，不是游戏本体，也不是运行时 mod。
- 工具直接读取本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，不启动游戏。
- 主要模块为 `codex_parser.py`、`codex_database.py`、`codex_save.py`、`codex_server.py`、`codex_launcher.py` 和 `codex_update.py`；本地网页服务的静态资源位于 `web/`。
- 在线 GitHub Pages 站点源码位于 `pages/`（HTML/CSS/JS 与预提取图标 `pages/icons/`），由 `codex_pages*.py` 从静态库构建，GitHub Actions（`.github/workflows/pages.yml`）构建发布到 `build/pages`；改在线站点先查 `pages/`，不要和 `web/` 混淆。
- 源码根目录的 `survival_log_codex.sqlite3` 是跟踪的静态配置库，`survival_log_codex_runtime.sqlite3` 是未跟踪的完成状态、存档元数据和 runtime 缓存库；源码版不生成存档同步诊断日志。源码静态库随 Git 管理，个人状态需要单独备份 runtime 库；独立版使用 exe 同目录的单文件数据库，备份该单一文件即可，日志为 `SurvivalLogDataViewer.log`。
- 文档、代码和提交内容一律不写入本机绝对路径（Steam 库、磁盘布局等个人信息）。CLI 缺省的游戏目录通过 Steam 库自动发现（`codex_update.py`），找不到时报错并要求用 `--game-root` 指定；用户通过 `--game-root` 指定其他路径时，以命令参数为准。
- 输出目录通过 `--output-dir` 指定，默认是脚本所在目录下的 `snapshots/`。输出文件只能写入用户指定的输出目录。
- UnityPy 默认从源码根目录下的 `_vendor_unitypy` 加载；`SURVIVALLOG_UNITYPY_DIR` 可以覆盖默认路径。

## 2. 安全和数据边界

- 游戏安装目录、存档目录、mod DLL、资源包和原始 catalog 一律只读处理。
- 不修改、覆盖、移动、删除或重命名游戏目录中的文件；不写入存档，不改变 mod，不启动游戏进行验证。
- 不上传或泄露游戏资源、存档、用户路径之外的私人数据、完整解析结果或不必要的调试数据。
- 图鉴条目来自静态配置；完成状态只读读取用户本机 `HistorySave.bytes`，不读取库存、其他运行时修改或联网数据。
- 解析器只能覆盖用户明确指定输出目录中的目标 Markdown、用户指定的 SQLite 数据库或数据库内派生状态，不得删除目录中的其他文件。
- 删除项目文件前必须只读确认精确目标、父目录和文件类型。用户未明确要求时不得递归删除；需要删除时优先移入回收站并说明可恢复性。
- 不覆盖或回退已有未提交修改；禁止 `git reset --hard`、`git clean -fd`、`git restore .`、`git checkout -- .`、强制 push 或其他不可逆 Git 操作。

## 3. 解析不变量

- 最终数据源是当前本地游戏版本；参考仓库只用于字段命名、结构理解和交叉校验，不能替代本地资源。
- 必须保留 YooAsset catalog 定位、bundle 名称和物理文件 hash 解析、bundle 解密、UnityFS 读取、TextAsset 提取和 MemoryPack 反序列化流程。
- 当前 bundle 解密算法为：

  ```text
  Salt = SL_BundleCrypto_v1_9f3d7a1c
  key  = MD5(Salt + BundleName) + MD5(BundleName + Salt)
  data[i] ^= key[i % 32]
  ```

- 必须验证 catalog 读取到末尾、每张 MemoryPack 表的对象数量和字段数量、每行字段完整读取，以及数据游标到达原始数据末尾。
- 新版本 schema 变化必须报出表名、行号、字段数量或 offset 等清晰错误，不得静默按旧 schema 猜测。
- 关联 ID 必须保留原始数字并尽量解析名称；无法解析时显示 `ID:xxxx`，空值或游戏使用的 0 哨兵显示为“无”。本地化名称按本地化字段、非本地化配置键、ID 顺序回退。

## 4. 分类和关联规则

六类主图鉴必须通过统一的分类注册表和 `extract_category` 流程导出；辅助配置单独导出为 `auxiliary`，不计入六类完成进度。

- 食品：`Config_Item` 中 `InCodex == true && Category == 1` 的条目，关联 `Config_ItemSubCategory` 和 `Config_FoodType`。
- 菜肴：`Config_CookingRecipe` 全部行，因该表没有 `InCodex` 字段，关联 `Config_Item` 和 `Config_ItemSubCategory`。
- 植物：`Config_Plant` 中 `InCodex == true` 的条目及其 `Config_PlantLv`，收获物、种子和枯萎产物关联 `Config_Item`。
- 猎物：`Config_Item` 中 `InCodex == true && Prey_Rarity > 0` 的条目，同时保留原始字段。
- 制造：`Config_ProductionList` 中 `InCodex == true` 的条目及其 `Config_ProductionLv`，材料、产物、失败产物和完美产物关联 `Config_Item`。
- 家具：`Config_Furniture` 中 `InCodex == true` 的条目，按语义关联家具功能、种植、烹饪、电力、状态、标签和伙伴配置表。

食品和猎物允许重叠，不得照搬参考网页的物品分类。六个主图鉴分类均严格使用配置中的 `InCodex == true`，只有没有该字段的菜肴表保留全部行。家具中的功能 ID 对应 `Config_FurnitureFunc`，种植、烹饪和电力 ID 对应各自关联表，包裹、材料、产物、种子和燃料 ID 对应 `Config_Item`，允许菜肴 ID 对应 `Config_CookingRecipe`，伙伴触发家具和伙伴配置 ID 对应 `Config_Furniture`；没有独立配置表的条件组、奖励组、动作、房间和掉落组保留原始 ID。

菜肴库存读取主控背包、工作台抽屉，以及 `ChapterAgentMap` 中按配置语义识别为储物容器且位置属于玩家家中的全部容器。`Config_Furniture` 的 `FurnitureFunc` 包含 215 或 `ShowStorage > 0` 时视为储物家具，不依赖本地化名称；家具优先使用 `BagFurnitureConfigId`，否则使用 `AgentConfigId`，同名的多个家具实例均保留。容器位置结合主控 `MapConfigIdHome`、实例 `MapConfigId` 和 `SlotPosPoint` 判断：家中槽位进入库存，邻居槽位、其他地图和无法确认的位置不进入库存；每个实例仍输出位置、实例 ID 和槽位诊断。单独的 `IsDoorBox == true` 可作为无配置映射时的存档兼容识别。车辆后备箱和普通 `ChapterAgentMap` 条目忽略。旧版 `DoorBoxItems`/`DoorBoxItems2` 仅保留 15000/15001 的兼容回退，且只在没有对应实际家具时使用。

当前版本的全量配置数量和实际图鉴展示数量只在 `parser_notes.md` 维护，其他文档不得复制固定数字。

## 5. 架构和命令行

- 配置表使用集中 schema 和通用 MemoryPack 读取层，不为单个字段复制临时解析器。
- 保持解析层、配置关联层、分类层、Markdown 渲染层、数据库层、网页服务层和 CLI 层边界清晰，不混入无关重构。
- 输出 Markdown 必须包含适用的配置 ID、名称、本地化名称、分类、属性、材料、产物、种子、家具功能、等级、经验、时间、概率、价格和耐久等字段，并保留原始字段含义。
- 不指定 `--category` 或指定 `all` 时生成六类主图鉴和辅助配置；单分类支持 `food`、`dish`、`plant`、`prey`、`craft`、`furniture`、`auxiliary`。
- `all` 使用 `--output-dir`，显式单分类可以使用 `--output`；输出路径不得位于游戏安装目录。
- 参数错误、资源缺失、catalog 版本变化、bundle 解密失败、TextAsset 缺失和 schema 不匹配必须返回非零退出码，并给出可操作的中文错误信息。
- 源码模式以只读方式打开静态库并附加 runtime 库；独立包使用 exe 同目录单文件数据库。README 由打包脚本从用户区生成，不能把开发者说明带入发布包；每次打包从静态库生成空运行时表，不读取旧发布数据库或旧完成状态，且发布目录不预置日志。

## 6. 修改前调查和编辑

- 开始任务前执行 `git status --short`，查看目标文件和相关文档，确认已有未提交修改及其归属。
- 使用 `rg` 或 `rg --files` 搜索文件和文本；独立文件检查尽量并行执行。
- 涉及新配置表、字段、分类规则或游戏版本时，先检查当前 catalog、bundle、MemoryPack 数据和本地 HotUpdate/interop 元数据。
- 涉及资源包解密或二进制格式时，只用副本、内存数据或临时隔离目录实验，保留原始文件只读。
- 手工修改使用 `apply_patch`；不使用 shell 重定向、临时脚本或 Python 代替普通文件编辑。
- 默认使用 ASCII；已有中文文件保持 UTF-8。注释只写复杂逻辑所需的背景。
- 用户要求说明、审查或诊断时不擅自改代码；用户要求实现时完成修改、验证和结果交付。

## 7. 验证和交付

- 至少执行：

  ```powershell
  python -m py_compile "codex_parser.py" "codex_save.py" "codex_database.py" "codex_server.py" "codex_launcher.py" "codex_update.py"
  ```

- 涉及解析、资源定位、分类规则或共用导出层时，使用当前完整游戏目录执行默认七份导出、七个单分类入口、SQLite 构建和网页服务验证。
- 校验食品和猎物的字段筛选，植物、制造和家具的配置表全量收录，六类分类映射数量及食品/猎物共享主完成状态。
- 确认所有解析表读到 EOF，未知关联 ID 明确显示为 `ID:xxxx`；隔离测试资源缺失、catalog 版本变化、空列表、空本地化名称和未知 ID。
- 验证存档写入中、主文件失败和 `.bak` 回退时不会清空上一次有效状态；验证后台标签页或切回游戏不会触发退出，明确关闭页面后约 30 秒退出，`--headless` 保持常驻。
- 验证重新运行只覆盖 Markdown 和 SQLite 派生状态，不修改游戏文件、mod DLL、存档、Steam Cloud 或 catalog。
- 修改前后检查 `git status --short`、`git diff --stat`、目标文件 diff 和 `git diff --check`。若当前目录不是 Git 仓库，明确记录，不伪造 diff 或提交状态。

## 8. 文档和版本控制

- 解析行为、资源来源、版本号、分类规则、已知限制或 CLI 变化时同步更新 `parser_notes.md`，但不复制整份工作规范。
- 不创建与任务无关的日志、缓存、测试数据或文档。
- 不自动把游戏资源、存档、数据库或临时文件加入 Git；`snapshots/` 中七份 Markdown 是版本化派生结果。
- 完成逻辑完整且经过验证的功能单元后，默认创建本地 commit；只提交本任务明确修改的已跟踪文件，不重写外部未提交修改。
- commit 信息使用 `type: description` 格式，type 为英文，description 为中文。
