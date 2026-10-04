# Survival Log 图鉴离线解析说明

## GitHub Pages 静态浏览

在线图鉴、补给推荐和独立详情页支持简体中文与 English。`pages/i18n.js` 共用 `pages/locales/en.json` 的界面词条、参数化文案与数字格式；语言优先级为 URL `lang`、本机语言偏好、浏览器语言，未知语言回退简体中文。切换不改变条目 ID、品质键、已选材料或筛选条件；跨页面链接携带语言。配置键和关联 ID 保留原样，未提供或存在歧义的英文文本回退中文，手动成就攻略尚未翻译。

`codex_pages_i18n.py` 只读提取本地 `LocalTxt/Main.bytes` 和 `LocalTxt/English.bytes`，按 MemoryPack 字符串字典严格验证条目数量、非空唯一键和 EOF。仅将当前公开网页用到的文本写入 `pages/locales/game-en.json`，不导出完整语言表、资源包或私人数据。刷新命令为 `python codex_pages_i18n.py --game-root "游戏目录" --output-dir pages/locales`；Pages 构建与 CI 直接复制已生成的公开语言文件，无需安装游戏。

烹饪食材按 `Config_ItemSubCategory` 提供分类按钮与数量，支持分类和高/中/低档组合筛选；没有参与档位规则的分类明确显示“不影响档位”。列表名称旁以颜色和文字同时标明档位。菜肴食材选择器同样支持分类、档位筛选与图标卡片，重复点击仍按独立用量累计。小视口允许页面滚动，保持结果列表有足够空间。

烹饪食材的“仅可种植 / 捕捉”筛选以当前条目的 `sources` 中存在 `plant` 或 `prey` 关联为准，与分类、档位、搜索、标签和属性条件取交集；重置清除该条件，其他分区不应用它。浏览提示仅保留标题旁的问号图标，点击展开、点外部或按 Escape 收起，保留中英文可访问名称。

种植手册从公开 `Config_Plant` 导出空间、光照需求、耐寒与基础生长时间，优先以 `Gain` / `Perfect_Gain` 对应的食物图标显示植物；图片注明收获物名称，无已提取图标时仍用分类占位。食材详情按收获物 ID 反查种植入口，食品/猎物共享条目增加猎物分类入口，独立详情页保留相同链接，不推断未解析的陷阱、掉落或野外采集来源。

只读核对本地 `1.1.18293 / catalog 2.3.1` 的 `Config_Plant`、`Config_FurniturePlant`、`Config_Furniture` 严格读取及 EOF，确认静态库相应行完全一致。当前游戏 `PlantPanel.html` 的 `checkSeedEnv` 使用 `actualLight >= lightNeed` 与 `coldStress <= coldResistance`；容量判定为植物 `Size <= Capacity`，种满用量为 `floor(Capacity / Size)`。寒冷是游戏环境数值，不转换成摄氏温度。容器下拉只收录公开家具，通过 `PlantFurnitureID` 解析被动 `AddLight` / `AddHeat`，通电时计入 `ElectricLight` / `ElectricHeat`。

`codex_pages_environment.py` 使用集中 schema，只读提取 `Config_Weather`（11 字段）、`Config_EnvArea`（6 字段）、`Config_EnvAreaWeather`（5 字段）、`Config_MapRoom`（5 字段）和供暖家具，验证成员数量、字段类型和 EOF。字段类型和顺序来自当前本地 IL2CPP 元数据；新增 schema 不改变六类注册表或默认辅助导出范围。刷新命令为 `python codex_pages_environment.py --game-root "游戏目录" --output pages/planting-environment.json`。版本化文件仅包含当前页面使用的天气、楼层、区域参数、供暖值和 `RoomTemp_Max`，没有游戏路径、原始资源或 runtime 状态。Pages 构建仅在预设版本与静态库版本一致时嵌入环境；否则提示手动输入，不套用其他版本数值。

核对当前 native `EnvAreaHelper.GetLightMul` / `GetAreaTemperature` / `GetParamRow`（RVA `0x305C1F0` / `0x305BB90` / `0x305C5C0`）与 `PlantComponent.EvaluateEnvironment`（RVA `0x2DF7650`）：区域参数优先匹配当前天气 ID，回退 `WeatherID=0`；有效光照为天气 `LightValue × LightMul + 容器补光`；有效寒冷为 `max(0, ColdValue − 区域温度 − 容器加热)`。区域温度包含 `TempAdd` 与同一区域运行设备的 `HeatOutput`，区域 `DeviceHeat=false` 时不计设备；`RoomTemp_Max>0` 才限制区域温度，当前为 0。空调 ID 21007 供暖 2，燃料暖炉 ID 65001 供暖 1，未运行时不计。地下室对应区域 5（光照倍率 0、保温 2），一楼区域 1（0.5、1），二楼室内按区域 2 / 阳光房（1、1），二楼露台区域 3（1、0、不接受设备供暖）；所选楼层对应 `Config_MapRoom` 行的光照和保温与区域默认参数交叉校验。晴天、阴天、雨天分别使用 native 天气行 1/2/3，无寒潮至重度寒潮的晴天为 1/7/8/9、阴天为 2/4/5/6、雨天为 3/15/16/17；寒雨光照为 0，不把普通雨天光照 1 直接叠加寒潮。

