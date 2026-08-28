# 存档可用食材获取流程与证据记录

> 文档状态：当前实现基线记录
>
> 记录日期：2026-08-29
>
> 对应代码基线：`e7a5f39 fix: 按章节分组隔离存档食材`

本文档记录 Survival Log 图鉴工具从存档中获取“当前存档可用食材”的完整过程、历史修正、实测证据和后续排查方法。它是库存来源问题的长期调查记录，供后续修改解析器和复现问题时使用。

文档中的结论使用以下标记：

- `[已验证]`：由当前代码、单元测试、静态资源检查或实际存档读取直接确认。
- `[推断]`：由多个字段或受控 A/B 存档对比推导，但没有拿到游戏方法体或写入调用链的直接证明。
- `[未确认]`：当前没有足够证据，不得据此新增筛选规则。

## 1. 结论摘要

当前最容易造成库存错误的部分不是 `SpecificItems`、`TagCombo` 或菜肴档位算法，而是把错误的容器当成当前角色、当前章节的家中容器。正确的处理顺序必须是：

```text
HistorySave.bytes
  -> 当前子存档文件
  -> GameSaveData / CurSave
  -> LeadingRole 角色上下文
  -> InitChapterId 选择 ChapterAgentMap 章节组
  -> 储物家具配置识别
  -> 地图 + 角色槽位 + 章节组判断容器归属
  -> 读取容器 ItemList
  -> 形成库存
  -> 交给现有菜肴匹配逻辑
```

目前已经确认的规则如下：

1. `LeadingRole.Name` 是当前角色名称；`HistoryList.Name` 是历史记录显示标签，通常是时间或存档标签，不能用来识别角色。
2. `ChapterAgentMap` 的外层键是章节分组键，不是角色 ID，也不是地图 ID；不能使用“外层键等于角色 ID”或“数值最大的键就是最新”这类替代规则。
3. 当前有正值且能在 `ChapterAgentMap` 中找到的 `GameSaveData.InitChapterId` 是选择章节组的首要依据。
4. 选中章节组后，容器仍须同时满足储物行为、实例地图与主控家地图一致、当前角色槽位一致，才能计入家中库存。
5. 静态数据库中的 `storage_furniture` 表是储物家具配置的权威来源，必须覆盖所有 `FurnitureFunc` 包含 `215` 或 `ShowStorage > 0` 的配置，不受图鉴可见性和本地化名称影响。
6. 主控背包和工作台抽屉是直接来源；车辆后备箱、普通非储物 `ChapterAgentMap` 条目、其他章节组和无法确认位置的容器不计入可烹饪库存。

## 2. 范围和边界

### 2.1 本文档覆盖

- `HistorySave.bytes` 如何发现并选择子存档。
- 子存档的 schema、兼容版本和严格 EOF 校验。
- 角色名称、数字身份、家地图和角色槽位的解析。
- `ChapterAgentMap` 章节组的选择。
- 储物家具配置表的生成和读取。
- 容器位置分类、实际物品堆读取和旧字段回退。
- 后端 JSON、网页诊断和缓存失效信息。
- 历史实现、错误表现、实测样本和未来修改检查清单。

### 2.2 本文档不改变

以下逻辑属于库存数据的下游消费者，本轮记录不应重新修改：

- 菜肴 `SpecificItems` 的实际物品多重集合匹配。
- 菜肴 `TagCombo` 的分类组合和档位计算。
- 特色菜肴与通用菜肴的优先级。
- 近匹配、缺少物品候选、完成状态和菜肴计划布局。

“可用食材”在不同输出层有一个必须保留的区别：

- 库存展示要求物品在配置中属于 `Category == 1`、`CanCook == true` 且 `InCodex == true`。
- 菜肴匹配要求物品属于已知的可烹饪食品且数量为正，但不额外要求 `InCodex == true`，以保持当前匹配行为。

## 3. 端到端流程

