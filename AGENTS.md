# SurvivalLogDataViewer 工作规范

本文件是本项目唯一的长期工作规范。当前任务状态、长期决定和操作限制统一写在本文件中，避免生成多份相互重复的规则文件。

规则冲突优先级：用户当前要求、本文、实际代码与配置、项目说明文档、历史记录。文档与代码行为冲突时，以代码和本地游戏资源为事实，并修正文档；不能为了符合旧文档修改已验证的本地数据。

## 1. 项目定位

- 本项目是 Survival Log 的离线图鉴数据解析工具，不是游戏本体，也不是运行时 mod。
- 工具直接读取本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，不启动游戏。
- 当前主要脚本为 `codex_parser.py`，主要技术说明为 `parser_notes.md`，用户入口为 `README.md`。
- 默认输出七份 UTF-8 Markdown 到 `snapshots/`：六类主图鉴 `snapshots/survival_log_food.md`、`snapshots/survival_log_dish.md`、`snapshots/survival_log_plant.md`、`snapshots/survival_log_prey.md`、`snapshots/survival_log_craft.md`、`snapshots/survival_log_furniture.md`，以及 `snapshots/survival_log_auxiliary.md`。
- 数据库构建脚本为 `codex_database.py`，存档读取脚本为 `codex_save.py`，本地标准库网页服务为 `codex_server.py`，自动更新模块为 `codex_update.py`，静态资源位于 `web/`；源码数据库默认文件为 `data/survival_log_codex.sqlite3`，独立版数据库仍位于 exe 同目录。
- 当前默认游戏目录是 `G:\SteamLibrary\steamapps\common\Survival Log`；用户通过 `--game-root` 指定其他安装位置时，以命令参数为准。
- 输出目录通过 `--output-dir` 指定，默认是脚本所在目录下的 `snapshots/`。输出文件只能写入用户指定的输出目录，不得写入游戏安装目录。

## 2. 绝对安全规则

- 游戏安装目录、存档目录、mod DLL、资源包和原始 catalog 一律按只读数据处理。
- 不修改、覆盖、移动、删除或重命名游戏目录中的文件；不写入存档，不改变 mod，不启动游戏进行验证。
- 不上传或泄露游戏资源、存档、用户路径之外的私人数据、解析出的完整资源内容或不必要的调试数据。
- 解析器可以覆盖输出目录中用户明确要求重新生成的 Markdown，但不得顺手删除图片、说明、脚本、未知文件或其他用户资料。
- 删除项目文件前必须先用只读检查确认精确目标、父目录和文件类型。用户未明确要求时不得执行递归删除；需要删除时优先移入回收站，并在结果中说明删除对象和可恢复性。
- 不覆盖或回退已有未提交修改。发现工作区有既有修改时，先区分其归属；与当前任务无关的修改必须保留。
- 禁止使用 `git reset --hard`、`git clean -fd`、`git restore .`、`git checkout -- .`、强制 push 或其他不可逆 Git 操作。
- 不能判断操作风险、目标范围或回滚方式时，暂停写操作，先说明影响和需要的授权。

## 3. 数据与解析边界

- 最终数据源是当前本地游戏版本；参考仓库只用于字段命名、结构理解和交叉校验，不能替代本地资源。
- 图鉴条目来自静态配置；完成状态只读读取用户本机 `HistorySave.bytes` 中的游戏存档数据，不读取玩家库存、运行时修改或联网数据。
- 当前资源定位流程必须保留：YooAsset catalog 定位、bundle 名称和物理文件 hash 解析、bundle 解密、UnityFS 读取、TextAsset 提取和 MemoryPack 反序列化。
- 当前 bundle 解密算法为：

  ```text
  Salt = SL_BundleCrypto_v1_9f3d7a1c
  key  = MD5(Salt + BundleName) + MD5(BundleName + Salt)
  data[i] ^= key[i % 32]
  ```

- 解析器必须验证 catalog 读取到末尾、每张 MemoryPack 表的对象数量和字段数量、每行字段完整读取，并验证数据游标到达原始数据末尾。
- 新版本 schema 发生变化时，应报出表名、行号、字段数量或 offset 等清晰错误；不得静默按旧 schema 猜测并生成看似正常的数据。
- 关联 ID 必须保留原始数字，同时尽可能解析为名称。无法解析的值统一使用 `ID:xxxx`；空值或游戏使用的 0 哨兵统一显示为“无”。
- 本地化名称为空时，按配置键、非本地化名称、ID 的顺序回退；不得伪造名称。

