# gushi.in 社区回测内容核验与 Agent 加固

- 核验日期：2026-10-13
- 目标：`www.gushi.in` 牛来股市社区；不混入相邻 `i.gushi.in` 量化选股平台数据。
- 机器可读来源目录：`backtest/gushi_community_inventory_20261013.json`
- 逐帖主张/判定台账：`backtest/gushi_community_assessments_20261013.json`
- 388 个标题候选的正文状态索引：`backtest/gushi_candidate_body_status_20261013.json`（只存元数据：状态、响应哈希、响应字节数、首帖字符数与日期，不存正文）
- 判定状态：**采纳 / 待实验 / 不适用 / 无法验证**。帖子中的收益数字都保留为“作者主张”，未经复现不作事实或生产依据。

## 1. 检索覆盖与边界

### 社区公开目录

按帖子时间排序读取 5 个社区分类的全部公开列表页；目录采集只用无登录态 GET，不带 Cookie、不发帖、不调用付费功能。

| 分类 | URL | 页面 | 唯一帖子 |
|---|---|---:|---:|
| 最好的地方 | `/forum/1` | 14 | 261 |
| 经验分享 | `/forum/5` | 12 | 229 |
| 社区共建 | `/forum/6` | 3 | 44 |
| 纯净水 | `/forum/7` | 11 | 220 |
| 指标公式 | `/forum/8` | 13 | 257 |
| **合计** |  | **53** | **1,011** |

53/53 页 HTTP 200；按帖子 ID 去重后 1,011 条。标题高召回筛选词包括“回测、未来函数、样本外、收益曲线、量化、策略、公式、滑点、成本、交易、验证、复盘、指标、开盘、成交、仓位、参数、选股、择时、复权、因子、胜率、夏普、最大回撤”等，命中 388 条。标题筛选只用于召回，不代表正文相关或方法有效。

对 388 条标题命中逐篇作无登录 GET：385 篇正文可读、1 篇正文仅图片、2 篇（topic/1009、/1010）HTTP 403 且页面明示需要 TL1；没有升级权限或消费积分。对 385 篇可读正文做第二轮回测/未来函数/样本/成本/收益关键词筛查，发现 13 个额外方法或信号候选。最终对 48 个 topic 形成 51 项逐条判定；其余可读正文保留响应哈希、长度、日期与读取状态，仅作标题/正文关键词筛查，未作语义结论或本地策略复现。topic/296 主帖是图片，未做 OCR。

每条“全文”状态都附可核查的抽取长度 `main_body_chars`：首帖抽取文本的字符数（空白归一化，索引内已写明口径）。385 条全文的最小值 3、中位数 997、最大值 9,074；短正文是真实存在的灌水/提问帖，不是抽取失败。闸门据此要求“全文”必须同时观测到 HTTP 200 与正数长度，缺长度即拒绝——这一条正是本轮修掉的自证漏洞。

- 社区站内 `/search` 请求返回“请登录后操作”，因此没有声称取得登录态站内搜索结果。
- 外部索引的宽泛 `site:gushi.in` 查询命中经验分享分类页；对分类/“回测、未来函数”等窄查询有空结果。空索引结果不作为“站内不存在”的证据。
- 顶栏“量化选股”链接指向 `i.gushi.in`，与社区帖子不同源，按任务边界排除。此前 `i.gushi.in` 的每日策略/共振数据不计入本次社区帖子证据。
- 目录日期是页面显示的“最新活动时间”，不是一律等同原帖创建日。逐帖台账另记录正文首帖日期；相对日期保留原显示文本和本次抓取日期，不擅自换算。

## 2. 方法、规则与经验评估

