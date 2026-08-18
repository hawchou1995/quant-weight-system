# -*- coding: utf-8 -*-
"""生成 Aroon 穷举分析 HTML 仪表盘"""
import json
from pathlib import Path
BASE = Path('.').resolve()
d = json.load(open(BASE / 'aroon_exhaust_results.json', encoding='utf-8'))
b = d['baseline']
oos = json.load(open(BASE / 'aroon_oos_top.json', encoding='utf-8'))

# 全样本候选（去重 label）
seen = {}
for r in d['results']:
    if r.get('aroon_th') is None:
        continue
    lbl = r['label']
    if lbl in seen:
        continue
    seen[lbl] = r
cands = sorted(seen.values(), key=lambda r: -r['total_return_pct'])


def rel(r):
    return (r['total_return_pct'] - b['total_return_pct'],
            r['max_drawdown_pct'] - b['max_drawdown_pct'],
            r['sharpe'] - b['sharpe'])


cells = {(r['aroon_th'], r['mom_th']): r for r in cands}
moms_r = sorted({r['mom_th'] for r in cands if r.get('fac', 0.6) == 0.6})

rows_html = ''
for r in cands[:15]:
    rr, rd, rs = rel(r)
    flag = '✅' if (rr > 0 and rd >= 0 and rs > 0) else '·'
    rows_html += (f"<tr><td>{r['label']}</td><td class='pos'>{r['total_return_pct']:+.1f}%</td>"
                  f"<td class='sub'>(Δ{rr:+.1f})</td><td>{r['max_drawdown_pct']:+.2f}%</td>"
                  f"<td>{r['sharpe']:.3f}</td><td>{rs:+.3f}</td>"
                  f"<td>{r['win_rate_pct']:.1f}%</td><td>{r['total_trades']}</td><td>{flag}</td></tr>")

oos_segs = ['2016-2019', '2020-2021', '2022-2026']


def oos_rows():
    out = ''
    for lbl in ['baseline', 'A75_M80', 'A80_M80', 'A80_M85', 'A85_M85']:
        if lbl not in oos:
            continue
        cells_s = ''
        for seg in oos_segs:
            s = oos[lbl][seg]
            cells_s += (f"<td>{s['ret']:+.1f}%<br><span class='sub'>{s['dd']:+.2f}% / 夏普{s['sh']:.2f}</span></td>")
        out += f"<tr><td>{lbl}</td>{cells_s}</tr>"
    out += '</table><table class="tbl"><thead><tr><th>Δ vs 基线 →</th>' + \
           ''.join(f"<th>{s}</th>" for s in oos_segs) + "<th>稳健判定</th></tr></thead>"
    for lbl in ['A75_M80', 'A80_M80', 'A80_M85', 'A85_M85']:
        if lbl not in oos:
            continue
        cells_s = ''
        good = 0
        for seg in oos_segs:
            dret = oos[lbl][seg]['ret'] - oos['baseline'][seg]['ret']
            dsh = oos[lbl][seg]['sh'] - oos['baseline'][seg]['sh']
            cls = 'pos' if dret > 0 else 'neg'
            cells_s += f"<td class='{cls}'>{dret:+.1f}% / 夏普{dsh:+.2f}</td>"
            if dret > 0 and dsh > 0:
                good += 1
        cells_s += f"<td>{good}/3 段收益+夏普双升</td>"
        out += f"<tr><td>{lbl}</td>{cells_s}</tr>"
    return out


hm_rows = ''
for a in sorted({r['aroon_th'] for r in cands if r.get('fac', 0.6) == 0.6}):
    tds = ''
    for m in moms_r:
        r = cells.get((a, m))
        if r is None:
            tds += '<td class="hm-cell na">—</td>'
            continue
        rr = r['total_return_pct'] - b['total_return_pct']
        if rr >= 400:
            bg, c = '#1a7f37', '#fff'
        elif rr >= 200:
            bg, c = '#2da44e', '#fff'
        elif rr >= 0:
            bg, c = '#4ac26b', '#fff'
        else:
            bg, c = '#d1242f', '#fff'
        tds += f"<td class='hm-cell' style='background:{bg};color:{c}'>{r['total_return_pct']:+.0f}</td>"
    hm_rows += f"<tr><td class='hm-hd'>{a}</td>{tds}</tr>"