## 4. 配置表和分类规则

六类导出在解析和导出层面一视同仁。新增分类时应扩展配置表、分类处理器、输出文件名和验证项，不得再为菜肴保留单独的兼容导出路径。

- 食品：`Config_Item`，关联 `Config_ItemSubCategory`、`Config_FoodType`。
- 菜肴：`Config_CookingRecipe`，关联 `Config_Item`、`Config_ItemSubCategory`。
- 植物：`Config_Plant`、`Config_PlantLv`，收获物、种子和枯萎产物关联 `Config_Item`。
- 猎物：没有独立 `Config_Prey` 时使用 `Config_Item` 中的 `InCodex`、`Prey_Rarity`、`CaptureExp` 和图鉴字段。
- 制造：`Config_ProductionList`、`Config_ProductionLv`，材料、产物、失败产物和完美产物关联 `Config_Item`。
- 家具：`Config_Furniture` 及 `Config_FurnitureFunc`、`Config_FurnitureCook`、`Config_FurniturePlant`、`Config_FurnitureElectrical`、`Config_FurnitureState`、`Config_FurnitureTag`、`Config_FurniturePartner`。

食品和猎物按游戏 Codex 字段分类：先要求 `Config_Item.InCodex == true`；`Prey_Rarity > 0` 的物品归入猎物；`Category == 1` 的物品归入食品。食品和猎物允许重叠，不得直接照搬参考网页中的物品分类。
当前版本主图鉴数量基准为：食品 174、菜肴 496、植物 34、猎物 19、制造 125、家具 87。参考进度为食品 61、菜肴 93、植物 14、猎物 15、制造 110、家具 73，总计 366/935，约 39%；参考进度只用于验收，不推断具体完成 ID。

家具关联字段必须按语义解析：功能 ID 对应 `Config_FurnitureFunc`，种植、烹饪和电力配置 ID 对应各自关联表，包裹、材料、产物、种子和燃料 ID 对应 `Config_Item`，允许菜肴 ID 对应 `Config_CookingRecipe`，伙伴触发家具和伙伴配置 ID 对应 `Config_Furniture`。没有独立配置表的条件组、奖励组、动作、房间和掉落组等引用保留原始 ID。

## 5. 代码架构边界

- 配置表使用集中 schema 和通用 MemoryPack 读取层；不要为每个字段复制一套临时解析器。
- 六类输出应通过统一的分类注册表和统一的 `extract_category` 流程完成；每类只提供自己的数据选择和 Markdown 渲染器。辅助配置作为独立的 `auxiliary` 导出，不计入六类完成进度。
- 数据库使用 SQLite 保存主条目、分类映射、共享主完成状态、分类完成状态、关联关系和辅助配置；食品/猎物重复分类的同一源条目只保存一份主完成状态，分类统计按存档分类分别计数。
- 不在输出流程中写只针对菜肴的隐式分支、旧单文件兼容函数或特殊覆盖参数。命令行的 `--category`、`--output-dir` 和显式单分类 `--output` 语义必须适用于所有分类。
- 保持解析层、配置关联层、分类层、Markdown 渲染层和 CLI 层边界清晰。无关重构不得混入数据解析任务。
- 输出 Markdown 中必须包含适用的配置 ID、名称、本地化名称、分类、属性、材料、产物、种子、家具功能、等级、经验、时间、概率、价格、耐久等字段；新增字段时保留原始字段含义。
- 脚本只读游戏源文件，并将派生结果写入输出目录。不得把生成 Markdown 反向作为下一次解析的数据源。

## 6. 命令行约定

- 不指定 `--category` 时默认生成六类主图鉴和辅助配置。
- `--category all` 显式生成全部七份输出；`food`、`dish`、`plant`、`prey`、`craft`、`furniture`、`auxiliary` 分别生成对应输出。
- all 模式使用 `--output-dir` 指定目录；显式单分类时可以用 `--output` 指定该分类的单个 Markdown 路径。
- 参数错误、资源缺失、catalog 版本变化、bundle 解密失败、TextAsset 缺失和 schema 不匹配必须返回非零退出码，并给出可操作的中文错误信息。
- 重新运行只覆盖目标 Markdown、用户指定的 SQLite 数据库或数据库内派生状态，不修改游戏文件、mod DLL、存档或 Steam Cloud 文件。

## 7. 修改前调查

