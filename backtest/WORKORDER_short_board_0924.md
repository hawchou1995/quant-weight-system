# 工单：短线板块 6 项任务收口（2026-09-24 起）

契约目标工件：`.pi/goal/收口短线板块-6-项任务-gushi-补采-免手动登录-打板族竞价置顶-左侧捡漏-热榜哨兵上线-子页隔离-云端与-pages-同-20260924-2207.md`
仓库：`D:/Documents/Workbuddy/股票基金/quant-weight-system`
PY：`C:/Users/Admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe -X utf8`（3.13）
bsk：`C:\Users\Admin\.local\bin\bsk.exe`（daemon pid 13356 / WS 52800；扩展 id `hhcmgoofomhgciiibhipgmgkgnoenaoi` v0.3.1，须处于「已启用」；session `lzpt` ← browser `71802be5`）

## 已完成（判据 A / B）
- **A** `bsk browsers` → `71802be5 chrome 153.0.0.0 0.3.1 1`；`session lzpt` → `https://i.gushi.in/factor.html` → `/api.php?action=me` 返回 JSON 且 `role=vip`。未 kill Chrome / 未复制 profile / 未取凭据。
- **B** 新增 `backtest/gushi_bsk_collect.py`（bsk 通道采集器，复用 `gushi_daily_collect.py` 的 FACTORS/RESON/counts/day_lines 作 schema 真值源；分块取数 10/6/6 + 失败降级逐端点；只有 `role=="vip"` 才落盘；`picks_daily.jsonl` 幂等追加）。
  - 实测：`--date 2026-09-24` → **factor 45 条 / resonance 587 条**；`gushi_data/health.json` 的 `2026-09-24` 由 `GAP_ALL` → **`OK`（jsonl 632 行）**。
  - `gushi_daily_collect.py` 的 `wait_clear()` 已改（备份 `.bak-waitclear-20260924_221656`，+15/−4）：判据含英文 `Just a moment...` + 轮询 `/api.php?action=me` 返回 JSON。
  - 残留（如实记录）：`2026-09-21/09-22` 仍 `GAP_RESON`（站点侧共振档位取回为空）。

## 未完成（判据 C~I）

### D｜`#bt-short` 参数化 + 恰好新增 2 个子标签（我本人做）
- `build_dual_system.py`：
  - L2609-2612 `SHORT_VIEW_HTML`：`subnav("short", [("st-qlch","超跌低开低吸"),("st-kh","超卖伏击"),("st-etf","ETF轮动"),("st-stk","股票池"),("st-fund","基金池")], default_key="st-qlch")` → **追加 `("st-zuoce","左侧捡漏")`、`("st-sentinel","热榜哨兵")`（恰好 +2，四字名）**。
  - L2647-2648 是 `.subview` 之外的**单块** `<div class="pool-sec">回测数据</div>{bt_short_html()}`（`bt_short_html()` 定义在 L1006）→ 被 5 个子标签共用 = 契约点⑤。
  - 改法：`bt_short_html()` 改为输出**每子标签一块** `<div class="bt-sub" data-bt-sub="<key>">…</div>`，由 `SUBNAV_JS` 在激活子标签时同步显隐（`.bt-sub{display:none}.bt-sub.on{display:block}`）。
  - `ui_subtab.py`：`SUBNAV_CSS` 加 `.bt-sub` 规则；`SUBNAV_JS` 的 `activate()` 里对 `view.querySelectorAll('[data-bt-sub]')` 按 `key` 切 `.on`。
  - 子标签 ↔ 回测内容映射（互不重复）：`st-qlch`=超跌低开低吸、`st-kh`=超卖伏击（现 `bt_short_html()` 的卡组）、`st-etf`=ETF、`st-stk`=股票池、`st-fund`=基金、**`st-zuoce`=左侧捡漏（bt520 纯左侧簿留出/全期）**、**`st-sentinel`=热榜哨兵（jiandi top30 影子）**。
  - 新增子视图：`subview("st-zuoce", "左侧捡漏", …, ZUOCE_CARD + watch_card(...))`、`subview("st-sentinel", "热榜哨兵", …, SENTINEL_CARD + watch_card(...))`。
  - L2966 侧栏过滤映射可选追加两项（非必需）。
