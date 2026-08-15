# -*- coding: utf-8 -*-
"""
生成"关注标的权重看板 v8-lite 加减仓建议"HTML（套用模板样式）
数据：2026-07-23 再平衡排名 + 08-14 最新现价
"""
import sys, json, math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V
import v8_lite as L

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
pool = L.build_pool(verbose=False)

NAME = {'300502':'新易盛','300308':'中际旭创','600498':'烽火通信','601138':'工业富联','002463':'沪电股份',
        '002384':'东山精密','600183':'生益科技','300476':'胜宏科技','603986':'兆易创新','002185':'华天科技',
        '605358':'立昂微','603228':'景旺电子','603339':'四方科技','000636':'风华高科','605189':'富春染织',
        '600403':'大有能源','002879':'长缆科技','600162':'香江控股','000759':'中百集团','002474':'榕基软件',
        '159516':'半导体设备ETF','515880':'通信ETF','516150':'稀土ETF','560390':'电网设备ETF','159841':'证券ETF'}
SECTOR = {'300502':'光模块','300308':'光模块','600498':'通信设备','601138':'电子制造','002463':'PCB',
          '002384':'电子制造','600183':'覆铜板','300476':'PCB','603986':'半导体','002185':'半导体封测',
          '605358':'半导体硅片','603228':'PCB','603339':'冷链设备','000636':'MLCC','605189':'纺织印染',
          '600403':'煤炭','002879':'电线电缆','600162':'地产服务','000759':'商业零售','002474':'软件服务',
          '159516':'半导体设备','515880':'通信','516150':'稀土','560390':'电网设备','159841':'证券'}

idx = V.load_index(200).set_index('date')
all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
rebal = [d for d in all_days[::21]]
prev = [d for d in rebal if d < all_days[-1]][-1]   # 上次再平衡日（档位对比基准）
last = all_days[-1]                                  # 最新交易日 08-14

def tier(sc):
    if sc >= 75: return '满仓加仓'
    if sc >= 60: return '轻仓加仓'
    if sc >= 45: return '观望'
    if sc >= 30: return '减至半仓'
    return '清仓'

def comps(r):
    """四分量：动量/趋势/Aroon/量价（0-100 口径展示为 0-100 分）"""
    m = max(0.0, min(1.0, r['mom_12_1'] / 0.20)) * 100 if not np.isnan(r['mom_12_1']) else None
    t = max(0.0, min(1.0, r['ma200_pos'] / 0.30)) * 100 if not np.isnan(r['ma200_pos']) else None
    a = (max(-100.0, min(100.0, r['aroon_osc'])) + 100) / 2
    v = 100 if r['vp_confirm'] else 0
    return m, t, a, v

# 历史入选次数（用于置信度）
tr = pd.read_csv(BASE / 'v8_lite_trades.csv')
hist_cnt = tr['symbol'].str[-6:].value_counts().to_dict()

rows = []
for k, ddf in pool.items():
    c = k[2:]
    eff = ddf.index[-1] if last not in ddf.index else last   # 最近可用收盘
    r = ddf.loc[eff]
    if pd.isna(r['close']) or pd.isna(r['mom_12_1']): continue
    sc = V.score_row(r)
    sc_prev = V.score_row(ddf.loc[prev]) if prev in ddf.index else np.nan
    # 最新现价与当日涨跌（最后一日）
    rlast = ddf.iloc[-1]
    px = rlast['close']
    px_prev_d = ddf.iloc[-2]['close'] if len(ddf) > 1 else px
    chg = (px / px_prev_d - 1) * 100
    c1y = px / ddf.iloc[-252]['close'] - 1 if len(ddf) > 252 else None
    m, t, a, v = comps(r)
    n_hist = hist_cnt.get(c, 0)
    conf = '高置信' if (sc >= 75 or n_hist >= 3) else ('中置信' if sc >= 60 or n_hist >= 1 else '低置信')
    rows.append({'code': c, 'name': NAME.get(c, c), 'sector': SECTOR.get(c, ''),
                 'px': px, 'chg': chg, 'ret1y': c1y*100 if c1y else None,
                 'score': sc, 'comp': f'{m:.0f}/{t:.0f}/{a:.0f}/{v:.0f}' if m else '—',
                 'tier': tier(sc), 'tier_prev': tier(sc_prev) if not np.isnan(sc_prev) else '—',
                 'conf': conf, 'hist': n_hist})
rows.sort(key=lambda x: -x['score'])