种植手册默认显示当前满足环境的植物，取消“只看当前可种”显示全部及空间、光照、寒冷不满足的原因。未选容器时明确提示尚未核对空间。条件保存在本机，切换分类、语言和刷新保留；重置恢复晴天、无寒潮、一楼和无运行供暖设备。手动环境值替代天气、楼层和供暖计算，容器加成仍单独应用，空值不核对该项。预设仅计同区域一台运行空调和一台燃烧暖炉，未叠加植物天赋、种子库存、灾前限制、后续天气、生长速度、温室承诺和其他供暖来源；多设备或特殊区域可手动填写。截图的角色个人抗寒属于体感档位，不作为植物抗寒加成。用户重度寒潮截图验证光照 1、寒冷 3，一楼空调后光照 0.5、寒冷 0；普通小型花盆在地下室寒冷 1，草菇耐寒 0 不满足，移至一楼空调制热后满足。

植物默认按普通 `Gain` 是否含 `Config_Item.Category=1` 的食用收获优先，再按基础 `GrowthTime` 升序，空间和 ID 打破并列；另可按最快基础收获、最省空间、最高耐寒、最低光照需求或原图鉴顺序排列。非图鉴排序在显示全部时将当前满足条件的植物排在前面，未知数值放在末尾。基础生长时长没有冒充实际收获倒计时。食用、其他收获在卡片中标明，不使用完美产物或返种猜测用途。

`codex_pages.py` 以 SQLite `mode=ro` 读取仓库已公开的静态配置库，使用现有字段标签和详情格式器生成 `pages/` 的独立浏览网页。构建不访问游戏安装目录，不附加 runtime 库，不读取存档；导出保留当前条目、六类映射、成就（含隐藏成就）、原始关联 ID 和配置字段。元数据仅允许导出游戏版本和数据库 schema 版本，不发布游戏目录、存档路径、完成状态或缓存。

在线版提供名称/ID、菜肴食材选择和制造/家具材料检索，并使用相对路径适配 Pages 项目子目录。食品展示 `ValueDisplay1..5` 的饱腹、心态、精力、健康、生命值，数值全部来自当前跟踪的静态库。默认只展示非零属性，负数保留，缺失属性显示未提供；详情可展开完整五项。物品信息同时展示配置重量、尺寸、使用次数和基础保质期，不将静态保质期冒充实例剩余时间或冷藏时间。

菜肴通过 `PerfectItemID`、`GoodItemID`、`NormalItemID`、`FailItemID` 引用静态库 `recipe_items` 中的成品，按品质展示五维属性和 `ItemDes2_Local` 食用说明，不使用配方的 `SatietyStandard` 冒充食用效果。只导出被引用成品的属性、标签、分类、说明和图标，不发布 `recipe_items` 全集。页面支持标签/可烹饪/正属性筛选和属性降序；食品、菜肴和猎物默认按当前显示品质的每次饱食降序，重置恢复该默认值；种植排序见上文，其余分类保留图鉴顺序。菜肴“仅专用菜谱”只保留有具体食材关系的配方，查询多个食材时仍逐槽位匹配重复用量；未输入食材时显示所有专用配方。食材关联菜肴以具体物品 ID 或烹饪子分类识别，分类匹配仅表示可以占用该类槽位，不能据此声称完整组合必定能做出该菜肴；仍需满足其余食材、档位和特色配方优先规则。

只读核对当前游戏 `ItemDetailPopup.html`、IL2CPP 元数据和 `Config_ConstantText` 后，确认物品弹窗显示分类、子分类、`FoodTag1`（食用方式）与 `FoodTag2`（食物特点）。标签来自 `FoodTag1_n` / `FoodTag2_n` 的本地化文本，分别生成辅助表 `FoodTag1` / `FoodTag2`；相同数字不能跨字段合并。`FoodTag1=3` 是“熟食”，不是“蛋奶”；“蛋奶”来自食材分类表 `Config_FoodType`，旧网页错误地用该表解析食用标签。`FoodTag3` 保留原始 ID，不用于弹窗标签；未知标签显示 `ID:xxxx`。`SubCategory` 单独经 `Config_ItemSubCategory` 解析。网页展示“优良”，内部品质键仍保留 `良好` 以兼容现有数据。

