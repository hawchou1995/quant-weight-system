# 云端发布验收 + 数据落地 · 运行手册（2026-09-24 起）

## 0. 一条命令（本机验收 + 落地）
```powershell
cd D:\Documents\Workbuddy\股票基金\quant-weight-system
$PY = "C:/Users/Admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
& $PY -X utf8 backtest\cloud_accept_data.py --sample 12              # 只读验收（下载到 _cloud_local\ + 五项判据）
& $PY -X utf8 backtest\cloud_accept_data.py --sample 12 --inplace    # 校验 rc=0 且 as_of 已推进到今天 → 落地（旧件备份 *.bak-cloudsync-<ts>）
& $PY -X utf8 backtest\apply_data_delta.py --latest                  # 回灌云端 K 线 delta + A5/qlch 策略状态（见 §4 / §5）
```
退出码：`0` 全过 / `3` 有失败项 / `4` 环境异常。报告：`_cloud_local\accept_report.json`。

## 1. 五项判据（脚本自动输出）
| # | 判据 | 说明 |
|---|---|---|
| 1 | 14 个发布物 md5 == 线上 `_cloud_manifest.json` | 报「清单过期(rt 覆盖)」属正常：盘中快照 workflow 也写 gh-pages |
| 2 | `index.html` 与 `dual_system.html` 同 md5 | 云端发布结构门禁 |
| 3 | 运行期依赖 `as_of` == 今日 | 数据新鲜度（等价 G2） |
| 4 | **三方价格一致率 100%** | 云端 `short_signals.js` 的 px ↔ 本机 `data_full` 收盘 ↔ 腾讯 K 线（+ 新浪 akshare 抽查）|
| 5 | 本地差异清单 | 本机落后于云端的文件（`--inplace` 会覆盖并备份）|

## 2. 云端运行侧（发布是否真的发生）
```powershell
& "C:\Users\Admin\.workbuddy\binaries\gh\gh.exe" run list -R hawchou1995/quant-weight-system --workflow close_refresh_cloud.yml --limit 3 --json databaseId,status,conclusion,event,createdAt,headSha
powershell -NoProfile -File <scratch>\analyze_run.ps1 -RunId <id>    # 日志 5 段分析
```
判据：`publish=true` / `status=ok` / `chain rc=0` / `G1 结构门禁` 通过 / `G2 新鲜度` fresh / staging 13 项。
已知可接受软失败：**只剩 `em-bulk-all` clist 被拦**；`kxmm` 的 `[skip] kxmm 凭证不存在` 属计划内跳过（不算软失败）。
`factor_gate_daily` 的 scipy 已补齐（2026-09-24 commit `dbcc302`，`.github/cloud/requirements.txt`）→ 该步已转绿；**若再出现「缺 scipy」＝硬问题**。
2026-09-24 已修：kv 共振面板改由 `rebuild_panels.py` 每轮自建（不再依赖 498MB 的 `panel_kv_0913.npz` 种子），
`recreenscreen_regen` 与 6 个 qlch 臂随之不再软失败；A5 三步也已从"跳过"改为真实执行（`--skip-a5` 已移除）。
**实测（run `35992226836` @`dbcc302`，2026-09-24）：15 步全绿、全日志 0 条 `[软] 失败`、`chain rc=0`、`publish=true`、
staging 14 文件 / 7119 KB；kv 面板 `saved panel_kv_0913.npz 498 MB`；6 臂各 `QLCH PAPER DONE …（已写盘）`；
A5 三步（扫描 / `A5 PAPER OK` / `a5_pool.js as_of=2026-09-24`）+ `revscreen_regen` + `factor_gate_daily` 全绿。**

## 3. 前提与限制（重要）
- 云端**只发布看板产物**（js/json/html）。K 线原始数据（`data_full/`、`index_000300.csv`）在云端 runner 的 cache 里，
  本机取不到 → 通过 §4 的 `data-delta` 工件回流。
- 本机链定时任务已于 2026-09-24 停用 → 本机 `data_full/*.csv`、`index_000300.csv` 不再本地自更新，
  改由 §4 云端回灌（当前尾行 2026-09-24）。
- `.github/workflows/*` 现在可直接 push：gh token 已含 `workflow` scope（B 方案，2026-09-24 起）。
- 相关脚本：`backtest/cloud_accept_data.py`（本手册主体）、`backtest/build_data_delta.py` + `backtest/apply_data_delta.py`（数据/状态回流）、
  `backtest/gushi_data_guard.py`（gushi 采集体检）。

## 4. 本机 K 线同步（云端 data-delta 工件，2026-09-24 起）
云端链跑完后额外产出 `_cloud_delta/`（`delta_bars.csv` = 最近 3 个交易日全市场日线，约 1.3MB；
+ `index_000300_tail.csv` + `delta_meta.json` + `state_meta.json` + 状态目录，见 §5），
由 workflow 用 `actions/upload-artifact` 上传（artifact 名 `data-delta`，保留 45 天；步骤用 `always()`，链失败也产出）。

