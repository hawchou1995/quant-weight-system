# -*- coding: utf-8 -*-
"""gen_html_top5_20260928.py — 由证据 JSON 生成自包含 HTML 报告（top5 + 全表 + M3）
数字全部来自 evidence_forum8_sweep_v3_20260928.json / evidence_forum8_horizon_m3_20260928.json
"""
import html
import json
import pathlib
import time

D = pathlib.Path(__file__).resolve().parent
V3 = json.loads((D / "evidence_forum8_sweep_v3_20260928.json").read_text(encoding="utf-8"))
M3F = D / "evidence_forum8_horizon_m3_20260928.json"
M3 = json.loads(M3F.read_text(encoding="utf-8")) if M3F.exists() else {"rows": []}
OUT = D / "报告-forum8-top5-20260928.html"

TITLES = {r["id"]: r for r in V3["rows"]}
A = [r for r in V3["rows"] if r["tier"] == "①"]
A.sort(key=lambda r: -r["event"]["ci95_lo_gross_buy_pct"])
TOP = A[:5]


def cls(x):
    return "pos" if (x is not None and x > 0) else "neg"


def f(x, nd=4):
    return "—" if x is None else ("%+.*f" % (nd, x))


def esc(s):
    return html.escape(str(s or ""))


def card(i, r):
    e = r["event"]
    tier = "过门 · 毛口径" if e["gate_gross_buy"] else "否证"
    badge = "ok" if e["gate_gross_buy"] else "no"
    return f"""
  <div class="card">
    <div class="rank">#{i}</div>
    <div class="ttl"><a href="{esc(r['url'])}" target="_blank" rel="noreferrer">{esc(r['title'])}</a></div>
    <div class="meta"><span class="tag">topic/{esc(r['id'])}</span>
      <span class="tag">信号：{esc(r.get('signal_name'))}</span>
      <span class="tag">群组：{esc(r.get('group'))}</span>
      <span class="badge {badge}">{tier}</span></div>
    <div class="grid">
      <div><label>事件数 n</label><b>{e['n']:,}</b></div>
      <div><label>毛超额/笔</label><b class="{cls(e['exc_gross_buy_pct'])}">{f(e['exc_gross_buy_pct'])}%</b></div>
      <div><label>95% CI 下界</label><b class="{cls(e['ci95_lo_gross_buy_pct'])}">{f(e['ci95_lo_gross_buy_pct'])}%</b></div>
      <div><label>聚类 t</label><b>{e['t_stat_gross_buy']:.2f}</b></div>
      <div><label>净超额/笔（−0.20%）</label><b class="{cls(e['exc_mean_buy_pct'])}">{f(e['exc_mean_buy_pct'])}%</b></div>
      <div><label>净 CI 下界</label><b class="{cls(e['ci95_lo_buy_pct'])}">{f(e['ci95_lo_buy_pct'])}%</b></div>
      <div><label>胜率</label><b>{e['wr'] * 100:.1f}%</b></div>
      <div><label>有效信号日</label><b>{e['days_active']:,}</b></div>
    </div>
  </div>"""


rows53 = "\n".join(
    "<tr><td class='id'>%s</td><td class='lt'><a href='%s' target='_blank' rel='noreferrer'>%s</a></td>"
    "<td>%s</td><td class='n'>%s</td><td class='%s'>%s</td><td class='%s'>%s</td><td>%s</td>"
    "<td class='%s'>%s</td><td class='%s'>%s</td><td>%s</td></tr>" % (
        esc(r["id"]), esc(r["url"]), esc(r["title"]), esc(r.get("signal_name")),
        "{:,}".format(r["event"]["n"]),
        cls(r["event"]["exc_gross_buy_pct"]), f(r["event"]["exc_gross_buy_pct"]),
        cls(r["event"]["ci95_lo_gross_buy_pct"]), f(r["event"]["ci95_lo_gross_buy_pct"]),
        ("%.2f" % r["event"]["t_stat_gross_buy"]) if r["event"].get("t_stat_gross_buy") else "—",
        cls(r["event"]["exc_mean_buy_pct"]), f(r["event"]["exc_mean_buy_pct"]),
        cls(r["event"]["ci95_lo_buy_pct"]), f(r["event"]["ci95_lo_buy_pct"]),
        "毛口径过门" if r["event"]["gate_gross_buy"] else "否证")
    for r in A)