菜肴的“我想用这些材料”支持搜索后选择实际食材或任意分类，重复添加按份数占用独立槽位；烹饪等级按 `MinLevel` 筛选可制作的配方。每种食材的档位复用本地 `Config_GlobalSetting` 的分类价格阈值，组合取参与计算食材中的最高档，可手动选择中档/高档保底。未选满时列出可补齐槽位与档位的候选，完整具体组合先匹配 `SpecificItems`，再匹配同档位 `TagCombo`，相同分类组合与档位使用最小配方 ID。茶树菇和白玉菇为低档，松茸为高档，灵芝为中档；灵芝参与的高档结果仍需其他高档食材或保底。野鸡新增专用配方“野鸡炖蘑菇”，指定野鸡与平菇。

当前版本只读核对 `CookingTierResolver.Resolve`、`ResolveIngredientTier`、`GameKey` 阈值 getter 和烹饪 UI 的 `ResolvePredictionTier` / `SelectBestMatchedRecipe`：食材档位按整件 `price` 判断，阈值包含等号，不按每次价格、食材档位总和、平均值或全部达到某档判断。蔬菜高/中档阈值为 30/16，菌菇为 15/6，鱼类为 150/50。花椰菜价格 30 是高档，因此猪五花/小家鼠 + 花椰菜 + 灵芝/白玉菇均可匹配高档山野三鲜；生态香米 + 花椰菜 + 小家鼠匹配招牌盖饭。负鼠、胡萝卜、纯牛奶均为中档，组合匹配蛋肉菜炒。冷冻野生虾价格 100 为中档，配中档灵芝为菌菇鱼汤，配高档松茸为山海菌鱼汤。`GetCookTagTierFloorRank` 从当前 `AE_CookTagTierFloor` 状态效果取得保底，不是“三个中档”的额外条件。

菜肴页面增加“按冰箱食材配餐”，与指定材料逐槽位查询分别保留选择。手动登记任意数量食材种类和剩余可烹饪用量，多个冰箱可合并登记；数量是物品栏剩余使用次数，例如野兔 2/3 填 2，不是整件数。登记以 `survival-log-pantry-v1` 保存在本机，不读取存档或上传库存。按实际数量枚举指定配方和通用分类组合，排除被完整指定配方抢先匹配的通用组合；同分类重复用量不超过登记库存，每道菜独立比较，不预留或扣减共享食材。选择饱腹、心态、精力、健康或生命排序时，对每道通用菜推荐该目标恢复最高的实际组合，再以每锅总属性比较菜肴；详情同时显示具体材料、每锅总恢复、分份次数与每次食用效果。品质为所选情景，不推断成功率，不叠加角色、状态或设施效果。

在线浏览将食品按 `CanCook` 分为烹饪食材（130）和即食食品（61）；这只是浏览分区，不修改原六类分类注册表、食品/猎物映射或数据库。旧 `#food/物品键` 链接会自动进入正确分区，既有 `/guide/food/ID/` 详情地址保留。`Config_Item.UseTimes` 用作食品每份的配置使用次数，`CantUse` 用于区别不可直接食用；缺失值显示未提供，不默认填 1。生态香米每份 7 次，90 压缩饼干每份 10 次。页面与静态详情采用游戏物品栏的深灰、暖棕与金黄视觉，次数统一以白色数字显示在物品图标左下角；这是整份可用总次数，不模拟库存剩余量。菜肴次数随品质切换，通用配方标为“可变”，未知配置标为“—”。各品质详情分别展示对应次数。

菜肴成品的配置 `UseTimes` 不能直接当作实际可吃次数。只读核对当前 `1.1.18293` 的 IL2CPP v31 元数据与 native 方法确认：`ItemValueDisplayHelper.GetEffectiveMaxUseTimes` 优先使用实例 `MaxUseTimes`，否则回退配置 `UseTimes`；`SettleCookingResult` 将配方 `SatietyStandard` 传给 `CookingFormula.CalcSplit`。`CalcProductVD` 对固定食材配方取成品配置五项属性并分别向上取整；通用配方按参与食材、档位、品质与基础饱食奖励计算整份属性。`CalcSplit` 在总饱食超过正阈值时执行 float32 除法并向上取整，至少 1 份，之后按份数分摊五项属性。固定配方据此导出 `serving_count` 和 `per_use_stats`，同时保留原始 `stats`；佛跳墙完美/良好各 2 次，普通/失败各 1 次。通用配方不发布伪固定次数，显示配置参考属性、分份标准和总饱食计算入口。配置阈值或成品属性缺失时不猜测。

再次核对 `CookingFormula.CalcProductVD` / `CalcSplit`：通用配方仅合计投入食材的 `ValueDisplay1/4/5`（饱腹/健康/生命），乘档位系数高 1.7、中 1.4、低 1.1，再乘品质系数失败 0.5、普通 0.9、良好 1.2、完美 1.5；只有饱腹额外加 `用量数 × 2`，最后分别向上取整。心态、精力直接取对应品质的成品配置并向上取整，不合计食材这两项。重复物品按参与次数加权，乘加步骤和分份使用 float32；分份优先取配方正 `SatietyStandard`，否则使用全局 `CookingSatiety_SplitThreshold`。`codex_pages_cooking.py` 严格读取本地 catalog 与 `Config_GlobalSetting` 后，仅导出上述参数到 `pages/cooking-model.json`；公开模型与静态库游戏版本必须一致，否则不推荐无法确定效果的通用组合。未指定真实材料时仍显示配置参考效果，不把参考值当成具体组合产量。