本机合并（**先校验、后写盘**）：
```powershell
& $PY -X utf8 backtest\apply_data_delta.py --latest                 # 下载 + 多源校验（抽样 vs 腾讯K线，需100%一致）+ 幂等 append
& $PY -X utf8 backtest\apply_data_delta.py --src <dir> --dry-run    # 只算不写
& $PY -X utf8 backtest\apply_data_delta.py --rollback 2026-09-24    # 撤掉某日追加的行
```
- 校验不过（rc=3）**绝不写盘**（K 线与策略状态都不写）。
- 日志 `_cloud_local/delta_applied.json`（近 60 次，含 `state` 段）；`--dry-run` 不写日志。
- 实测：构建 7197 只 / 20916 行 / 1.3MB → 抽样 10/10 与腾讯K线一致 → 写入 60 票 + 1 指数行
  → 二次运行 0 行（幂等）→ 回滚干净。

## 5. 策略状态回灌：A5（打板族）+ qlch（超跌低开低吸）
看板两组池的数据源是**策略状态文件**（不是 K 线）：A5 走 `paper_state.json`，qlch 走 6 个
`qlch_paper_state*.json` + `qlch_candidates.json`。云端在仓库内副本上跑，状态随 actions/cache 滚动，
本机拿不到 → 若不同步，本机实验目录会永久停在旧日期。故随 §4 同一工件 `data-delta` 一起回流
（体积小：A5 状态 ~35KB、qlch 六臂 ~10KB、candidates ~19KB）。

**工件内容**（云端 `build_data_delta.py --a5-dir/--backtest-dir` 产出）：
| 工件内路径 | kind | 日期键 |
|---|---|---|
| `a5/paper_state.json` | `a5-state` | `last_scan` |
| `a5/reports/report_*.md`（最近 3 份） | `a5-report` | 文件名内日期 |
| `qlch/qlch_paper_state*.json`（6 臂） | `qlch-state` | `last_run` |
| `qlch/qlch_candidates.json` | `qlch-candidates` | `updated` |
| `state_meta.json` | 逐文件清单：rel/kind/date/bytes/src | — |

**本机落点**（`apply_data_delta.py → dest_paths()`）：
- `a5-state` → ① 仓库 `backtest/a5_experiment/paper_state.json`（周种子保鲜）
  ② `D:/Documents/Workbuddy/股票基金/打板系统A5实验_20260827/paper_state.json`（可用 `--a5-ext` 改）
- `a5-report` → 上述两处的 `reports/`
- `qlch-*` → 仓库 `backtest/`

**覆盖规则**：只前进不回退（本地日期 ≥ 云端日期 → skip）｜写前备份旧件 `.bak-a5sync-<ts>`（A5）/`.bak-statesync-<ts>`（qlch）｜
报告已存在不覆盖｜同一 delta 重跑幂等｜`--dry-run` 不动盘｜`--no-state` 只并 K 线不回灌状态。

```powershell
& $PY -X utf8 backtest\apply_data_delta.py --latest --dry-run       # 先看计划（含 [state] 段）
& $PY -X utf8 backtest\apply_data_delta.py --latest                 # 落地
& $PY -X utf8 backtest\apply_data_delta.py --latest --no-state      # 只并 K 线
& $PY -X utf8 backtest\build_data_delta.py --out _cloud_delta --no-state   # 本地调试：只产 K 线 delta
```

**判据**：日志 `[state] 工件内 N 个状态文件：写入 x / 跳过 y / 报告归档 z`；
两处 A5 `last_scan` == 运行当日；6 个 qlch `last_run` + `qlch_candidates.updated` == 运行当日；
两处旧件均出现 `.bak-a5sync-<ts>`、qlch 出现 `.bak-statesync-<ts>`。

**回退**：把 `.bak-a5sync-<ts>` / `.bak-statesync-<ts>` 复制回原名即可（不删任何备份）。

**回归测试**（2026-09-24，隔离沙箱 46 项，只用复制品，真实仓库零改动）：
干跑零改动 → 正跑写入两处 A5 + 6+1 qlch + 新报告归档（旧报告未覆盖）→ 同 delta 二次幂等（md5 全等）→
更旧 delta 不回退（md5 全等 + skip 日志）→ 坏价 delta rc=3 且 K 线/状态零写盘 → `--no-state` 不打包状态。

## 6. 时长基线（2026-09-24，run `35992226836` @`dbcc302`）
整轮 job **105m25s**（11:18:11Z→13:03:36Z）；链内 `11:19:22→13:02:56` = **6215s**。阶段耗时（秒，相邻段落时间戳差）：
`update_daily 2644` → `fetch_val_em_daily 1415` → `fund_nav_update 699` → `build_short_pool 229` → `review_daily 244` →
`市值快照 89` → `rebuild_panels 61`（内含 kv 19.5s）→ `shadow_ret20 32` → `build_satellite_pool 48` → `signal_satellite 42` →
`khunter_paper 167` → `khunter_paper_c 162` → `a5_paper 23` → `revscreen_regen 0.36` → **6×qlch ≈130** →
**A5 三步 ≈11** → `factor_gate_daily 0.45` → `build_dual_system 0.87`。
**结论**：>90 分钟的原因 100% 是既有数据抓取（2644+1415+699 = 4758s = 链的 **77%**）；
本次新解锁的 kv 面板 19.5s + qlch 六臂 ≈130s + A5 ≈34s ≈ **184s（占链 3.0%）** →
**不构成拖垮 15:05 cron，kv 面板无需纳入 actions/cache**（该判断只作结论，未改缓存策略）。