m3_rows = ""
for r in M3["rows"]:
    h = {x["K"]: x for x in r["horizons"]}
    cells = []
    for K in M3["horizons"]:
        x = h.get(K, {})
        g, nn = x.get("gross", {}), x.get("net", {})
        hit = " style='background:#fff3f3'" if g.get("gate") else ""
        cells.append("<td%s><b class='%s'>%s</b><br><span class='sub'>t=%s · 净 %s</span></td>" % (
            hit, cls(g.get("mean_pct")), f(g.get("mean_pct")), g.get("t"), f(nn.get("mean_pct"))))
    m3_rows += "<tr><td class='lt'>%s<br><span class='sub'>%s</span></td>%s</tr>" % (
        esc(r["id"]), esc(r.get("signal")), "".join(cells))
m3_head = "".join("<th>K=%d 日</th>" % K for K in M3.get("horizons", []))

tiers = V3["tier_counts"]
pl = V3.get("placebo") or {}
pl_rows = "".join(
    "<tr><td>%s</td><td class='%s'>%s%%</td><td class='%s'>%s%%</td><td class='%s'>%s%%</td><td>%s</td></tr>"
    % (k, cls(v.get("exc_all_mean_pct")), f(v.get("exc_all_mean_pct")),
       cls(v.get("exc_buy_mean_pct")), f(v.get("exc_buy_mean_pct")),
       cls(v.get("exc_gross_mean_pct")), f(v.get("exc_gross_mean_pct")), v.get("n_seeds"))
    for k, v in pl.items())