无 `TagCombo` 条件的兜底菜肴在 `SettleCookingResult` 的兜底分支同样按 `isExact=true` 使用配置属性，按固定属性计算次数；字段本身缺失时不假定为兜底。正式数据的黑暗料理由此显示可吃 1 次，而不是伪标为随食材变化。

本次将正式解析器、七份导出和静态库统一更新至当前本地版本。新版元数据确认 `Config_Item` 在 `UseAction` 前增加 `TradeSellRate: Single`（61 字段）；`Config_PlantLv` 末尾增加 `unlock_recipes: List<int>`（11 字段）；`Config_Furniture` 末尾增加 `BagAcceptCategory`、`RobotPlayerID`（59 字段）；`Config_FurnitureTag` 增加排序、维度及说明字段（10 字段）。`Config_ConstantText` 按三个字符串字段严格读取，验证非空唯一键和 EOF，仅提取食用标签进入导出，不公开完整常量表。所有配置保留对象成员数量与 EOF 校验，不静默兼容未知 schema。

`codex_pages_icons.py` 是独立的只读图标提取工具，复用现有 catalog EOF 验证与 bundle 名称/hash 定位、解密流程，只处理当前公开图鉴条目、成就及其菜肴成品、植物收获物、普通制造产物所引用的图标。生成带透明背景的 PNG 缩略图及只含游戏版本和图标文件名的清单；没有有效纹理的资源记录为缺失，网页使用分类符号占位。本次图标与静态库均来自本机游戏 `1.1.18293 / catalog 2.3.1`，图片不用于替换数值来源。Pages 构建只复制有公开引用的图标，工作流不读取游戏。

本地 catalog 中部分动物图标存在路径，但 bundle 的容器指针为零，无法解引用。提取器对缺失引用按同一配置的 `WebIcon`、`ICON` 或 `WebSmallIcon` 回退到游戏自带 `WebUI/Res` PNG，不按名称猜测、不访问网络。仅允许当前公开引用涉及的 Food、Furniture、Structure、Material、Literature、icon、Consumable、Electrical、RobotModule 目录中的单层 PNG 文件，拒绝越界与文件符号链接。回退图片同样缩放至最长边 192、保留透明通道，沿用配置图标路径的哈希文件名；清单的 `web_ui_icons` 仅记录回退图标文件名，不泄露本机路径。

家具使用配置 `ICON`，成就使用 `WebIcon`；制造使用 `ProductID` 中第一个有图标的普通产物，并注明“制造产物”，不借用失败产物、完美额外产物或材料图标。植物沿用实际收获物图片，花卉共用图片时遵循游戏配置。上述图片同时用于交互列表、详情与独立 HTML / 分享信息；不更改图鉴分类、成就说明或条目数量。

当前公开植物、制造、家具、成就的缺图数均为零；新增补齐植物 9、制造 163、家具 110、成就 93 条，实际发布使用 1039 张去重图标。图片字段与普通产物 ID 已逐项对照本地严格读取的配置表；发布构建仍只复制当前网页引用的图片。

`codex_pages_seo.py` 从同一公开导出数据生成独立 HTML 详情。导航统一进入首页查询图鉴和补给推荐；旧 `/guide/` 和分类目录地址仅保留自动跳转到首页或对应查询分类的兼容页面，标为 `noindex,follow`，不再生成另一套目录列表。属性、标签、各品质效果、材料关联及成就说明直接存在于独立详情 HTML，不依赖 JavaScript 抓取；首页禁用 JavaScript 时在原页面提供可展开的条目链接。食品与猎物共享条目只生成首个分类下的详情地址，其他分类链接到该页。各页包含独立标题、描述、canonical、Open Graph / Twitter 信息和 WebPage / CollectionPage / BreadcrumbList JSON-LD；游戏菜肴不使用现实食谱的 Recipe 类型。`sitemap.xml` 仅列出首页、补给推荐及独立详情的完整网址，不收录兼容跳转页，不包含交互图鉴的 hash 状态，不虚构更新时间。

新增 `--site-url` 指定站点的 HTTP(S) 根网址（默认当前在线版），生成 canonical、分享及站点地图地址；参数拒绝片段、查询、登录信息和相对路径段，写入前检查所有页面目标中的符号链接。Actions 默认按仓库生成项目 Pages 网址，仓库变量 `PAGES_SITE_URL` 可覆盖自定义域名和用户主页地址。项目子目录中的 `robots.txt` 不能控制域名根的抓取规则，因此不生成；首页条目链接和站点地图提供发现入口，提交到站长平台属于独立操作。

