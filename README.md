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

## 从源码运行

需要 Python 3.11 或更高版本。解析游戏资源时需要 UnityPy；项目默认从 `D:\Codex\000\_vendor_unitypy` 查找本地依赖，也可以设置 `SURVIVALLOG_UNITYPY_DIR`。

启动本地网页：

```powershell
python .\codex_server.py --database .\survival_log_codex.sqlite3
```

构建数据库：

```powershell
python .\codex_database.py `
  --game-root "G:\SteamLibrary\steamapps\common\Survival Log" `
  --database .\survival_log_codex.sqlite3
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