- 构建：`python build_dual_system.py` → 产物 `index.html` 与 `dual_system.html`（1,142,771 B，两者同内容）。

### F｜物理隔离校验
- 已有 `_verify_track_sep_0923.py`（仓库根）→ 跑通留证据；新增子标签的选股池/跟踪池/模拟盘状态文件不得交叉读写。
- 新增产物命名一律带策略前缀：`zuoce_jianlou_*` / `sentinel_*`。

### C｜打板族竞价置顶（A5）
- 模板 = qlch 实时链路（ADR-0009，浏览器端判定）：`intraday_live.py`（`INTRADAY_JS` L22+、`QLCH_JS` L536-896、`judge()` L637-658、`render()` L697、`window.QLCH_ON_QUOTES` L459-460/L874、开市窗口 09:15–15:05 L124、`WL_TBL` L40、表 id 硬编码 L553）；`build_dual_system.py:2651-2734 qlch_live_payload()`。
- A5 侧：`a5_pool.js`（29,211 B）、`build_a5_pool.py`（仓库根，264 行）、`backtest/a5_experiment/paper_daban_a5.py`（`gap=o/pc-1`@L472、闭区间、`ROOM_MIN=0.20`）、`backtest/a5_paper_state.json`、A5 视图 `index.html` L715-796（`#view-a5`）。
- 判定口径：`gap∈[-5%,-2%]`（闭）、`rel_pos≤0.5`、`amt≥5e7`、`room≥0.20`；09:15–09:25 仅灰标「竞价预判」；09:25 后命中并置顶（视图态只改 DOM 顺序）。
- 夹具：`node v24.13.0` 跑真 JS，覆盖边界 `gap=-5.00%` / `-2.00%` 判命中。
- 与 D8 同区域（`intraday_live.py`/`build_dual_system.py`）→ **串行施工**。

### E｜复测门（bt520 留出）
- 产物 `backtest/bt520_holdout_0924.json`（子代理 `strategy-backtest-expert` fe06ac45 正在跑）。
- 留出段 2016-01-04→2017-12-29（488 交易日）；主口径 = 40 draws 随机起始日**年化中位数**；种子 `np.random.default_rng(20260926+d), d=0..39, offset=int(rng.integers(0,244)), ann_days=244`；冻结配置 `KB=5 · wB=0.8`；交付配置 `KB=5 · wB=1.0`（=左侧捡漏）。
- `>0` → 可上模拟盘；`≤0` → **只上回测数据、不开模拟盘**，结论写 `docs/adr/0010-short-board-new-strategies-onboarding.md`；再过 `overfit-auditor` DSR/PBO。

### H｜云端接入四处
1. `daily_refresh.py`：STEPS + git 白名单 + 校验清单
2. `.github/cloud/cloud_refresh.py`：SYNC 清单
3. 部署清单
4. 以一次链运行 rc=0 验证（否则给出 15:05 cron 等待核查口径）

### G｜推送与线上
- `git fetch` → 提交（含 `docs/adr/0010-*.md`，当前未被 git 跟踪）→ `git push origin main` → `HEAD == origin/main` → Pages build success → 线上 cache-bust 见 2 个新子标签。

### I｜当日产物 as_of = 2026-09-24
- `zuoce_jianlou_*`（左侧捡漏）与 `sentinel_*`（热榜哨兵）；打板族/超跌低开低吸当日池同为 2026-09-24。

## 纪律红线
- 不提取/打印 cookie/token/密码/身份字段；不绕 MFA；不复制 Chrome profile；**不 kill 用户 Chrome**。
- `E:\PI\投资\bt520_turtle_regime\` **只读不改**；要改参数须复制到 scratch 改副本。
- 改动先备份、幂等、`py_compile` 自检；失败如实记录，不放宽判据。
- 只动任务列出的改动点；其余共用点只出报告。