个人完成状态和库存匹配仍属于本地版；在线数据只随仓库静态库及网页工作流更新。输出目录只覆盖网页资源、被引用的图标、`data.json`、`.nojekyll`、`sitemap.xml`、`recommendations/` 推荐页和当前 `guide/` 页面，保留其他文件；schema 不匹配时构建报错。部署流程见 `.github/workflows/pages.yml`。

### 补给推荐

`codex_pages_recommendations.py` 只使用本次只读构建已获取的静态条目、引用物品和公开字段，生成 `/recommendations/`。不修改解析器、六类映射或数据库，不引入库存、存档和商店运行时数据。推荐数据按字段白名单嵌入推荐页，不复制到主图鉴 `data.json`；页面沿用游戏物品栏风格和图标左下角次数，包含独立 SEO、canonical 与站点地图入口。无需 JavaScript 也可阅读默认前期、普通品质排行和完整方法说明；交互支持阶段、品质、仅本阶段配方、保质值、名称/食材与排序，查询条件保留在网址中。

囤货按整包基价、`ValueDisplay1 × UseTimes`、背包 `Size` 乘积和基础 `Life` 比较；保质只使用正配置值，不猜测时间单位或冷藏修正。食材一份用量的经济模型为 `price / UseTimes`，固定配方重复 `SpecificItems` 计为重复消耗用量；每锅摊销成本按用量相加，从零购买金额按每种食材所需整包数向上取整，两种成本同时展示。固定配方沿用已核对的五项向上取整与分份规则，每锅一件成品、多次食用，不能再次将次数乘入整锅属性。饱食增量扣除输入各用量的原始饱食。通用配方不使用成品参考属性计算固定总产量或成本；零价、未知次数、缺失属性和兜底结果不作为零成本高分推荐。

阶段按 `MinLevel ≤ 1/2/3` 对应前中后期，默认包含之前等级，品质仅作为普通/良好/完美情景。固定菜肴评分权重为饱食/摊销价 50%、饱食/烹饪小时 20%、饱食增量/摊销价 15%、辅助恢复/摊销价 15%；即食囤货为饱食/基价 50%、保质 25%、饱食/背包格 15%、辅助恢复/基价 10%；烹饪备料为单次用量价格优势 35%、保质 25%、当前阶段可计分固定配方覆盖 25%、最佳关联菜肴指数 15%。辅助恢复权重依次为心态 1、精力 0.5、健康 1、生命 0.5；负面恢复额外按 2/1/3/2 加权除以总饱食扣分，最高 30。各项按同类、同阶段、同品质有效候选的中位并列百分位转成相对分；单一候选为 50，全部非负指标的零收益为 0，搜索和排序不改变评分池。综合分在 0—100 内，表示本站比较模型，不是成功概率。

植物 `Gain` 重复 ID 计普通基础数量，每物品乘 `UseTimes` 得到可选的原始食用饱食或烹饪用量，二者不相加。按 `GrowthTime/86400 × Size` 归一化，评分为单位尺寸每日基础饱食 40%、烹饪用量 35%、当前阶段固定配方覆盖 25%；不推断实际设施容量，不计完美收获、返种、种植等级和设施加成，不从 `HarvestTime` 猜测无限重复收获。返种配置概率仅作明细。当前跟踪库在普通品质下可计分即食 46；前/中/后期备料 82/115/121、固定菜肴 93/256/405；食物类基础收获作物 29。配置价格、基础属性与静态库版本一致，不模拟商店库存、角色、额外效果、饱食溢出、燃料和行动成本。

## 成就模块（当前实现）

手动导入成就时，当前资源中的 `Config_Achievement` 按 21 字段 MemoryPack schema 读取，并以配置 ID 为主键写入静态库 `achievements` 表；`achievement_conditions.json` 保存全部成就的分类、完成条件、完成方法、数值门槛、角色限制、排除项、配置引用和注意事项。条件文件的 `source_version` 仅记录人工整理时参考的资源版本，不参与自动更新版本判断；手动导入仍校验 ID 集合、名称和隐藏标记。自动更新六类图鉴时跳过 `Config_Achievement` 和条件文件，保留已有成就内容及完成状态。

当前本地资源中有尚未补入条件说明文件的成就，完整手动重建静态库会在 ID 集合严格校验处报错。六类自动更新路径 `refresh_achievements=False` 可正常构建并保留已有成就；公开网页继续使用已跟踪静态库中的人工成就说明。

成就完成状态只读取 `HistorySave.bytes` 的全局 `HistoryData.UnlockedAchievementIds`，不按 `Save_*.bytes` 子存档区分。当前配置中未出现的已解锁 ID 只写入诊断；旧存档无法确认该字段时，以及主存档和 `.bak` 都无法读取时，保留上一次有效成就状态。成就使用 runtime 的 `achievement_completion` 表和独立的 `已完成/总数`统计，不计入六类图鉴总进度；网页侧边栏显示全部成就，包括隐藏成就，约每 5 秒轮询一次。