| 阶段 | 主要输入 | 当前处理 | 失败或保护行为 |
| --- | --- | --- | --- |
| 1. 历史索引 | `HistorySave.bytes` | 读取 `HistoryList`，得到子存档文件名、显示名和历史 `PlayerSelectId` | 历史文件或 schema 无法读取时报告诊断 |
| 2. 子存档定位 | `HistoryList` 文件名 | 只接受单层 `Save_*.bytes` 文件名；先读主文件，失败后按规则尝试 `.bak` | 文件缺失、路径不合法或主文件失败会保留错误原因 |
| 3. 稳定读取 | 子存档二进制 | 读取前后比较文件大小和修改时间，避免读取游戏正在写入的文件 | 文件在读取期间变化则放弃本次读取 |
| 4. wire 解析 | `GameSaveData` | 按当前 schema 解析完整对象，只捕获库存所需字段，但仍跳过并校验全部字段 | schema 成员数变化、字段读取失败或尾部残留都报错 |
| 5. 当前保存 | `CurSave` | 从当前 `SaveChildData` 读取 `LeadingRole`、`ChapterAgentMap` 和直接库存字段 | `CurSave` 缺失或为 null 时该子存档失败 |
| 6. 角色上下文 | `LeadingRole`、根 `PlayerSelectId`、历史 `PlayerSelectId` | 先用名称，名称不可用时按数字身份顺序回退 | 无法解析角色时不读取依赖角色槽位的章节容器 |
| 7. 章节组 | `InitChapterId`、`ChapterAgentMap` | 选择与 `InitChapterId` 相同的外层键 | 缺失或不匹配时才尝试唯一槽位+地图候选；歧义则跳过章节容器 |
| 8. 配置识别 | 静态库 `storage_furniture` | 按家具功能和容量识别储物配置，不依赖名称 | 旧库缺少专用表时才使用兼容回退 |
| 9. 容器归属 | 章节组键、`MapConfigId`、`MapConfigIdHome`、`SlotPosPoint` | 联合判断 `home`、`other` 或 `unknown` | 只有 `is_home == true` 的容器进入库存 |
| 10. 物品堆 | `ItemList` 中的 `ItemConfigId`、`ItemCount` | 读取正整数物品堆并保留来源和容器 | ID 或数量非法的堆跳过并写入诊断 |
| 11. 下游输入 | `SaveInventoryState` | 展示层合并同一物品的来源；匹配层使用可烹饪物品 | 不在本流程中改变菜肴匹配算法 |

## 4. 关键字段词典

| 字段或变量 | 含义 | 在库存流程中的作用 |
| --- | --- | --- |
| `HistoryList.Name` | 历史记录的显示名称或时间标签 | 仅用于网页显示和存档标识，不能作为角色名 |
| `HistoryList.PlayerSelectId` | 历史索引记录中保存的数字角色身份 | `GameSaveData.PlayerSelectId` 不可用时的第二级身份回退 |
| `LeadingRole.Name` | `CurSave.LeadingRole` 的当前角色名称 | 当前格式中的首要角色身份来源；先做 NFKC 标准化、去空格和大小写折叠 |
| `GameSaveData.PlayerSelectId` | 当前子存档根对象的数字角色身份 | 名称缺失、未知或冲突时的第一级数字回退 |
| `LeadingRole.AgentConfigId` | 主控角色实体的配置 ID | 保存角色实体身份，也可通过已验证映射回退到角色 ID |
| `resolved_player_select_id` | 解析器最终采用的角色 ID | 决定角色槽位前缀和角色上下文输出，不等于章节组键 |
| `MapConfigIdHome` | 主控角色记录的家地图配置 ID | 容器必须与它一致，才能通过地图证据 |
| `GameSaveData.InitChapterId` | 存档初始化/当前章节组 ID | 用于选择 `ChapterAgentMap` 的外层键；当前不作为角色 ID使用 |
| `CurSave.ChapterAgentMap` | 章节组到 `AgentSave` 列表的字典 | 外层键分组容器；只有选中的组可为当前库存提供容器 |
| `chapter_map_key` | `ChapterAgentMap` 的某个外层整数键 | 记录容器来自哪一组；不应解释为角色或地图 ID |
| `AgentSave.MapConfigId` | 容器实例当前所在地图 ID | 与 `MapConfigIdHome` 比较，判断地图是否一致 |
| `AgentSave.MapConfigIdHome` | 容器或实体保存的家地图相关字段 | 当前主要作为容器诊断字段保留，不能单独替代主控家地图比较 |
| `AgentSave.ChapterId` | 容器实体内部保存的章节字段 | 当前只作为诊断元数据，不替代 `InitChapterId` 选择外层组 |
| `AgentSave.SlotPosPoint` | 容器放置位置名称 | 通过角色专属前缀判断属于哪个角色的家中槽位 |
| `AgentSave.BagFurnitureConfigId` | 包裹/家具对应的家具配置 ID | 当它是已知储物配置时优先作为有效家具 ID |
| `AgentSave.AgentConfigId` | 实体自身配置 ID | `BagFurnitureConfigId` 不可用或不是储物配置时使用 |
| `AgentSave.IsBagFurniture` | 标记实体是否为家具类实体 | 作为原始诊断字段保留；储物识别以配置行为为主 |
| `AgentSave.IsDoorBox` | 门箱/箱体兼容标记 | 只在地图明确为当前家中且角色已知时保留兼容识别 |
| `AgentSave.ItemList` | 一个容器中的物品堆列表 | 只有被判定为 `home` 的储物实例才读取进可用库存 |
| `ItemSave.ItemConfigId` | 物品配置 ID | 关联静态 `Config_Item`，决定名称、类别和是否可烹饪 |
| `ItemSave.ItemCount` | 该堆物品数量 | 只有正整数数量才是有效库存堆 |
| `storage_furniture` | 静态数据库专用储物家具表 | 当前储物配置的权威来源；存储 `config_id` 和名称 |
| `container_counts` | 按容器类型统计的有效物品堆数量 | 用于网页和调试，不等同于物品总数量 |
| `storage_containers` | 所有识别出的储物实例及位置诊断 | 即使容器不计入库存，也保留 `other`/`unknown` 信息供排查 |
| `InventoryItem.source` | 物品堆的来源名称 | 区分主控背包、家具、工作台或兼容字段 |
| `InventoryItem.container` | 稳定的容器键 | 连接物品堆和容器来源，便于定位串库问题 |

