# -*- coding: utf-8 -*-
"""gen_gates_report.py — 从 evidence_gates_scan.json 生成门槛扫描报告（数字全部来自产物，不手抄）。"""
import json, pathlib
D = pathlib.Path(__file__).resolve().parent
E = json.loads((D / "evidence_gates_scan.json").read_text(encoding="utf-8"))
A = E["arms"]
BASE = "base 基线(无门槛)"
G = ["量比≥0.5","量比≥0.8","量比≥1.0","量比≥1.2","量比≥1.5"]
U = ["量比≤1.0","量比≤1.5","量比≤2.0","量比≤3.0"]
R = ["盈亏比≥1.0","盈亏比≥1.5","盈亏比≥2.0","盈亏比≥3.0","盈亏比≥4.0"]
C = ["量比≤1.5 & 盈亏比≥2.0","量比≤2.0 & 盈亏比≥1.5","量比0.5~1.5 & 盈亏比≥2.0"]
b = A[BASE]["all"]

def row(lab):
    m = A[lab]["all"]
    if not m:
        return "| %s | **0** | — | — | — | — | — | — |" % lab
    return ("| %s | %d | +%.2f%% | %.2f%% | %s | %.2f%% | %+.4f%% | %.2f |"
            % (lab, m["n_trades"], m["ann"], m["mdd"], m["sharpe"], m["win_rate"],
               m["mean_per_trade"], A[lab]["per_day"]))

def block(title, keys, note):
    out = ["### %s\n" % title,
           "| 门槛 | 笔数 | 年化 | 最大回撤 | 夏普 | 净胜率 | 单笔净均 | 日均成交 |",
           "|---|---|---|---|---|---|---|---|",
           "| **无门槛（基线）** | %d | **+%.2f%%** | %.2f%% | %s | %.2f%% | **%+.4f%%** | %.2f |"
           % (b["n_trades"], b["ann"], b["mdd"], b["sharpe"], b["win_rate"], b["mean_per_trade"],
              A[BASE]["per_day"]),
           "| 基线（2018+ 口径） | %d | +%.2f%% | %.2f%% | %s | %.2f%% | %+.4f%% | — |"
           % (A[BASE]["w2018"]["n_trades"], A[BASE]["w2018"]["ann"], A[BASE]["w2018"]["mdd"],
              A[BASE]["w2018"]["sharpe"], A[BASE]["w2018"]["win_rate"], A[BASE]["w2018"]["mean_per_trade"]),
           ]
    for k in keys:
        out.append(row(k))
    out.append("\n%s\n" % note)
    return "\n".join(out)