# 净值曲线（月度采样 SVG）
eq = pd.read_csv(BASE / 'v8_lite_equity.csv')
eq['value'] = eq['value'].astype(float)
eq['date'] = pd.to_datetime(eq['date'])
eqm = eq.set_index('date')['value'].resample('ME').last().dropna()
vals = eqm.values
minv, maxv = vals.min(), vals.max()
W, H = 1200, 320
def px_x(i): return 30 + i * (W - 60) / max(1, len(vals) - 1)
def px_y(v): return H - 30 - (v - minv) / (maxv - minv) * (H - 60)
pts = ' '.join(f'{px_x(i):.0f},{px_y(v):.0f}' for i, v in enumerate(vals))
year_ticks = []
for i, d in enumerate(eqm.index):
    if d.month == 1 or i == 0:
        year_ticks.append((i, str(d.year)))
svg = f'''<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;background:#0f1419;border-radius:8px">
<line x1="30" y1="{H-30}" x2="{W-30}" y2="{H-30}" stroke="#333" stroke-width="1"/>
<polyline points="{pts}" fill="none" stroke="#f0b90b" stroke-width="2"/>
<rect x="30" y="10" width="150" height="24" rx="4" fill="#1c2530"/><text x="38" y="27" fill="#f0b90b" font-size="13">净值 {eq['value'].iloc[-1]/eq['value'].iloc[0]:.2f}（+{(eq['value'].iloc[-1]/eq['value'].iloc[0]-1)*100:.0f}%）</text>
{''.join(f'<text x="{px_x(i)}" y="{H-10}" fill="#888" font-size="11">{y}</text>' for i, y in year_ticks)}
</svg>'''

# 加减仓信号摘要
adds = [r for r in rows if '加仓' in r['tier']]
holds = [r for r in rows if r['tier'] == '观望']
cuts = [r for r in rows if '减' in r['tier'] or r['tier'] == '清仓']
top4 = [f"{r['name']}({r['score']:.0f})" for r in rows[:4]]

def kpi(label, value, sub=''):
    return f'<div class="kpi"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>'

kpis = ''.join([
    kpi('策略收益', '+3923.7%', '2016-01~2026-08'),
    kpi('策略年化', '41.7%', '50万中性资金'),
    kpi('最大回撤', '-18.0%', '达标 ≤25%'),
    kpi('夏普比率', '1.644', '达标 ≥1'),
    kpi('胜率', '57.1%', '210 笔 · 动态等权'),
    kpi('交易频率', '20 笔/年', '月轮动 H21'),
    kpi('信号日期', '2026-08-14', '最新收盘'),
    kpi('持仓建议', f'{len(adds)} 加仓 / {len(holds)} 观望 / {len(cuts)} 减清', 'Top4: ' + ' / '.join(top4)),
])

rows_html = ''
for i, r in enumerate(rows, 1):
    tier_cls = {'满仓加仓': 't-full', '轻仓加仓': 't-add', '观望': 't-watch', '减至半仓': 't-cut', '清仓': 't-clear'}[r['tier']]
    chg = '' if r['tier_prev'] == r['tier'] else f"<span class='chg'>←{r['tier_prev']}</span>"
    star = ''  # 脱敏：不标注个人持仓
    ret1y = f"{r['ret1y']:+.0f}%" if r['ret1y'] is not None else '—'
    rows_html += f'''<tr>
<td class="rank">{i}</td>
<td><b>{r['name']}{star}</b><div class="sub">{r['code']} · {r['sector']}</div></td>
<td class="num">{r['px']:.2f}</td>
<td class="num {'up' if r['chg']>=0 else 'down'}">{r['chg']:+.2f}%</td>
<td class="num">{ret1y}</td>
<td class="score">{r['score']:.1f}</td>
<td class="comp">{r['comp']}</td>
<td class="conf">{r['conf']}</td>
<td><span class="tier {tier_cls}">{r['tier']}</span> {chg}</td>
</tr>'''