## 5. 角色上下文解析

### 5.1 已验证的角色映射

| 角色 ID | 已观察名称 | `LeadingRole.AgentConfigId` | 家中槽位前缀 |
| ---: | --- | ---: | --- |
| 1 | `玩家-打工仔` | `1` | `HomeBuildingPos`、`Home_` |
| 2 | `玩家-大学生` | `1002` | `NeighborGirlBuildingPos` |
| 3 | `玩家-仓库管理员` | `1003` | `WarehousePos` |

上述名称是当前本地存档中已验证的精确名称。未知名称不做模糊匹配，不把相似字符串自动归入某个角色。

### 5.2 解析顺序

1. 读取并标准化 `LeadingRole.Name`。
2. 名称命中已验证映射，且没有与数字身份冲突时，使用名称对应的角色 ID。
3. 名称缺失、未知或与数字身份冲突时，按以下顺序回退：
   1. `GameSaveData.PlayerSelectId`
   2. `HistoryList.PlayerSelectId`
   3. `LeadingRole.AgentConfigId` 的已验证映射
4. 将角色名、最终角色 ID、主控配置 ID、家地图 ID、解析来源和诊断写入 `SaveRoleContext`。
5. 所有身份来源都不可用时，角色为 `unresolved`；不读取依赖角色槽位的 `ChapterAgentMap` 容器，但仍读取主控背包和工作台抽屉等直接来源。

### 5.3 冲突处理原则

角色名称不是无条件覆盖一切字段的强制常量。名称明确且数字字段缺失时可以直接采用；名称明确但和数字身份冲突时，必须降级到数字回退并输出诊断。这样可以发现存档字段不一致，而不是静默选择可能错误的槽位。

角色解析来源目前在网页中显示为：

- `leading_role_name`
- `game_save_player_select_id`
- `history_player_select_id`
- `leading_role_agent_config_id`
- `unresolved`

## 6. `ChapterAgentMap` 章节组选择

### 6.1 当前正式规则

`ChapterAgentMap` 的结构是：

```text
Dictionary<int, List<AgentSave>>
```

对外层整数键的选择按以下顺序处理：

