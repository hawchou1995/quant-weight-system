# A 股行情数据源与拉取链路说明

> **文档定位**：说明本项目在拉取 A 股行情时使用的全部数据源、调用方式、优先级与降级顺序，供项目说明、交接与排障使用。
> **适用代码库**：`quant-weight-system`（三池系统 + 看板 + 回测）。
> **股票池口径**：沪深 A 股 + 北交所 + ETF + 场外基金；历史区间自 **2016-01-01** 起。
> **复权口径**：全库统一 **前复权（qfq）**，见 §5。
> **最后更新**：2026-09-23（补 §1.2 收盘补齐链路与批量兜底通道；§1.1 速览表附当前可用性实测）。

---

## 目录

1. [总览：数据源分层](#1-总览数据源分层)
2. [数据源详解](#2-数据源详解)
3. [调用方式与适用场景矩阵](#3-调用方式与适用场景矩阵)
4. [优先级与降级/回退顺序](#4-优先级与降级回退顺序)
5. [复权（qfq）处理逻辑](#5-复权qfq处理逻辑)
6. [配置项与完整示例](#6-配置项与完整示例)
7. [常见问题与注意事项](#7-常见问题与注意事项)
8. [附录 A：文件与代码索引](#附录-a文件与代码索引)
9. [附录 B：数据源可用性回执](#附录-b数据源可用性回执)

---

## 1. 总览：数据源分层

本项目**不使用单一数据源**，而是按「吞吐 × 新鲜度 × 复权口径一致性」三个维度分层：批量源负责日常增量，单只源负责规范化与兜底，人工源负责极端降级。

### 1.1 速览表

| # | 数据源 | 端点 / 接口 | 复权口径 | 原始成交量单位 | 典型吞吐 | 链路角色 |
|---|---|---|---|---|---|---|
| ① | **TickFlow** | `free-api.tickflow.org/v1/klines/batch` | 前复权 `adjust=forward` | **手** | 100 只/批 × 0.83s，10 并发 → 全库约 8–10s | **历史日线增量首选** |
| ② | **新浪** | `stock_zh_a_daily` / `klc_kl.js` + `qfq.js` | 前复权 `adjust=qfq` | **股** | 0.4s/只（直连）；akshare 封装 1.79s/只 | **规范化基准源**（复权重拉唯一合法源） |
| ③ | **腾讯 fqkline** | `web.ifzq.gtimg.cn/.../fqkline/get?...,qfq` | 前复权 `qfqday` | **手** | 单只，并行 8 线程 → 全库约 12–15min | **增量降级源** |
| ④ | **腾讯 day** | 同上，`adjust` 留空 | **不复权** | **手** | 单只，0.5s/只 | **退市股历史专用** |
| ⑤ | **腾讯实时** | `qt.gtimg.cn/q=` | 不适用（快照） | 手 | 200 只/块 × 10 并发 | **盘中实时行情 / 全市场快照** |
| ⑥ | **东方财富** | `push2his.eastmoney.com/api/qt/stock/kline/get` | 前复权 `fqt=1` | **手** | 0.17s/只（纯 JSON，无 JS 解码） | **备选提速源** |
| ⑦ | **westock CLI**（2026-09-14 起可脚本化） | 本机 `westock.exe kline --fq qfq` → `westock_dump_builder.py` → `fetch_close_westock.py --dump` | 前复权 | **手**（合并时 ×100） | 批量 20 码/次，分钟级 | **降级兜底（原为人工，现已自动化）** |
| ⑧ | **tushare pro** | `pro.daily` + `adj='qfq'` | 前复权 | 手 | — | **预留占位**（无 token，未启用） |

> 成交量单位是历史事故高发区，详见 [§7 Q1](#q1-成交量单位为什么必须统一为股)。

> **当前可用性（2026-09-23 实测）**：① TickFlow **已被拒**（`klines/batch` 403；探样返回旧交易日 → 自动回退）；② 新浪 **可用**（直连 0.4–0.47s/只）；③④ 腾讯 fqkline/day **可用**；⑤ 腾讯实时 **可用**，且 2026-09-23 起新增「腾讯批量快照」通道（**400 码/请求，全市场约 6s**）；⑥ 东方财富 push2* 家族 **持久被拦**（clist/stock/ulist 三端点 502 / 握手超时 / RemoteDisconnected；出口无关、非请求头指纹问题、静默 13 分钟无自愈）→ **链路不再依赖它**，但接线保留 + 探活闸（解封后自动恢复为首选）；⑦ westock CLI **可用**（20 码/次，分钟级，二道兜底）；⑧ tushare 未启用。

### 1.2 收盘补齐链路（2026-09-23 起）

**主力：`update_daily.py` 内「批量通道」块**（滞后清单落盘后立即执行，`--bulk-source auto|tx|westock`，默认 `auto`）：

- 腾讯批量快照 `backtest/em_tencent_fill.py --syms-file`（400 码/请求，全市场 ≈6s）；失败/残缺 → 自动降级 westock CLI（`westock_dump_builder.py` → `fetch_close_westock.py --dump`，复用解析不重写）。
- 传「过滤后的 lag syms」→ `--limit / --only / --pools-only` 语义不被绕过（防意外全市场写盘）。
- **写盘硬门**：收到的行情时间戳「日期 == 交易日 且 ≥15:00」才写 —— 否则会把盘中价当收盘价写进历史（不可逆污染）。
- 写盘后**必须回写 manifest**（`data_index.update_entries`，`rows=0` = 保留原值）；不回写则下轮仍判「滞后」→ 退回 1.4s/只慢通道，快通道白跑。
- 批量失败/部分成功：剩余标的自动回落慢通道，不会静默丢失；`--no-bulk` 可整体关闭。

**兜底链：`backtest/em_bulk_all.py`**（链内第 46 步，`[软]` 失败只告警不阻断）：

`① A 股 clist（首选）→ ② ETF/LOF clist（首选）→ ③ 缺口 ulist（次选）→ ④ 残余单只 → ⑤ 腾讯批量快照`

- **探活闸**：端点被拦时每步 **≤3 次单发探测**（timeout 6s）即退，秒级让位下一通道（不做「N 重试 × 多页 + 长冷却」的硬敲）。
- **零请求原则**：没有缺口就一个请求都不发（`③ gap=0 → return`；`④ stale=0 → exit 0`）。
- **rc 语义**：`0` 成功 / `1` 异常 / `2` 口径未对齐（拒写）/ `3` 端点不可用（限流或被拦）。

> **精度须知**：腾讯批量快照的成交额只到**万元**整数（东方财富到元）→ `amount` 列约 0.001% 级差异；`date / OHLC / volume` 逐位一致。凡吃 `amount` 的量比/成交额类因子，请用 EM 口径数据，勿用兜底行。

### 1.3 分层架构

```
                          ┌──────────────────────────────────────────┐
   日常增量（收盘后）      │  refresh_daily.py / tickflow_update.py   │
                          └──────────────────┬───────────────────────┘
                                             │ 探样 sh600000 比对「预期最新交易日」
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
            ① TickFlow 批量            ② 新浪 qfq              ③ 腾讯 fqkline qfq
            （100 只/批）              （逐只 0.4s）            （逐只，降级）
                    │                        │                        │
                    └────────────┬───────────┴────────────┬───────────┘
                                 ▼                        ▼
                        落库 data_full/<sym>.csv   ⑦ westock MCP（前两者全挂 → 人工补当日）
                        （统一列序 / 统一「股」）
                                 │
                                 ▼
                    复权基准漂移兜底 run_rebase_check() —— 强制用 ②新浪 全量重拉
```

**分层要点**：

- **增量走批量**（①），**规范化走单只**（②），**兜底走人工**（⑦）。
- 退市股（④）与 ETF 走独立分流，不参与上面的延迟优先级竞争。
- 盘中实时（⑤）与历史日线是**两套独立链路**，不要混用。

---

## 2. 数据源详解

### 2.1 TickFlow —— 历史日线增量首选

**实现**：`tickflow_update.py`（独立跑）、`update_daily.fetch_tickflow_batch()`（被收盘管道调用）

| 项目 | 内容 |
|---|---|
| 端点 | `https://free-api.tickflow.org/v1/klines/batch` |
| 方法 | `GET` |
| 认证 | 无需 token（free-api） |

**请求参数**

| 参数 | 取值 | 说明 |
|---|---|---|
| `symbols` | `600000.SH,000001.SZ,...` | 逗号分隔，**单次硬上限 100 只** |
| `period` | `1d` | 固定日线 |
| `count` | `10000` | 足够覆盖全部上市历史 |
| `adjust` | `forward` | 前复权 |

**代码点符号转换**：`sh600000 → 600000.SH` / `sz000001 → 000001.SZ` / `bj920000 → 920000.BJ`

**返回格式**（JSON，按符号聚合）

```jsonc
{
  "data": {
    "600000.SH": {
      "timestamp": [1451606400000, 1451692800000, ...],   // 毫秒时间戳
      "open":   [...], "high": [...], "low": [...], "close": [...],
      "volume": [...],        // ⚠ 单位 = 手
      "amount": [...]         // 成交额，与 akshare 完全一致
    }
  }
}
```

**解析要点**

```python
dt = datetime.fromtimestamp(t / 1000).strftime("%Y-%m-%d")   # 毫秒 → 日期
vol = int(d["volume"][i]) * 100                              # ⚠ 手 → 股
if dt < "2016-01-01": continue                               # 统一裁到 2016 起
```

**特点与实测**

- **性能**：100 只/批 × 0.83s，10 批并发 → 1000 只约 1.13s → 全库约 **8–10 秒**（对比 akshare 串行 1.79s/只 ≈ 3.7 小时，快 **400+ 倍**）。
- **口径验证**：对 akshare `qfq` 逐日比对 `sh600000` 2016–2026 共 2578 天 → `open/high/low/close` 最大相对误差 **0.13%**（复权基准微差），`amount` **完全一致**。
- **超时策略**：`timeout = max(30, 15 + len(batch) * 0.3)`，按批量大小自适应。
- **缺点**：复权基准与新浪存在约 0.13% 微差，故**不能用于复权基准规范化重拉**（那是新浪的专职，见 §4.3）。

---

### 2.2 新浪 —— 规范化基准源

新浪在本项目承担**两个不可替代的角色**：全库建库的基座，以及**复权基准规范化重拉的唯一合法源**。

#### 路径 A：akshare 封装（建库/单只通用）

```python
ak.stock_zh_a_daily(symbol="sh600519", start_date="20160101", end_date="20301231", adjust="qfq")
```

- 优点：封装完整、返回已是「股」单位、无需处理 JS。
- 缺点：每次调用**新建 py_mini_racer JS VM** 解码 `klc_kl.js`（实测 HTTP 0.1s / 全流程 **1.79s**，JS 解码是瓶颈）→ 8 线程也只有约 1 只/s。

#### 路径 B：直连（并行提速）

**实现**：`fast_sina_fetch.py`

| 用途 | 端点 |
|---|---|
| 原始行情（JS 加密） | `https://finance.sina.com.cn/realstock/company/{sym}/hisdata_klc2/klc_kl.js` |
| 前复权因子（纯 JS 对象） | `https://finance.sina.com.cn/realstock/company/{sym}/qfq.js` |

**关键技巧**：每线程**复用同一个 MiniRacer 上下文**（`hk_js_decode` 只 eval 一次，存在 `threading.local()` 中），消除重复建 VM 的开销。

**前复权公式**：

```
qfq 价 = 原始价 ÷ 该日前复权因子        # 逐日因子来自 qfq.js
        再 round(2)，最后裁到 2016-01-01 起
```

```python
raw = decode(klc_kl.js)                     # → date/open/high/low/close/volume/amount
fac = eval(qfq.js)["data"]                  # → [date, qfq_factor] 列表
temp = merge(raw, fac, how="outer").ffill()  # 因子缺失日向前填充
for col in ("open", "high", "low", "close"):
    temp[col] = (temp[col] / temp["qfq_factor"]).round(2)
```

**返回格式与特点**

- 列序：`date, open, high, low, close, volume, amount`（`HEADERS` 全库统一）
- **volume 单位 = 股**（唯一不需要 ×100 的源）
- 失败重试 3 次，退避间隔 `0.3s × attempt`

#### ETF 走独立接口

```python
ak.fund_etf_hist_sina(symbol="sh515880")   # ETF 无复权参数，返回原始价
```

**注意**：新浪 ETF **不支持复权**，落库为原始价；因此 ETF 与股票在除权处理上不同源，跨类型比较时需留意。

---

### 2.3 腾讯 fqkline —— 增量降级源

**实现**：`update_daily.fetch_tx_qfq()`

```
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,2000,qfq
```

| 项目 | 说明 |
|---|---|
| `param` 结构 | `{sym},day,{start},{end},2000,qfq` |
| **铁律** | **起止日期留空**（`,day,,,2000,qfq`）→ 返回最新；**带日期参数会命中滞后缓存节点**（止于前日） |
| 返回字段 | `data[sym].qfqday`（优先）或 `data[sym].day` |
| 行序 | `[date, open, close, high, low, volume, (row[6])]` |
| volume | **手** → 需 ×100 |
| **amount** | **`row[6]` 通常是 dict 或缺失 → `amount = 0`** |

**代码要点**

```python
url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
       f"?param={sym},day,,,2000,qfq")     # ⚠ 不带日期
r = requests.get(url, timeout=20, headers=UA,
                 proxies={"https": None, "http": None})   # 直连，绕开本机代理
kl = data.get("qfqday") or data.get("day") or []
vol = float(row[5]) * 100.0                # 手 → 股
amt = float(row[6]) if isinstance(row[6], (int, float)) else 0.0   # ⚠ 多数为 0
```

**定位**：**只做增量追加，绝不做复权重拉**。原因见 §4.3 与 §5.4。

---

### 2.4 腾讯 day —— 退市股专用（不复权）

**实现**：`fetch_full_universe.fetch_tx_delist()`

```
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2015-01-01,{END},2000,
```

> 注意最后一个字段（复权标识）**故意留空** → 返回**不复权**数据。

**为什么退市股必须走不复权**：腾讯**前复权对退市股仅保留约 500 根 K 线（截断）**，而不复权数据从 2015 年起完整。因此退市股历史只能取不复权序列。

**代价**：`amount = 0`（该接口不含成交额），且与在市股票存在复权口径差；退市股仅用于补全「全量回测池」的生存偏差校正，不进入实盘信号链路。

---

### 2.5 腾讯 qt.gtimg.cn —— 盘中实时行情

**实现**：`build_market_breadth.py`

```
https://qt.gtimg.cn/q=sz000001,sh600000,sh688111,...
```

| 项目 | 说明 |
|---|---|
| 请求头 | `User-Agent: Mozilla/5.0 NiuOne/1.0`、`Referer: https://stock.qq.com/`、`Connection: close` |
| **编码** | **GBK**（必须 `.decode("gbk", errors="replace")`） |
| 分隔 | 每条 `v_sz000001="字段1~字段2~...";`，字段以 `~` 分隔 |
| 字段数 | ≥ 49 个 |
| 关键字段 | `fields[2]` = 代码、`fields[3]` = 当前价 |
| 时间戳 | 末段 14 位 `YYYYMMDDHHMMSS`（东八区） |

**默认参数**（可用环境变量覆盖）

| 参数 | 默认值 | 环境变量 |
|---|---|---|
| 分块大小 | 200 只/块 | `DEFAULT_CHUNK_SIZE` 对应项 |
| 并发 | 10 | `DEFAULT_WORKERS` |
| 单次截止 | 25s | `DEFAULT_DEADLINE_SECONDS` |

**适用场景**：市场情绪晴雨表（涨跌平 / 涨跌停炸板 / 量能）、盘中实时价 patch。**不用于历史 K 线**。

**代码空间**（有界扫描，避免全市场 5000+ 只）：

```
sz000001–sz003999 | sz300001–sz301999 | sh600000–sh605999 | sh688000–sh689999
```

---

### 2.6 东方财富 push2his —— 备选提速源

**实现**：`fast_em_fetch.py`

```
https://push2his.eastmoney.com/api/qt/stock/kline/get
  ?secid={secid}&fields1=f1,f2,f3,f4,f5,f6
  &fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
  &klt=101&fqt=1&beg={beg}&end={end}
```

| 参数 | 说明 |
|---|---|
| `secid` | `sh → 1.xxxxxx`；`sz/bj → 0.xxxxxx` |
| `klt` | `101` = 日线 |
| `fqt` | `1` = 前复权（与新浪 qfq 口径一致，实测价格完全吻合） |
| `beg` / `end` | `YYYYMMDD`，**支持增量区间**（只拉缺失段） |

**特点**：纯 JSON、**无 JS 解码** → 0.17s/只；volume = 手（×100）。适合作为新浪慢速封装的替代提速路径。

---

### 2.7 westock —— 降级兜底（2026-09-14 升级为可脚本化）

**实现**：`westock_dump_builder.py`（新，拉数+生成 dump）+ `fetch_close_westock.py`（原有，合并落库）

**背景**：此前 ⑦ 是**人工**步骤（agent 用 westock MCP `data_kline` 拉数 → 手工整理 dump JSON）。2026-09-14 本机装了 **westock CLI**（腾讯自选股，`C:\Users\Admin\.local\bin\westock.exe`，无 key、无 MCP 依赖）→ 该步骤已可全自动。

**两段式流程（现可一条命令）**

```bash
# 1) 生成 dump（自动：CLI 拉数 → 解析 markdown → 只保留「比本地更新」的行）
python westock_dump_builder.py --lag-list data_lag_list.csv --limit 200
python westock_dump_builder.py --codes sh600301,sz000001 --days 5
# 2) 合并进 data_full
python fetch_close_westock.py --dump westock_dump_20260914.json
```

**dump 格式**（不变，勿改行序）

```jsonc
{
  "sh600498": [["2026-08-19", 39.5, 37.35, 39.97, 37.01, 850587, 3274091599], ...],
  "sz002185": [[...]]
}
```

**⚠ 行序铁律**

```
[date, open, last, high, low, volume, amount]
              ^^^^ last = 收盘价（不是 high！）
```

`WESTOCK_COLS = ["date", "open", "last", "high", "low", "volume", "amount"]`
> 历史事故：曾按 `[date,open,high,low,close,...]` 解析 → `last→high / high→low / low→close` **整体错位**。已修复，勿回退。

**⚠ 停牌全零行（2026-09-14 新增，勿删）**：westock 对**停牌日**返回 `open/high/low/volume/amount 全 0` 的占位行（仅 `last` = 前收）。实测 `sh600301` 2026-09-14：
```
| 2026-09-14 | 0 | 45.43 | 0 | 0 | 0 | 0 | 0 | 0 |
```
直接合并会写出「全零 K 线」→ 毒化 ATR / rolling-min / 量比 / 换手类因子。`westock_dump_builder.py` 已按「open=high=low=volume=0 即丢弃」过滤并单独打印 **[停牌] N 只**；手工路径同样必须滤。

- volume = 手 → ×100（`fetch_close_westock` 内已处理）；最新在前（倒序）
- 仅用于**已有本地文件**的补数；新标的不走此路径（须走 `fetch_full_universe.py` 建库）
- 其他维度（本机 CLI 实测均可用）：`chip` 筹码成本分布、`sector valuation`（板块估值**历史百分位+月/季/周/年对比**）、`sector oper/forecast/finance`（申万经营/预测/财务）、`fund north-holding|south-holding|margin|block`、`notice|risk|report|consensus|esg|score`、`macro`（cn/us/hk/jp/eu）——见 vault `06-信息基础设施-Infra/ops-搜索与金融数据源选型.md`

---

### 2.8 tushare pro —— 预留占位

`update_daily.py` 中已预留第三源注册位（`fetch_ts_pro_daily`），可在新浪/腾讯双源失效时补充：

```python
# pro.daily(...) + adj='qfq'，需自备 token（环境变量 TUSHARE_TOKEN）
# 当前无 token → 仅占位，不启用
```

---

### 2.9 akshare —— 库角色

akshare **不是独立数据源**，而是对上述源（新浪、腾讯、东财）的封装库。在本项目的使用方式：

| 调用 | 实际背后源 | 用途 |
|---|---|---|
| `stock_zh_a_daily(adjust="qfq")` | 新浪 | A 股日线（qfq） |
| `fund_etf_hist_sina` | 新浪 | ETF 日线（原始价） |
| `stock_zh_a_spot()` | 新浪快照 | 在市股票列表 |
| `fund_etf_category_sina` | 新浪分类 | ETF 列表 |
| `stock_info_sh_delist` / `stock_info_sz_delist` | 东财 | 退市股票列表 |
| `stock_zh_a_hist_tx(adjust="qfq")` | 腾讯 | 补数重试（走不同域名，抗 WAF） |

> **为什么还要自己写直连**：akshare 的 JS 解码开销（1.79s/只）是性能瓶颈，且部分接口无复权参数 / 行序不一致，需绕过封装直连。

---

## 3. 调用方式与适用场景矩阵

| 场景 | 首选源 | 脚本 | 命令 |
|---|---|---|---|
| **每日全库增量（收盘后）** | ① TickFlow 批量 | `tickflow_update.py` | `python tickflow_update.py --workers 10` |
| **一键收盘管道（7 步）** | ① → ② → ③ 自动 | `refresh_daily.py` | `python refresh_daily.py` |
| **首次全量建库** | ② 新浪 + ④ 腾讯 | `fetch_full_universe.py` | `python fetch_full_universe.py` |
| **盘后增量 + 自带多源降级** | ①→②→③ 自动探测 | `update_daily.py` | `python update_daily.py` |
| **复权基准规范化重拉** | ② 新浪（**唯一**） | `update_daily.run_rebase_check()` | 收盘管道自动触发 |
| **单只快速取数（研调）** | ② 新浪直连 | `fast_sina_fetch.py` | `python fast_sina_fetch.py sh600000` |
| **单只增量（东财备选）** | ⑥ 东财 | `fast_em_fetch.py` | `from fast_em_fetch import fetch_em_incr` |
| **历史补数重试（抗 WAF）** | ③ akshare hist_tx | `retry_hist_tx_0821.py` | `python retry_hist_tx_0821.py --workers 6` |
| **退市股历史** | ④ 腾讯 day | `fetch_full_universe` 内 | 建库流程内自动分流 |
| **ETF 历史** | ② 新浪 ETF | `fetch_sina_etf` | 建库流程内自动分流 |
| **盘中实时行情 / 全市场快照** | ⑤ 腾讯实时 | `build_market_breadth.py` | `python build_market_breadth.py --output market_breadth.js` |
| **极简报错后的人工补数** | ⑦ westock MCP | `fetch_close_westock.py` | `python fetch_close_westock.py --dump <file>.json` |
| **基金净值** | 东财（`v8_fund_system`） | — | `python refresh_daily.py --fund` |

---

## 4. 优先级与降级/回退顺序

### 4.1 历史日线增量（主链路）

**优先级判断依据 = 新鲜度优先，其次吞吐。**

```
                        探样 sh600000，取回最新日期 tf_d
                                   │
              ┌────────────────────┴────────────────────┐
              │  tf_d >= expected_trade_date() ?        │
              └────────────────────┬────────────────────┘
                    是 ┌───────────┴───────────┐ 否
                       ▼                       ▼
              source = "tickflow"      探样新浪 sina_d
              （100 只/批 × 10 并发）          │
              ┌────────────────────┬──────────┴──────────┐
              │ sina_d >= exp ?    │                     │
              └────────┬───────────┘                     │
                是 ┌───┴───┐ 否                          │
                   ▼       ▼                             ▼
          source="sina"  source="tx"      ┌── 仍滞后/失败 ──┐
          （逐只 0.4s）  （腾讯 qfq 降级）  ▼                ▼
                                    报错 + 输出 westock 降级指引
                                    不盲目拉取（避免旧数据覆盖/卡死）
```

**回退顺序**：**① TickFlow → ② 新浪 → ③ 腾讯 fqkline qfq → ⑦ westock（人工）**

**逐级判断细节**

| 级别 | 判断 | 命中动作 |
|---|---|---|
| ① TickFlow | 探样 `sh600000`，`tf_d >= exp` | `source="tickflow"`，批量 100 只/批 × 10 并发 |
| ② 新浪 | TickFlow 失败或滞后 → 探样新浪 | `source="sina"`，逐只 8 线程（0.4s/只） |
| ③ 腾讯 qfq | 新浪失败或滞后 | `source="tx"`，**自动进入 `--pools-only` 模式**（只补池内+跟踪池） |
| ⑦ westock | ③ 也滞后 | **报错退出**，打印 westock 降级指引，**不盲目拉取** |

**为什么降级源自动缩到 `--pools-only`**：新浪源连续多日滞后时全市场滞后来可达数千只，腾讯逐只重拉需 1–2 小时。此时只保「池内 + 跟踪池（含掉榜标的）」新鲜，避免管道卡死。

**⚠ 降级模式的卡死与续跑（2026-09-14 实测，见 §7 Q12）**：降级（tx）跑完增量 + 复权检测后，进程可能**无法退出**（疑似线程池 worker 阻塞在无超时 socket 上）→ 收盘链在这一步挂住、后续步骤全部不执行。判据与处置见 Q12。

**2026-09-14 真实降级链回执**：15:39 探样 TickFlow 返回 **09-10**（滞后）→ 探样新浪返回 **09-11**（滞后）→ 自动切腾讯 qfq 降级（`--pools-only`，411 只池内+跟踪池 28 秒更新完）→ 复权检测 400 候选/0 修复（16:21）。**16:33 复测 TickFlow 已恢复**（返回 09-14）→ 直接跑 `tickflow_update.py --workers 10` 补齐全市场（原 1–2 小时的活降到分钟级）。**源滞后是分钟级抖动，降级后应择机复测首选源并回补全市场。**

**「预期最新交易日」判定**（`expected_trade_date()`，工作日启发式，无节假日历）：

```python
d = now.normalize()
if now.hour < 15: d -= 1 day     # 15:00 前视为未收盘 → 昨日
while d.weekday() >= 5: d -= 1 day   # 跳过周末
```

### 4.2 全量建库（按标的类型分流，非延迟竞争）

首次建库时，不同标的**没有优先级之分，而是按类型分流**：

| 标的类型 | 源 | 复权 | 说明 |
|---|---|---|---|
| 在市 A 股（沪深北） | ② 新浪 `stock_zh_a_daily` | qfq | 约 5542 只，0.4s/只 |
| ETF（约 1629 只） | ② 新浪 `fund_etf_hist_sina` | **原始价** | 新浪 ETF 无复权参数 |
| 退市股票（沪 159 + 深 208） | ④ 腾讯 `day` | **不复权** | 复用腾讯前复权会截断至 500 根 |

循环内节流：股票/ETF `sleep 0.35s`，退市股 `sleep 0.5s`；断点续跑（文件存在且 >100 字节即跳过）。

### 4.3 复权规范化重拉（强制新浪）

**这是全链路唯一一处「指定源、不允许降级」的地方。**

```python
# update_daily.run_rebase_check()
fetcher = F.fetch_sina_daily      # ⚠ 强制新浪；参数 source 仅保留调用兼容，一律忽略
```

**为什么必须锁死新浪**：

1. **跨源存在系统性口径差**：2026-09-05 三源对照实测，新浪 vs 腾讯 qfq 最高 **0.72%** 系统性偏差（如 `sh600351` 实测 53 行不一致）。
2. 若用「当前活动 source」（可能已是 tx）做验证/覆盖，会把复权基准在 **sina/tx 之间来回振荡**，漂移永远修不干净。
3. 腾讯**仅作增量追加**是安全的——增量 append 当日行不受 qfq 历史基准影响；**但绝不用于复权重拉覆盖**。

### 4.4 实时行情

无降级设计（单源：⑤ 腾讯 `qt.gtimg.cn`）。若失败则该轮晴雨表数据缺失，不阻塞主链路（`build_market_breadth.py` 有截止时间与最小行数阈值保护）。

### 4.5 判断依据汇总（为什么是这个顺序）

| 判据 | 说明 | 影响的顺序 |
|---|---|---|
| **新鲜度（首要）** | 探样返回日期是否 ≥ 预期最新交易日 | 决定 ①/②/③ 谁被激活 |
| **吞吐** | 100 只/批 vs 1.79s/只 vs 0.17s/只 | TickFlow 优先；东财可作新浪替代 |
| **复权口径一致性** | 新浪是规范化基准；腾讯与其有 0.72% 差 | 腾讯只能降级增量、不能重拉 |
| **接口能力边界** | 横截面 vs 单只；是否支持增量区间 | 决定各源分工 |
| **抗限流** | akshare hist_tx 走不同域名，未受 WAF 限制 | 打 WAF 时的补数通道 |

---

## 4.6 分工定案：日更 / 批量历史 / 按需（2026-09-16）

**背景**：同一天里既要「每天拿到全市场最新截面」，又要「一次性建十几年历史库」，还要「临时查一只票」——
三种活的成本结构完全不同，**混用会造成小时级等待（已踩坑：用东财分页做日更）**。定案如下：

| 场景 | 走哪个源 | 形态 | 实测 |
|---|---|---|---|
| **日更（每日 15:35 后，增量截面）** | **fuyao（同花顺官方 MCP，已在 ZCode）** | 一次调用返回**当日全市场** | 龙虎榜实测：**1 次调用 = 73 条**（含机构/游资净额、涨停原因、概念、热度、1日/3日区间），**零分页** |
| **批量历史（一次性建库）** | **东财 datacenter 分页** | 500 行/页，脚本化翻页、断点续跑 | 2026-09-16 建成 13 表 ≈300MB（业绩预告 84.7MB / 大宗 57.5MB / 龙虎榜席位 54.8MB / 龙虎榜明细 44.3MB / 股东户数 36.2MB / 增减持 14.4MB …） |
| **按需单票 / 小批量** | **westock CLI** | 单二进制、无 key | `fund margin|lhb|block <code>` 实测 **844~887 ms/次** |
| 成篇研究报告 / Excel 模型 | Wind Alice（`alice-financial-copilot`） | 自然语言出报告，耗积分 | key 已配 `~/.wind-alice/config.env` |
| 分钟线 / 25 年日线 | TDX/TQLEX 直连（`tdxhub.icfqs.com:7615`，token 在 `personal/api-keys.md`） | 单票直连 | 见 §2.7 上文与分时三源表 |

**冒烟自检（各源一行，出问题先跑这个）**：
```bash
# fuyao（同花顺官方）：当日龙虎榜截面（应返回 count>0 且有 stock_items）
#   —— 在 ZCode 内直接调用 MCP 工具 get_a_share_special_data_dragon_tiger_list
# westock CLI（~0.9s）
westock fund lhb sh600519
# 东财 datacenter（分页）：任一 altdata 脚本的小样模式
python backtest/altdata_lhb.py --limit 1
# TDX/TQLEX 直连
python backtest/tdx_data_0913.py --help
```

**注意**：ETF 不在本表讨论范围（短线线自有 ETF 轮动）；本表服务于「行情 + 资金/筹码 + 事件」三条数据主线。

## 5. 复权（qfq）处理逻辑

### 5.1 为什么统一前复权

- 全仓库下游（`v9_auto` / `khunter` / `build_dual_system` 等）全部按 `data_full/<sym>.csv` 路径读取，**统一前复权**。
- 切换复权口径（如改后复权）会让**全部历史回测数值作废**——收益远小于风险。
- 因此吸收外部工程写法时：**吸收「断点表 + 索引」思想，不吸收存储与复权口径变更**。

### 5.2 新浪 qfq 的两条实现路径

| 路径 | 实现 | 公式 |
|---|---|---|
| akshare 封装 | `stock_zh_a_daily(adjust="qfq")` | 库内部处理 |
| 直连 | `fast_sina_fetch.py` | `qfq 价 = 原始价 ÷ qfq_factor`，round(2) |

因子缺失日用 `ffill()` 向前填充后统一除算。

### 5.3 复权基准漂移（除权假缺口）检测

**问题场景**：某股**当天除权**，其尾日 = 最新 → 被判「fresh」→ **不重拉** → 本地历史仍停在除权前基准，而新增行是真实价 → 除权日出现**假缺口**（假 `-X%` 污染 RSI / 突破信号 → 误触发超卖买入）。

**兜底检测**（收盘管道每日自动跑，`run_rebase_check()`）：

| 常量 | 默认值 | 含义 |
|---|---|---|
| `REBASE_JUMP_PCT` | `5.0` | 近 32 日存在 \|单日跳变\| ≥ 此值 → 候选（疑似除权假缺口） |
| `REBASE_VOL_MAX` | `4.0` | 且跳变日成交量 ≤ 前 5 日均量 × 此值（真涨跌停通常放量，除权正常量） |
| `REBASE_DRIFT_PCT` | `0.3` | 重拉 qfq 对比重叠区 \|Δ\| > 此值 → **确认**基准漂移 |
| `REBASE_MAX_CAND` | `400` | 每日候选上限（防异常行情日扫崩） |

**三段式流程**：

```
① 候选剪枝（无网络）→ 近 32 日 ≥5% 未放量跳变
② 重拉验证（有网络）→ 与本地重叠区比对 |Δ收| > 0.3% 确认为漂移
③ 全量 qfq 重拉覆盖 → 统一到新浪口径
```

**关键细节**

- 阈值 0.3 是**对齐 A1 证据阈值**后的选择：0.5 会漏掉 `sh603259`(-0.329%) 与 `sz300012`(-0.367%)；新浪源自比噪声 ≈ 0，无假阳性风险。
- **限流保护**：候选间 `sleep 1.2s`（0.35s 连发 400 请求会触发新浪限流 → 整批 verify 静默失败 → 0 修复）。全量 400 候选约 8–10 分钟。
- **新浪不可用探针**：源不可用时**显式跳过本轮并打印**，避免静默漏检。

### 5.4 跨源复权差一览

| 源 | 相对新浪 qfq 的偏差 | 影响 |
|---|---|---|
| TickFlow | 约 **0.13%**（复权基准微差） | 可用作增量；不可用于规范化重拉 |
| 腾讯 qfq | 最高约 **0.72%**（个案） | 仅降级增量；**禁止重拉覆盖** |
| 东财 `fqt=1` | 实测价格**完全吻合** | 可作新浪替代提速源 |

---

## 6. 配置项与完整示例

### 6.1 关键常量表

| 常量 | 位置 | 默认值 | 说明 |
|---|---|---|---|
| `TF_API` | `tickflow_update.py` | `https://free-api.tickflow.org/v1/klines/batch` | TickFlow 端点 |
| `BATCH_SIZE` | 同上 | `100` | **API 硬上限** |
| `HIST_DAYS` | 同上 | `10000` | 请求历史根数 |
| `--workers` | 同上 | `10` | 并发批数 |
| `--skip-ttl` | 同上 | `30` | 跳过清单有效期（天） |
| `START_DATE` | `fetch_full_universe.py` | `20160101` | 建库起始 |
| `END_DATE` | 同上 | `20301231` | **必须取未来**（见 §7 Q4） |
| `UPD_RETRIES` | `update_daily.py` | `3` | 单只重试次数 |
| `_backoff` | `fetch_full_universe.py` | `1.5s → 3.0s → 6.0s`（封顶 8s） | 指数退避 |
| `STALE_DAYS` | `data_index.py` | `3.0` | manifest 过期天数 |
| `MIN_FILES` | 同上 | `100` | manifest 可信最小文件数 |
| `DEFAULT_CHUNK_SIZE` | `build_market_breadth.py` | `200` | 实时行情分块 |
| `DEFAULT_WORKERS` | 同上 | `10` | 实时行情并发 |
| `DEFAULT_DEADLINE_SECONDS` | 同上 | `25` | 实时行情截止 |

### 6.2 完整配置示例

**A. TickFlow 增量（推荐日常用法）**

```bash
# 全量增量：自动扫描滞后文件 → 批量更新
python tickflow_update.py

# 全库全量重建
python tickflow_update.py --all

# 只更新前 500 只滞后
python tickflow_update.py --limit 500

# 调整并发（默认 10）
python tickflow_update.py --workers 10

# 指定代码（逗号分隔）
python tickflow_update.py --symbols sh600000,sz000001

# 强制重试已知无源清单（默认 TTL 30 天）
python tickflow_update.py --no-skip
```

**B. 多源自动降级增量（带降级链路）**

```bash
python update_daily.py                      # 自动选源（TickFlow→新浪→腾讯）
python update_daily.py --limit 100          # 限量
python update_daily.py --only etf           # 仅 ETF
python update_daily.py --only stock         # 仅股票
python update_daily.py --source sina        # 强制新浪
python update_daily.py --source tx          # 强制腾讯降级源
python update_daily.py --all                # 降级源下也全量（约 1–2 小时）
python update_daily.py --force              # 源滞后也继续（节假日场景）
```

**C. 收盘一键管道**

```bash
python refresh_daily.py            # 完整 7 步（含基金净值则加 --fund）
python refresh_daily.py --fund     # 含基金净值更新（较慢）
python refresh_daily.py --skip-fetch   # 跳过行情拉取，只重建看板
```

**D. 实时行情快照**

```bash
python build_market_breadth.py --output market_breadth.js
```

**E. 单只取数（研调/验证）**

```bash
python fast_sina_fetch.py sh600000        # 新浪直连前复权
```

```python
# 东财增量（区间）
from fast_em_fetch import fetch_em_incr
df = fetch_em_incr("sh600000", "2026-09-14")          # 默认从 20160101 起
```

**F. westock 人工兜底**

```bash
# 1) agent 用 westock MCP data_kline 拉取 → 整理为 dump JSON
# 2) 合并进 data_full
python fetch_close_westock.py --dump westock_dump_2026-09-14.json --codes data_lag_list.csv
```

### 6.3 环境与目录配置

| 项目 | 值 |
|---|---|
| 历史库目录 | `data_full/<sym>.csv`（统一列序 `date,open,high,low,close,volume,amount`） |
| 索引 manifest | `data_full/_index.csv`（字段 `sym,last_date,rows,mtime,size`） |
| 滞后清单 | `data_lag_list.csv` |
| 失败清单 | `data_full_fail_list.csv`（TickFlow 专有：`data_full_fail_list_tickflow.csv`） |
| 跳过清单 | `data_full_skip_list.csv`（`sym,YYYY-MM-DD` 两列，TTL 30 天） |
| 指数源 | `index_000300.csv`（**唯一源**，看板 `as_of` 取末行日期） |
| 符号约定 | `sh600000` / `sz000001` / `bj920000` |
| 代理 | 腾讯/东财请求显式 `proxies={"https": None, "http": None}` 直连 |

---

## 7. 常见问题与注意事项

### Q1 成交量单位为什么必须统一为「股」？

**全库落库单位 = 股**，但多数源的原始单位是**手**。各源处理方式：

| 源 | 原始单位 | 落库动作 |
|---|---|---|
| TickFlow | 手 | **×100** |
| 新浪（`klc_kl.js`） | 股 | 不动 |
| 腾讯 fqkline | 手 | **×100** |
| 腾讯 day（退市） | 手 | **×100** |
| 东财 push2his | 手 | **×100** |
| westock | 手 | **×100** |

**自检判据**：

```
r = (amount / volume) / close
```

| r 区间 | 判定 |
|---|---|
| `r < 3` | 正常（单位已是股） |
| `3 < r ≤ 15` | 可疑 |
| `r > 15` | **单位是手，未换算** |
| `r ∈ (1.5, 3)` | 盲区 → 查复权连续性区分（Class-B 断裂 / 合法） |

> **事故记忆**：2026-09-12 全库收口 `263,837 行 × 100` + 6 处源头补丁（changelog v5.13.2）。**任何新增数据源/新增接口，落库前必须跑一次该判据。**

### Q2 腾讯源为什么绝不能覆盖成交额？

腾讯 `fqkline` 的 `row[6]` 通常是 dict 或缺失 → `amount = 0`。而 `merge_save()` 用 `concat(keep="last")`，**会拿这些 0 覆盖本地真实成交额**。

**2026-09-11 事故**：当日 `pools_only` 命中 410 只池/跟踪标的，把 2024-01-17 起成交额整段打成 0 → `v8_factor_cache` 重建后 `amt20 = 0` → `v9_rank_board` 的 `amt20 < 5e6` 过滤把它们全部剔除 → **选池被静默改写**（美盈森 002303 从 v9 中长线池消失）。

**两道防线**（保留，勿删）：

1. 新数据 `amount <= 0` 时**沿用本地同日真实值**（绝不拿 0 覆盖非 0）；
2. 合并后对仍为 0 的 2024+ 行做 `vol × close × 多倍自锚定` 兜底。

### Q3 腾讯接口为什么不能带日期参数？

**带日期参数会命中滞后缓存节点**（返回止于前日的数据）。
→ **必须用无日期变体**：`,day,,,2000,qfq`。

### Q4 `END_DATE` 为什么必须取「未来」？

`fetch_full_universe.py` 中 `END_DATE = "20301231"`。

> 历史事故：其曾硬编码为 `"20260814"`，导致 `fetch_sina_daily` 只返回到 08-14，而本地已到 09-04。`run_rebase_check` 用它全量覆盖漂移文件时，会把本地文件**截断回 08-14 → 丢失近 3 周真实行情**。改为远未来日期后，新浪源才返回最新数据，全量覆盖才安全。

### Q5 限流怎么处理？

| 场景 | 处理 |
|---|---|
| 新浪 rebaes 验证 | 候选间 `sleep 1.2s`（0.35s 连发 400 请求必触发限流） |
| 建库循环 | 股票/ETF `sleep 0.35s`；退市 `sleep 0.5s` |
| 通用退避 | `_backoff()`：`1.5s → 3.0s → 6.0s`（封顶 8s） |
| 腾讯 24 并发打 WAF | 改用 `akshare hist_tx`（走不同域名，未受限） |
| 单只重试 | `UPD_RETRIES = 3` + 指数退避 |

### Q6 节假日被误判为「源滞后」怎么办？

`expected_trade_date()` 是**工作日启发式、无节假日历**，节假日会误判为滞后 → 自动切腾讯源（腾讯同样返回最近交易日，切换无害）；腾讯也滞后才报错。

**此时**：确认是节假日后加 `--force` 继续。

### Q7 停牌 / 退市股票怎么处理？

| 情况 | 处理 |
|---|---|
| 长期停牌 / 退市 / 源不提供 | 记入 `data_full_skip_list.csv`，**TTL 30 天**后自动重试（防复牌被永久跳过） |
| 源本身滞后（有数据但末行 < 全库最新） | 归入 `stale`，同样进跳过清单 |
| 退市股历史 | 走腾讯 `day`（**不复权**，前复权对退市股仅 500 根截断） |

### Q8 并行更新会不会写坏文件？

不会——**按符号分文件，不同 sym 写不同文件无冲突**；且 `save_csv()` 采用**临时文件 + `os.replace()` 原子写**，避免并行写产生半截文件。

### Q9 滞后扫描为什么有时很快、有时很慢？

走 `data_full/_index.csv` manifest（断点表）：
`≡ SQL SELECT symbol, MAX(date) GROUP BY symbol`，**4.5s → 0.53s（8.5x）**。

manifest **缺失 / 过期（>3 天）/ 文件数偏差 >10%** → **自动回退全量扫描**（行为与旧版逐位一致）。

### Q10 PandaData Connector 能用吗？

**账号级 API 权限不足**：`auth_status` 返回正常（`ok=true`、`data_mode=gateway`），但**所有业务方法返回 `200103 API访问权限不足`**，非方法/参数问题。

→ **业务数据一律走本地 `data_full`**，报告须披露调用回执（见附录 B）。

### Q11 数据修复后的审计纪律

- 按 **mtime** 审计「产物 vs 修复时间」——修复前的产物必须重跑。
- **污染影响面 ≠ 窗口内笔数**：必须重跑，不能只改窗口内记录。
- **口径变化必须隔离实验**，不得与策略改动混跑。

### Q12 降级模式跑完后进程不退出（收盘链挂住）怎么办？

**现象（2026-09-14 实测）**：`update_daily.py` 在 tx 降级通道下打印完「复权基准检测完成」后**再无输出、进程不退出**；`daily_refresh.py --force` 因此在第一步卡住 52 分钟（日志末行停在复权检测），整条链中止：`❌ 失败: 数据更新 update_daily · 总耗时 3141s`。

**判据（勿凭猜，按此三步取证）**：
1. **日志 mtime 停滞**（>5 分钟无新行）；
2. **CPU 采样不动**：连续两次采样 `Get-Process <pid> | Select CPU`，20 秒内增量为 0 → 不是在算；
3. **IO 增量为 0 且有残留 TCP 连接**（`Get-NetTCPConnection -OwningProcess <pid>`）→ 阻塞在网络等待（疑似线程池 worker 无超时读）。
> 与「复权检测慢」区分：检测阶段每只 `sleep 1.2s`、400 只约 8–10 分钟，期间**进程 CPU 会缓慢增长**且最终会打印完成行。

**处置**：
```bash
# 1) 数据是否已落盘（先验证，别急着重跑）
tail -2 index_000300.csv                 # 指数是否已到当日
head -3 data_lag_list.csv                # 滞后清单已生成
# 2) 只杀自己的链（PID 见 Get-CimInstance Win32_Process 的父子关系；勿用 /T 误伤他人进程）
# 3) 跳过数据步续跑剩余全链
python daily_refresh.py --force --skip-data
# 4) 首选源恢复后回补全市场
python tickflow_update.py --workers 10
```
**★★ 最终定案（2026-09-16，纠正 09-15 的结论）**：真正的「进程永不退出」根因是
**py_mini_racer 在解释器退出阶段 join 其 `run_event_loop` 线程且无超时**（与代理无关）。
- **最小复现**：一个**只**执行 `MiniRacer(); c.eval("1+1")` 的脚本 → 解释器退不出（外部 `timeout` 杀掉，exit=124）；
  线程表可见 `Thread-1 (run_event_loop)` 残留。
- 因此 0914 / 0915 / 0916 三天日志都恰好停在「复权基准检测完成」之后——**复权检测是唯一使用 akshare
  （→ py_mini_racer JS 解码）的相位**。
- **修复**：`update_daily.py` 在 `__main__` 收尾处 `sys.stdout.flush(); os._exit(rc)`（绕过 atexit / 线程 join）。
  验证：同一最小复现脚本加 `os._exit(0)` → **exit=0 秒退**；真实数据步端到端（`REBASE_BUDGET_S=8 --limit 2`）
  → **14 秒自行退出、rc=0**（修复前必被 timeout 杀）。
- 09-15 记录的「akshare 请求无 timeout × 代理抖动」是**另一**真实问题（循环内单候选阻塞），
  由「单候选 90s 闸」兜住；相位预算同时由 1500s 上调为 **2400s（可 env `REBASE_BUDGET_S` 覆盖）**
  ——实测 400 候选正常需 ~30min（0916 只跑完 336/400 就耗尽 1500s）。两者都保留。

**✅ 根因已定位并修复（2026-09-15 深夜）**：真因不是「线程池缺 shutdown」，而是
**akshare `stock_zh_a_daily` 内部的 `requests.get` 不带 timeout**（`akshare/stock/stock_zh_a_sina.py:177`），
而**本机代理（`127.0.0.1:<随机端口>`，VPN/Clash 类）会抖动**——代理一挂/半死，该请求就永久阻塞，
`run_rebase_check` 的串行循环随之整段挂死（0914 卡 52min / 0915 卡 76min 同一机制；
实测证据：故障时 akshare 抛 `ProxyError: Unable to connect to proxy 127.0.0.1:48765`，
同一时刻 `urllib.getproxies()={}` 且显式禁代理的 `requests.get` 返回 200 → 证明是瞬时/半死代理态）。

**已落地的三层防护**（口径不变——仍用 akshare 通道，因其为历史基准权威）：
1. **单候选墙钟上限** `REBASE_TRY_TIMEOUT=90s`：`_run_with_deadline()` 用 daemon 线程包裹
   `verify_rebase_drift` 与全量重拉，超时打印 `[超时] … 跳过（不再阻塞整相位）`；
2. **整相位预算** `REBASE_BUDGET_S=1500s`：用尽即收工并打印 `[收工] 已处理 x/y`，剩余候选下次续跑；
3. **探针也入闸**：`probe_date()` 加 60s 上限（它是链路第一个网络调用，此前若卡死会先卡在探针）；
4. **数据步进程环境禁代理**：`daily_refresh.py` 给「数据更新」步注入 `HTTP_PROXY='' / NO_PROXY='*'` 环境
   （akshare 改不了 timeout，就让它不经过代理；git push 等步骤仍用默认环境，不influence GitHub 访问）。

**验证证据**：`_run_with_deadline(lambda: sleep(9999), 3)` → 3.0s 返回且不误伤正常调用；
probe 失败路径 → 立即跳过打印「新浪源不可用」；端到端 3 只候选走完整检测 → 12.7s 完成并正确修复
`bj920006` 基准漂移（810 行）。

**附带修复（同次排查发现，两个静默缺陷）**：`fast_sina_fetch.py`（新浪直连快通道）此前**对所有标的静默返回 None**——
① 新浪 `klc_kl.js` 日期带 `Z`（UTC-aware）与 `qfq.js` 朴素日期 merge → `TypeError: Cannot join tz-naive with tz-aware`；
② 全表 `ffill().dropna()` 把未使用列（postVol/postAmt）的空值当作缺失 → 6005 行被砍到 52 行。
两处已修（现返回 2601 行 / 3.3s）。**但该通道与 akshare 存在历史基准差**（茅台 2203/2590 行差>0.01；
北交所 `bj920006` 最大差 31%）→ **不可用于复权重拉**，仅作速度路径候选，用前须逐票对拍。

### Q13 westock 补数时哪些行必须丢弃？

**停牌全零行**：westock 对停牌日返回 `open/high/low/volume/amount 全 0`（仅 `last`=前收）。实测 `sh600301` 2026-09-14。合并前必须过滤（判据：open=high=low=volume=0 → 丢弃），否则写出假 K 线毒化 ATR / rolling-min / 量比。`westock_dump_builder.py` 已内置该过滤并打印 `[停牌] N 只`。详见 §2.7。

---

## 附录 A：文件与代码索引

| 文件 | 职责 |
|---|---|
| `tickflow_update.py` | TickFlow 批量增量更新器（首选源） |
| `update_daily.py` | 多源自动降级日线增量（主编排） |
| `refresh_daily.py` | 收盘 7 步一键管道 |
| `fetch_full_universe.py` | 全量建库（新浪 + 腾讯退市分流）、`fetch_sina_daily` / `fetch_sina_etf` / `fetch_tx_delist` / `save_csv` / `_backoff` |
| `fast_sina_fetch.py` | 新浪直连前复权（线程复用 MiniRacer） |
| `fast_em_fetch.py` | 东财 push2his 增量（前复权，纯 JSON） |
| `fetch_close_westock.py` | westock 补数合入 data_full（dump JSON → 落库） |
| `westock_dump_builder.py` | **（2026-09-14 新增）** 调本机 westock CLI 拉数 → 生成 dump JSON（含停牌全零行过滤），把原人工步骤自动化 |
| `data_index.py` | `_index.csv` manifest 断点表 + 索引 |
| `build_market_breadth.py` | 腾讯实时行情快照（晴雨表） |
| `retry_hist_tx_0821.py` | 腾讯 hist_tx 补数重试（抗 WAF） |
| `fetch_hist_akshare.py` | akshare 批量历史下载（新浪） |
| `_tmp_verify_qfq.py` | 本地 vs akshare 官方 qfq 逐日口径对比 |

## 附录 B：数据源可用性回执

> 采集时间：**2026-09-14 16:07 (GMT+8)**。以下为网关真实返回，未做任何推断补数。

| 接口 | 实际参数 | 状态 | 行数 | 数据日期范围 | 关键字段 |
|---|---|---|---:|---|---|
| `auth_status` | 无 | **成功** | — | — | `ok=true`、`auth_enabled=true`、`data_mode=gateway`、`username=8617602520599`、`reauth_required=false` |
| `get_last_trade_date` | 无 | **权限不足** | 0 | — | `code=200103`、`message=API访问权限不足` |
| `get_trade_cal` | `start_date=20260901, end_date=20260915` | **权限不足** | 0 | — | `code=200103`、`message=API访问权限不足` |

**结论**：PandaData 为**账号级权限不足**（认证通过、业务接口全禁），非方法名/参数错误，亦非 0 行空结果，故不触发「0 行参数复查」流程。已按契约显式报告阻塞状态与错误码。本项目业务数据统一走本地 `data_full` 面板，与本文档所述自主拉取链路一致。

### 附录 B-2：2026-09-14 收盘链路数据源回执（实测，未做推断补数）

| 时刻 | 源 | 探样/实测 | 返回日期 | 判定 |
|---|---|---|---|---|
| 15:39 | ① TickFlow | `sh600000` 探样 | **2026-09-10** | 滞后 → 回退 |
| 15:39 | ② 新浪 | 探样 | **2026-09-11** | 滞后 → 回退 |
| 15:39 | ③ 腾讯 qfq | 降级通道 | **2026-09-14** | 可用 → `--pools-only` 更新 411 只（28s，0 失败） |
| 16:21 | — | 复权基准检测 | — | 候选 400 / 确认漂移 **0**（耗时约 42 分钟） |
| 16:33 | ① TickFlow | 复测 `600000.SH`（3 根） | **2026-09-14** | **已恢复** → `tickflow_update.py --workers 10` 全市场补齐 |
| 16:33 | westock CLI | `kline sh600519 --fq qfq` | 2026-09-14（收 1277.96） | 可用（与本地/同花顺口径交叉一致） |
| 16:33 | westock CLI | `kline sh600301` | 2026-09-14 **全零行** | **停牌** → 已过滤（Q13） |

**覆盖面**（`data_full` 尾部日期分布）：16:29 = 09-14: **3025** / 09-11: 4189；16:41 = 09-14: **3875** / 09-11: 3339（TickFlow 补齐进行中）。

**判词**：8 个源里 ①② 同时滞后约 1 小时（分钟级抖动），③ 承担当日增量；**首选源恢复后必须复测并回补全市场**（本次 16:33 复测即恢复）。westock（⑦）现已可脚本化，降级链最后一环不再依赖人工。

**✅ 已结案（2026-09-15 复测，两条独立证据）**：`tickflow_update.py` 的自报计数**不可信**（打印「✅ 已更新 0 / 源滞后 N」），但**写入是真实发生的**——证据①：跑完后 `data_full` 覆盖面 7188/7540（95.3%）末行=当日；证据②：抽到的「仍非当日」标的为 sh600003/sh600005/sh600065 等**退市/长期停牌股**（本就不该有当日行情）。→ 结论：**计数口径 bug（待修，不影响数据）**，勿据此判断更新是否发生；判据一律用「末行日期分布」实测。
**下列原存疑标注已作废（保留供追溯）**：：本次 `tickflow_update.py --workers 10` 的**自身汇总与磁盘事实不一致**——它打印「✅ 已更新 0 / 源滞后 6886 / 无数据 300」，但同期 `data_full` 有 6972 个文件被重写、覆盖面从 3875 → 7183 只（95.3%）。两种可能未区分：(a) TickFlow 实际写入而计数器口径有 bug；(b) 写入来自另一路径（tx 降级/他处进程）。**已确认的事实**：覆盖面 95.3%、抽样 400 只单位自检 `r=(amount/volume)/close` 中位 0.999 / 最大 1.04 / 0 异常（口径正确）。**待办**：下次跑 TickFlow 时用「更新前差异行数」核对计数器口径；并复核 `data_full_skip_list.csv` 是否因误判把本应重试的标的锁 30 天。

---

*本文档仅供项目内部工程说明使用；所有回测与信号结论均不代表投资建议。*