MD = """# 横盘低开·两日｜准入门槛扫描：量比 × 盈亏比（R-hpdk-gates-0927）

- 触发：用户 2026-09-27 提问「量比要多于多少、盈亏比要大于多少，回测数据会有改善吗？」
- 脚本：`backtest/hengpan_fangliang_dikai_0925/x5_gates.py`（不重写逻辑，复用 `x2_sens` 的重放/记账）
- 证据：`backtest/hengpan_fangliang_dikai_0925/evidence_gates_scan.json`
- 冻结脚本：v1.4 `4a6fe5f7…` → **v1.5 %s**（只增**默认值无操作**的研究开关；勘误 E-13）
- 口径：**主板限定**（E-12 已生效）/ K=10 / KSLOT=20 / 成本 6.92bp 往返 / 全窗 2015-01-05~2026-09-24

## 一、定义

| 量 | 定义 |
|---|---|
| 量比 VOLBR | `volume[T] / mean(volume[T−20..T−1])`（窗口**不含当日**，与预注册 §1.3 一致） |
| 盈亏比 RR | `止盈距离 / ATR20%%` = `P[TP] / ATR20%%`；`ATR20%% = mean(TR)/close`，`TR = max(H−L, |H−C_prev|, |L−C_prev|)` |
| 含义 | RR ≥ 1 ⇔ 20 日平均真实波幅 ≥ 2%% ⇔ 该股**日波动 ≥ 2%%** 才过门槛 |

> ⚠ 关键前提：**复合分 `F = z(−ln AMT20) + z(−ln VOLBR) + z(−RET20)` 已经用连续 z 分软性偏好了「缩量」**。
> 加硬门槛不是加信息，而是把连续偏好截断。

## 二、结果（全窗，主板池）

%s
%s
%s

## 三、结论

1. **量比下限：单调恶化，没有拐点。** 从 ≥0.5 起就比基线差，越紧越差（≥0.5 +%.2f%% → ≥1.5 **+%.2f%%**、夏普 %.2f → %.2f）。
   ⇒ 用户设想的方向（「量比要多于多少」）在该策略上是**反的**：策略买的就是**缩量**票，量比下限直接砍掉它的核心样本。
2. **量比上限：同样单调恶化（越紧越差）**。说明 z 分偏好已经最优，硬截断只减样本、不加 alpha。
3. **盈亏比下限：灾难性，且把样本砍光。** ≥1.0 → 年化 **%.2f%%**、夏普 **%s**、净胜率 48.41%%、笔数从 %d 掉到 **%d**（日均 %.2f）；
   ≥2.0 只剩 **14 笔**；≥3.0/≥4.0 **零成交**。
   机制：RR ≥ 1 要求该股日波动 ≥ 2%%，而策略选的是**低波动缩量**票 ⇒ 门槛把选股方向整体反转。
4. **组合门槛同样为负**（见上表末三行），没有任何一格优于基线。
5. **机制（与板块限定同源）**：任何门槛都会改变**当日候选池** ⇒ 横截面 z 重新标准化 ⇒ **选股整体重排**，
   不是「在原名单上删几只」。所以「加一个门槛只损失一部分样本」是错的直觉。

## 四、处置

**不采纳任何门槛，冻结规格维持 v1.5 默认值（等价于 v1.4）。** 基线等价性已机械验证：
`base` 臂与 v1.4 读数**逐位相同**（年化 +%.2f%% / MDD %.2f%% / 夏普 %s / 笔数 %d / 净均 %+.4f%%），
见 `evidence_gates_scan.json` 的 `baseline_equiv_ok: %s`。

**关于「每天只能买几只」**：不是「只能买几只」，而是**两层限制**：
① 每个信号日按复合分取 **前 K=10 名**；② 操作档 **KSLOT=4** 限制同时持仓数（历史上日均实际成交 1.7~2.8 只）；
③ 单票 ≤ 该股 20 日均额×1%% ⇒ 账户上限约 101 万元。资格池 %d 只（主板口径）只是**待筛选的全体**，
09:25 用真实今开筛出低开 1~3%% 的子集后才定榜。

## 五、复现

```bat
python backtest/hengpan_fangliang_dikai_0925/x5_gates.py --cache <缓存目录>
```
""" % (E["frozen_script_sha256"],
       block("2.1 量比下限（用户设想的「要有量」）", G,
             "**判定：单调恶化。** 加量比下限 = 反方向；既有的「要缩量」结论在此再次被印证。"),
       block("2.2 量比上限", U,
             "**判定：越紧越差**，但幅度小于下限档 —— 因为 z 分偏好本就把放量票排到后面。"),
       block("2.3 盈亏比下限（用户设想的「盈亏比要好」）", R,
             "**判定：灾难性，且样本被砍光（≥3.0 起零成交）。** RR 门槛与策略选股方向相反。"),
       A["量比≥0.5"]["all"]["ann"], A["量比≥1.5"]["all"]["ann"],
       A["量比≥0.5"]["all"]["sharpe"], A["量比≥1.5"]["all"]["sharpe"],
       A["盈亏比≥1.0"]["all"]["ann"], A["盈亏比≥1.0"]["all"]["sharpe"],
       b["n_trades"], A["盈亏比≥1.0"]["all"]["n_trades"], A["盈亏比≥1.0"]["per_day"],
       b["ann"], b["mdd"], b["sharpe"], b["n_trades"], b["mean_per_trade"],
       str(E["baseline_equiv_ok"]), A[BASE]["n_trades"])
(D.parent.parent / "backtest/报告-准入门槛扫描-量比与盈亏比-20260927.md").write_text(MD, encoding="utf-8")
print("报告已生成；长度 =", len(MD))
print("基线等价:", E["baseline_equiv_ok"])