1. 收集所有合法数字外层键。
2. 如果 `InitChapterId` 是正整数，并且该值存在于外层键集合中，选择同值外层键，来源记录为 `game_save_init_chapter_id`。
3. 如果 `InitChapterId` 缺失或不在键集合中，且角色已经解析，寻找同时满足“当前角色槽位 + `MapConfigIdHome`”的候选组。
4. 只有候选组唯一时才使用 `unique_role_slot_and_map` 回退。
5. 候选组有多个时，来源为 `ambiguous_role_slot_and_map`，不选择任何组。
6. 没有候选时，来源为 `unresolved`，不读取依赖章节组的容器。

当前明确禁止：

- 用 `resolved_player_select_id` 直接作为 `ChapterAgentMap` 外层键。
- 用 `MapConfigIdHome` 直接作为外层键。
- 用最大的外层键替代 `InitChapterId`。
- 因为某一外层键下有家地图容器，就把该组当成当前组。

选定一个外层键后，其他组的储物实例仍可以出现在 `storage_containers` 中，但位置只能是 `other`，其中的 `ItemList` 不会加入当前库存。这样既能避免串库，又能在网页中看到被排除的证据。

### 6.2 为什么不是角色 ID

角色 1、角色 2、角色 3 的实际样本都出现过外层键 `1`，因此外层键不可能稳定表示角色 ID。角色之间的家地图和槽位不同，外层键仍然可以重复。

当前角色 2 A/B 样本中，`InitChapterId=2`，外层键包含 `1、2、1000、1004`，并且受控交换物品只改变了键 `2` 下的两个容器。角色 1 当前样本也有 `InitChapterId=2`，外层键包含 `1、2、1000、1004、1005、1002`，程序选择键 `2` 后可以读到键 `2` 中的物品 `2130`（可乐）。这些证据支持“键 2 是当前章节组”，不支持“键 2 是角色 2”。

### 6.3 “键越大越新”的判断

目前不能使用外层键数值大小判断新旧。键 `1` 在当前样本中仍保留容器，说明旧章节或历史记录不会被删除；键 `2` 被 `InitChapterId=2` 指向，才是当前读取依据。`1000`、`1004` 等更大的键也没有因此成为当前组。

更准确的表述是：

> `InitChapterId` 是当前存档提供的章节选择证据；外层键是章节分组索引。数字大小没有被验证为时间顺序。

## 7. 储物家具与容器归属

### 7.1 静态储物配置

`codex_recipe.py` 从静态库的 `storage_furniture` 表读取家具配置。该表由当前本地游戏资源中的 `Config_Furniture` 生成：

```text
FurnitureFunc 包含 215  或  ShowStorage > 0
```

识别不依赖：

- `is_current` 图鉴可见性；
- 本地化名称；
- 是否恰好叫“冰箱”“冰柜”；
- 某一个固定的配置 ID列表。

当前本地资源重建结果为 85 条储物配置，检测到需要保留的非当前家具配置 `80062`。如果旧数据库没有 `storage_furniture` 表，才回退到旧的当前可见家具行；专用表存在但为空时，不重新引入旧表中的家具。

### 7.2 实例配置 ID

对一个 `AgentSave`，家具配置 ID按以下原则确定：

1. `BagFurnitureConfigId` 是已知储物配置时优先使用。
2. 否则使用 `AgentConfigId`。
3. 即使多个配置显示名称相同，也按配置 ID和实例 ID分别保留，不能按名称合并。

旧兼容 ID：

- `15000`：双开门冰箱，对应旧字段 `DoorBoxItems`。
- `15001`：冰柜，对应旧字段 `DoorBoxItems2`。

### 7.3 三重归属条件

一个 `ChapterAgentMap` 中的储物实例只有同时满足以下条件，才是当前角色的家中容器：

1. 所在外层键等于已选择的 `resolved_chapter_map_key`。
2. 实例 `MapConfigId` 与主控 `MapConfigIdHome` 一致。
3. `SlotPosPoint` 以当前角色对应的家中槽位前缀开头。

位置分类如下：

