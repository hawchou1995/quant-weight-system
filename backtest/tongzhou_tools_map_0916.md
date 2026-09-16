# 同舟金融研究 MCP · 能力盘点（84 工具实测）— 2026-09-16

> 接入：`backtest/connector_tongzhou.py`（MCP OAuth 自动续期，token 不入库、不入报告）
> 端点：`https://mcp-gateway.textmind-gz.com/mcp/tongzhou-research` · 实测 `initialize_status=200, tools_count=84`
> 证据（每次调用原始返回，全量未截断）：**`backtest/tz_data/raw/*.json`**（17 份）+ `backtest/tz_data/ff_page{1,2}.json`（资金流 31 行业 × 623 日）
> 纪律：本表每一行的"能取到什么"均来自本会话真实调用返回，不是按工具名推测。全表 **禁用 token 明文**。

## 〇、84 工具分组

| 前缀 | 数量 | 定位 |
|---|---|---|
| `fin_data__` | 30 | 行情/K线/快照/筛选/榜单/资金流/财务指标/事件窗口收益/宏观 |
| `fin_graph__` | 21 | 行业图谱：身份解析/产业链框架/**公开因子框架**/因子证据面板/拥挤度/异动 |
| `doc_search__` | 17 | 新闻/公告/研报/结构化事件/**事件回测三件套** |
| `same_boat__` | 16 | 同舟要闻/行业观点/分析师/研究图表（本轮未展开） |

---

## 一、核心盘点表（因子证据 / 事件回测 / 形态检测 三条轴）

| 工具 | 能取到什么（字段级 · 附原始返回片段） | PIT 安全 | 可否转因子 |
|---|---|---|---|
| **`fin_graph__get_public_factor_framework`** | 某主题的**定性**研究因子清单：`factor_name / factor_type / node_path / public_brief / source_family`。白酒Ⅲ 返回 13 条（"领先指标：批价与库存"、"基酒产能与储量"…）。**无任何数值字段** | 不适用（定性） | ❌ **不可**。是研究框架节点，不是可计算因子 |
| **`fin_graph__get_factor_evidence_panel`** | 因子 → 数据维度 → **可用指标名**：`linked_data_dimensions[{key_points,node_path,source_family}] + available_metrics[]`。白酒Ⅲ 给到 12 个指标名（"白酒批发价格指数:总指数:全国:当旬值"、"批发参考价:飞天茅台:23年飞天(原)"…）。**只有名，没有值** | 不适用 | ❌ 不可（仅指标目录；价值=知道同舟有哪口数据） |
| **`fin_graph__get_factor_metric_values`** | 上述指标名的**短历史值**：`unit / latest{value,date} / history[{value,date}]`。实测"白酒批发价格指数"：`unit=2012年2月=100`，`latest=104.2 (2026-09-10)`，history 仅 **12 点（旬频）**；`max_points_per_metric` 上限 **24** | 疑似安全（旬频公开指数） | ❌ **不可**。历史 ≤24 点（~2 年旬频）、覆盖单指标、无横截面 → 无法支撑 5 相位回测 |
| **`doc_search__search_backtested_events`** | 事件文档 + **已成熟回测窗口**：`title/publish_date/source/event_type[]/related_industry[]/related_stock[]` + `backtest{status,validity,returns{3d,5d,7d,10d,20d,60d},up_probability{5d},cumulative_return_path{-20..+5},withheld_windows[]}` + `doc_id/evidence_ref`。实测茅台调价文：`returns{3d:-6.23%,5d:+1.62%}, up_probability{5d:0.6}`，路径从 −20 日起 | ⚠️ **未申报目标标的**：返回是该事件的**已实现**事后收益，`related_stock` 是 6~47 只的松散关联（含"啤酒""专业连锁"），**无法判定收益算在谁身上**；`withheld_windows` 显式隐藏未成熟窗口 → 只能事后看 | ❌ **禁用于回测**（疑似前视 + 目标未声明）。可做**事件研究校验** |
| **`doc_search__get_event_backtest`** | 同上，按 `event_id/doc_id` 取单条 compact 结果；note 明写 "Only matured compact event return windows are returned. Future or not-yet-complete windows are withheld. 60d is the v1 proxy for roughly three months." | 同上（事后口径） | ❌ 同上 |
| **`doc_search__aggregate_similar_event_backtest`** | **实测不可用**：无 seed → `-32012 Research evidence reference is invalid or expired`（要求网关原生会话内证据引用）；同会话内传刚检索到的 `seed_event_id` → 服务端崩溃 `Error calling tool: 'list' object has no attribute 'strip'` | — | ❌ **服务端坏**（两种入参形态各实测 1 次，均失败） |
| **`fin_data__detect_stock_patterns`** | **横截面形态筛选**：`pattern ∈ {up_days, down_days, limit_up_days, limit_down_days}`（实测其它值报 `UNSUPPORTED_PATTERN`），`days ≤ 10`；返回 `ticker/security_name/start_date/end_date/observed_days/matched_days/total_change_ratio/daily_points[]/industry/board`；**支持 `as_of_date` 历史回看**（实测 2025-06-10） | ✅ **安全**（只用到 as_of 及之前 K 线；已本地复算对拍） | ⚠️ 可转但**无增量**：本地面板可逐字复算（见 §二对拍），且单日 `limit` 默认 50 上限（实测 50 条）会截断全市场 |
| **`fin_data__compute_market_reaction_windows`** | **显式 target 的事件研究**：给定 `target{market,ticker}` + `events[{event_id,event_date}]` + `windows[]`，返回逐事件 `returns{3d,5d,20d}`、`base_trade_date`（自动顺延到交易日）与 `aggregate{sample_count,average_return,median_return,win_rate}`；note 明写 "descriptive evidence, not a strategy backtest or prediction" | ✅ 安全（只吃事件日 + 事后价格，且**目标由调用方声明**） | ⚠️ 不是因子源，是**验证器**：可用来核验自有事件策略的事件后反应（同族 `compute_batch_reaction_windows` 支持多目标，官方描述上限 10 标的 × 50 事件） |
| **`fin_graph__get_industry_crowding`** | **实测不可用**：`错误：行业拥挤度获取失败（ClientConnectorError）`（食品饮料/industry01，2026-09-16 22:50 实测） | — | ❌ 上游挂 |
| **`fin_graph__get_industry_chain_research_map`** | 产业链框架**定性**结构：`identity{canonical_id,display_name,source_ids{lycode/sw_index_code/rfg_frame_id/graph_subject…}}` + `frame{node_count:41,updated_at}` + `decision_branches[{title,path}]`（"行业景气度与周期位置判断"等 3 条一级决策点）；`key_factors[] / data_requirements[] / coverage_gaps[]` **实测全为空数组** | 不适用 | ❌ **不可**（无量化字段）。唯一可用物=`identity.source_ids` 的**跨源代码映射**（lycode↔申万指数代码↔主题篮子 ID） |
| **`fin_data__get_industry_fund_flow_series`** | **本轮唯一可转因子的量化源**：申万一级行业日频主力资金流，字段 `trade_date / main_net_inflow_amount(CNY) / turnover_amount(CNY) / net_inflow_to_turnover_ratio / change_ratio(%)`；单次 ≤10 行业 × `limit ≤ 500` 交易日 | ✅ **安全**（T 日盘后汇总，T+1 起可用；已用 `_lag1` 变体做边界检验，IC 几乎不变） | ✅ **可转**（已转，见 `报告-同舟MCP挖掘与因子化_20260916.md`）。硬约束：**2024-01-02 起**、**日历缺 5.0%** |
| `fin_data__rank_industry_fund_flows` | 同源"最新交易日"横截面：31 行业 × `window_metrics{1d,5d,20d}`（`net_inflow_amount/turnover_amount/net_inflow_to_turnover_ratio`）+ `rank` | ✅ 安全 | ⚠️ 只有**最新一日**，无历史 → 不能直接回测（历史需走 `get_industry_fund_flow_series`） |
| `fin_data__screen_stocks` | 受控条件筛选（白名单字段）：`ticker/security_name/trade_date/prev_close/close/change_ratio/amount/volume/turnover_rate/market_cap/pe_ttm/pb/limit_status/industry/board`；**支持历史 `trade_date`**，`board=主板`、`status=limit_up` 实测可查 2025-06-10 | ✅ 安全（给定 trade_date） | ⚠️ 可转但**与本地重复**；且**不过滤 ST**（§三-2） |
| `fin_data__query_financial_indicators` | 财务关键指标**快照**：`roe/roa/roic/gross_profit_margin/operating_profit_margin/net_profit_margin/debt_to_asset_ratio…`，按 `fiscal_year/fiscal_period` 返回 ≤20 行（实测茅台 5 期） | ⚠️ **未申报 PIT**：只有 `fiscal_year/fiscal_period`，**无公告日字段** | ❌ 不可（本地 `yjbb_quarterly.csv` 已按法定披露截止日建 PIT 面板，此源字段更少且 PIT 不可判定） |
| `fin_data__query_sector_valuation` | 申万行业 PE/PB 历史分位（返回 Markdown 表） | — | ❌ **上游挂**：实测 `错误：行业估值外部数据源暂不可用，请检查服务配置或稍后重试` |
| `fin_graph__list_supported_subjects` | 期望=图谱主题清单 | — | ❌ **上游挂**：`错误：图谱主题列表获取失败（ClientConnectorError）`。替代：`resolve_research_identity`（实测可用）+ `list_industry_indices` |
| `fin_graph__resolve_research_identity` | **跨源身份映射**：`canonical_id / display_name / aliases / coverage{lycode,same_boat,fin_data_basket,market_data,sw_hierarchy,rfg_frame} / source_ids{lycode, sw_index_code, fin_data_sw_basket_id, rfg_frame_id, graph_subject} / mappings[{source,source_id,match_method,confidence}]` | 安全（静态映射） | ⚠️ 非因子，但是**所有 fin_graph__ 调用的前置门**（`subject` 必须来自它，如 `graph_subject=白酒Ⅲ`） |
| `doc_search__search_events` / `search_normalized_events` / `get_entity_event_timeline` | 结构化事件检索：**必须**至少给 `query/ticker/company/industry/content_type/source_name` 之一（只给日期区间 → `INVALID_QUERY`），单次 ≤50 条 | 公告类含公告日，安全 | ❌ 不可（**无法按日期区间全量枚举**，逐实体/关键词调用无法拼出全市场历史事件流；单次 50 条封顶） |

---

## 二、`detect_stock_patterns` 本地复算对拍（口径验证）

`pattern=up_days, days=5, as_of_date=2025-06-10`，API 返回 50 条 → 用本地 `oss_panel_0913` 逐股复算"截至 06-10 连续 5 日收涨"：

| 校验 | 结果 |
|---|---|
| 主板样本（30 只，剔除 300/688） | **30/30 全部命中**，误报 0 |
| 非主板样本 | 20 只（未加 `board` 过滤时混入创业板/科创板，符合预期） |
| **`total_change_ratio` 语义** | **是 5 日单日涨幅的算术和，不是复利**（29/30 条满足）：共创草坪 API **50.01%** vs 本地复利 **61.10%**、单日和 **50.03%**。跨期/复利场景直接用会系统性低估 |

## 三、`screen_stocks` 本地复算对拍 + 口径陷阱

`trade_date=2025-06-10, board=主板, status=limit_up` 返回 50 条（字段含 `prev_close/close/limit_status/pe_ttm/pb`），与本地面板逐条对拍：

| 项 | 结论 |
|---|---|
| 涨幅口径一致 | **50/50 全部一致到小数点后 2 位**（如 002172 本地 +10.12% = API 10.1205） |
| 12 条"本地非涨停"的真相 | 全是 **ST/*ST/退市** 股（*ST岭南 +5.15%、退市苏吴 +5.14%、*ST美谷 +5.30%…）——**API 的 `limit_up` 把 5% 板也算涨停，且不过滤 ST**。若直接拿来当"打板池"，会混入 24% 的 ST/退市样本 |
| 价格基准差异 | 同一标的两源价格可差 2~3 倍（海航科技 API prev_close 3.36 vs 本地 1.46）→ 本地 `data_full` 与同舟的**复权/股本口径不同**，两源**不可混算收益** |

## 四、资金流数据的两个硬边界（转因子前必须知道）

| 边界 | 实测证据 |
|---|---|
| **历史起点 = 2024-01-02（硬地板）** | `start_date=2016-01-01, end_date=2024-07-08, limit=500` → 仍只回 `evidence_window{start:2024-01-02, end:2024-07-08, trading_days:123}`；换 2020-01-01 同结论。与 limit 无关，是**源库起点** |
| **日历缺口 5.0%** | 面板可用窗 654 个交易日中，资金流缺 **33 日**（`2025-09-17/18`、`2025-11-03/04`、`2026-08-11/12/14/18/20/21`、`2026-08-31~09-04`…），另有 2 日为面板不存在的日期 → 缺失清单落盘 `tz_data/tz_flow_calendar_gap_0916.json`。**用 min_periods 容错，不可当作完整日历** |
| `limit` 上限 500 | `limit=2000` 返回 0 点（静默失败，`evidence_window=null`） |

---

## 五、判词（按能力轴）

| 轴 | 判词 |
|---|---|
| **公开因子证据面板**（fin_graph__） | **名不副实**：是"研究框架节点目录 + 指标名"，数值只有 ≤24 点旬频短序列 → **不可转因子**，唯一价值是"知道同舟有哪 12 个白酒指标名"（可作数据地图） |
| **事件回测三件套**（doc_search__） | `get_event_backtest`/`search_backtested_events` 返回**已实现事后收益**且**收益目标标的未申报**（关联股票 6~47 只）+ 未成熟窗口 withhold → **判"疑似前视，禁用于回测"**；`aggregate_similar_event_backtest` **服务端坏**（无法用） |
| **形态检测**（detect_stock_patterns） | **真实可用、口径干净**（本地复算 30/30 吻合），但**本地可复算 → 无增量**；且 `total_change_ratio` 是算术和、单日 limit 50 截断 |
| **事件研究器**（compute_market_reaction_windows） | **可用的验证器**（目标由调用方声明、只吃事后价格），**不是因子源** |
| **行业资金流**（fin_data__） | **唯一可转因子源**：字段干净、PIT 安全、31 行业 × 623 日；代价=2024-01 起 + 5% 日历缺口 |
| **图谱类**（crowding / chain map / subjects） | crowding 与 subjects **上游挂**；chain map 仅定性 + 身份映射。`identity.source_ids` 的跨源代码映射（lycode↔申万↔篮子）是**值得单独收编的副产品** |

---
---

# 【第二轮追加】2026-09-16 · 剩余 33 工具（`doc_search__` 17 + `same_boat__` 16）

> 范围界定：84 = `fin_data__`30 + `fin_graph__`21（第一轮 51）+ **`doc_search__`17 + `same_boat__`16（本轮 33）**
> 证据：`backtest/tz_data/raw/` 本轮 **80 份原始返回**（序号 30~99 + `h`/`i` 探针前缀），全量未截断（最大单份 402 KB）
> 详细报告：**`backtest/报告-同舟MCP剩余33工具_20260916.md`**
> 纪律：33/33 全部真实调用过（含失败），无望文生义；全表无 token 明文。

## 六、本轮 33 工具判定一览（简表，字段级明细见详报 §一）

### 6.1 `doc_search__`（17）

| 工具 | 判定 | 一句话结论 |
|---|---|---|
| `search_announcements` | **辅助** | **唯一能按"类型+日期"全市场枚举的公告源**；`limit` **硬上限 50、无翻页** → 计数被系统性截断，只能取样不能计数 |
| `search_company_news` | **辅助** | 字段全（含 `event_type/related_industry/related_stock`），但**纯日期 → `INVALID_QUERY`** |
| `search_hot_news` | **辅助** | **唯一允许纯日期枚举的新闻源**（单日 23 条），量小 |
| `search_morning_trading` | **辅助** | 纯日期可枚举（单日 4 条），源 2018-05-08 起 37,276 条 |
| `search_research_reports` | **辅助** | 公司级须传 `company/ticker`+长窗；**纯日期无返回** → 不能按日枚举 |
| `search_documents` | **辅助** | 统一入口 9 种 doc_type；research 路径单次 ≤20 |
| `search_events` | **辅助** | 结构化事件；纯日期 → `INVALID_QUERY` |
| `search_normalized_events` | **辅助** | `events[{event_date,event_category,event_type[]}]`，弱版日历 |
| `get_entity_event_timeline` | **辅助** | 复盘主干候选（茅台 180 天 → 18,931 字符） |
| `search_backtested_events` | **不可用（回测）**/辅助 | 沿用第一轮"疑似前视"判词，本轮复测一致 |
| `get_event_backtest` | **不可用（回测）**/辅助 | 同上（传 `doc_id` 可正常返回 1,567 字符） |
| `aggregate_similar_event_backtest` | ❌ **不可用（服务端坏）** | **本轮复测**：只传 `query` 也报网关层 `-32012`；两种入参形态全部失败 |
| `get_document` | **辅助** | `news/company_news/research/hot_news/announcement/morning_trading` **6 类全部成功**；`doc_id` 是短期 opaque 引用，**禁止持久化** |
| `get_document_summaries` | **辅助** | 1~5 篇有界并发；必须用当次 `evidence_ref` |
| `get_document_source_coverage` | **辅助（最有价值单品）** | **11 源完整数据地图 + 日期边界**（research 862 万条/2002 起、announcement 156 万条/2018 起、report_chart 486 万张） |
| `get_research_coverage` | **辅助/受限** | **`mapped_count=0`，6/6 票全失**；`sample_count/yearly_counts` 可用但**疑似非 PIT** |
| `list_categories` | **辅助** | 索引路由探查（`all/default` → `daily_event_analysis, report_chunks_data`） |

