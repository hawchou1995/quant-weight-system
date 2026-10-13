# gushi 数据采集管道 · 运维说明

> 建于 2026-09-24，2026-10-09 加固（R-gushi-pipeline-1009）。
> 本文是这条线的**唯一说明书**：断点、护栏、损失语义、排障。

---

## 1. 它是什么 / 什么时候跑

从 `i.gushi.in`（牛来量化选股）抓当日「策略股池 + 共振选股」数据，落盘后供回测与看板使用。

| 项 | 值 |
|---|---|
| 计划任务 | `GushiDailyCollect_1840`（Windows 任务计划程序） |
| 触发 | 周一~周五 **18:40**（`DaysOfWeek=62` = Mon–Fri） |
| 动作 | `cmd.exe /c "<repo>\backtest\gushi_daily_run.cmd"` |
| 身份 | user `Admin`，`RunLevel=Limited`，`LogonType=Interactive`（**需已登录桌面**，Chrome 自动化要桌面会话） |
| 单轮耗时 | 常态 2–6 分钟；含重试约 10 分钟 |

**为什么是 18:40**：站点当日数据实测最早 **~16:22** 才上线；采集器自己也有一道
`--allow-early` 守卫，早于 16:20 会**主动拒绝**采当日，防止抓到半成品。

### 硬约束：共振数据只对「最新交易日」存在

站点共振接口（`r_*`）**只提供最新交易日**的数据。当天不采，**该日共振永久丢失**（`health.json` 标 `GAP_RESON`）。
策略数据（`f_*`）标 `GAP_ALL` 的可以事后回补（窗口内）。

---

## 2. 一轮管道做了什么

```
preflight login (v4)  →  collect --renew  →  bsk fallback  →  guard --days 5 --dedupe
                                                              →  guard --days 1（校验）
                                                              →  若今日缺：等 3 分钟重试一轮
```

| 步骤 | 脚本 | 作用 |
|---|---|---|
| 前置登录 | `_gushi_login_v4.py` | 确保量化站会话有效；`guest` 时自动走 LINUX DO OAuth |
| 采集 | `gushi_daily_collect.py --days 3 --renew` | CDP 驱动 Chrome 取数；`--renew` 非 VIP 时自动兑 1 天 VIP |
| 兜底 | `gushi_bsk_capture.py --only-if-missing` | 走 bsk 扩展通道补 |
| 体检/去重 | `gushi_data_guard.py --days 5 --dedupe` | 去重 jsonl + 写 `health.json` |
| 校验 | `gushi_data_guard.py --days 1` | 只看最新交易日；有空洞 → exit 3 |

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常（含「发布窗口前，今日尚无数据」这一正常情形） |
| 3 | **今日数据仍缺，且已过发布窗口（≥17 点）** → 真失败，任务置红 |

> 发布窗口前（<17 点）跑，`verify_rc=3` 只写 `[note]`，**不置红** —— 避免手动早晨跑一次就一片红。

---

## 3. 2026-10-09 修的三个断点（09-28 ~ 10-08 连续 10 天静默丢数的根因）

| # | 断点 | 证据 | 修法 |
|---|---|---|---|
| ① | 采集前**没有登录步骤**。登录态一失效，全通道空手，无人知道 | `collect_last.log`：`[cf] 挑战通过=False` → `role=None`；连跑 10 天全空 | `.cmd` 增加 `_gushi_login_v4.py` 前置步骤 |
| ② | `.cmd` **从不传 `--renew`**，VIP 一过期就永远采不到（非 VIP 数据被站点脱敏，采集器按设计拒落盘） | `expires_at=2026-10-01 14:55:41`（VIP 到期）；日志 `role=regular 非 VIP → 拒绝落盘` | 采集调用加 `--renew` |
| ③ | `.cmd` 末尾**无条件 `exit /b 0`**，把失败吞掉 | 任务 `LastTaskResult=0`（成功），而当日数据为 0 | 透出 exit 3 |

### 附带修掉的 4 个坑

1. **`_gushi_login_v3.py` 从来就没成功登录过**：它的「模态已打开」判据只找
   `input[type=password]`，而本站登录模态**默认落在「使用 LINUX DO 登录」标签**，
   密码框宽高为 0 ⇒ 永远误判「弹窗未打开」→ 点完入口就 `return`。
   → v4 改用 **`#linuxdoLogin` 的 JS `.click()`**（id 恒定、始终在 DOM 内，父容器只是 `display:none`）。
2. **CF 顺序错**：v4 原先「先读 `me` 再等 CF」，刚拉起窗口时页面还在挑战页 ⇒ `role=None`
   被误判成未登录。→ 改为先等放行再决策。
3. **CF 挡 XHR 时被当成 guest**：页面 DOM 正常但 `/api.php?action=me` 返回 **403 HTML**。
   此时重走 OAuth 纯属白点、且更招 CF。→ 显式识别挑战（status 403 / title `請稍候` /
   body 含 `Just a moment`）并耐心等（预算 ~180s）；仍未放行则返回 **1（环境问题）**，不冒充 guest。
4. **`i.gushi.in` 子串判据认错标签页**（`page_ws()` / v4 的 `quant_ws()`）：
   linux.do 授权 URL 的 `redirect_uri=https%3A%2F%2Fi.gushi.in%2F...` **查询串里就含 `i.gushi.in`**
   ⇒ 授权页被当成量化站页。→ 改按 **host** 判定（`gushi_daily_collect._is_quant_url`）。
