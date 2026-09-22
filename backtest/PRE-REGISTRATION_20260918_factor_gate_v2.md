# 规格冻结 · 2026-09-18 · `factor_gate` v2 —— 补齐三类缺陷检查（R-factorgate-v2-0918）

> 冻结时间：2026-09-18 22:00（**先冻结后写**）
> 性质：**基础设施件，非研究臂**——n_trials = 0，零生产变更
> 动机：0918 一天内踩到**四类**缺陷（★175 前视 / ★176 WARMUP 门 / ★177 样本塌缩 / ★178 inf 静默污染），
> 但 v1 的 `factor_gate` **只能自动拦住第一类**，其余三类仍靠人记得。本版补齐。

## 一、新增三个模式（接口冻结）

```
python factor_gate.py finite-check <npz> [--keys a,b,c] [--panel] [--ret]
python factor_gate.py sample-check <factor.npz> [--ths 0.01,0.03,0.05] [--min 30] [--panel]
python factor_gate.py warmup-check <panel.npz> [--thr 0.5]
```

## 二、三个判据（冻结）

### 2.1 `finite-check` —— 拦 ★178（inf 静默污染）
- 对 npz 内指定键（默认全部数组键）报 `NaN / +inf / -inf` 计数
- `--ret`：另算 `C[1:]/C[:-1]-1`，**定位产生 inf 的零/负价单元**（报行列与代码）
- **判据：任一数组含 ±inf → FAIL**（NaN 只警告不判 FAIL，因面板天然含 NaN）
- **同时检查「基准序列」概念**：`--bench` 传入后可单独校验其有限性（基准是全局放大器）

### 2.2 `sample-check` —— 拦 ★177（阈值处样本塌缩）
- 输入因子面板 + 阈值列表；每档报 **事件数 n** 与 **唯一标的数 uniq**
- 阈值按**当日截面分位**解释（与项目口径一致）
- **判据：`uniq < min`（默认 30）→ 该档判「不可判定」**（而非"未过门"）
- 附报因子分布分位（p1/p5/p10/p25/p50），便于判断阈值落在哪

### 2.3 `warmup-check` —— 拦 ★176（引擎域门切掉制度段）
- 输入含 `mask` 的面板 + 可选 `codes`
- 计算每只票 **首个 `mask=True` 的索引**分布
- **判据：若 `min(首个有效索引) > 0` 且几乎全部票都 > 0 → 检出 WARMUP 门**，
  报出隐含 warmup 天数并 **WARN**：凡收益集中在上市初期的策略必须走裸面板版
- 报 min / p25 / median 首个有效索引 + >0 的票数

## 三、验收测试（冻结，`selftest2` 必须全过）

| # | 测试 | 期望 | 依据 |
|---|---|---|---|
| T5 | `finite-check` 跑**真实** `_tmp_0918_sn_panel_ext.npz`（含零价行） | **FAIL**，并定位到零价单元 | ★178 真实案例 |
| T6 | `sample-check` 跑真实 FR 面板 + 阈值 `0.01,0.02` | 至少一档 **uniq < 30 → 不可判定** | ★177 真实案例（θ=3% 仅 3 只） |
| T7 | `warmup-check` 跑真实 `panel_kv_0913.npz` | **检出 warmup = 120**（该面板 `listed>=120` 实证） | ★176 真实案例 |
| T8 | **回归**：v1 的 `selftest` 四项仍全过 | ALL PASS | 不得破坏既有验收 |

**三个新模式若不能分别抓住对应真实案例，视为无效交付。**

## 四、边界

- `finite-check` 的 `--ret` 需面板键名约定（close/open/…），非通用
- `sample-check` 的分位解释依赖 `mask`（可选）；不传则用 `isfinite`
- `warmup-check` 只能**检出**门的存在，不能判断该门是否正确——**是否该去掉须人判**
- 三者均为**静态检查**，不能替代 `audit` 的截断重算（因果审计）

## 五、执行结果（跑后回填）

**执行**：2026-09-18 22:30。`factor_gate.py` 355 → **约 370 行**，四个模式 + 两组 selftest 全部落地。

## 5.1 验收结果：**SELFTEST2 ALL PASS（T5/T6/T7）+ v1 SELFTEST ALL PASS（T8 回归）**

| # | 测试 | 期望 | **实测** | 判 |
|---|---|---|---|---|
| T5 | `finite-check --ret` 真实扩展面板 | FAIL | **verdict=FAIL**，`ret_nonfinite_cells=51`，**`zero_neg_prev_close=190`**，样例单元 `[[508,4387],[510,4387],…]` | **PASS** |
| T6 | `sample-check --abs` 主板 FR + θ=3%/5% | ≥1 档 UNDECIDABLE | **θ=3% → uniq=4；θ=5% → uniq=11，均 UNDECIDABLE** | **PASS** |
| T7 | `warmup-check` 真实 KV 面板 | 检出 warmup≈119 | **warmup_detected=true，implied=119，gt0_share=1.0** | **PASS** |
| T8 | v1 `selftest` 四项回归 | ALL PASS | **ALL PASS** | **PASS** |

**三个新模式分别抓住了今天真实发生的对应缺陷（★178 / ★177 / ★176），交付有效。**

## 5.2 实施中的两处口径修正（**跑前性质**，如实申报）

**修正 A · `sample-check` 增加绝对阈值模式 `--abs`**：
原规格写「阈值按**当日截面分位**解释」。实测发现**分位口径永远取横截面的固定比例，结构上不可能检出「绝对阈值无样本」**——
而这正是 ★177 的原案（FR<5% 仅 12 只，是**绝对量级**问题）。
首跑 T6 用分位口径得 `uniq=683/1026`（判 OK，漏报）；改 `--abs` 后得 **uniq=4/11 → UNDECIDABLE**（正确命中）。
⇒ **两种口径并存**（默认分位，`--abs` 走绝对值），**默认行为不变**。

**修正 B · `finite-check --ret` 只计 `inf`，不计 `NaN`**：
首版用 `~np.isfinite(r)` 统计，把面板天然的大量 `NaN` 也算成缺陷（首跑报 2,343,753 格）。
改为 `np.isinf(r)` 后归位到 **51 格真 inf**。这与 ★178 的教训同源（**混淆 NaN 与 inf**）——
**这个错我在写检查器时又犯了一次**，值得记录。

**修正 C · `load_panel` 增加 `mask`→`MB` 回退**：扩展面板用 `MB` 作键名，加回退后
`finite-check`/`sample-check` 可直接吃扩展面板。

## 5.3 边界（重申）

- 三个新模式均为**静态检查**，**不能替代 `audit` 的截断重算**（因果审计）；四类检查各自独立、互补
- `sample-check` 的 `--abs` 需调用方知道因子的**绝对量级**；分位口径对大横截面天然不会报警（设计使然）
- 仍**未接进流程**：本版仍是手动 CLI。要真正防返工，须把它写进因子立项的固定步骤（或挂到日链/看板）

**n_trials 实际**：0（基础设施件）。

产物：`factor_gate.py`（v2）/ `PRE-REGISTRATION_20260918_factor_gate_v2.md` / `_tmp_gate_FR_mb.npz`