| 条件 | `location` | 是否计入库存 |
| --- | --- | --- |
| 章节组、地图和当前角色槽位均确认 | `home` | 是 |
| 章节组不一致 | `other` | 否 |
| 地图与家地图不一致 | `other` | 否 |
| 已知其他角色槽位 | `other` | 否 |
| 章节组、地图或槽位缺失，无法确认 | `unknown` | 否 |
| 未解析角色且依赖角色槽位 | 不选择章节组 | 否 |

空的 `SlotPosPoint` 不能仅因为地图相同就被当作家中容器。唯一保留的兼容例外是：角色已知、实例 `MapConfigId` 明确等于 `MapConfigIdHome`、当前章节组已选中，并且 `IsDoorBox == true`。这个例外只用于识别旧式门箱，不能绕过章节组和地图证据。

### 7.4 直接来源和兼容回退

始终按直接字段读取：

- `LeadingRole.ItemList`：主控背包。
- `WorkbenchDrawerItems`：工作台抽屉，作为家中直接容器，不依赖章节组。

章节容器读取：

- 选中的章节组中，所有通过储物配置和位置判断的 `home` 容器。
- 同名家具实例全部保留，来源和实例信息不丢失。

旧字段回退：

- 只对配置 ID `15000`、`15001` 使用 `DoorBoxItems`、`DoorBoxItems2`。
- 只有没有对应实际标记家具，且角色已经解析为已知角色时才使用。
- 实际家具与旧字段同时存在时，以实际家具为准，并记录冲突诊断。

明确忽略：

- `VehicleTrunkItems` 车辆后备箱。
- 没有储物行为配置的普通 `ChapterAgentMap` 条目。
- 邻居槽位、其他角色家中槽位、其他地图和其他章节组的容器。

## 8. 物品堆和输出层

### 8.1 原始物品读取

每个来源的 `ItemList` 都按以下规则处理：

- `ItemConfigId` 必须是正整数。
- `ItemCount` 必须是正整数。
- 同一物品在不同容器中的原始堆先保留来源和容器信息。
- 非法 ID或数量跳过，并追加诊断；数据库中找不到的物品在展示层报告未知并排除。

### 8.2 菜肴存档 JSON

每个存档的菜肴计划包含以下库存上下文：

```json
{
  "file_name": "Save_...bytes",
  "player_select_id": 2,
  "role_name": "玩家-大学生",
  "resolved_player_select_id": 2,
  "leading_role_config_id": 1002,
  "home_map_config_id": null,
  "role_resolution_source": "leading_role_name",
  "role_diagnostics": [],
  "resolved_chapter_map_key": 2,
  "chapter_resolution_source": "game_save_init_chapter_id",
  "chapter_diagnostics": [],
  "container_counts": {},
  "storage_containers": [],
  "inventory": [],
  "diagnostics": []
}
```

上面是字段形状示例，`home_map_config_id`、容器和物品内容必须以实际存档为准，不能把示例值当成固定值。

`storage_containers` 的每个元素保留：

- 配置 ID和名称；
- 实例 ID；
- 实例 `MapConfigId`；
- 主控 `home_map_config_id`；
- `chapter_map_key`；
- 实例 `ChapterId`；
- `slot_pos_point`；
- `location`、`location_label`、`is_home`；
- 物品堆数量。

网页通过 `/api/recipe-plans` 显示角色名、角色解析来源、章节组来源和键，以及容器位置和诊断。`RECIPE_PLAN_CACHE_VERSION` 当前为 `6`，库存输入或 JSON 上下文发生变化时必须递增，避免继续使用旧库存结果。

## 9. 历史实现与问题演变

