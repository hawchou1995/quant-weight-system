# gushi 每日选股记录 · 数据字典（本地落地版）

最后更新：2026-09-23

## 1. 一句话
`i.gushi.in` 每日出票（因子策略票 + 共振票）落地到本仓 `backtest/gushi_data/`，
研究侧统一经 `backtest/gushi_picks.py` 读取，不再各自解析原始 JSON。

## 2. 来源与身份要求
- 站点：`https://i.gushi.in/factor.html`（策略选股页；接口按 bucket 返回）
- **落盘硬门：接口返回 `role == "vip"`**；regular / 游客 / 脱敏行一律拒绝写盘（避免把 `******` 掩码数据写进本地）
- 登录方式：**LINUX DO OAuth**（账号 `HawChow`）；会话保存在自动化 profile `D:\Tools\chrome-auto-profile`
- 采集通道：Chrome CDP `9223`（自动化 profile）；端口不通时采集器自行以该 profile 拉起 Chrome

## 3. 目录与文件（`backtest/gushi_data/`）

| 路径 | 内容 | 说明 |
| --- | --- | --- |
| `daily/<交易日期>.json` | 当日全量 bucket 原始返回 | 采集落盘主产物；8 个文件，2026-09-14 起 |
| `picks_daily.jsonl` | 每日扁平化票池（追加写） | 研究主消费对象；4211 行（含 09-21/22/23 回补 869 条） |
| `picks_0913.jsonl` | legacy 历史样本 | 由 `gushi_picks.py` 与 `picks_daily.jsonl` 合并去重 |
| `raw/`、`raw_vip/` | 一次性原始抓取存档（各 11 个文件，2026-09-09…09-11） | 历史留档，不参与日常读取 |
| `renew_log.jsonl` | 续费流水 | 见 §9 |
| `window.json`、`merged_stats.json`、`replay_0913.json`、`rule_*.json`、`inference_auc_0913.json` | 研究/回测产物 | 由既有 harness 产出，非采集产物 |

## 4. `daily/<日期>.json` 结构

顶层为 dict，键是站点 bucket 名：

- factor 族：`f_1`、`f_2`、`f_3`、`f_4`、`f_5`、`f_9`、`f_11`、`f_ten31`、`f_bigcap`
- 共振：`reson`
- 共振子策略：`r_baofactor13`、`r_fengkou`、`r_fivestar`、`r_gnbid`、`r_highscore`、`r_hottopic`、`r_linkgene`、`r_momentum`、`r_researchhot`、`r_sectorlead`

每个 bucket 形如：

```
{"code": 200, "msg": "OK",
 "result": {"stock_count": 6, "trading_date": "2026-09-23", "is_today": true,
            "role": "vip", "stock_list": [ ... ]}}
```

`result.stock_list[]` 字段：

| 字段 | 含义 |
| --- | --- |
| `stock_code` / `stock_name` | 6 位代码 / 名称 |
| `trade` | 站点内部票 ID |
| `price` | 现价（字符串） |
| `open_rise` | 开盘涨幅 %（字符串） |
| `change_rate` | 当日涨幅 %（字符串，如 `10.0021`） |
| `entity_rate` | 实体涨幅（数值） |
| `market_value` | 市值，单位**元**（数值） |
| `factor_tags[]` | `[{factor_name: ...}]`，命中因子策略 |
| `factor_count` | 命中因子数 |
| `block_names[]` | 概念/板块名列表 |
| `concept_blocks[]` | `[{block_name, change_rate}]` 板块涨幅明细 |

## 5. `picks_daily.jsonl` 记录契约（研究直接消费）

一行一条、UTF-8、`ensure_ascii=false`：

```json
{"date":"2026-09-14","kind":"factor","strategy":"竞价多头","fid":"1",
 "stock_code":"300562","stock_name":"乐心股份","price":"17.67","open_rise":"3.75",
 "change_rate":"12.4761","entity_rate":8.41,"market_value":3868390255.0781,
 "total_score":134,"factor_count":1,"tags":["竞价多头量化策略"],"concepts":["血氧仪","智能医疗",...]}
```

口径：
- `kind`：`factor` = 因子策略票；`resonance` = 共振票
- `strategy` / `tags`：策略与因子名（中文），`fid` 为站点 bucket 序号
- `price` / `open_rise` / `change_rate` **是字符串**，计算前需 `float()`
- `change_rate` 为百分数（`12.4761` = +12.48%）；`market_value` 单位为元
- ⚠ PowerShell `Get-Content` 默认编码会显示为乱码，读文件请显式 UTF-8

## 6. 覆盖区间与已知缺日（截至 2026-09-23）
- `gushi_picks.py` 统计：**5182 条（去重后）| 覆盖 19 个交易日：2026-08-28 … 2026-09-23**
- 按 kind：`factor` 809 条、`resonance` 4373 条
- `daily/`：8 个文件，2026-09-14 … 2026-09-23（09-21 / 09-22 / 09-23 于 2026-09-23 23:38 回补）
- **已知缺日**：`2026-09-21`（daily 77 KB）、`2026-09-22`（98 KB）**仅 factor 票，resonance = 0** —— 站点未提供历史共振，回补只对当日有效
- 站点窗口硬限 **15 天**：早于窗口的日期无法再回补，只能在窗口内做补救

## 7. 读取契约（研究侧唯一入口）

```powershell
python backtest/gushi_picks.py            # 全量：合并 legacy + 每日累积并按 (date,kind,strategy,stock_code) 去重
python backtest/gushi_picks.py --since 2026-09-01
```

新研究一律走这个入口；直接读 `daily/*.json` 只在需要 bucket 级原始字段（`concept_blocks` 等）时使用。

## 8. 采集与保活
- **链尾唯一采集点**：`daily_refresh.py` L285 起，`python backtest/gushi_daily_collect.py --days 10 --renew`
  （链尾 = 唯一允许续费的入口）
- **Windows 计划任务**：`GushiDailyCollect_1840`，周一~周五 **18:40**，`--days 3`（幂等，已落盘日期自动跳过）
  - 首跑 2026-09-23 23:39 → `result=0`（成功）
  - 不带 `--renew`，避免重复扣积分
- 采集日志关键行：`[todo] 待采日期 N 个` → `2026-09-23 | factor 49 条 / resonance 729 条` → `role=vip | 增采 N 条`

## 9. 积分与续费
- `renew_log.jsonl`（当前 1 条）：`{"date":"2026-09-17","ok":true,"order":"QPP2026...","balance_before":53,"plan":"vip_7d"}`
- 当前状态：`vip_7d` 卡有效至约 **2026-09-24**；余额 53 积分（**余额 < 60 需告警**）
- 续费入口：`https://gushi.in/index.php?a=quant_points_payment&offer=vip_7d`（由 `--renew` 驱动）

## 10. 限制与不在范围
- **云端（GitHub Actions）不接管 gushi**：依赖本机登录态 Chrome；Phase 2 再评估 cookie 移植
- 本数据是「站点出票结果快照」，不是行情数据；价格/涨幅以站点为准，勿与本地 K 线口径混用
- 站点改版/掩码策略变化会使字段失效 → 采集器有 `role!=vip 拒写` 兜底，宁可缺数据不写坏数据