### 6.2 `same_boat__`（16）

| 工具 | 判定 | 一句话结论 |
|---|---|---|
| `get_schema` | **辅助（必读前置）** | 9 张虚拟表全列清单，应作所有 `same_boat__` 调用的第一跳 |
| `list_research_sectors` | **辅助（标的对齐钥匙）** | **100 个行业目录**，含 `category`(申万一级名) + `market_code`(申万三级 `.SL`) |
| `search_research_sectors` | **辅助** | 参数是 **`query` 不是 `keyword`**；"光模块" → 0 条（须用其词表） |
| `list_market_news` | **辅助** | `popularity_score/importance_score/sectors/analysts/publish_time`；`sectors` 须用其词表 |
| `get_market_news` | **辅助** | 单条要闻详情 |
| `get_market_news_analysis` | **辅助** | **`analyst_id` 必填且须用该条新闻自己的分析师**（用错→`result=null`） |
| `list_market_viewpoints` | **辅助** | ⚠️ `limit=200` 实收 50 条**且全在同一天** → **只是当日报表快照，不是历史面板** |
| `list_sector_viewpoints` | **辅助** | 🔴 **历史硬上限 1 年**：氯碱翻到底 648 条（最早 2025-09-17）；银行Ⅲ 438 条 |
| `list_analyst_viewpoints` | **辅助** | 单分析师观点（祖老师 10 条 → 118,148 字符） |
| `get_market_viewpoint_detail` | **辅助** | 观点全文（分节 + images/charts） |
| `list_market_quotes` | ❌ **不可用（上游挂）** | `MARKET_QUOTE_UPSTREAM_UNAVAILABLE`，**3 次实测** |
| `get_market_quote_analysis` | ❌ **不可用（同上）** | 取不到任何 `quote_id`，必然连带 |
| `search_analysts` | **辅助** | 20 位分析师，含 `follow_count/ref_count/tags/research_categories` |
| `get_analyst_profile` | **辅助** | 单分析师资料（`follow_count=33`/`ref_count=763`） |
| `get_research_visual_evidence` | **辅助** | `research-visual/1` 图表证据；`market_viewpoint` **不接受 `analyst_id`** |
| `generate_content_url_link` | **辅助（回链交付）** | `content_type ∈ {market_viewpoint, market_news, market_quote}`；`market_news` 需带 `analyst_id` |