| 提交 | 阶段 | 当时做法或暴露问题 | 后续修正 |
| --- | --- | --- | --- |
| `da07400` | 统一图鉴筛选与冰箱库存 | 初始将主控背包与冰箱/冰柜接入菜肴库存；储物配置范围有限，早期依赖名称或固定映射。后续检查发现旧静态配置只覆盖约 14 组储物家具，无法覆盖所有有效家具。 | 扩展为基于配置行为的储物表，并保留兼容字段。 |
| `d88af81` | 收紧菜肴库存与近匹配 | 主要修正 `SpecificItems`、`TagCombo`、特色菜优先和近匹配语义；这些不是容器来源问题。 | 后续库存修正必须避免误改下游匹配。 |
| `ee8d5b8` | 读取家中全部储物容器 | 从只读冰箱/冰柜扩展为读取家中的全部储物容器，加入容器位置和实例诊断，以及工作台抽屉。 | 继续加强家具配置和地图/槽位证据。 |
| `4d4a850` | 重建储藏容器与筛选逻辑 | 发现仅按名称、固定家具或宽松地图条件会把历史、邻居或同名容器纳入库存。 | 改为配置行为、地图、槽位联合判断；空槽位不再仅凭地图视为家中。 |
| `947c869` | 按存档角色补齐库存 | `LeadingRole.Name` 未被读取；角色 1/2/3 家中槽位不同；旧静态表漏掉角色 1 的 `2130` 和角色 2 的 `2152`/配置 `80062` 等来源。 | 建立角色上下文、角色槽位映射和完整 `storage_furniture` 权威表。 |
| `e7a5f39` | 按章节分组隔离库存 | 多个外层键都包含家中容器，直接按角色或最大键选择会串入旧章节记录。 | 捕获 `InitChapterId`，优先选择对应章节组；增加章节来源诊断并将缓存版本升至 6。 |

历史修正反映出一个固定原则：库存来源的每次扩展都必须同步回答“这是哪个角色、哪个章节组、哪张地图、哪个槽位、哪个容器实例”，不能只增加一个物品列表字段。

## 10. 实际存档证据

### 10.1 角色 2 受控 A/B 对比

样本位于项目测试目录，使用脱敏相对路径表示：

- A：`test/Save_2026_08_24_08_48_30.bytes`
- B：`test/Save_2026_08_24_08_48_30.bytes_2`

两份文件的共同上下文：

| 字段 | 值 |
| --- | --- |
| `LeadingRole.Name` | `玩家-大学生` |
| `PlayerSelectId` | `2` |
| `InitChapterId` | `2` |
| `ChapterAgentMap` 外层键 | `1、2、1000、1004` |
| 角色家槽位 | `NeighborGirlBuildingPos...` |

用户只交换了冰柜和豪华版双门冰箱中的两个物品，其他物品未动：

| 章节组 / 容器 | A | B |
| --- | --- | --- |
| 键 `2` / 冰柜 `15001` | 冻干草莓 `2152` | 鸽子 |
| 键 `2` / 豪华版双门冰箱 `80062` | 鸽子 | 冻干草莓 `2152` |
| 键 `1` | 未发生对应交换变化 | 未发生对应交换变化 |

当前解析器选择键 `2`，并将键 `2` 下符合地图和角色槽位的两个容器标为 `home`；键 `1` 下的容器可保留为 `other`，其中物品不进入库存。

结论：

- `[已验证]` 受控物品交换发生在键 `2` 的对应容器中。
- `[已验证]` `InitChapterId=2` 能稳定选择当前应读取的组。
- `[已验证]` 配置 `80062` 必须进入储物家具表，即使它不是当前图鉴可见配置。
- `[推断]` 键 `1` 是保留的旧章节/历史分组；具体的写入和清理生命周期仍需游戏方法体或更多受控样本证明。

### 10.2 角色 1 当前样本

实际本机保存目录中的两个样本记录为：

- `Save_2026_08_20_16_03_52.bytes`
- `Save_2026_08_25_23_32_05.bytes`

共同观察结果：

| 字段 | 值 |
| --- | --- |
| `LeadingRole.Name` | `玩家-打工仔` |
| `PlayerSelectId` | `1` |
| `InitChapterId` | `2` |
| `ChapterAgentMap` 外层键 | `1、2、1000、1004、1005、1002` |
| 当前选择组 | 键 `2` |
| 关键物品 | `2130`（可乐）可从当前组读到 |

键 `1` 和键 `2` 都可能含有角色 1 家中槽位样式的容器，但当前规则只把键 `2` 的容器计入库存。这是“容器存在”与“容器属于当前活动章节”的区别。

### 10.3 旧格式角色 1/2/3 样本

项目测试目录 `test/SLGame/Saves` 中的旧样本为：

- `Save_2026_08_22_00_54_43.bytes`
- `Save_2026_08_22_01_53_43.bytes`
- `Save_2026_08_22_02_58_43.bytes`

