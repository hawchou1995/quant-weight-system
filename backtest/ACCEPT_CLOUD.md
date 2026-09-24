# 云端发布验收 + 数据落地 · 运行手册（2026-09-24 起）

## 0. 一条命令（本机验收 + 落地）
```powershell
cd D:\Documents\Workbuddy\股票基金\quant-weight-system
$PY = "C:/Users/Admin/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
& $PY -X utf8 backtest\cloud_accept_data.py --sample 12              # 只读验收（下载到 _cloud_local\ + 五项判据）
& $PY -X utf8 backtest\cloud_accept_data.py --sample 12 --inplace    # 校验 rc=0 且 as_of 已推进到今天 → 落地（旧件备份 *.bak-cloudsync-<ts>）
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
& "C:\Users\Admin\.workbuddy\binaries\gh\gh.exe" run list -R hawchou1995/quant-weight-system --workflow close_refresh.yml --limit 3 --json databaseId,status,conclusion,event,createdAt,headSha
powershell -NoProfile -File <scratch>\analyze_run.ps1 -RunId <id>    # 日志 5 段分析
```
判据：`publish=true` / `status=ok` / `chain rc=0` / `G1 结构门禁` 通过 / `G2 新鲜度` fresh / staging 13 项。
已知可接受软失败：kv_resonance npz 相关（recreenscreen + 6 个 qlch 臂）、factor_gate 缺 scipy、em-bulk-all clist 被拦。

## 3. 前提与限制（重要）
- 云端**只发布看板产物**（js/json/html）。**K 线原始数据（`data_full/`、`index_000300.csv`）在云端 runner 的 cache 里，本机取不到**。
- 本机链定时任务已于 2026-09-24 停用 → 本机 `index_000300.csv`、`data_full/*.csv` **不再自动更新**（当前止于 2026-09-23）。
- 若要让本机 K 线也"吃云端数据"，需在 `.github/workflows/close_refresh.yml` 增加一个「当日数据 delta 工件」上传步骤（约 400KB/日：每只票当日 OHLCV 一行），本机下载后 append + 多源抽查校验。该改动属 workflow 文件 → 只能走 web UI 提交（token 无 workflow scope）。
- 相关脚本：`backtest/cloud_accept_data.py`（本手册主体）、`backtest/gushi_data_guard.py`（gushi 采集体检）。