## 七、本轮判词

| 轴 | 判词 |
|---|---|
| **`same_boat__` 观点/新闻/分析师轴（16）** | **全部真实可用（除行情异动 2 件上游挂）**，字段结构化程度高（`sentiment_score`/`analyst_count`/`importance_score`/`popularity_score`/`publish_time`）→ **复盘/选题/拥挤度极佳**；但**历史硬上限 1 年** → **不可转因子** |
| **`doc_search__` 新闻/研报轴（17）** | 可检索、字段干净、**PIT 到秒**；但纯日期枚举大多被封、公告 `limit≤50` 无翻页 → 计数不可信、`get_research_coverage` 映射全失、`aggregate_similar_event_backtest` 网关层永久失败 → **不可转因子**，**复盘归因 + 原文取证**价值高 |
| **本轮因子结论** | 🔴 **0 个可转因子**。两条候选轴均被历史深度卡死（观点 1 年 / 公告·研报检索侧 1 年余，库存虽到 2002·2018 但检索不到）→ **无法满足统一口径回测**，故**未触发引擎**。基线已复核：`asts_0916/base_equity_off0.csv` 170,000 → 480,479.01 / 1231 交易日 ≈ **22.87% 年化**（与参考一致，可随时复跑） |
| **上游/服务端坏（3 件）** | `aggregate_similar_event_backtest`（`-32012`）、`list_market_quotes` + `get_market_quote_analysis`（`UPSTREAM_UNAVAILABLE`） |

## 八、运维补记

1. **token 过期 + refresh 失效**：`refresh_token` 被服务端判 `device session is no longer active` → **必须重走设备码授权**；本轮新增 `backtest/_tz_device_auth_0916.py`。
2. **修复 `connector_tongzhou.py` 静默 401**：`token_obtained_at` 缺失时不触发续期 → 已加 `got <= 0` 强制续期分支（refresh_token 会轮换并落盘）。
3. **`MCPClient.call_tool` 会把返回截到 6000 字符** → 本轮全部改用 `rpc("tools/call")` 直取，保证原始返回全量未截断。

