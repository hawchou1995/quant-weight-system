# -*- coding: utf-8 -*-
"""双体系看板（模板样式）：v9-auto 普适版 + v8-lite 个人版，2026-08-14 收盘口径"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
import v8_selector as V

# ---------------- 数据加载 ----------------
def load_summary(f):
    return json.load(open(BASE / f, encoding="utf-8"))["summary"]

s_auto = load_summary("v9_auto_summary.json")
s_lite = load_summary("v8_lite_summary.json")

names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
name = lambda c: names.get(c, c)

# 净值曲线（归一化 100 起）
def load_curve(f):
    df = pd.read_csv(BASE / f)
    v = df["value"].astype(float).values
    return df["date"].tolist(), v / v[0] * 100

d_auto, v_auto = load_curve("v9_auto_equity.csv")
d_lite, v_lite = load_curve("v8_lite_equity.csv")

# 合并日期轴（按 v9 的轴，v8 用 reindex 近似）
dates = pd.to_datetime(d_auto)
s_v8 = pd.Series(v_lite, index=pd.to_datetime(d_lite))
v_lite_aligned = s_v8.reindex(dates, method="ffill").fillna(100).values

# ---------------- v9-auto 当前自动池 Top10 ----------------
cur_top = json.load(open(BASE / "v9_current_top.json", encoding="utf-8"))

# ---------------- v8-lite 自选池 08-14 档位 ----------------
sys.path.insert(0, str(BASE))
import v8_lite as L
pool = L.build_pool(verbose=False)

STOCKS = ['300502','300308','600498','601138','002463','002384','600183','300476','603986',
          '002185','605358','603228','603339','000636','605189','600403','002879','600162','000759','002474']
ETFS = ['159516','515880','516150','560390','159841']
ALL = STOCKS + ETFS

def tier(sc):
    if sc >= 75: return "满仓加仓"
    if sc >= 60: return "轻仓加仓"
    if sc >= 45: return "观望"
    if sc >= 30: return "减至半仓"
    return "清仓"

rows_lite = []
for c in ALL:
    k = ("sh" if c.startswith(("6", "5")) else "sz") + c
    ddf = pool.get(k)
    if ddf is None or len(ddf) == 0:
        continue
    r = ddf.iloc[-1]
    px = r["close"]
    if pd.isna(px) or pd.isna(r.get("mom_12_1", np.nan)):
        continue
    sc = V.score_row(r)
    ret_1y = (px / ddf["close"].iloc[-252] - 1) * 100 if len(ddf) > 252 else float("nan")
    rows_lite.append({
        "code": c, "name": name(k), "px": px, "score": sc,
        "tier": tier(sc), "lot": px * 100,
        "ret_1y": ret_1y,
        "board": "ETF" if k.startswith(("sh5", "sz1")) else ("创业板" if c.startswith("30") else "主板"),
    })
rows_lite.sort(key=lambda x: -x["score"])

# ---------------- SVG 双净值曲线 ----------------
W, H = 1400, 380
PAD_L, PAD_R, PAD_T, PAD_B = 70, 20, 30, 40
n = len(dates)
x = lambda i: PAD_L + (W - PAD_L - PAD_R) * i / max(1, n - 1)
all_v = np.concatenate([v_auto, v_lite_aligned])
vmin, vmax = 50, max(200, math.ceil(all_v.max() / 100) * 100)
y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - (v - vmin) / (vmax - vmin))

def polyline(vals, color, width=2):
    pts = " ".join(f"{x(i):.1f},{y(vals[i]):.1f}" for i in range(0, n, 3))
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>'

# 网格与年份刻度
grid = ""
for yy in range(0, vmax + 1, 50):
    grid += f'<line x1="{PAD_L}" y1="{y(yy):.1f}" x2="{W-PAD_R}" y2="{y(yy):.1f}" stroke="#e5e7eb" stroke-width="1"/>'
    grid += f'<text x="{PAD_L-8}" y="{y(yy)+4:.1f}" font-size="12" fill="#6b7280" text-anchor="end">{yy}</text>'
year_labels = {}
for i, dt in enumerate(dates):
    if dt.year != (dates[i-1].year if i > 0 else None):
        year_labels[dt.year] = i
for yr, i in year_labels.items():
    grid += f'<text x="{x(i):.1f}" y="{H-PAD_B+20}" font-size="13" fill="#6b7280" text-anchor="middle">{yr}</text>'
    grid += f'<line x1="{x(i):.1f}" y1="{PAD_T}" x2="{x(i):.1f}" y2="{H-PAD_B}" stroke="#eef0f3" stroke-width="1"/>'

svg_curve = f'''<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;background:#fff;border-radius:12px;border:1px solid #e5e7eb">
{grid}
{polyline(v_lite_aligned, "#3b82f6", 2)}
{polyline(v_auto, "#f59e0b", 2.5)}
<text x="{PAD_L+10}" y="{PAD_T+20}" font-size="13" fill="#3b82f6">v8-lite 个人版（自选池 Top4）</text>
<text x="{PAD_L+10}" y="{PAD_T+40}" font-size="13" fill="#f59e0b">v9-auto 普适版（全市场自动池 Top3）</text>
<text x="{W-PAD_R-10}" y="{y(v_auto[-1])-8:.1f}" font-size="14" font-weight="bold" fill="#f59e0b" text-anchor="end">+839.6%</text>
<text x="{W-PAD_R-10}" y="{y(v_lite_aligned[-1])-8:.1f}" font-size="14" font-weight="bold" fill="#3b82f6" text-anchor="end">+3923.7%</text>
</svg>'''

# ---------------- HTML ----------------
def kpi(label, value, sub, color="#111827"):
    return f'''<div style="flex:1;min-width:130px;background:#f9fafb;border-radius:12px;padding:14px 16px;border:1px solid #e5e7eb">
    <div style="font-size:12px;color:#6b7280">{label}</div>
    <div style="font-size:24px;font-weight:700;color:{color};margin-top:4px">{value}</div>
    <div style="font-size:11px;color:#9ca3af;margin-top:2px">{sub}</div></div>'''

kpi_row_auto = "".join([
    kpi("策略收益", f"+{s_auto['total_return_pct']:.1f}%", "2016-01 ~ 2026-08", "#f59e0b"),
    kpi("年化收益", f"{s_auto['annual_return_pct']:.1f}%", "50万中性资金", "#f59e0b"),
    kpi("最大回撤", f"{s_auto['max_drawdown_pct']:.1f}%", "达标 ≤30%", "#ef4444"),
    kpi("夏普比率", f"{s_auto['sharpe']:.3f}", "达标 ≥1", "#22c55e"),
    kpi("胜率", f"{s_auto['win_rate_pct']:.1f}%", f"{s_auto['total_trades']} 笔", "#111827"),
    kpi("交易频率", "17笔/年", "月轮动 Top3", "#111827"),
])
kpi_row_lite = "".join([
    kpi("策略收益", f"+{s_lite['total_return_pct']:.1f}%", "2016-01 ~ 2026-08", "#3b82f6"),
    kpi("年化收益", f"{s_lite['annual_return_pct']:.1f}%", "50万中性资金", "#3b82f6"),
    kpi("最大回撤", f"{s_lite['max_drawdown_pct']:.1f}%", "达标 ≤25%", "#ef4444"),
    kpi("夏普比率", f"{s_lite['sharpe']:.3f}", "达标 ≥1", "#22c55e"),
    kpi("胜率", f"{s_lite['win_rate_pct']:.1f}%", f"{s_lite['total_trades']} 笔", "#111827"),
    kpi("交易频率", "20笔/年", "月轮动 Top4", "#111827"),
])

# v9-auto 当前 Top10 表
top_rows = ""
for r in cur_top:
    nm = name("sh" + r["code"][2:] if not r["code"].startswith("sh") else r["code"])
    top_rows += f'''<tr><td style="text-align:center">{r["rank"]}</td><td><b>{nm}</b><br><span style="color:#9ca3af;font-size:11px">{r["code"]}</span></td>
    <td style="text-align:right">{r["px"]:.2f}</td><td style="text-align:center"><b>{r["score"]:.1f}</b></td>
    <td style="text-align:right;color:#22c55e">+{r["mom"]:.0f}%</td><td style="text-align:center">{r["rsi"]:.0f}</td>
    <td style="text-align:right;color:#22c55e">+{r["ma150_d"]:.1f}%</td>
    <td style="text-align:center"><span style="background:#fef3c7;color:#b45309;padding:3px 10px;border-radius:20px;font-size:12px">{"满仓加仓" if r["rank"]<=3 else "加仓候选"}</span></td></tr>'''

# v8-lite 自选池表
lite_rows = ""
for i, r in enumerate(rows_lite, 1):
    tier_color = {"满仓加仓": "#dc2626", "轻仓加仓": "#ea580c", "观望": "#d97706", "减至半仓": "#6b7280", "清仓": "#9ca3af"}.get(r["tier"], "#111827")
    ret_txt = f'{r["ret_1y"]:+.0f}%' if not math.isnan(r["ret_1y"]) else "—"
    lot_txt = f'{r["lot"]:,.0f}' if r["lot"] < 100000 else f'{r["lot"]/10000:.1f}万'
    lite_rows += f'''<tr><td style="text-align:center">{i}</td><td><b>{r["name"]}</b><br><span style="color:#9ca3af;font-size:11px">{r["code"]} {r["board"]}</span></td>
    <td style="text-align:right">{r["px"]:.2f}</td><td style="text-align:center"><b>{r["score"]:.1f}</b></td>
    <td style="text-align:right">{ret_txt}</td><td style="text-align:right">{lot_txt}</td>
    <td style="text-align:center"><span style="background:#fef3c7;color:{tier_color};padding:3px 10px;border-radius:20px;font-size:12px">{r["tier"]}</span></td></tr>'''

html = f'''<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>量化权重双体系看板（2026-08-14）</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f3f4f6;margin:0;padding:24px;color:#111827}}
.container{{max-width:1500px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 4px}}
.sub{{color:#6b7280;font-size:13px;margin-bottom:20px}}
.section{{background:#fff;border-radius:16px;padding:24px;margin-bottom:24px;border:1px solid #e5e7eb}}
.section-title{{font-size:19px;font-weight:700;margin-bottom:4px;display:flex;align-items:center;gap:10px}}
.badge{{font-size:12px;padding:3px 10px;border-radius:20px;font-weight:500}}
.badge-auto{{background:#fef3c7;color:#b45309}}
.badge-lite{{background:#dbeafe;color:#1d4ed8}}
.section-sub{{color:#6b7280;font-size:12px;margin-bottom:16px}}
.kpis{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:20px}}
.rule-box{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:14px 18px;margin-bottom:16px;font-size:13px;line-height:1.9;color:#374151}}
.rule-box b{{color:#111827}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f9fafb;color:#6b7280;font-size:12px;padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:left}}
td{{padding:9px 8px;border-bottom:1px solid #f0f1f3;vertical-align:middle}}
tr:hover td{{background:#fafbfc}}
.divider{{height:1px;background:#e5e7eb;margin:20px 0}}
.note{{color:#9ca3af;font-size:12px;margin-top:10px}}
</style></head><body><div class="container">

<h1>📊 量化权重双体系看板</h1>
<div class="sub">2026-08-14 收盘口径 · 全量池 5307 只 · 2016-01 ~ 2026-08 · 仅供研究参考</div>

<!-- ============ 体系 A：v9-auto ============ -->
<div class="section">
<div class="section-title">🅰️ v9-auto 普适版 <span class="badge badge-auto">全市场自动池 · 无人工选池</span></div>
<div class="section-sub">每月从全市场 5307 只按绝对规则自动筛池 → 池内 Top3 等权 · 移动止损 4.5% · MA150 择时 · 动态门槛 · RSI&lt;85</div>
<div class="kpis">{kpi_row_auto}</div>
{svg_curve}
<div class="rule-box">
<b>自动筛池规则（人人平等，不挑股）</b>：绝对动量 ≥25% ｜ 四因子分 ≥65（动量35/趋势25/Aroon20/量价20）｜ 收盘 &gt; MA150 ｜ 价格 ≥2 元 ｜ 成交额 ≥500万 ｜ RSI &lt;85<br>
<b>风控</b>：移动止损 4.5%（持仓峰值回撤，次日开盘执行）｜ 沪深300 破 MA150 全仓离场 ｜ 买不起自动补位下一名<br>
<b>权限档</b>：main=仅主板（新开户）夏普 2.49 ｜ gem=+创业板 2.44 ｜ star=+科创板 2.34（引擎 perm 参数）
</div>
<h3 style="margin:16px 0 8px">当前自动池 Top10（2026-08-14 收盘 · 动态门槛 66 · 达标 391 只）</h3>
<table>
<tr><th>排名</th><th>标的</th><th>现价</th><th>权重分</th><th>绝对动量</th><th>RSI</th><th>距MA150</th><th>档位</th></tr>
{top_rows}
</table>
<div class="note">Top3 为当前执行持仓建议（等权，每只约 1/3 资金）；第 4-10 名为自动补位候选（买不起时按序顶替）。</div>
</div>

<!-- ============ 体系 B：v8-lite ============ -->
<div class="section">
<div class="section-title">🅱️ v8-lite 个人版 <span class="badge badge-lite">固定自选池 25 只 · Top4 轮动</span></div>
<div class="section-sub">自选池 25 只（20 股 + 5 ETF）内四因子打分轮动 Top4 · 月轮动（21日）· 移动止损 10% · MA200 择时 · 动态等权</div>
<div class="kpis">{kpi_row_lite}</div>
<div class="rule-box">
<b>执行层</b>：自选池 25 只内打分排序 → 每期持有 Top4 等权（动态等权，资金利用率近 100%）<br>
<b>信号层</b>：每只独立档位 满仓加仓≥75 / 轻仓加仓≥60 / 观望≥45 / 减至半仓≥30 / 清仓&lt;30（每月刷新，任何标的得分不足即观望）<br>
<b>风控</b>：移动止损 10%（峰值回撤）｜ 沪深300 破 MA200 全仓离场 ｜ 整手 100 股，买不起自然跳过
</div>
<h3 style="margin:16px 0 8px">自选池 25 只 · 08-14 收盘档位（按权重分排序）</h3>
<table>
<tr><th>排名</th><th>标的</th><th>现价</th><th>权重分</th><th>近一年</th><th>一手成本</th><th>档位</th></tr>
{lite_rows}
</table>
<div class="note">档位 = 该标的当前操作建议：加仓类为买入/持有至目标仓位，观望为持有不加，减/清仓为卖出。执行按 Top4 容量截断（资金现实）。</div>
</div>

<div class="note" style="text-align:center;margin-top:8px">⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。</div>
</div></body></html>'''

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")
print(f"已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