当时按取证 schema 分别对应角色 1、2、3；三份样本都出现过 `ChapterAgentMap` 外层键 `[1]`。这些文件使用旧的根对象、`AgentSave`、`ItemSave` 成员数量（约 `54/115/15`），不能把旧取证读取结果直接当成当前生产 schema 的完整兼容证明。

结论：

- `[已验证]` 外层键 `1` 不能代表角色 1，因为角色 2、3 的旧样本也出现键 `1`。
- `[已验证]` 外层键不是稳定的角色槽位编号。
- `[未确认]` 旧格式中是否也存在与当前 `InitChapterId` 完全相同的选择字段，需要单独补充兼容 schema 和样本验证。

### 10.4 最初错误页面的记录

在容器隔离修正前，页面曾显示以下库存结果：

```text
番茄 x 2
金针菇 x 2
草莓 x 3
菠菜 x 2
白玉菇 x 1
玉米 x 2
花椰菜 x 1
卷心菜 x 1
可乐 x 6
冻干草莓 x 1
西瓜 x 1
胡萝卜 x 1
南瓜 x 1
火腿肠 x 6
精制碘盐 x 1
即食燕麦片 x 1
生态香米 x 1
白砂糖 x 1
午餐肉罐头 x 2
```

用户实际检查到的角色 2 主要容器内容包括：

- 冰柜：精制碘盐、冻干草莓、黄酒、胡萝卜、茄子 `x4`、黄瓜 `x3`、火腿肠 `x5` 等。
- 豪华版双门冰箱：野兔、豆豉辣酱、火腿肠 `x3`、韭菜 `x4`、冷冻青豆、鸽子等。

这组记录用于回归对照，不直接证明每个页面差异的唯一原因。后续必须同时输出角色、章节组、容器实例和物品来源，才能区分“容器没读到”“读到了但被位置排除”“物品不在食品配置”三类问题。

## 11. 诊断和接口契约

### 11.1 `SaveRoleContext`

当前后端上下文字段为：

```text
role_name
resolved_player_select_id
leading_role_config_id
home_map_config_id
resolution_source
diagnostics
resolved_chapter_map_key
chapter_resolution_source
chapter_diagnostics
```

角色诊断和章节诊断必须保留原始原因，例如名称缺失、名称未知、名称与数字身份冲突、`InitChapterId` 不在键集合、候选组不唯一等。不能只输出最终的角色 ID或容器数量。

### 11.2 `StorageContainer`

每个识别出的储物实例必须至少能回答：

```text
配置是什么？实例是谁？来自哪个外层键？实例在哪张地图？
主控家地图是什么？槽位是什么？位置判定是什么？里面有多少物品堆？
```

因此必须保留 `config_id`、`name`、`instance_id`、`map_config_id`、`home_map_config_id`、`chapter_map_key`、`chapter_id`、`slot_pos_point`、`location`、`is_home` 和 `item_stack_count`。

### 11.3 缓存

菜肴计划缓存签名包含：

- `RECIPE_PLAN_CACHE_VERSION`；
- `HistorySave` 文件签名；
- 直接子存档和 `.bak` 文件签名；
- 游戏版本、数据库 schema 和导入时间。

只要库存来源、容器判定或 JSON 上下文发生变化，就必须递增计划缓存版本。当前基线版本为 `6`。

## 12. 测试与验证基线

### 12.1 单元测试覆盖

当前 `tests/test_save_inventory.py` 已覆盖：

- 标记家具优先于旧字段回退。
- 未知物品、非法数量和空列表诊断。
- `FurnitureFunc=215`、`ShowStorage>0` 和无关家具排除。
- 同名家具配置和多个实例分别读取。
- `BagFurnitureConfigId` 与 `AgentConfigId` 优先级。
- 角色 1/2/3 的槽位前缀隔离。
- 角色名成功解析、未知名称回退、名称缺失回退、名称冲突回退、无法解析。
- 空槽位、地图不一致、已知其他角色槽位和未知槽位。
- `InitChapterId` 选择章节组且不依赖角色 ID。
- `IsDoorBox` 兼容识别、旧字段映射和工作台抽屉。

当前 `tests/test_recipe.py` 和 `tests/test_recipe_signature.py` 已覆盖：