条件整理的边界包括：制造图鉴成就是图鉴解锁数，不是累计制造次数；社区群成就是成功发送表态/回复次数，取消、普通私聊和独立八卦选项不计；纪念品成就要求 9300-9307 各至少有一个实例实际摆放，仅拥有或放在背包中不计；3003 的预算使用灾变前配置预算，储蓄能力提高可用资金额度不会改变原始预算门槛；结局成就 1102-1108 仍要求实际触发对应结局事件，并遵守公共的承诺消耗、单存档单路线和最终尸潮边界。

## 1. 项目结论

本项目直接读取当前本地游戏安装目录中的 YooAsset catalog、加密 UnityFS bundle 和 MemoryPack 配置，并只读读取用户本机 `HistorySave.bytes` 中的图鉴完成状态。不启动游戏，不修改存档、mod DLL、游戏资源或 Steam Cloud。

当前本地游戏资源版本为 `1.1.18293`，catalog 版本为 `2.3.1`。完整解析生成六份主图鉴和一份辅助配置；成就配置另外写入 SQLite 的 `achievements` 表：

- [survival_log_food.md](./snapshots/survival_log_food.md)
- [survival_log_dish.md](./snapshots/survival_log_dish.md)
- [survival_log_plant.md](./snapshots/survival_log_plant.md)
- [survival_log_prey.md](./snapshots/survival_log_prey.md)
- [survival_log_craft.md](./snapshots/survival_log_craft.md)
- [survival_log_furniture.md](./snapshots/survival_log_furniture.md)
- [survival_log_auxiliary.md](./snapshots/survival_log_auxiliary.md)

当前原始主配置表数量为：`Config_Item` 3857、`Config_CookingRecipe` 524、`Config_Plant` 42、`Config_ProductionList` 820、`Config_Furniture` 1556。严格按展示规则导出的数量为：食品 191、菜肴 524、植物 38、猎物 23、制造 163、家具 110，六类分类映射合计 `1049`，去重条目 `1026`；辅助配置 `591` 行。当前 `Config_Achievement` 读取 93 行、21 个字段；静态库刷新保留原有人工成就说明。原始配置总量与 `InCodex == true` 筛选（菜肴表无该字段）后的图鉴展示基数不能混用。

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

当前严格 `HistoryData-v16` schema 的第 4 个字段为全局 `UnlockedAchievementIds`；它与 `CodexUnlocked` 同属 HistorySave，不属于任意 `Save_*.bytes` 子存档。旧版结构扫描只有在能通过公共前缀确认该整数列表时才标记成就状态可用；无法确认时只保留旧状态，不把候选字节猜成成就。同步时当前配置 ID 之外的存档 ID 进入诊断，不显示为虚假成就。

解析器校验 `HistoryData` 成员数、历史条目成员数、分类 ID、集合长度、重复 ID 和文件读取稳定性。存档正在写入或主文件解析失败时，只读尝试同名 `.bak`；两者均失败则数据库保留上一次有效完成状态。未识别的存档条目 ID 会保留在诊断结果中，不会静默转换为其他条目。

独立版首次实际使用、首次 API 同步或启动错误时才建立分发目录中的 UTF-8 JSON Lines 日志 `SurvivalLogDataViewer.log`；新打包目录不预置日志，源码版不生成存档同步诊断日志。分发目录不可写时回退到 `%LOCALAPPDATA%\SurvivalLogDataViewer`。日志记录存档签名、解析阶段、图鉴映射 offset、候选评分、分类数量和错误原因，不记录原始存档字节；相同存档签名和错误只记录一次，日志达到 2 MiB 时轮转一个 `.1` 文件。

完成状态由 `HistorySave.bytes` 实时读取，具体完成数量随存档变化。食品和猎物可能引用同一个 `Config_Item`；数据库在 `completion` 中只保存一份主状态，同时在 `category_completion` 中保存按分类的完成状态，使两个分类分别计数。成就使用独立的 `achievement_completion` 表和独立统计，不并入六类图鉴总进度。

### 成就条件说明

`Config_Achievement` 使用当前 bundle 中验证过的 21 字段 schema：ID、排序、名称/本地化名称、描述/本地化描述、Steam 成就键、图标、展示标记、成就类型、浮点 `Value` 列表、分类、触发模式、计数器键、比较方式、阈值、条件组 ID、隐藏标记、进度计数器键和进度目标。解析器验证对象数量、字段数量、浮点列表长度、重复 ID 和数据 EOF。

人工整理的条件保存在跟踪文件 [`achievement_conditions.json`](./achievement_conditions.json)，由 `codex_achievements.py` 校验 ID 集合、名称和隐藏标记；`source_version` 只作为说明来源记录。每条说明包括分类、完成条件、完成方法、数值门槛、角色限制、排除项、配置引用和注意事项；当前版本的结局成就 1102-1108 还共享“必须实际触发结局、同一存档只能承诺一条路线、承诺事件消耗 9048、撑过最终尸潮”等边界说明。资源版本更新时自动更新只处理原有六类图鉴，不会重新读取或覆盖成就内容；用户需要手动整理成就说明后，再执行显式的成就导入/数据库构建。

