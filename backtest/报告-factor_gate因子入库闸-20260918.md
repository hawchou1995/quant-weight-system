# 报告 · `factor_gate.py` 因子入库前置闸（R-factorgate-0918）

> 交付：2026-09-18 17:40 · 规格冻结 `PRE-REGISTRATION_20260918_factor_gate.md`
> 性质：**基础设施件，非研究臂**（n_trials = 0）——不产生任何策略结论。
> 动机：R-lookahead-0918（scipy 居中窗口前视 n//2 天）本可由一次自动化因果审计拦下，
> 却让当日五轮工作全部返工。

## 一、交付与验收

**验收结论：`selftest` 四项全过（ALL PASS）——工具能抓住造成当日返工的那个 bug。**

| # | 测试 | 期望 | **实测** | 判 |
|---|---|---|---|---|
| T1 | 负对照：居中 `maximum_filter1d` 构造的 rel_pos60 | audit FAIL | mismatch_rows **7/8**（CLI 12 抽样下 **11/12**），max_abs_diff **4.05** | **PASS** |
| T2 | 正对照：尾随 `roll_trailing` 同一因子 | audit PASS | mismatch_rows **0/8**（CLI 0/12），max_abs_diff **0.0** | **PASS** |
| T3 | profile：尾随 rel_pos60 全市场四分位 | 极差 < 1pp | **0.325pp**（B1 +0.383 / B2 +0.550 / B3 +0.517 / B4 +0.225），非单调 | **PASS** |
| T4 | compare：`S=(rel_pos60<当日q20)` 纯因子代理 | ratio < 1.5 → 非信号 | **ratio = 1.000**（信号均值与同桶市场均值逐位相同） | **PASS** |

T3 复现了勘误后的量级（0.16–0.38pp），**与勘误前的前视读数 9.79pp 相差约 25 倍** → 工具确实能分辨真假。

## 二、三个判据

### A. 因果审计 `audit`（本轮核心价值）

**原理：截断重算。** 对抽样日 i，用 `panel[:i+1]`（**只含历史**）重算因子，其第 i 行必须与全量重算的第 i 行**逐位一致**。
任何形式的前视——居中窗口、全序列归一化、跨期 shift、未来填充——都会在此暴露。

```
python factor_gate.py audit <module:function> [--sample N] [--tol X]
判据：mismatch_rate == 0 且 max_abs_diff <= tol(1e-6)     FAIL 即拒绝入库，不看收益数字
```

### B. 无信号全市场分位画像 `profile`

```
python factor_gate.py profile <factor.npz> [--nb K] [--hold H]
```
输出每桶 n/均值/中位/胜率 + 单调性 + 极差。**用途：给出该因子的「市场级效应量级」基准线。**

### C. 信号 vs 市场量级比 `compare`

```
python factor_gate.py compare <factor.npz> <signal.npz>
判据：ratio = 信号组均值 / 同日同桶市场均值；ratio < 1.5 → 判「非信号」
```
含义：**若某"信号"的效应量级不超过它所在因子桶的全市场均值，它就不是信号，只是该因子（或该桶）的代理。**
这正是 R-lookahead 那类假信号的通用形态。

## 三、随附工具函数

`roll_trailing(a, n, kind)` —— 尾随极值窗口，`origin = n - 1 - n // 2`。
**后续因子作者应直接调用它；禁止裸用 `scipy.ndimage.maximum/minimum_filter1d` 的默认参数。**

## 四、建议固化的使用流程

因子/信号立项固定三步：
1. `audit` —— 前视审计，FAIL 即停（**不看收益**）
2. `profile` —— 取得市场级基准线
3. `compare` —— 有入场掩码者，验证 ratio ≥ 1.5

## 五、边界与未办

- `audit` 要求因子生成函数是**纯函数** `func(panel) -> array`；依赖全局状态/外部文件的因子须先包装
- `audit` 只抽样（默认 12 日）：**通过 ≠ 安全，只能证伪**——FAIL 一定有问题，PASS 不代表无前视
- `compare` 的阈值 1.5 为**先验设定**，未做网格；若后续认为过严/过松，须新预注册
- 未做：与看板/生产链自动接线（当前为手动 CLI）；多因子批量审计封装

## 六、交付物

- `backtest/factor_gate.py`（221 行，含 `roll_trailing`）
- 规格冻结：`backtest/PRE-REGISTRATION_20260918_factor_gate.md`
- 演示产物：`_tmp_factor_relpos60.npz` / `_tmp_signal_fproxy.npz`