| 来源 | 原帖主张/内容 | 评估与状态 | 适用条件/不采纳原因 |
|---|---|---|---|
| [topic/465](https://www.gushi.in/topic/465) | 五维检查：指标重绘/前向引用、K 线信息时点、选股与盘中可用性、信号回溯/周期错位、样本/参数/成本。 | **采纳（仅采纳审计结构与控制组纪律）**。五维映射到现有信息集、同-bar 与交易时钟探针；先证明探针能捕获已知前视，再允许给“未发现”结论。 | 不采纳“90% 指标……”等无样本主张；不照搬“收盘选股、次日开盘一概前视”的过度概括。T 日收盘信号、T+1 执行可以因果正确；问题在于用尚未发生/尚未可用信息决定同一成交。帖子中“信号永不修改”也不作普遍硬规则，须保存每次信号的点时状态与修订记录。 |
| [topic/468](https://www.gushi.in/topic/468) | 上线检查包含规则固定、仓位/止损、成本滑点、行情适配和复盘记录，也含主观心理建议。 | **待实验**。只把可量化的成本、成交、规则、适用行情与记录要求映射到门禁候选；本轮未把 12 项整体当作已证实清单。 | 作者没有提供 12 项检查前后的对照实验；心理成熟等项目不适合作为自动化回测 PASS 条件。 |
| [topic/911](https://www.gushi.in/topic/911) | 作者称在 2025-08-08 至 2026-09-24 做了 3,700,710 组固定规则比较，披露费用、滑点、整手、资金占用、无法卖出顺延，并给出多种收益曲线。回复还给了“全量买入”负向结果和指数过滤结果。 | **规则待实验；所有收益数字无法验证**。全期遍历后选中的“固定参数”仍是全期选优，固定不等于预注册/OOS。 | 未取得原始候选收益矩阵、每日成分、订单/成交明细和独立封存样本；同帖回复不是独立复核。候选若复现，须先锁定单一规则，再按试验总数审计 DSR/PBO/多重检验。 |
| [topic/918](https://www.gushi.in/topic/918) | 参数含“开盘涨幅≤4%”，按实际开盘涨幅排序，最多两只，再按同一开盘价买入；作者贴一年曲线并提示样本偏向历史有利部分。 | **当前执行规则不适用；收益主张无法验证**。开盘涨幅既作筛选/排序，又把同一开盘价记作成交，属于同-bar 信息/成交矛盾。 | 不能用开盘后才知道的排序结果假设已在同一开盘价成交。事前盲挂只能检验重定义后的新规则，不能声称忠实复现原规则。 |
| [topic/300](https://www.gushi.in/topic/300) | 14:30 出票、约 14:55 看涨幅区间后买入，T+1 收盘卖；回复指向 14:57 后收盘竞价。 | **待实验**。页面给出可转成假设的时间线，但未交代完整信号快照、订单提交时刻、排队/部分成交/撤单语义。 | 仅用日线数据无法验证 14:55 信号和价格成交。需要分钟/竞价数据及可执行订单相位；否则只算研究上界，不作组合结果。 |
| [topic/330](https://www.gushi.in/topic/330) | 评分/价位/市值/换手过滤，开盘价上浮 1.5% 逐级委托，收盘竞价卖出；称资金利用率约 50%。 | **待实验**。具体条件可转成一条封存假设。 | 评分最早可用时点、逐级委托延迟、部分成交与收盘竞价未成交处理没有展开，也没有逐笔证据；不直接用于生产。 |
| [topic/460](https://www.gushi.in/topic/460) | 佣金、过户费、卖出税、最低佣金及小额往返成本示例。 | **待实验（费率示例不采纳）**。保留“成本要按方向分项且含最低收费”的检查点。 | 券商套餐、交易品种与政策费率会变；文中的具体数值不是本仓户头费率。运行时用实际账户/日期口径，不把帖子费率写成常量。 |
| [topic/461](https://www.gushi.in/topic/461) | 比较不复权、前复权、后复权并建议回测用前复权。 | **待实验；不采纳“一律前复权”**。需要在数据合同中注明复权方式与调整锚点。 | 当前复权历史可能被后续分红/送转修订；信号序列与执行价的锚点需点时一致。项目现有数据修订/复权护栏继续作为真值，不被帖子覆盖。 |
| [topic/795](https://www.gushi.in/topic/795) | 介绍 9:15–9:30 竞价阶段、撤单与静默期，并声称极端限价可“确保成交”。 | **不适用为权威规则源**。已有 `fleur_absorb` ADR-0004/`engine/session.py` 与 QWS 交易时钟门禁。 | 本帖仅作二级线索；“挂涨停/跌停确保成交”不是成交保证，不能替代队列/可成交性建模。 |
| [topic/842](https://www.gushi.in/topic/842)、[topic/849](https://www.gushi.in/topic/849)、[topic/568](https://www.gushi.in/topic/568)、[topic/618](https://www.gushi.in/topic/618)、[topic/753](https://www.gushi.in/topic/753) | 公式/指标源码及“无未来、高胜率、99% 精度、5000 只提炼”等表述。 | 具体公式是**待实验的策略候选**；所有精度/胜率/无未来宣称均**无法验证**。 | 无定义过的指标分母、点时样本、搜索次数、基准、全量成交和费用。公式里看见 REF 或 MA 不代表已证明全链因果；FINANCE/当前资料字段还需检查点时可用日期。 |
| [topic/1000](https://www.gushi.in/topic/1000)、[topic/785](https://www.gushi.in/topic/785) | “买入理由失效”止损、仓位/止盈建议。 | **待实验/不适用**。逻辑止损只能在可编码、固定时点的规则中验证；泛化仓位建议不直接采纳。 | 个案复盘不是对照研究；不据此替换已冻结止损、仓位或生产参数。 |
| [topic/352](https://www.gushi.in/topic/352)、[topic/385](https://www.gushi.in/topic/385)、[topic/408](https://www.gushi.in/topic/408)、[topic/430](https://www.gushi.in/topic/430)、[topic/907](https://www.gushi.in/topic/907)、[topic/924](https://www.gushi.in/topic/924) | 连续 T+1 策略实盘/持仓日记。 | **无法验证为策略绩效**；只保留为观察记录。 | 无完整券商成交单、现金/持仓全量和成本复核；topic/385 标题日期 `20290922` 与正文/列表时间冲突，本身说明标题不能代替时间戳。 |
| [topic/1009](https://www.gushi.in/topic/1009)、[topic/1010](https://www.gushi.in/topic/1010) | 竞价/T+1 策略历史数据帖子。 | **无法验证**。 | HTTP 403 明示 TL1 权限；不升级、不用积分、不推测正文。 |
| [topic/296](https://www.gushi.in/topic/296) | 标题询问某策略是什么以及回测数据。 | **无法验证**。 | 正文为图片，本轮文本抓取为空；未将图表或看不到的规则臆造成结论。 |
| [topic/1013](https://www.gushi.in/topic/1013)、[topic/1014](https://www.gushi.in/topic/1014)、[topic/360](https://www.gushi.in/topic/360) | 提问/征求复盘数据、数据源观点或请求别人回测。 | **不适用为方法/规则证据**。 | 讨论问题本身没有提供可验证规则或实验结果。 |
| [topic/435](https://www.gushi.in/topic/435)、[topic/447](https://www.gushi.in/topic/447)、[topic/11](https://www.gushi.in/topic/11)、[topic/1019](https://www.gushi.in/topic/1019) | 自动交易 API、信号浏览器插件、工具预告或平台登录事件。 | **不适用**。 | 属执行工具/平台运维，不是回测有效性方法；工具可用不等于策略有效。 |

### 正文第二轮发现（13 个额外候选）

- [topic/86](https://www.gushi.in/topic/86)：回复建议同一信号下分别核算 T+1 开盘卖/收盘卖，并统计涨跌停开盘无法买入项；**待实验**，锁定 exit 前先预注册，不能事后选最好结果。
- [topic/109](https://www.gushi.in/topic/109)：提出跨时间稳定、分组收益单调、成本/过拟合披露；**待实验**为诊断项，组别与时间窗须预先固定，不能把一段好看的曲线当证明。
- [topic/805](https://www.gushi.in/topic/805)：分时公式以当日动态高低价构造阈值；**待实验**，必须逐时点重放，不能用完整日线 high/low 解释盘中信号。
- [topic/488](https://www.gushi.in/topic/488)、[/504](https://www.gushi.in/topic/504)、[/517](https://www.gushi.in/topic/517)、[/557](https://www.gushi.in/topic/557)：参数化公式/调参提示，**待实验**，全都只是候选，不等于已验证策略。
- [topic/578](https://www.gushi.in/topic/578)、[/604](https://www.gushi.in/topic/604)、[/933](https://www.gushi.in/topic/933)：公式/准确率/未来函数讨论，**无法验证**其效果或“无未来”结论；topic/933 的评论区争论不等于运行探针。
- [topic/484](https://www.gushi.in/topic/484)、[/605](https://www.gushi.in/topic/605)、[/1031](https://www.gushi.in/topic/1031)：公式入门或泛化交易建议，**不适用**为可复现实验方法。

## 3. 本地核验及限制

### topic/465 方法灵敏度复跑

执行：`python backtest/audit_lookahead_gushi465_20260928.py --out <scratch>/evidence_lookahead_gushi465_20261013.json`，退出码 0，耗时 92.9 秒。HPDK 2018+ 基线年化 62.50%/夏普 2.50；故意把成交价改成入场日最低价的前视正控得到年化 800.72%（Δ +738.22pp）、夏普 14.20，说明此类大幅价格前视能被抓到。QLCH 按已实现收益排序的正控使训练窗 CAGR 从 25.3868% 到 125.8077%（Δ +100.4209pp）。冻结脚本 SHA256 前后相同：`2351eb9d42acc62e35049d47785e755ff9ce5a0a60d178e90c7baa83f47800a2`。

这证明的是**该探针对所注入的大幅前视有分辨力**，不证明全仓所有策略无未来函数，也不验证帖子 911/918 的收益。排序正控在 HPDK 的响应仅 +1.76pp（K=10、槽位20、排序不常约束组合），不能把弱响应误读为探针故障或无风险。

### 交易时钟门禁

`python tools/gate_trading_clock.py --selftest`（交易时钟门禁属另一条工作线，本仓未跟踪该文件）：坏例检出 4，正例误报 0，退出码 0。topic/795 的二级帖子不替代 ADR-0004/引擎时钟。

### 证据闸与回归自检

| 检查 | 命令 | 结果 |
|---|---|---|
| 闸门自检 | `python tools/gushi_backtest_evidence_gate.py --selftest` | 通过 7/7，退出码 0 |
| 离线单测 | `python -m unittest discover -s backtest -p 'test_gushi_backtest_evidence_gate.py' -v` | 通过 17/17，退出码 0 |
| 真实产物校验 | `python tools/gushi_backtest_evidence_gate.py --check --inventory ... --review ... --body-scan ...` | PASS：53/53 页、1,011 帖、388 候选、51 项判定，退出码 0 |
| 既有账本回归 | `python backtest/test_independent_paper_ledgers.py` | 通过 9/9，退出码 0 |

闸门会直接校验已发布的真实产物（目录、正文状态索引、评估台账），因此“索引里 `main_body_chars` 全为 0”这类生产者漏记字段的问题不会再沉默通过：`full_body` 行必须带 HTTP 200 与正数字符数，缺一即报 `full_body requires HTTP 200 and nonempty extracted text`。

## 4. 实施变更

1. `subagents/strategy-backtest-expert.md`（专家团仓库）：增加外部社区来源分账、状态枚举、五维时点审计、同-bar 判据、阳性/阴性控制、全期搜索/样本泄漏审查、受限正文处理规则，以及“标全文必须带可核查抽取长度”的取证要求与含 `--body-scan` 的闸门命令。
2. `tools/gushi_backtest_evidence_gate.py`（quant-weight-system）：只读扫描 5 个公开分类；生成 topic-ID/标题/URL/最新活动时间清单；列表标题高召回筛选并标明“标题级无法验证”，正文 review 另行评估；`--check` 强制 `--inventory`/`--review`/`--body-scan` 三件套；正文状态校验要求 `full_body` 具备 HTTP 200 与正数 `main_body_chars`、`image_only` 不带文本长度、`login_gated` 有实测 403；对 `采纳` 强制 full body、本地 PASS、positive/negative control 与 evidence files；`待实验` 强制实验计划和零生产变更；拒绝 `i.gushi.in` 混源。
3. `backtest/test_gushi_backtest_evidence_gate.py`：离线回归覆盖来源域、正文受限、正负控、缺失理由、实验计划、重复 ID、URL 对齐、目录解析，以及正文状态索引的全文长度/403/图片三类断言，并新增对已发布真实产物直接跑闸门的回归（17 项）。
4. `backtest/gushi_community_inventory_20261013.json`、`backtest/gushi_candidate_body_status_20261013.json`、`backtest/gushi_community_assessments_20261013.json`、`backtest/gushi_audit_validation_20261013.json`：1,011 条标题目录、388 条正文状态（含首帖字符数，仅元数据）、48 个 topic/51 项主张评估、topic/465 本地阳性对照回执。
5. 本报告记录检索范围、逐帖判断与无法验证的内容。

**零生产变更**：未改选股公式、交易信号、费率、持仓/模拟盘状态或看板；不把任何帖子中的回测收益数字导入生产。

## 5. 复现命令

```powershell
python tools/gushi_backtest_evidence_gate.py --selftest
python tools/gushi_backtest_evidence_gate.py --scan --out backtest/gushi_community_inventory_20261013.json
python tools/gushi_backtest_evidence_gate.py --check --inventory backtest/gushi_community_inventory_20261013.json --review backtest/gushi_community_assessments_20261013.json --body-scan backtest/gushi_candidate_body_status_20261013.json
python -m unittest discover -s backtest -p 'test_gushi_backtest_evidence_gate.py' -v
python backtest/test_independent_paper_ledgers.py
python backtest/audit_lookahead_gushi465_20260928.py --out <scratch>/evidence_lookahead_gushi465_20261013.json
python tools/gate_trading_clock.py --selftest   # 本地工具，本仓未跟踪
```

`--check` 的三个输入缺一即参数错误；`--body-scan` 是 388 条候选的元数据索引，不含正文。以上除标“本地工具”的一条外，命令与文件均在 `quant-weight-system` 仓库内。

## 6. 仍未验证

- 1,011 条公开目录标题全部采集；388 条高召回标题候选的正文读取状态逐条登记（385 可读、1 图片正文、2 TL1 限制），可读正文做了第二轮关键词筛查。48 个 topic/51 项主张有逐条评估；其余可读公式/策略正文未作逐条语义复现，故不宣称所有 388 条都已人工判定或策略验证。
- 登录态内部搜索不可用（`/search` 提示登录）；精确索引搜索为空不是不存在的证据。
- TL1 受限 topic/1009、1010 未读；图片 topic/296 的图表未作 OCR。
- 911/918 以及公式贴没有原始历史成分、逐笔委托/成交或外部可校验数据；未复制回测收益，尚未开展新策略复现。
- 本轮不消耗会员积分、不升级 TL、不发帖、不改账号权限。