5. **`me` 响应信封没剥**：`{"code":200,...,"result":{...role...}}`，role 在 `result` 里。
   读原始响应后忘了剥 ⇒ role 恒 None。→ `unwrap_me()`。

---

## 4. VIP 与积分（这条线的常态成本）

站点对**非 VIP** 返回脱敏数据（股票名/代码全 `******`），采集器**设计性拒绝落盘**以保护数据集。
所以这条线**必须有 VIP**。

| 项 | 值 |
|---|---|
| VIP 1 天体验 | 30 论坛积分 |
| VIP 30 天 | 600 论坛积分 |
| 兑换入口 | <https://gushi.in/index.php?a=quant_points_payment> |
| 账号绑定 | 量化账号已绑定 `HawChow` |
| 2026-10-09 状态 | 兑换 1 天档后 **VIP 有效期至 2026-10-09 22:46:34**，余额 **452** |

**自动续费（`--renew`）的四道护栏**（采集器内 `auto_renew()`，2026-09-16 用户授权）：

1. 只买 **1 天档**（30 积分），不碰 600 档；
2. **每日最多 1 次**（`renew_log.jsonl` 记账）；
3. 仅在**确有缺失交易日**时触发（周末/节假日不花分）；
4. 余额不足**立即停并告警**，不重试。

> 余额按 30/天 计：452 分 ≈ 可撑 **15 个交易日**。之后要么攒到 600 换 30 天档（更划算），
> 要么继续按天兑。**余额见底 = 这条线再次静默断掉**（护栏 4 会打印告警）。

---

## 5. 手工操作

```powershell
cd "D:\Documents\Workbuddy\股票基金\quant-weight-system"

# 只看登录态（不点任何东西）
backtest\_gushi_login_v4.py --check          # 0=vip / 2=已登录非vip / 3=guest / 1=CF挡着

# 强制重走 OAuth（会话坏了时）
backtest\_gushi_login_v4.py --force

# 完整一轮（等价计划任务）
cmd /c backtest\gushi_daily_run.cmd

# 只采指定日（强制重采）
backtest\gushi_daily_collect.py --date 2026-10-08
```

⚠ **别高频连跑**：连续多轮自动化会触发站点 Cloudflare 加严（实测 2026-10-09：
连跑几轮后 API 一律 403 + title `請稍候`，需等一两分钟放行）。v4 会识别并等，但没必要反复试。

---

## 6. 排障速查

| 现象 | 判据 | 处置 |
|---|---|---|
| 今日空手，`[cf] 挑战通过=False` | CF 拦截 | 等几分钟；持续则在自动化窗口手工过一次挑战 |
| `role=regular/guest`，日志有「拒绝落盘」 | 非 VIP（脱敏） | 检查积分余额；`--renew` 应自动处理，若余额 <30 需充值 |
| `[窗口] 站点可查起点 ...` | 待采日期超出站点 15 天硬限 | 正常，更早的日期不再重试 |
| `GAP_RESON` | 该日共振永久缺失 | **无法回补**（站点只给最新交易日）。教训：当天必跑 |
| `GAP_ALL` | 策略数据缺 | 窗口内可回补：`gushi_daily_collect.py --days N` |
| 任务历史「成功」但没数据 | 旧的 `exit /b 0` 吞错 | 2026-10-09 已修；如仍见，检查 `.cmd` 是否被改回 |

---

## 7. 相关文件

| 路径 | 说明 |
|---|---|
| `backtest\gushi_daily_run.cmd` | 管道入口（计划任务调用） |
| `backtest\_gushi_login_v4.py` | 登录（LD OAuth 自助） |
| `backtest\_gushi_login_v3.py` | **已废**（模态判据坏，从未成功）。保留仅作案卷 |
| `backtest\gushi_daily_collect.py` | 采集器（含 `--renew` 自动续费） |
| `backtest\gushi_bsk_capture.py` | bsk 兜底通道 |
| `backtest\gushi_data_guard.py` | 去重 + 体检 + `health.json` |
| `backtest\gushi_data\daily\<date>.json` | 每日原始落盘 |
| `backtest\gushi_data\picks_daily.jsonl` | 摊平明细（去重后） |
| `backtest\gushi_data\health.json` | 体检结果（`rows` / `gaps` / `note`） |
| `backtest\gushi_data\renew_log.jsonl` | 续费记账（每日 1 次的依据） |
| `backtest\gushi_data\collect_last.log` | 本轮运行日志（>2MB 自动轮转 `.1`） |

---

## 8. 当前已知损失（不可回补）

| 日期 | 状态 | 策略 | 共振 |
|---|---|---|---|
| 2026-09-28 | `GAP_RESON` | 33 ✅ | **0（永久丢失）** |
| 2026-09-29 | `GAP_RESON` | 33 ✅ | **0（永久丢失）** |
| 2026-09-30 | `GAP_RESON` | 37 ✅ | **0（永久丢失）** |
| 2026-10-01 ~ 10-07 | — | 国庆假期，非交易日 | — |
| 2026-10-08 | `OK` | 35 ✅ | 551 ✅ |

> 09-28 ~ 09-30 三天在断点期内（VIP 于 10-01 到期、登录态更早已失效），
> 共振当天未采，**按站点机制已永久不可得**。策略部分已于 2026-10-09 回补完成。
