# 接线规格冻结 · 2026-09-18 · 四检查接入流程（R-gatewiring-0918）

> 冻结时间：2026-09-18 23:00（**先冻结后改**）
> 性质：**流程接线 + 文档规程**，n_trials = 0
> 动机：`factor_gate` v2 已能拦四类缺陷，但**仍是手动 CLI——没有人会被自动拦住**。本件做「机器自动拦 + 文档规定动作」双保险。

## 一、方案（用户已批准：第 1 项 + 第 2 项组合）

### 1.1 机器自动拦 —— 新增日链步骤
- 新建 `backtest/factor_gate_daily.py`：**只跑便宜且高信号的检查**，输出紧凑摘要
  - `warmup-check` 于 `panel_kv_0913.npz`（**只读 mask，~10MB，轻量**）→ 若 warmup 门变化则 WARN
  - `finite-check` 于**日链自身产出的状态文件**（JSON 数字叶子扫 inf/NaN）
    目标：`satellite_paper*.json`、`a5_paper_state.json`、`khunter_paper*.json`、
    `exit_control_state.json`、`paper_state.json`、`pct40_exits_state.json`
  - **不跑** `audit`（需纯函数，无法自动列举）、**不默认跑** `--ret`（需载入价格面板，重）
- 退出码语义：**仅 FAIL 时非零**；WARN 不影响退出码
- 接入 `daily_refresh.py` 的 `STEPS`，**显示名带 `[软]` 后缀**（非阻断，失败只告警继续）——
  遵守既有约定（`name.endswith("[软]")` 且 returncode≠0 才「只告警继续」）

### 1.2 文档规定动作 —— 改 `AGENTS.md`
在 `D:\Documents\Workbuddy\股票基金\AGENTS.md` **追加一节**「因子立项前置检查」：
- 新增/修改任何因子、信号、出场规则前，**先跑四检查**：`audit` → `finite-check` → `sample-check` → `warmup-check`
- 判据：`audit` FAIL 即停**且不看收益**；`sample-check` 判「不可判定」而非"未过门"；`sample-check` 需同时跑分位与 `--abs`
- 命中即记入陷阱库

## 二、验收（冻结）

| # | 测试 | 期望 |
|---|---|---|
| W1 | `factor_gate_daily.py` 空跑（状态文件齐全） | 输出紧凑摘要，**退出码 0**（无 FAIL） |
| W2 | 构造一个含 `inf` 的假状态 JSON 喂入 | **FAIL 且退出码非零**（能拦） |
| W3 | `daily_refresh.py` 语法 + `STEPS` 含新步且名字带 `[软]` | 通过 |
| W4 | `AGENTS.md` 追加后**原有内容零删除**（diff 验证） | 通过 |

**W2 是核心：检查必须真的能拦住，不能只是跑通。**

## 三、边界

- 日链步骤**只覆盖产出物**（状态文件 + 面板 mask），**不覆盖"新写的因子脚本"**——那部分靠 AGENTS.md 规程
- `warmup-check` 只能**检出**门的存在，不能判断该门是否正确
- 不阻断链：FAIL 也只告警（`[软]`），避免误伤日更

## 四、执行结果（跑后回填）

**执行**：2026-09-18 23:40。**四项验收全部通过。**

| # | 测试 | 期望 | **实测** | 判 |
|---|---|---|---|---|
| W1 | `factor_gate_daily.py` 空跑 | 紧凑摘要 + 退出码 0 | 受检 **6 个状态文件全 PASS**；warmup WARN（符合预期）；**退出码 0** | **PASS** |
| W2 | 喂含 `inf`/`nan` 的假状态文件 | FAIL + 退出码非零 | **FAIL，退出码 1**，精确报出 `[('/nav','inf'), ('/positions[0]/ret','nan')]` | **PASS** |
| W3 | `daily_refresh.py` 语法 + 新步带 `[软]` | 通过 | STEPS **31→32 步**；新步在**第 30 位**（其后紧跟「看板重建」，**FAIL 在部署前可见**）；`endswith("[软]")=True` | **PASS** |
| W4 | `AGENTS.md` 追加后零删除 | 通过 | **removed lines = 0**，added = 21，新节标题正确 | **PASS** |

**W2 是核心**：检查**真的能拦住**——不只是跑通，而是对污染值给出精确 JSON 路径且退出码非零。

## 5.1 实施中抓到的两处自身缺陷（如实申报）

1. **路径解析错（两次同源）**：首版 `p = BASE / rel` 使 `backtest/xxx.json` 变成 `BASE/backtest/backtest/xxx.json`
   → **受检文件 0 个却报 PASS**（静默空跑）。改「候选路径依次尝试」后修复。
   这是**项目既有陷阱「相对路径 IO 静默落空」的又一次复现**——该陷阱早已在库，我仍然踩了。
2. **W2 首跑假阴性**：正因为上面的路径错，含 inf 的测试文件根本未被加载 → 报 PASS + 退出码 0。
   **若无 W2 这条验收，这个缺陷会直接上生产并继续静默**。这印证了「验收必须能证伪」的必要性。

## 5.2 边界（重申）

- 日链步骤**只覆盖产出物**（6 个状态 JSON + 面板 mask），**不覆盖"新写的因子脚本"**——那部分靠 §1.2 的 AGENTS.md 规程
- `warmup-check` 只能**检出**门的存在，不能判断该门是否正确
- 不阻断链：FAIL 也只告警（`[软]`），避免误伤日更
- 本次改动**触及生产文件 `daily_refresh.py`**（原 31 步 → 32 步），已备份
  `D:/Tools/cache/mem_bak_0918/daily_refresh_pre_gate.py`；`AGENTS.md` 同备份

**n_trials 实际**：0（流程接线）。

产物：`backtest/factor_gate_daily.py` / `daily_refresh.py`（+1 步）/ `AGENTS.md`（+1 节）/ `_tmp_gate_bad.json`（测试夹具）