C = """
:root{--bg:#f6f8fa;--card:#fff;--border:#d0d7de;--text:#1f2328;--faint:#656d76;--accent:#0969da}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);padding:24px;max-width:1180px;margin:0 auto}
h1{font-size:24px;margin-bottom:4px} h2{font-size:18px;margin:24px 0 10px} .sub{color:var(--faint);font-size:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:16px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
.kpi .v{font-size:22px;font-weight:700} .kpi .l{color:var(--faint);font-size:12px;margin-top:2px}
.tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
.tbl th,.tbl td{border:1px solid var(--border);padding:7px 10px;text-align:right}
.tbl th{background:#f6f8fa;font-weight:600} .tbl td:first-child{text-align:left;font-weight:600}
.pos{color:#1a7f37;font-weight:600} .neg{color:#d1242f;font-weight:600}
.hm-cell{text-align:center;min-width:58px;padding:6px;font-weight:600;font-size:12px}
.hm-cell.na{background:#eaeef2;color:#999}
.hm-hd{background:#f6f8fa;font-weight:700;text-align:center}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;background:#ddf4ff;color:#0969da;font-size:12px;margin-left:8px}
.warn{background:#fff8c5;border:1px solid #d4a72c;color:#7d4e00;border-radius:10px;padding:12px 14px;margin-top:12px;font-size:13px}
"""

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>Aroon 中长线参数穷举 · 全量池 2016-2026</title>
<style>{C}</style></head><body>
<h1>Aroon 中长线系统参数穷举 <span class="badge">全量池 · 2016-01-04 → 2026-08-17</span></h1>
<div class="sub">基线 = run_auto() 无抑制 · 两阶段穷举 + 收敛性补测，共 <b>{len(cands)}+ 有效参数组</b></div>

<div class="kpis">
<div class="kpi"><div class="v">+191.9%</div><div class="l">基线收益（无抑制）</div></div>
<div class="kpi"><div class="v" style="color:#1a7f37">+1193.2%</div><div class="l">最优 A85_M85</div></div>
<div class="kpi"><div class="v">0.669 → 1.369</div><div class="l">夏普翻倍</div></div>
<div class="kpi"><div class="v" style="color:#1a7f37">-22.3% → -15.6%</div><div class="l">最大回撤改善 6.7pct</div></div>
</div>

<div class="card">
<h2>全样本收益 Top 15</h2>
<table class="tbl"><thead><tr><th>参数</th><th>总收益</th><th>Δ收益</th><th>最大回撤</th><th>夏普</th><th>Δ夏普</th><th>胜率</th><th>交易</th><th>有效</th></tr></thead>
<tbody>{rows_html}</tbody></table>
</div>

<div class="card">
<h2>热力图：总收益 %（aroon_th 行 × mom_th 列，fac=0.6）</h2>
<div class="sub" style="margin-bottom:8px">颜色 = 收益（绿深=越优）；列 = {', '.join('M%d' % int(m*100) for m in moms_r)}</div>
<div style="overflow-x:auto"><table class="tbl">
<thead><tr><th>aroon↓\\mom→</th>{''.join(f'<th>M{int(m*100)}</th>' for m in moms_r)}</tr></thead>
<tbody>{hm_rows}</tbody></table></div>
</div>

<div class="card">
<h2>样本外稳健性（2016-2019 / 2020-2021 / 2022-2026 三折）</h2>
<table class="tbl"><thead><tr><th>参数</th><th>2016-2019</th><th>2020-2021</th><th>2022-2026</th></tr></thead><tbody>{oos_rows()}</tbody></table>
<div class="warn">⚠ <b>关键发现：制度依赖</b>——4 个最强候选全部呈现「2/3 段收益+夏普双升、1 段拖累」，拖累段无一例外是 <b>2020-2021 疯牛段</b>（低 Aroon 但趋势延续的票被抑制 = 错过疯牛加速）。全样本最优主要由 2016-2019 与 2022-2026 两大段贡献。</div>
</div>

<div class="card">
<h2>结论与建议</h2>
<ol style="line-height:1.9;font-size:14px;padding-left:22px">
<li><b>全样本确实存在大幅优化空间</b>：高 Aroon 阈值(≥75)+高动量(≥0.8)把「表面动量」收紧为「强趋势确认动量」，10.6 年收益 +192%→最高 +1193%，回撤与夏普双改善——<b>收益随阈值单调上升</b>（A70→A90 递增），说明这是系统性的强趋势过滤价值，非单点过拟合。</li>
<li><b>但不能无条件投产</b>：OOS 三年段一致显示疯牛段（2020-2021）被抑制拖累（Δ-67~-94pct）。原意「顶部规避」在高阈值下实际是「只买最强趋势」，代价是牛市主升中段错过。</li>
<li><b>平衡推荐 A80_M80</b>（+1125%/回撤-15.6%/夏普1.368，胜率49.8%）：收益接近最优、OOS 拖累段相对温和，交易数不变(259)、样本 10.6 年充分。</li>
<li><b>进阶：市场状态自适应</b>——Aroon 阈值做成状态条件（牛热放松 A60-M70 / 震荡弱势收紧 A80-M80），可留到下一轮用 idx_vol/热度做条件回测验证。</li>
<li>原缺陷案例（海川智能 Aroon=24 追高）已被更广义的「动量+趋势确认」机制覆盖，是通用防追高。</li>
</ol>
</div>
<div class="sub" style="text-align:center;margin:18px 0">数据源：v9 全量池因子缓存 · 引擎 v9_auto.run_auto · 仅供个人研究参考，不构成投资建议</div>
</body></html>"""

(BASE / 'aroon_exhaust_dashboard.html').write_text(html, encoding='utf-8')
print('已生成 aroon_exhaust_dashboard.html', len(html), 'bytes')