其中，图纸成就按制造图鉴解锁数判断，不按累计制作次数判断；社区成就按成功发送的社区群表态/回复次数判断，取消回复、普通私聊和独立八卦选项不计；纪念品成就要求指定 9300-9307 家具各至少有一个实例实际摆放，只有拥有或放在背包中不计。`3003` 的“预算”取灾变前配置预算，储蓄能力增加的是可用资金上限，不会改变该成就的原始预算门槛；是否满足仍以游戏实际触发的条件组和禁用标记为准。

### 存档可烹饪菜肴

完整的库存来源历史、字段词典、实测证据和后续排查清单见 [`save_inventory_pipeline.md`](./save_inventory_pipeline.md)。

`codex_save.py` 对当前版本的 `HistoryData` 使用严格的 16 成员 schema。`GameSaveData` 的标准 `CurSave` 使用当前 176 成员 schema；同时兼容已验证的 181 成员历史变体（`SaveChildData` 末尾增加 5 个整数）和 183 成员历史变体（末尾增加 6 个整数及一个 `Dictionary<int,string>`），三种形式都必须完整读取到文件末尾。`HistoryList` 中的子存档文件名必须是单层 `Save_*.bytes` 文件名，并在读取前后检查文件大小和修改时间；主文件解析失败时才尝试同名 `.bak`。全局 `HistoryData.CodexUnlocked` 是菜肴图鉴完成状态的唯一来源，因此“未完成菜肴”与具体子存档库存无关，所有 `HistoryList` 子存档共用同一份未完成列表。`AgentSave.CookingLevel` 会随存档保留，但不再直接决定通用菜肴的 `Tier`；它在游戏 native 逻辑中属于配方显示、解锁和制作可用性的另一层条件。运行时 `Save_*.bytes` 里的 `CodexUnlocked`、`UnlockedCookingRecipeIds`、`CraftLevel` 和 `CraftUnlockedCookingRecipeIds` 不参与当前菜肴候选过滤，`UnlockedCookingRecipeIds` 仅作为存档中的配方解锁/发现记录。

子存档按当前 `GameSaveData` 的 `CurSave` 读取。主控 `LeadingRole.ItemList` 始终作为背包来源；先读取 `LeadingRole.Name` 并按已验证名称映射确定角色，再按 `GameSaveData.PlayerSelectId`、`HistoryList.PlayerSelectId`、`LeadingRole.AgentConfigId` 的顺序兼容回退，名称未知、缺失或与数字身份冲突时会保留角色上下文和诊断。储物家具以静态库 `storage_furniture` 表为权威来源，覆盖当前 `Config_Furniture` 中 `FurnitureFunc` 包含 215 或 `ShowStorage > 0` 的全部配置，不受图鉴 `is_current` 可见性影响，也不按本地化名称筛选；旧数据库缺少专用表时才回退到旧的当前图鉴行。家具优先使用 `BagFurnitureConfigId`，否则使用 `AgentConfigId`，同名的多个家具实例均单独保留。容器必须同时有储物行为配置、当前角色槽位和地图证据：先比较主控 `MapConfigIdHome`、`ChapterAgentMap` 地图键与实例 `MapConfigId`，任一地图 ID 不一致始终判定为其他位置；再按当前角色选择槽位，角色 1 使用 `HomeBuildingPos`/`Home_`，角色 2 使用 `NeighborGirlBuildingPos`，角色 3 使用 `WarehousePos`。空槽位不再因地图相同而视为家中，其他角色的已知槽位判定为其他位置，未知槽位判定为未知并跳过库存；位置、实例和角色解析诊断仍保留在后端 `storage_containers`/存档 JSON。`IsDoorBox == true` 仅在地图明确属于当前家中时作为兼容储物容器读取；工作台抽屉 `WorkbenchDrawerItems` 作为家中直接容器读取，车辆后备箱和普通 `ChapterAgentMap` 条目忽略。旧版 `DoorBoxItems`/`DoorBoxItems2` 只对 15000/15001 保留兼容回退，且仅在没有对应实际家具并已解析出已知角色时使用。

