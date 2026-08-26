# Survival Log Data Viewer

离线读取 Survival Log 本地资源的图鉴查看器。它不启动游戏，不修改游戏文件、Mod、Steam Cloud 或存档；图鉴配置来自本机游戏资源，完成状态只读取 `HistorySave.bytes`。

## 普通用户

1. 解压完整的 `dist/SurvivalLogDataViewer/` 文件夹。
2. 双击 `生存日志图鉴.exe`。
3. 程序会自动打开浏览器。首次启动会从 Steam 的 `libraryfolders.vdf` 查找游戏；游戏版本变更时自动重新解析并导入图鉴。

发布包中的数据库是 `SurvivalLogDataViewer.sqlite3`。它初始不包含任何完成状态，启动后会按默认路径同步当前用户的存档：

```text
%USERPROFILE%\AppData\LocalLow\LLS\SLGame\Saves\HistorySave.bytes
```

默认存档不存在时，程序会弹出文件选择窗口。程序只读读取所选文件，也会在主文件写入期间尝试同名 `.bak` 备份。

存档同步异常的详细诊断会写入数据库同目录的 `.log` 文件：源码运行默认是 `survival_log_codex.log`，独立版默认是 `SurvivalLogDataViewer.log`。日志只记录解析阶段、文件摘要、候选映射位置和错误原因，不写入原始存档内容；目录不可写时会回退到 `%LOCALAPPDATA%\SurvivalLogDataViewer`。

## 图鉴页面

- 左侧切换食品、菜肴、植物、猎物、制造和家具。
- 条目按 ID 从小到大排列，点击整行即可在右侧查看详情。
- “成品名称”检索只匹配条目名称、名称键和 ID。
- “材料”检索只匹配菜肴食材、制造材料和家具制造材料；两个检索条件可以同时使用。
- 详情顶部只显示当前分类的重点信息，其余字段默认折叠。

## 文件与存储管理

根目录中的源码和说明文件应保留；7 份 `survival_log_*.md` 是当前解析结果的版本快照，也继续纳入版本控制。

| 文件或目录 | 用途 | 生命周期 |
| --- | --- | --- |
| `.gitignore` | Git 忽略规则 | 长期保留 |
| `AGENTS.md` | 项目安全、数据边界和验收规范 | 长期保留 |
| `README.md` | 用户和开发者入口说明 | 长期保留 |
| `parser_notes.md` | 资源格式、schema 和解析限制 | 长期保留 |
| `codex_parser.py` | 解析游戏资源并导出 Markdown | 源码 |
| `codex_database.py` | 构建、查询和同步 SQLite | 源码 |
| `codex_save.py` | 只读解析游戏存档 | 源码 |
| `codex_server.py` | 本地 HTTP 服务和 API | 源码 |
| `codex_launcher.py` | 独立版启动和自动更新 | 源码 |
| `codex_update.py` | Steam 游戏发现和版本更新 | 源码 |
| `package_frontend.ps1` | PyInstaller 打包入口 | 源码 |
| `survival_log_codex.spec` | PyInstaller 依赖配置 | 源码 |
| `survival_log_*.md` | 七类图鉴和辅助配置快照 | 生成后审阅、提交 |
| `data/` | 源码运行数据库和诊断日志 | 自动生成，可重建 |
| `web/` | 静态网页资源 | 源码资源 |
| `test/` | 存档测试夹具和报告 | 本地测试数据 |
| `_vendor_unitypy/` | 源码解析所需的本地 UnityPy 依赖 | 本地依赖，勿删运行模块 |
| `build/` | PyInstaller 中间产物 | 可随时删除并重建 |
| `dist/` | 独立版分发目录和压缩包 | 发布/测试产物 |
| `__pycache__/` | Python 字节码缓存 | 可随时删除 |

源码数据库默认位于 `data/survival_log_codex.sqlite3`，日志位于同目录。首次运行发现旧的根目录数据库时，程序会先校验并迁移它；迁移失败会保留旧文件。独立版仍使用 exe 同目录中的 `SurvivalLogDataViewer.sqlite3`，分发时必须整体携带 `dist/SurvivalLogDataViewer/`，不能只复制 exe。

## 从源码运行

需要 Python 3.11 或更高版本。解析游戏资源时需要 UnityPy；项目默认从 `D:\Codex\000\_vendor_unitypy` 查找本地依赖，也可以设置 `SURVIVALLOG_UNITYPY_DIR`。

启动本地网页：

```powershell
python .\codex_server.py --database .\data\survival_log_codex.sqlite3
```

构建数据库：

```powershell
python .\codex_database.py `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --database .\data\survival_log_codex.sqlite3
```

导出七份 Markdown：

```powershell
python .\codex_parser.py `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --output-dir .
```

Windows 文件夹版打包：

```powershell
PowerShell -ExecutionPolicy Bypass -File .\package_frontend.ps1
```

打包脚本会复制一份空完成状态数据库，清除全部 `save_*` 元数据，并把产物写入 `dist/SurvivalLogDataViewer/`。源码数据库不会写入游戏安装目录。

## 文件说明

- `codex_parser.py`：读取 YooAsset、解密 UnityFS 并解析 MemoryPack 配置。
- `codex_database.py`：构建和查询 SQLite 数据库。
- `codex_save.py`：只读解析 `HistorySave.bytes`。
- `codex_update.py`：发现 Steam 游戏目录并按版本自动更新数据库。
- `codex_server.py`：标准库本地网页服务。
- `codex_launcher.py`：独立版启动器。
- `parser_notes.md`：资源格式、字段和解析边界的技术说明。

详细限制、schema 校验和数据来源见 [`parser_notes.md`](./parser_notes.md)。