- 专用 `storage_furniture` 表权威读取。
- 非 `is_current` 的储物配置仍被保留。
- 旧数据库缺表时兼容回退。
- 库存展示与菜肴匹配对 `InCodex` 的不同要求。
- 同一物品跨多个来源的合并和缓存失效。

### 12.2 已完成验证

截至本记录对应的代码基线，已完成：

- 64 项 Python 单元测试。
- 主要 Python 模块 `py_compile`。
- `web/app.js` 语法检查。
- 当前游戏资源的默认七类导出和七个单分类入口。
- SQLite 静态数据库构建，包含 85 条储物家具配置。
- 网页服务 `/api/state` 和 `/api/recipe-plans` 返回 200。
- 三个实际子存档可被解析，并输出角色和章节上下文。
- `git diff --check` 通过。

文档变更本身完成后仍需再次执行 `git diff --check`，并确认没有代码、数据库、存档或游戏资源变更。

## 13. 已知限制和未确认语义

1. 本地 IL2CPP dump 已确认 `InitChapterId` 是 `GameSaveData` 的实际序列化字段，`ChapterAgentMap` 的实际类型是 `Dictionary<int,List<AgentSave>>`，但没有可用的方法体，无法直接证明游戏如何创建、复制和清理每个外层分组。
2. A/B 对比能证明当前活动物品变化与键 `2` 相关，并和 `InitChapterId=2` 一致，但不能仅凭一次对比完整证明所有章节切换生命周期。
3. `AgentSave.ChapterId` 已被读取并输出，但目前不能替代 `InitChapterId` 选择外层组。
4. 外层键的数字大小规律没有被验证为保存时间顺序；任何“取最大键”方案都属于未经证实的猜测。
5. 旧格式 `54/115/15` 样本的取证读取，不等于当前生产解析器已经支持该格式。若要正式兼容，必须增加明确 schema、成员数量和 EOF 测试。
6. 当前三名角色的名称和槽位映射来自本地已验证样本，不应对未知角色名称进行推断或模糊匹配。

## 14. 后续修改检查清单

### 修改前

- [ ] 确认问题是库存来源、容器归属、物品配置，还是下游菜肴匹配。
- [ ] 使用存档副本做实验，原始存档只读。
- [ ] 先输出 `LeadingRole.Name`、三个身份字段、`MapConfigIdHome`、`InitChapterId` 和全部外层键。
- [ ] 按外层键列出储物配置 ID、实例 ID、实例地图、槽位、`ChapterId` 和物品堆。
- [ ] 不把外层键当作角色 ID、地图 ID或新旧排序。

### 修改中

- [ ] 新增字段时保持完整 wire 读取和严格 EOF 校验。
- [ ] 新容器配置优先从 `Config_Furniture` 行为字段确认，不用本地化名称猜测。
- [ ] 容器位置必须同时使用章节组、地图和角色槽位证据。
- [ ] 无法确认时保留诊断并跳过库存，不静默纳入。
- [ ] 保持背包、工作台抽屉、实际家具和旧字段回退的来源边界。
- [ ] 不修改 `SpecificItems`、`TagCombo`、档位和近匹配逻辑来掩盖库存来源错误。
- [ ] 库存来源语义或 JSON 变化时递增 `RECIPE_PLAN_CACHE_VERSION`。

### 修改后

- [ ] 增加对应的最小单元测试和至少一个实际存档回归样本。
- [ ] 对可控物品做 A/B 交换，确认变化只出现在预期章节组和容器实例。
- [ ] 检查角色 1/2/3 家中容器互不串用。
- [ ] 检查其他章节组、其他地图、邻居槽位、空槽位和车辆后备箱仍被排除。
- [ ] 检查网页显示角色名、解析来源、章节键、容器位置和诊断。
- [ ] 执行 Python 编译、单元测试、导出、SQLite 构建、网页接口和 `git diff --check`。
- [ ] 确认 Git diff 只包含明确的代码/文档目标，没有游戏文件、存档或数据库副作用。

## 15. 变更记录

| 日期 | 内容 |
| --- | --- |
| 2026-08-29 | 创建本记录，整理角色隔离、章节组选择、储物配置、A/B 存档证据和后续排查规则。 |