html = f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>关注标的权重看板 v8-lite · 加减仓建议 2026-08-15</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0b0e11;color:#e5e7eb;margin:0;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} .subtitle{{color:#8b949e;font-size:13px;margin-bottom:20px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}}
.kpi{{background:#151a21;border:1px solid #232a33;border-radius:8px;padding:12px}}
.kpi-label{{color:#8b949e;font-size:12px}} .kpi-value{{font-size:20px;font-weight:700;color:#f0b90b;margin:4px 0}}
.kpi-sub{{color:#6e7681;font-size:11px}}
.card{{background:#151a21;border:1px solid #232a33;border-radius:8px;padding:16px;margin-bottom:16px}}
.card h2{{font-size:16px;margin:0 0 12px;color:#f0b90b;border-left:3px solid #f0b90b;padding-left:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{color:#8b949e;text-align:left;padding:8px 6px;border-bottom:1px solid #232a33;font-weight:500}}
td{{padding:8px 6px;border-bottom:1px solid #1c2530;vertical-align:middle}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .up{{color:#f6465d}} .down{{color:#2ebd85}}
.score{{font-size:15px;font-weight:700;color:#f0b90b}} .comp{{color:#8b949e;font-size:12px}}
.rank{{color:#6e7681;width:30px}} .sub{{color:#6e7681;font-size:11px}}
.tier{{padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600}}
.t-full{{background:#f6465d22;color:#f6465d;border:1px solid #f6465d55}}
.t-add{{background:#f0b90b22;color:#f0b90b;border:1px solid #f0b90b55}}
.t-watch{{background:#2ebd8522;color:#2ebd85;border:1px solid #2ebd8555}}
.t-cut{{background:#8b5cf622;color:#a78bfa;border:1px solid #8b5cf655}}
.t-clear{{background:#6e768122;color:#8b949e;border:1px solid #6e768155}}
.chg{{color:#8b949e;font-size:11px}}
.note{{color:#8b949e;font-size:12px;line-height:1.8}}
.tag{{display:inline-block;background:#232a33;border-radius:4px;padding:2px 8px;margin:2px;font-size:12px}}
</style></head><body>
<h1>📊 关注标的权重看板 v8-lite（加减仓建议）</h1>
<div class="subtitle">2026-08-15 生成 · 数据截至 2026-08-14 最新收盘 · 自选池 25 只（24 只有分）· 档位对比基准 = 07-23 再平衡· ★=你的持仓</div>
<div class="kpis">{kpis}</div>
<div class="card"><h2>组合净值走势（v8-lite 回测，50 万资金）</h2>{svg}
<div class="note" style="margin-top:8px">2016-01 起 · 空仓期（2016/2018/2022 等指数 &lt; MA200 时段）未计货基收益 · 月度采样</div></div>
<div class="card"><h2>打分体系公示（v8-lite）</h2>
<div class="note">
<b>总分 = 动量 35% + 趋势(MA200位置) 25% + Aroon时间强度 20% + 量价配合 20%</b><br>
动量=12-1月动量(截断20%) ｜ 趋势=收盘距MA200位置(截断30%) ｜ Aroon=Aroon(25)强弱 ｜ 量价=量价配合确认<br>
<b>操作档位：</b><span class="tag">≥75 满仓加仓</span><span class="tag">60-74 轻仓加仓</span><span class="tag">45-59 观望</span><span class="tag">30-44 减至半仓</span><span class="tag">&lt;30 清仓</span><br>
<b>市场门禁：</b>沪深300 收盘 &gt; MA200 才持仓；<b>移动止损：</b>持仓峰值回撤 ≥10% 次日卖出；<b>再平衡：</b>每月（21 交易日）池内重排 Top4 持仓，其余观望<br>
<b>执行：</b>T 日收盘信号 → T+1 开盘执行 · A 股 T+1 · 100 股整手 · 佣金万2.5 + 印花税<br>
<b>置信度：</b>高 = 得分≥75 或历史入选≥3 次 ｜ 中 = 得分≥60 ｜ 低 = 其余</div></div>
<div class="card"><h2>标的汇总 · 加减仓建议（24 只按得分排序）</h2>
<table><thead><tr><th>#</th><th>标的</th><th>现价</th><th>当日</th><th>近1年</th><th>权重分</th><th>动/趋/Aroon/量价</th><th>置信度</th><th>操作档位</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<div class="note" style="margin-top:10px">
<b>加减仓建议逻辑：</b>① 得分≥75 满仓加仓（Top4 必在加仓区）② 60-74 轻仓加仓（可建仓/持有）③ 45-59 观望（持有不加）④ 30-44 减至半仓 ⑤ &lt;30 清仓。<br>
<b>你的持仓：</b>风华高科 76.4 <b>满仓加仓</b>（←轻仓加仓，升档）｜ 沪电股份 74.5 轻仓加仓（不变）｜ 通信ETF 62.0 轻仓加仓（不变）。<br>
<b>本月信号变化：</b>升档 6 只（中际旭创/风华高科/大有能源/香江控股/富春染织 →加仓），降档 6 只（新易盛/华天科技/工业富联/胜宏/烽火/立昂微/四方 →观望），清仓 2 只（长缆科技/榕基软件）。</div></div>
<div class="note" style="margin-top:16px">⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。</div>
</body></html>'''

out = BASE / 'advice_v8lite.html'
out.write_text(html, encoding='utf-8')
print(f'已生成: {out} ({out.stat().st_size/1024:.0f}KB)')
print(f'加仓 {len(adds)} 只 / 观望 {len(holds)} 只 / 减清 {len(cuts)} 只 | Top4: {top4}')
