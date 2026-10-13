# -*- coding: utf-8 -*-
"""从证据 JSON 生成 `dashboard_short_pool_v16.html`（**不手改数字**，避免产物与证据漂移）

读入（全部为本目录脚本真跑产出）：
  evidence_short_pool_four_arms.json           四臂阶梯（保真度）
  evidence_short_pool_v16.json                 三成本档（主板 / 原口径）
  evidence_layered_v16.json                    分层 4 宇宙
  evidence_zero_overlap_20261008.json          修正后回归门（PASS）
  evidence_zero_overlap_prefix_20261008.json   修正前基线（FAIL）

用法：`python build_dashboard_short_pool_v16.py`
产物：`dashboard_short_pool_v16.html`（自包含，双击可开）

注：模板一律用 `@@占位@@` + `str.replace`，**不用 % 格式化** —— HTML/CSS 里到处是字面 `%`，
用 % 格式化会被当成格式符（本文件第一版就是这么崩的）。
"""
from __future__ import annotations

import html
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dashboard_short_pool_v16.html")
ARMS_ORDER = ["A_x3", "C_x3", "B_x3"]


def load(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def f(v, nd=2, dash="—"):
    if v is None:
        return dash
    return ("{:." + str(nd) + "f}").format(v)


def esc(s):
    return html.escape(str(s))


# --------------------------------------------------------------------------- §1
def sec_gates(post, pre):
    rows = []
    for a in ARMS_ORDER:
        po = (post or {}).get("arms", {}).get(a, {})
        pr = (pre or {}).get("arms", {}).get(a, {})
        if not po:
            continue
        g = po.get("gates", {})

        def mark(x):
            return "<td class='ok'>%s</td>" % x if x else "<td class='bad'>%s</td>" % x

        rows.append(
            "<tr><td><b>{a}</b></td>"
            "<td class='bad'>{p0}</td><td class='ok'><b>{q0}</b></td>"
            "<td class='bad'>{pm1}</td><td class='ok'><b>{qm1}</b></td>"
            "<td class='bad'>{pem}</td><td class='ok'><b>{qem}</b></td>"
            "{g1}{g2}{g5}<td>{st}</td></tr>".format(
                a=esc(a),
                p0=pr.get("n_common_shift0", "—"), q0=po.get("n_common_shift0", "—"),
                pm1=(pr.get("shift_scan") or {}).get("-1", "—"),
                qm1=(po.get("shift_scan") or {}).get("-1", "—"),
                pem=(pr.get("entry_distance") or {}).get("mode", "—"),
                qem=(po.get("entry_distance") or {}).get("mode", "—"),
                g1=mark(g.get("G1", {}).get("pass_")), g2=mark(g.get("G2", {}).get("pass_")),
                g5=mark(g.get("G5", {}).get("pass_")), st=esc(po.get("status", "—"))))
    return GATES_TPL.replace("@@ROWS@@", "".join(rows))


GATES_TPL = """
<h2>§1 验收门（G1/G2/G5）<span class="tag">左=修正前 · 右=修正后 · 同一脚本从产物复算</span></h2>
<p class="note">修正前基线由 <code>--suffix _LEGACYALIGN</code> 跑出；两版都留档，可随时断言。</p>
<table>
<thead><tr><th>臂</th><th>共有@0<br>修正前</th><th>共有@0<br>修正后</th>
<th>共有@−1<br>修正前</th><th>共有@−1<br>修正后</th>
<th>入场距离众数<br>修正前</th><th>入场距离众数<br>修正后</th>
<th>G1</th><th>G2</th><th>G5</th><th>判定</th></tr></thead>
<tbody>@@ROWS@@</tbody></table>
<p class="note"><b>阈值</b>：G1 = 位移 0 交集 ≥ 0.95 × min(n(L1), n(L2))；G2 = 位移 ±1 不得高于位移 0；
G5 = 已对齐键的出场交易日距离众数 = 0。<br>
<b>修正前</b>：共有 0 ／ 位移 −1 = 313~314 ／ 入场距离众数 = 1 ⇒ 引擎成交日<b>晚 1 个交易日</b>（FAIL）。<br>
<b>修正后</b>：共有 403~404 ／ 位移 −1 = 0 ／ 距离众数 = 0（PASS）。</p>
"""


# --------------------------------------------------------------------------- §2
def sec_four(fa):
    if not fa:
        return ""
    rows, cards = [], []
    for a in ARMS_ORDER:
        v = fa.get("arms", {}).get(a)
        if not v:
            continue
        fr = v.get("frozen", {})
        L1, L2 = v.get("L1_legacy_cache", {}), v.get("L2_engine_cache", {})
        L3, L4 = v.get("L3_engine_datafull", {}), v.get("L4_engine_itemized_enf", {})
        sc = L1.get("set_compare_vs_engine", {})
        # 注意：组合级读数只有 L4 有（L1/L2/L3 是交易级，没有组合净值）——
        # 每行各取自己的 `d["portfolio"]`，不能拿 L4 的往所有行上套（本文件第一版就是这个 bug）。
        for nm, d, cls in (("L1 生产状态机 @cache", L1, ""),
                           ("L2 引擎 @cache", L2, "hl"),
                           ("L3 引擎 @data_full", L3, ""),
                           ("L4 引擎 · 分项20万 · 可成交性（K=5）", L4, "")):
            rows.append(
                "<tr class='{cls}'><td>{nm}<b>{a}</b></td><td>"
                "{n}</td><td>{wr}</td><td>{md}</td><td>{mn}</td><td>{pf}</td>"
                "<td>{fn}</td><td>{fm}</td></tr>".format(
                    cls=cls, nm=esc(nm), a=esc(a),
                    n=d.get("n", "—"), wr=f(d.get("wr_pct")), md=f(d.get("med_pct"), 3),
                    mn=f(d.get("mean_pct"), 3),
                    pf=("%s / %s / %s" % (f(d["portfolio"].get("ann_pct")),
                                          f(d["portfolio"].get("mdd_pct")),
                                          f(d["portfolio"].get("sharpe"), 3)))
                    if d.get("portfolio") else "—",
                    fn=f(fr.get("n"), 0), fm=f(fr.get("mean"), 3)))
        cards.append(
            "<div class='card'><div class='ch'>{a}</div><div class='cb'>"
            "集合归因：共有 <b>{c}</b> · 仅生产 {ol}（均值 {om}%）· 仅引擎 {oe}</div></div>".format(
                a=esc(a), c=sc.get("n_common", "—"), ol=sc.get("n_only_legacy", "—"),
                om=f(sc.get("mean_only_legacy_pct"), 3), oe=sc.get("n_only_engine", "—")))
    return FOUR_TPL.replace("@@ROWS@@", "".join(rows)).replace("@@CARDS@@", "".join(cards))


FOUR_TPL = """
<h2>§2 移植保真度 · 四臂阶梯 <span class="tag">同一份 cache 上把生产状态机与引擎并排</span></h2>
<table>
<thead><tr><th>层</th><th>n</th><th>胜率%</th><th>中位%</th><th>均值%</th>
<th>组合 年化 / 回撤 / 夏普</th><th>冻结 n</th><th>冻结 mean%</th></tr></thead>
<tbody>@@ROWS@@</tbody></table>
@@CARDS@@
<p class="note"><b>关键</b>：C_x3 的 L2 与 L1 <b>逐位相同</b>（n=404 · 63.12% · 2.045% · 2.048%），
集合 <b>404/404</b>；A_x3 / B_x3 为 <b>403/404</b>（差 1 笔，该笔均值 −16.62%）。<br>
L4 的 n 远小于 L2，是因为 L4 是 <b>K=5 槽位组合级</b>、L2 是 <b>K 不限交易级</b> —— 口径不同，勿直接比 n。</p>
"""


# --------------------------------------------------------------------------- §3
def sec_cost(v16):
    if not v16:
        return ""
    blocks = []
    for uni, arms in (v16.get("results") or {}).items():
        rows = []
        for key, v in arms.items():
            p = v.get("portfolio", {})
            t = v.get("trade_level", {})
            mode = key.split(" | ")[-1]
            rows.append(
                "<tr class='{cls}'><td>{a}</td><td>{m}</td><td><b>{ann}</b></td><td>{mdd}</td>"
                "<td>{sh}</td><td>{np}</td><td>{n}</td><td>{mwn}</td></tr>".format(
                    cls="hl" if mode == "itemized_enf" else "",
                    a=esc(key.split(" | ")[0]), m=esc(mode),
                    ann=f(p.get("ann_pct")), mdd=f(p.get("mdd_pct")), sh=f(p.get("sharpe"), 3),
                    np=p.get("n_trades", "—"), n=t.get("n", "—"),
                    mwn="%s / %s%% / %s%%" % (f(t.get("mean_pct"), 3), f(t.get("wr_pct")),
                                              f(t.get("med_pct"), 3))))
        blocks.append(
            "<h3>{u}</h3><table><thead><tr><th>配置</th><th>成本档</th><th>组合年化%</th><th>回撤%</th>"
            "<th>夏普</th><th>组合笔数</th><th>交易级 n</th><th>交易级 均值/胜率/中位</th></tr></thead>"
            "<tbody>{r}</tbody></table>".format(u=esc(uni), r="".join(rows)))
    return COST_TPL.replace("@@BLOCKS@@", "".join(blocks))


COST_TPL = """
<h2>§3 三成本档 · 组合级 + 交易级 <span class="tag">K=5 槽位 · 原口径 1.15% vs 分项成本</span></h2>
@@BLOCKS@@
<p class="note">「分项成本」与「分项 + 强制可成交性」在 A59 / C50 上读数相同，
是因为这两档的<b>成交日拒单数 = 0</b>。</p>
"""


# --------------------------------------------------------------------------- §4
def sec_layered(lz):
    if not lz:
        return ""
    rows = []
    for uni, arms in (lz.get("results") or {}).items():
        for aid, v in arms.items():
            t = v.get("trade_level", {})
            po = (v.get("portfolio") or {}).get("orig_cost", {})
            pe = (v.get("portfolio") or {}).get("itemized_enf", {})
            rows.append(
                "<tr><td>{u}</td><td><b>{a}</b></td><td>{n}</td><td>{wr}</td><td>{mn}</td><td>{md}</td>"
                "<td>{oa}</td><td>{om}</td><td class='hl'>{ea}</td><td>{em}</td></tr>".format(
                    u=esc(uni), a=esc(aid), n=t.get("n", "—"), wr=f(t.get("wr_pct")),
                    mn=f(t.get("mean_pct"), 3), md=f(t.get("med_pct"), 3),
                    oa=f(po.get("ann_pct")), om=f(po.get("mdd_pct")),
                    ea=f(pe.get("ann_pct")), em=f(pe.get("mdd_pct"))))
    return LAYER_TPL.replace("@@ROWS@@", "".join(rows))


LAYER_TPL = """
<h2>§4 短线分层 · 4 宇宙 <span class="tag">该信号是否只在主板成立</span></h2>
<table><thead><tr><th>宇宙</th><th>臂</th><th>交易级 n</th><th>胜率%</th><th>均值%</th><th>中位%</th>
<th>组合·原口径 年化%</th><th>回撤%</th><th>组合·分项enf 年化%</th><th>回撤%</th></tr></thead>
<tbody>@@ROWS@@</tbody></table>
<p class="note"><b>读法</b>：可用性高度集中在<b>主板</b>（A59 / C50 均正）；创业 / 科创单笔期望被稀释到
0.1~1.2% 且回撤 −50% 级别；合池（股票一体）掺入弱板块后反而更差 ⇒ <b>该信号只在主板成立</b>。</p>
"""


# --------------------------------------------------------------------------- §5/§6
SELF_TPL = """
<h2>§5 成本口径只能读成「区间的两端」<span class="tag">不要用费用下限重算看板</span></h2>
<table><thead><tr><th>口径</th><th>往返</th><th>含义</th></tr></thead><tbody>
<tr><td>生产 <code>COST_BUY/SELL = 0.00575</code></td><td><b>1.15%</b></td>
<td><b>保守假设</b>：含滑点 / 冲击 / 排队成本的粗估</td></tr>
<tr><td>引擎 <code>cost.mode=itemized</code></td><td><b>≈0.163 pp</b></td>
<td><b>法定费用下限</b>：佣金 0.03%（含最低 5 元）+ 仅卖出印花税 0.1% + 仅沪市过户费 0.001%
+ 流量费 0.1 元。<b>不含任何滑点 / 冲击 / 排队</b></td></tr>
</tbody></table>
<p class="note">差额 <b>≈0.99 pp</b> 是<b>滑点假设</b>的贡献，不是「多算了手续费」。
拿零滑点的费用下限去重算看板年化会把读数系统性抬高 —— <b>该建议已撤回</b>；
要动这块需要<b>实测滑点</b>（成交价 vs 到达价），而不是换费用公式。</p>

<h2>§6 本轮自纠清单 <span class="tag">全部留痕</span></h2>
<table><thead><tr><th>#</th><th>现象</th><th>根因</th><th>处置</th></tr></thead><tbody>
<tr><td>1</td><td>B 版（30% 止损）读数与 A 版<b>完全相同</b></td>
<td>引擎 <code>stop_pct</code> 是<b>显式参数</b>，写进 spec 不生效 ⇒ 静默退化</td><td>显式传参，B 版已分离</td></tr>
<tr><td>2</td><td>交易级均收益 <b>−101%</b></td>
<td>K 极大时仓位被摊薄到 nav/K，而「最低佣金 5 元」是<b>绝对额</b> ⇒ 纯算术假象</td>
<td>改为按 <b>20 万名义额</b>解析重算</td></tr>
<tr><td>3</td><td>往返费用算出 <b>32759 pp</b></td>
<td><code>cost_breakdown</code> 的 <code>total</code> 是<b>元</b>，却与 NAV 空间相除（尺度差 1e6）</td>
<td>单位对齐 + 加守卫（费用率不在 [0.05, 3.0] pp 直接 raise）</td></tr>
<tr><td>4</td><td>交易集合「共有 = 0」</td>
<td><b>移植 off-by-one</b>：自查挪一天 × 引擎再挪一天 ⇒ 引擎成交日晚 1 个交易日</td>
<td>同 bar 对齐 + 低价过滤改精确判 + 固化回归门（PASS）</td></tr>
<tr><td>5</td><td>对齐修好后交易级仍少 89 笔</td>
<td>我给的 <code>apply_top_n=True</code> + <code>top_n=5</code> 是<b>生产没有的横截面上限</b>；
89 笔中 <b>97.8%</b> 落在共振日，引擎每天恰好只取 5 笔</td>
<td>改 <code>apply_top_n=False</code>；<b>两处 build_spec 同改</b>（曾漏改一次）</td></tr>
<tr><td>6</td><td>分项成本被解读成「看板数字被压低」</td><td>把<b>零滑点费用下限</b>当成真实成本</td>
<td>撤回该建议，改为区间两端表述（§5）</td></tr>
<tr><td>7</td><td>早先版本称「本机未装 pyarrow ⇒ 原脚本跑不起来」</td>
<td>pyarrow 在 <code>D:\\Tools\\pylibs</code>，置于 <code>sys.path</code> 且<b>在 import pandas 之前</b>
即可读 cache</td><td>更正；四臂的 L1 / L2 本来就跑在 cache 上</td></tr>
</tbody></table>
"""

TAIL_TPL = """
<h2>§7 遗留（本轮明确不处理）</h2>
<ol>
<li><b>存活偏差</b>：data_full 已剔除退市股，本看板所有读数含存活偏差，需外部数据源量化（独立项）。</li>
<li><b>C50 提为主卖出</b>：读数支持（主板 6.55% vs 4.84%、回撤 −22.36% vs −28.40%），
按既定范围<b>本轮只给读数、不改看板主次</b>。</li>
<li><b>组合级槽位分配未与 v8 <code>build_nav</code> 逐位对齐</b>：本轮只证明<b>交易级集合</b>的保真度（§2）。</li>
<li><b>滑点实测</b>：§5 两端点之间的真实位置未测。</li>
</ol>

<h2>§8 口径与可复现</h2>
<table><tbody>
<tr><th>信号 / 入场</th><td><code>15 信号任一 ∧ RSI(14)[i-1] &lt; 35 ∧ 熊市[i] ⇒ i 日开盘买</code>
（regime 取<b>入场日</b>状态，不是 i−1 —— 生产脚本里 <code>cand</code> 与 <code>is_bear_arr</code> 本来就错位）</td></tr>
<tr><th>出场</th><td><code>RSI(14)[i-1] &gt; ob</code> ⇒ i 日开盘卖（A=55 / C=50）；B 版加 30% 绝对止损</td></tr>
<tr><th>低价过滤</th><td>入场价 <code>o×(1+买成本) ≥ 3 元</code>（本轮改为用<b>成交日 open 精确判</b>）</td></tr>
<tr><th>数据</th><td>L1 / L2 = <code>v8_factor_cache.pkl</code>（as_of 2026-09-23）；
L3 / L4 / 三成本档 / 分层 = <code>D:\\Documents\\Quant data\\data_full</code>（至 2026-09-30）</td></tr>
<tr><th>引擎字段语义</th><td><code>engine/portfolio.py:178-179</code> 的 <code>entry_date=h["t_entry"]</code> 是
<b>cal 下标，不是日期</b>；调用侧经 <code>dump_trades()</code> 转 ISO 日期落盘，原下标留在
<code>entry_idx</code> / <code>exit_idx</code></td></tr>
</tbody></table>

<h3>复现（全部脚本 + 退出码）</h3>
<pre>cd D:\\Documents\\Workbuddy\\股票基金\\quant-weight-system\\backtest\\_audit_clock_20261008

# 修正前基线（应 FAIL）—— 退出码 1
$env:SP_ALIGN='legacy'; python short_pool_four_arms_20261008.py
python audit_zero_overlap_20261008.py --suffix _LEGACYALIGN --out evidence_zero_overlap_prefix_20261008.json --label prefix_offbyone
Remove-Item Env:\\SP_ALIGN

# 修正后（应 PASS）
python short_pool_four_arms_20261008.py        # rc=0  约 37 min
python short_pool_auction_backtest_v16.py      # rc=0  约 7 min
python short_pool_layered_v16.py               # rc=0  约 9 min
python audit_zero_overlap_20261008.py          # rc=0  verdict=PASS
python build_dashboard_short_pool_v16.py       # 本页即由它生成</pre>
<p class="note">证据文件：<code>evidence_short_pool_four_arms.json</code> ·
<code>evidence_short_pool_v16.json</code> · <code>evidence_layered_v16.json</code> ·
<code>evidence_zero_overlap_20261008.json</code> · <code>evidence_zero_overlap_prefix_20261008.json</code> ·
<code>报告-短线池超卖伏击-引擎重跑-20261008.md</code></p>
"""

CSS = """
:root{--bg:#0f1115;--fg:#e6e8eb;--mut:#98a2b3;--line:#242a35;--ok:#3ddc97;--bad:#ff6b6b;
--hl:#1b2330;--acc:#7aa2f7}
*{box-sizing:border-box}
body{padding:28px 22px 80px;background:var(--bg);color:var(--fg);
font:14px/1.62 "Segoe UI",-apple-system,"Microsoft YaHei",sans-serif;max-width:1560px;margin:0 auto}
h1{font-size:25px;margin:0 0 6px}
h1 span{color:var(--acc)}
h2{font-size:18px;margin:34px 0 10px;padding-bottom:7px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px;color:var(--acc)}
.tag{font-size:11.5px;color:var(--mut);font-weight:400;margin-left:8px}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;margin:10px 0 16px;font-variant-numeric:tabular-nums}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{background:#161a22;color:var(--mut);font-weight:600;font-size:12.5px}
tbody tr:nth-child(even){background:#12151b}
tr.hl{background:var(--hl)}
.ok{color:var(--ok);font-weight:600}
.bad{color:var(--bad)}
.note{color:var(--mut);font-size:12.5px;margin:8px 0 18px}
.note b{color:var(--fg)}
code{background:#161a22;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12.5px}
pre{background:#12151b;border:1px solid var(--line);border-radius:6px;padding:13px;overflow:auto;
font-size:12.5px;color:#cdd6e4}
.card{display:inline-block;border:1px solid var(--line);border-radius:8px;padding:10px 14px;
margin:0 10px 10px 0;background:#12151b;vertical-align:top}
.card .ch{font-weight:700;color:var(--acc);margin-bottom:4px}
.card .cb{font-size:12.5px;color:var(--mut)}
ol,ul{margin:8px 0 16px 22px}
li{margin:5px 0}
"""

DOC_TPL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>短线池 · 超卖伏击 — 引擎重跑看板（修正版）</title><style>@@CSS@@</style></head><body>
<h1>短线池 · <span>超卖伏击</span> — 引擎重跑看板（修正版）</h1>
<div class="sub">生成：@@GEN@@ · 由 <code>build_dashboard_short_pool_v16.py</code> 从证据 JSON 生成
（数字不手填）<br>引擎：<code>fleur_absorb</code> ·
<code>engine/portfolio.py</code> + <code>engine/spec.py</code>（分项成本）</div>
@@BODY@@
</body></html>"""


def main():
    fa = load("evidence_short_pool_four_arms.json")
    v16 = load("evidence_short_pool_v16.json")
    lz = load("evidence_layered_v16.json")
    post = load("evidence_zero_overlap_20261008.json")
    pre = load("evidence_zero_overlap_prefix_20261008.json")
    body = (sec_gates(post, pre) + sec_four(fa) + sec_cost(v16) + sec_layered(lz)
            + SELF_TPL + TAIL_TPL)
    doc = (DOC_TPL.replace("@@CSS@@", CSS)
           .replace("@@GEN@@", time.strftime("%Y-%m-%d %H:%M"))
           .replace("@@BODY@@", body))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print("已写出 %s（%d 字节）" % (os.path.basename(OUT), len(doc.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