数据库 schema v9 额外保存全部 `Config_Item` 的烹饪相关字段、按储物功能生成的家具映射和七类烹饪档位阈值及其 `Config_GlobalSetting` 键；旧 v5 数据库会强制重建，旧 v6 源码库会拆分为静态库和 runtime 库。菜肴匹配拆分为两个独立指令：`SpecificItems` 按 `Config_Item.Category == 1 && CanCook == true` 和实际物品 ID 多重集合精确匹配；`TagCombo` 按子分类数量枚举库存组合，并用参与食材的 `SubCategory`、`price` 和 `Config_GlobalSetting` 阈值解析 `CookingTier`，取支持质量档位的最高档，再应用可选的质量保底 rank，最后选择同档位配方。主食等不在 native 质量子分类集合中的食材只负责满足 `TagCombo`，不改变档位。两类结果仍互不预留或扣除共享食材，但每个完整食材组合先执行 `SpecificItems` 特色菜肴优先判断，只有未命中特色菜肴时才允许将 `TagCombo` 通用菜肴作为匹配候选；因此菠菜只有在补入后的完整组合没有命中特色菜肴时，才可作为通用菜肴候选。近匹配只在其他槽位和数量全部满足、加入候选食材后确实能得到有效目标通用菜肴且未命中特色菜肴时返回；候选可来自配置上可烹饪但当前尚未拥有的食材，并统一放在 `missing_item_candidates`。智能菜谱页面同时展示特色菜肴和通用菜肴结果；当前存档解析未持久化 native 的 `TagTierFloorRank`，因此计划构建默认使用保底 rank 0。

### ChapterAgentMap 外层键判定（当前实现）

实际存档对比表明，`ChapterAgentMap` 的外层键是章节分组键，不是角色 ID，也不是地图 ID；角色 1、2、3 的存档都可能同时出现键 `1` 和键 `2`。当前优先使用 `GameSaveData.InitChapterId` 选择同名外层键，并在存档 JSON 中记录选择来源和诊断。`InitChapterId` 缺失或对应键不存在时，才使用“角色槽位 + `MapConfigIdHome`”找到唯一候选；候选不唯一或无法确认时跳过依赖章节分组的容器。外层键选定后，容器还必须满足储物行为配置、实例 `MapConfigId == MapConfigIdHome` 和当前角色槽位三项条件；因此地图字段负责地图一致性，槽位字段负责角色归属，不能用任一字段替代外层键判定。该规则覆盖本节前文中将 `ChapterAgentMap` 键作为地图证据的旧表述。

当前已验证 `SaveChildData` 的标准 176 成员格式、末尾增加 5 个整数的 181 成员格式，以及末尾增加 6 个整数和一个 `Dictionary<int,string>` 的 183 成员格式；三种形式都必须严格读取到文件末尾。

## 3. 主图鉴分类和关联

食品和猎物使用当前游戏 Codex 字段，两个分类允许重叠：

- 食品：`Config_Item.InCodex == true && Category == 1`。
- 猎物：`Config_Item.InCodex == true && Prey_Rarity > 0`。
- 菜肴：当前 `Config_CookingRecipe` 的全部配置（该表没有 `InCodex` 字段）。
- 植物：`Config_Plant.InCodex == true`。
- 制造：`Config_ProductionList.InCodex == true`。
- 家具：`Config_Furniture.InCodex == true`。

因此，猎物物品可以同时出现在食品和猎物 Markdown 中；数据库只保存一份完成状态，并通过分类映射分别计数。主 Markdown 只展开主表条目，物品子分类、食品标签、植物等级、制造等级和家具辅助表集中写入 `survival_log_auxiliary.md`。

| 输出 | 主表 | 主要关联表 |
| --- | --- | --- |
| 食品 | `Config_Item` | `Config_ItemSubCategory`、`FoodTag1`、`FoodTag2` |
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

静态库保存主条目、分类映射、关联关系、辅助配置原始行、资源元数据，以及 schema v9 的菜肴物品、按储物功能生成的家具映射和烹饪档位规则；runtime 库保存共享主完成状态、分类完成状态、`save_*` 元数据和持久化缓存。查询通过附加 runtime 库跨库关联。重新导入使用事务和 upsert；存档同步先完整解析，成功后才在 runtime 事务中更新状态，失败不会清空上一次有效状态。菜肴库存不写入 SQLite，网页请求 `/api/recipe-plans` 时根据 `HistorySave.bytes` 列出的子存档重新计算，并附带角色上下文、回退诊断和每个储物容器的位置诊断；`POST /api/recipe-plans/refresh?file_name=...` 只重读指定的当前子存档，并将结果合并回现有计划。没有存档时可以使用 `--no-save-sync` 只构建静态数据库。

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

前端提供六类主图鉴分类和“智能菜肴”栏目、成品名称检索、材料检索、完成状态筛选、全量条目列表、关联数据和配置字段详情。菜肴栏目按 `HistoryData.LastPlayFileName` 默认选中存档，下拉切换后只展示该存档；页面采用固定视口高度，左侧拥有食材、右侧可烹饪菜肴和仅差一个食材结果分别滚动。菜肴轮询比较 payload revision，内容未变化时不重建列表，变化时恢复两个滚动列的位置，切换存档则回到顶部。结果卡片严格保持单行，只显示“特色菜肴”，每个食材使用独立高亮标签；近匹配把“缺少：”和“当前：”放在同一行。存档下拉菜单、文件名、模式/天数和【存档更新】按钮合并在同一行，按钮只刷新当前选中的子存档，前端不会写回存档。

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