- 开始任务前先执行 `git status --short`、查看目标文件和相关文档，确认已有未提交修改。
- 使用 `rg` 或 `rg --files` 搜索文件和文本；能并行读取的独立文件检查应并行执行。
- 先确定影响范围和验证范围，再编辑；不要因为发现无关问题而扩大任务。
- 涉及新配置表、字段、分类规则或游戏版本时，先检查当前 catalog、bundle、实际 MemoryPack 数据和本地 HotUpdate/interop 元数据；参考仓库仅作辅助。
- 涉及资源包解密或二进制格式时，必须保留原始文件只读，并用副本、内存数据或临时隔离目录进行实验。
- 如果用户要求的是说明、审查或诊断，不擅自改代码；如果用户要求实现，则完成修改、验证和结果交付，不停在方案阶段。
- 发现重大且无法从本地代码、资源和用户要求推断的选择时，说明冲突、影响、回滚方案和 2 到 3 个选项后再继续。

## 8. 编辑与工具约定

- 手工修改文件使用 `apply_patch`；不要用 `cat`、shell 重定向或临时脚本直接写项目文件。
- 不用 Python 代替 `apply_patch` 进行普通文件读写；Python 仅用于必要的解析、验证或测试。
- 默认使用 ASCII；本项目已有中文 Markdown、Python 和说明文件，确有必要时保持现有 UTF-8 编码。
- 注释只写复杂逻辑的必要背景，不写逐行复述代码的空洞注释。
- 不用 shell 命令串联无关操作；长任务过程中持续向用户报告调查、编辑和验证进度。
- 运行需要较长时间的命令时避免阻塞超过 60 秒；确保本次任务结束前所有相关命令都已完成。

## 9. 验证要求

窄范围代码改动至少执行语法检查和对应分类验证；涉及解析 schema、资源定位、分类规则或共用导出层时执行完整验证。

- 运行 `python -m py_compile "codex_parser.py" "codex_save.py" "codex_database.py" "codex_server.py" "codex_launcher.py" "codex_update.py"`。
- 使用当前完整游戏目录运行一次默认全量导出，确认生成七个 UTF-8 Markdown。
- 分别运行七个 `--category` 入口，确认输出路径、退出码、数量和内容正常。
- 校验当前主图鉴数量：食品 174、菜肴 496、植物 34、猎物 19、制造 125、家具 87；原始配置表数量不能直接当作图鉴数量。
- 构建 SQLite 数据库，确认六类分类映射合计 935，读取 `HistorySave.bytes` 得到 `366/935` 和 `61/93/14/15/110/73`；食品/猎物重叠条目共享主完成状态，启动本地网页服务验证存档同步和只读状态展示。独立版直接使用 exe 同目录数据库，不创建 AppData 副本；普通启动无终端并在网页心跳断开约 30 秒后退出，`--headless` 保持常驻。
- 确认所有解析表读取到 EOF，无未捕获 schema 错误；检查未知关联 ID 是否明确显示为 `ID:xxxx`。
- 抽查参考仓库和本地数据中的佛跳墙、清炒菌菇、蛋炒饭、松茸、硬纸、箱子和小家鼠等条目。
- 对资源缺失、catalog 版本变化、空列表、空本地化名称和未知 ID 做隔离测试；测试不得改动游戏目录。
- 验证重新运行只覆盖 Markdown 和 SQLite 派生状态，不修改游戏文件、mod DLL、存档或 catalog；检查目标文件大小、时间和 hash 时，不将检查命令误写成修改命令。
- 修改前后检查 `git status --short`、`git diff --stat` 和目标文件 diff；若当前目录不是 Git 仓库，明确记录这一事实，不伪造 diff 或提交状态。

## 10. 文档、状态与版本控制

- 解析行为、资源来源、版本号、分类规则、已知限制或 CLI 发生变化时，同步更新 `parser_notes.md`，但不复制整份工作规范。
- 不创建与用户要求无关的日志、缓存、测试数据或多余文档文件。
- 不自动把游戏资源、存档、生成的大型 Markdown、SQLite 数据库或临时文件加入 Git；检查 `.gitignore` 后再决定是否纳入版本控制。
- `snapshots/` 目录中的七份 Markdown 属于版本化派生结果，继续纳入 Git；其他生成的大型 Markdown 仍不自动加入 Git。
- 完成一个逻辑完整、经过验证的功能单元后，默认创建一次本地 commit。commit 只包含本任务明确修改的文件。有外部未提交修改时不得擅自提交或重写历史。
- commit提交信息为 type: description 格式，description 应能概括本次变更。type 为英文格式，description 为中文格式。