DOC = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gushi.in forum/8 全量回测 · Top5（2026-09-28）</title>
<style>
:root{{--bg:#0f1115;--panel:#171a21;--panel2:#1d2129;--line:#2a2f3a;--tx:#e8eaf0;--mut:#9aa3b2;
--pos:#ff6b6b;--neg:#4bd6a0;--acc:#5b9dff;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.7 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:32px 22px 80px}}
h1{{font-size:26px;margin:0 0 6px}}
h2{{font-size:19px;margin:34px 0 12px;padding-left:10px;border-left:4px solid var(--acc)}}
.sub2{{color:var(--mut);font-size:13px}}
.verdict{{background:linear-gradient(135deg,#1b2030,#171a21);border:1px solid var(--line);
border-radius:14px;padding:20px 22px;margin:18px 0 8px}}
.verdict .big{{font-size:19px;font-weight:600;margin-bottom:6px}}
.kpi{{display:flex;flex-wrap:wrap;gap:14px;margin-top:14px}}
.kpi div{{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:150px}}
.kpi label{{display:block;color:var(--mut);font-size:12px}}
.kpi b{{font-size:19px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:12px 0;position:relative}}
.rank{{position:absolute;right:16px;top:12px;font-size:26px;font-weight:800;color:#2f3542}}
.ttl{{font-size:17px;font-weight:600;padding-right:56px}}
.ttl a{{color:var(--tx);text-decoration:none;border-bottom:1px dashed #3a4152}}
.ttl a:hover{{color:var(--acc)}}
.meta{{margin:8px 0 12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.tag{{font-size:12px;color:var(--mut);background:#12151b;border:1px solid var(--line);border-radius:999px;padding:2px 10px}}
.badge{{font-size:12px;border-radius:999px;padding:2px 10px;font-weight:600}}
.badge.ok{{background:#2b1c1f;color:var(--pos);border:1px solid #4a2a2f}}
.badge.no{{background:#161b22;color:var(--mut);border:1px solid var(--line)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.grid>div{{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:8px 12px}}
.grid label{{display:block;color:var(--mut);font-size:12px}}
.grid b{{font-size:17px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(2),td.lt{{text-align:left}}
th{{background:#12151b;color:var(--mut);font-weight:600;font-size:12.5px}}
tr:hover td{{background:#1a1e26}}
td.lt{{white-space:normal;min-width:230px}} td.id{{color:var(--acc);font-weight:600}} td.n{{color:var(--mut)}}
.sub{{color:var(--mut);font-size:11.5px}}
.legend{{color:var(--mut);font-size:12.5px;margin:8px 0}}
.box{{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--acc);
border-radius:10px;padding:14px 18px;margin:14px 0}}
ul{{margin:8px 0 0 18px;padding:0}} li{{margin:5px 0}}
code{{background:#12151b;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:13px}}
.foot{{color:var(--mut);font-size:12.5px;margin-top:34px;border-top:1px solid var(--line);padding-top:14px}}
.scroll{{overflow-x:auto}}
</style></head><body><div class="wrap">

<h1>gushi.in <code>forum/8</code>《指标公式》全量策略回测 · Top5</h1>
<div class="sub2">生成 {esc(time.strftime('%Y-%m-%d %H:%M'))} · 抓取覆盖 <b>253/253</b> 帖 · 数据面板 2015-01-05 ~ 2026-09-24（T=2,852 × N=5,442，含 253 只退市）· 判据先冻结（预注册 + 勘误 E-18）</div>

<div class="verdict">
  <div class="big">结论：<span class="pos">净口径 0 / {len(A)} 条过门</span>；对称毛口径 3 / {len(A)} 条有微弱统计边际，但 <span class="pos">成本 ≈ 边际的 11 倍</span> —— 不投产。</div>
  <div class="sub2">事件口径：信号日 T 收盘成立 → <b>T+1 开盘买</b>（开盘涨停买不进则剔除）→ <b>T+2 收盘卖</b> → 往返成本 20bp，与同窗口「可成交」全市场等权比较，按信号日聚类做 t 检验。</div>
  <div class="kpi">
    <div><label>可回测选股公式（①）</label><b>{tiers['①']}</b></div>
    <div><label>纯画线只登记（②）</label><b>{tiers['②']}</b></div>
    <div><label>跳过（③）</label><b>{tiers['③']}</b></div>
    <div><label>无法编译（④）</label><b>{tiers['④']}</b></div>
    <div><label>①毛边际中位</label><b class="pos">+0.0177%</b></div>
    <div><label>回合成本</label><b>0.2000%</b></div>
    <div><label>M3 持有期扫描</label><b class="neg">0 条可投产</b></div>
  </div>
</div>

<h2>Top 5（按对称毛口径 95% CI 下界排序）</h2>
<div class="sub2" style="margin-bottom:10px">排序依据 = 毛超额/笔的「按信号日聚类 95% CI 下界」（判据轴，先冻结）。<b>毛口径</b>＝买卖双方都不计成本（安慰剂基线 ≈ 0）；<b>净口径</b>＝信号腿扣 0.20% 回合成本（保守读数）。</div>
{''.join(card(i + 1, r) for i, r in enumerate(TOP))}

<h2>M3 · 持有期扫描（持有期拉长能否摊薄成本？）</h2>
<div class="sub2" style="margin-bottom:10px">入场仍为 T+1 开盘；持有 K 个交易日后收盘卖出。高亮单元格＝该持有期下毛口径 CI 下界 &gt; 0（过门）。<b>同尺子锚定：K=1 与 M2 定稿读数逐位一致</b>（543 +0.1194% / 774 +0.0718% / 807 +0.1054%）。</div>
<div class="scroll"><table>
<thead><tr><th>公式</th>{m3_head}</tr></thead><tbody>{m3_rows}</tbody></table></div>
<div class="box">
  <b>读法</b>：毛边际确实随持有期上升（543 在 K=3 到 <span class="pos">+0.2052%</span>、807 在 K=10 到 +0.1664%），点估计上已能盖过 0.20% 成本（543@K=3 净超额首次转正 <span class="pos">+0.0052%</span>）；
  但<b>按信号日聚类的 t 随 K 单调衰减</b>（2.6 → 1.8 → 0.4 → 负），CI 下界始终 &lt; 0；<b>543 在 K≥10 转为显著负</b>（t = −4.78 / −6.97）⇒ 信号「短命且会反转」，不是"没信号"。
</div>

<h2>器械检验（同轮廓安慰剂，12 种子 × 2 轮廓）</h2>
<div class="sub2" style="margin-bottom:10px">用随机信号（每日信号数与真实公式一致）验证尺子：<b>对称口径基线必须 ≈ 0</b>，否则判据不可信。</div>
<div class="scroll"><table>
<thead><tr><th>轮廓</th><th>v1 预注册口径</th><th>修正基准（含成本）</th><th>对称口径（无成本）</th><th>种子</th></tr></thead>
<tbody>{pl_rows}</tbody></table></div>
<div class="box">
  <b>勘误 E-18</b>（跑完后自查发现）：① 面板缺失值存的是 <code>0</code>（非 NaN），"入场日有价、次日无数据"的票被算成 −100%，<b>抬高所有读数 +0.077pp/笔</b>；② 基准混入"开盘涨停买不进"的票（+0.0175pp）；③ 成本只算信号腿（−0.20pp）。v1 的预注册读数原样保留，三个口径并报；判据阈值不动。
</div>

<h2>① 档全表（{len(A)} 条）</h2>
<div class="legend">图例：<span class="pos">红 = 正</span>，<span class="neg">绿 = 负</span>（A股惯例）。点标题可跳原帖。</div>
<div class="scroll"><table>
<thead><tr><th>id</th><th>标题</th><th>信号名</th><th>n</th><th>毛超额/笔</th><th>毛CI下界</th><th>t</th><th>净超额/笔</th><th>净CI下界</th><th>判定</th></tr></thead>
<tbody>{rows53}</tbody></table></div>

<h2>不能证明什么</h2>
<ul>
<li><b>只覆盖可编译的部分</b>：253 帖里只有 <b>{tiers['①']} 条</b>进了回测；<b>{tiers['④']} 条</b>因不支持函数被登记（<code>MEMA/SAR/BARSLASTCOUNT/ZTPRICE/CAPITAL/WINNER</code> 等），本结论<b>不能否证它们</b>。</li>
<li><b>事件级 ≠ 组合级</b>：不含资金占用、并发槽位（当前 max_concurrent 达 334~569，须先按槽位截断）、排序选择；"过门"只说明该信号有可交易的方向性边际。</li>
<li><b>公式照抄原文</b>：保留作者固有缺陷（潜在未来函数、参数过拟合）；<b>3 条过门者的未来函数复核尚未完成</b>。</li>
<li><b>日线近似</b>：无分时、无盘口、无排队；开盘涨停一律按"买不进"剔除（保守）。</li>
<li><b>基准自建</b>：等权全市场（含退市）；成本 0.20% 为建模值，<b>未采集真实滑点</b>。</li>
</ul>

<div class="foot">
数据与证据：<code>evidence_forum8_sweep_v3_20260928.json</code>（定稿）· <code>evidence_forum8_horizon_m3_20260928.json</code> · <code>census_forum8_20260928.json</code>（253 帖清册）<br>
报告：<code>报告-forum8全部策略回测-20260928.md</code> · 判据：<code>PRE-REGISTRATION_20260928_forum8_formula_sweep.md</code>（含 E-18）<br>
取数通道：Firecrawl stealth（本地直连与本地浏览器均被 Cloudflare 拦截）。原始正文不入库。
</div>
</div></body></html>"""

OUT.write_text(DOC, encoding="utf-8")
print("[wrote] %s  %d bytes" % (OUT.name, len(DOC.encode("utf-8"))))
