# 工具规格冻结 · 2026-09-18 · `factor_gate.py` 因子入库前置闸（R-factorgate-0918）

> 冻结时间：2026-09-18 17:10（先冻结后写）
> 性质申报：**基础设施，非研究臂**——不产生策略结论，**n_trials = 0**。
> 动机：R-lookahead-0918 的 P0 勘误（scipy 居中窗口前视 n//2 天）本可由一次自动化因果审计拦下，
> 却让当日五轮工作全部返工。本工具把「前视审计」与「无信号全市场对拍」固化为**因子入库强制前置步骤**。

## 一、接口（冻结）

```
python factor_gate.py audit   <module:function> [--sample N] [--tol X]
python factor_gate.py profile <factor.npz>     [--nb K] [--hold H]
python factor_gate.py compare <factor.npz> <signal.npz> [--nb K]
python factor_gate.py selftest
```

- 因子/信号文件：`.npz`，键 `f`（因子）或 `sig`（信号），形状 (T,N) 与面板一致
- 因子生成函数签名（audit 用）：`func(panel: dict) -> np.ndarray(T,N)`；
  panel 键为 `close/high/low/open/amount/mask`，**须为纯函数（禁止依赖外部状态）**
- 面板：`kv_resonance_0913/panel_kv_0913.npz`（2599×4087，含退市）

## 二、三个判据（冻结）

**A. 因果审计（causality audit）**
对抽样日 i：`func(panel[:i+1])` 的第 i 行 必须等于 `func(panel)` 的第 i 行。
- 判据：`mismatch_rate == 0` 且 `max_abs_diff <= tol`（默认 1e-6）
- 抽样：默认 12 个 i（早/中/晚均匀 + 固定 seed），并要求 i >= 120
- **FAIL 即拒绝入库——不看任何收益数字**

**B. 无信号全市场分位画像（market-wide profile）**
- 分位桶：当日**截面**分位（默认 K=5 五分位）
- 前向收益：入场 T+1 开盘 → 出场 T+H+1 收盘（默认 H=10），仅用 mask 内标的
- 输出：每桶 n / 均值 / 中位 / 胜率；单调性；**极差 max−min**
- 用途：给出「该因子的**市场级**效应量级」基准线

**C. 信号 vs 市场量级比（signal-vs-market ratio）**
- 给定信号掩码 SIG，比较「信号子集前向收益」与「同日同因子桶的市场均值」
- 输出 `ratio = 信号组均值 / 市场同桶均值`
- **判据：ratio < 1.5 → 判「非信号」**（该"信号"只是因子本身的代理，不含额外信息）

## 三、验收测试（先冻结，`selftest` 必须全过）

| # | 测试 | 期望 |
|---|---|---|
| T1 | 负对照：用**居中** `maximum_filter1d` 构造的 rel_pos60 | `audit` **FAIL**（须能抓到今天的 bug） |
| T2 | 正对照：用尾随 `roll_trailing` 构造的同一因子 | `audit` **PASS** |
| T3 | profile：尾随版 rel_pos60 | 极差 **< 1pp**（复现勘误后 0.16pp 量级，非 9.8pp） |
| T4 | compare：`SIG = (rel_pos60 < 当日 q20)` 这一纯因子代理 | ratio **< 1.5 → 判「非信号」** |

**工具若不能同时通过 T1 与 T2，视为无效交付。**

## 四、交付物

- `backtest/factor_gate.py`（含 `roll_trailing` 安全工具函数，供后续因子作者直接复用）
- `backtest/报告-factor_gate因子入库闸-20260918.md`
- 本规格冻结文档

## 五、执行结果（跑后回填）

**执行**：2026-09-18 17:40。交付 `factor_gate.py`（221 行），**四项验收测试全过（ALL PASS）**。

| # | 期望 | 实测 | 判 |
|---|---|---|---|
| T1 负对照（居中 roll） | audit FAIL | mismatch_rows **7/8**（CLI 12 抽样 **11/12**），max_abs_diff **4.055** | **PASS** |
| T2 正对照（尾随） | audit PASS | mismatch_rows **0/8**（CLI **0/12**），max_abs_diff **0.0** | **PASS** |
| T3 profile 极差 | < 1pp | **0.325pp**（非单调） | **PASS** |
| T4 compare 纯因子代理 | NOT_A_SIGNAL | **ratio = 1.000** | **PASS** |

**结论**：工具通过全部冻结验收，**能自动拦截 R-lookahead-0918 那类前视缺陷**（T1 一击命中）。
T3 复现勘误后量级（0.16–0.38pp），与前视口径 9.79pp 相差约 25 倍 → 具备真假分辨力。

**CLI 四模式均经冒烟测试**：`audit`（正/负对照各一）、`profile`（5 桶 + 极差 0.382pp）、`compare`（ratio 1.0 → NOT_A_SIGNAL）、`selftest`。
**未办（明确记录）**：`audit` 只能证伪不能证明（抽样 12 日）；`compare` 阈值 1.5 为先验未扫描；未与看板/生产链自动接线；未做多因子批量封装。

**n_trials 实际**：0（基础设施件，不产生策略结论）。

产物：`factor_gate.py` / `报告-factor_gate因子入库闸-20260918.md` / `_tmp_factor_relpos60.npz` / `_tmp_signal_fproxy.npz`
