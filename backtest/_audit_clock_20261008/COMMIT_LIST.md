# 提交清单 · ADR-0004 交易时钟加固（2026-10-08）

> **本文件不执行提交。** 工作区在开工前**已含其它会话的未提交运行时状态**
> （`paper_state*.json`、`a5_pool.js`、`dual_system.html`、`snapshot_status.json` 等），
> `git add -A` 会把它们一并扫进提交 ⇒ 提交范围的决定留给用户。
> 下面是**只含本轮改动**的精确清单与可直接粘贴的命令。

---

## 一、真仓库（`D:\Documents\Workbuddy\股票基金\quant-weight-system`，git main）

### 1.1 已跟踪且被本轮修改（4 个）

```
CONTEXT.md
hpdk_card.py
intraday_live.py
backtest/a5_experiment/paper_daban_a5.py
```

### 1.2 本轮新增（未跟踪）

```
backtest/_audit_clock_20261008/（目录，见 §1.2 展开）
tools/gate_trading_clock_exempt.txt
tools/gate_hpdk_table_cols.py
backtest/hengpan_fangliang_dikai_0925/oos_run_v16_executable.py
backtest/hengpan_fangliang_dikai_0925/audit_samebar_causality_20261008.py
backtest/hengpan_fangliang_dikai_0925/oos_v16_trades.jsonl
backtest/hengpan_fangliang_dikai_0925/evidence_samebar_causality_20261008.json
backtest/hengpan_fangliang_dikai_0925/evidence_v16_executable_compare_20261008.json
backtest/hengpan_fangliang_dikai_0925/报告-B层D层加固-20261008.md
backtest/报告-同bar因果扫描与交易时钟修复-20261008.md
backtest/_audit_clock_20260808/            ← 见下方更正
```

`backtest/_audit_clock_20261008/`（目录，含本轮全部审计脚本与证据）：
```
quantify_band_cancel_bias.py
evidence_band_cancel_bias_20261008.json
a5_p5_probe.py
evidence_a5_p5_probe.json
archive_panel_and_rootcause.py
evidence_panel_rootcause_20261008.json
COMMIT_LIST.md                     ← 本文件
```

### 1.3 **明确不属于本轮**（勿一并提交；它们在本轮开工前就是 modified/untracked）

```
.github/probe/snapshot_status.json      a5_pool.js               backtest/_data_freshness.json
backtest/a5_experiment/paper_state.json backtest/a5_paper_state.json
backtest/engine_anchor.json             backtest/exit_control_state.json
backtest/fund_paper.json                backtest/gold_sat_paper.json
backtest/gushi_data/health.json         backtest/khunter_paper_state*.json
backtest/qlch_paper_state*.json         backtest/ret20_paper_l0*.json
backtest/satellite_paper_*.json         backtest/satellite_pool.json
backtest/sentinel_state.json            backtest/shadow_ret20/*   data_lag_list.csv
dual_system.html                        enhanced_data.js          etf_dashboard_snapshot.json
etf_paper_state.json                    index_000300.csv          review/*
sentinel_pool.js                        sentinel_track.js         short_pool.js
short_pool.json                         short_signals.js
```

### 1.4 建议命令（**执行权留给用户**）

```bat
cd /d "D:\Documents\Workbuddy\股票基金\quant-weight-system"
git add CONTEXT.md hpdk_card.py intraday_live.py ^
        backtest/a5_experiment/paper_daban_a5.py ^
        tools/gate_trading_clock.py tools/gate_trading_clock_exempt.txt tools/gate_hpdk_table_cols.py ^
        backtest/hengpan_fangliang_dikai_0925/oos_run_v16_executable.py ^
        backtest/hengpan_fangliang_dikai_0925/audit_samebar_causality_20261008.py ^
        backtest/hengpan_fangliang_dikai_0925/oos_v16_trades.jsonl ^
        backtest/hengpan_fangliang_dikai_0925/evidence_samebar_causality_20261008.json ^
        backtest/hengpan_fangliang_dikai_0925/evidence_v16_executable_compare_20261008.json ^
        "backtest/hengpan_fangliang_dikai_0925/报告-B层D层加固-20261008.md" ^
        "backtest/报告-同bar因果扫描与交易时钟修复-20261008.md" ^
        backtest/_audit_clock_20261008

git status --porcelain --untracked-files=no      :: 复核：只剩非本轮文件
```

> 注意 `oos_v16_trades.jsonl` 是 **12.5 MB** 的逐笔产物。若不希望入库，从上面的 `git add` 里去掉它即可
> —— 证据文件 `evidence_v16_executable_compare_20261008.json` 已含汇总读数。

---

## 二、工作区（`E:\PI\投资`，**非 git 仓库**，无需提交）

```
fleur_absorb/engine/session.py                  ← 新增（交易时钟真值源）
fleur_absorb/engine/audit.py                    ← P5–P8 探针
fleur_absorb/engine/spec.py                     ← execution.session / 分项成本 / R2 守卫
fleur_absorb/engine/portfolio.py                ← 成交日可成交性 + 分项成本
fleur_absorb/tests/test_session.py              ← 新增（16 项）
fleur_absorb/tests/test_fill_tradability.py     ← 新增（13 项）
fleur_absorb/tests/lookahead_negative_demo.py   ← 负例 4 → 8
fleur_absorb/tests/verify_acceptance.py         ← A12
fleur_absorb/tests/test_execution_contract.py   ← 嵌套覆写 + R2 用例
fleur_absorb/tests/run_all.py                   ← 新增（C4 一键运行器）
fleur_absorb/tools/export_bt520_clock_on.py     ← 新增（C1 导出）
fleur_absorb/docs/ADR-0004-…-same-bar-causality.md  ← 新增
fleur_absorb/docs/glossary.md                   ← 术语 31 → 40
fleur_absorb/subagents/strategy-backtest-expert.md  ← 铁律 6 条（与 ~/.agents 副本同 SHA）
fleur_absorb/out/bt520_393_clock_on_20261008.csv            ← 新增
fleur_absorb/out/报告-bt520新口径读数与锚差异-20261008.md    ← 新增
fleur_absorb/out/panel_manifest.json                        ← 新增
fleur_absorb/out/parity_bt520_baseline_20260922.{json,csv}  ← 基线归档
fleur_absorb/out/parity_bt520_isolation_noenforce.json      ← 隔离轮归档
holdings-watch/条件单清单-20260928.md                        ← 加「可执行时点」列
holdings-watch/holdings_watch.ps1                            ← 同款改写
C:\Users\Admin\.agents\subagents\strategy-backtest-expert.md ← 与 fleur_absorb 副本同步（同 SHA）
```

**面板归档（不进 git）**：`D:\Documents\Quant data\panel\panel_20261008.npz`（163.7 MB，
sha256 = `3a3a7a0c411dc00e6546a3272971e0a228da249f4a0e4c7ba144e0bde1cfe38e`）。

---

## 三、锚未被覆盖（复核用）

```
bt520_turtle_regime/out/**                      ← 全程未写（C1 只出独立产物）
backtest/hengpan_fangliang_dikai_0925/oos_run.py ← sha256 2351eb9d42acc62e… 未变
backtest/hengpan_fangliang_dikai_0925/{x2_sens,x5_gates,x3_board}.py、result_0925.json
backtest/clip_absorb_0925/**                    ← 并行会话产物，未碰
```
