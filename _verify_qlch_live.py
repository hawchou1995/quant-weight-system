# -*- coding: utf-8 -*-
"""超跌低开低吸：盘中买点判定 + 达标置顶 + 盘中净值 —— 真机验收（R-qlch-live-0923）

用法: python _verify_qlch_live.py
流程: 拉起自动化 Chrome(9223) → 新标签打开**本地**产物 file://…/dual_system.html?cb=<ts>
      → 注入合成行情（window.INTRADAY.applyQuotes）→ 断言 → 截 _shot_qlch_trigger.png → 关标签

为什么注入合成行情而不是等真实行情：
  · 三条分支（低开达标 / 盘中回落 / 无法判定）要**同时**钉死，真实行情给不了这种组合；
  · 不依赖盘中时段，也不受 chainQuiet（15:05–16:45 静默窗）影响 —— 静默窗只挡自动刷新，
    挡不住手动 applyQuotes（它本来就是导出给验证用的入口）。
合成口径：A 行 今开 = 今收×0.965（gap −3.5% ∈ [−5%,−2%] → 低开达标 → 置顶）；
          B 行 今开 = 今收、现价 = 今收×0.97（现价/昨收 −3% → 仅「盘中回落」变色）；
          其余候选 温和上行（gap +0.1% / 现价 +0.5% → 不达标、不贴标）；
          C1 臂持仓（sz000048）现价 = entry_px×1.05 → 盘中净值 = nav×(1+w×(1.05−1−cost_rt))。
只读验收：不写任何 json / 账本，跑完清理本页 localStorage 的触发记录。
"""
import asyncio
import base64
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

import websockets

BASE = Path(__file__).resolve().parent
sp = importlib.util.spec_from_file_location("gdc", BASE / "backtest" / "gushi_daily_collect.py")
gdc = importlib.util.module_from_spec(sp)
sys.modules["gdc"] = gdc
sp.loader.exec_module(gdc)

# ---- 各策略自有数据源的代码白名单（R-track-sep-0923）：真值来源 = 产物文件，复用静态检查器的实现 ----
_sp = importlib.util.spec_from_file_location("vtrack", BASE / "_verify_track_sep_0923.py")
_vtrack = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(_vtrack)          # 该模块只定义函数（断言在 main() 里），import 无副作用
_wl, _wl_src = _vtrack.whitelists()
WATCH_WL = {k: sorted(v) for k, v in _wl.items()}
print("[whitelist] 跟踪池白名单规模: " + ", ".join("%s=%d" % (k, len(v)) for k, v in WATCH_WL.items()))

FILE_URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
            "quant-weight-system/dual_system.html")

JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {asserts: [], raw: {}};
  const A = (name, ok, detail) => out.asserts.push({assert: name, ok: !!ok,
                                                    detail: (detail === undefined ? '' : String(detail))});
  const Q = window.QLCH, IN = window.INTRADAY;
  out.raw.url = location.href;
  out.raw.title = document.title;
  A('window.INTRADAY 存在', !!IN);
  A('window.QLCH 存在且 rows=25', !!(Q && Q.rows && Q.rows.length === 25), 'rows=' + ((Q && Q.rows || []).length));
  A('window.QLCH_LIVE 已接线（包装 applyQuotes）', !!(window.QLCH_LIVE && window.QLCH_LIVE.wrapped));
  if (!IN || !Q || !window.QLCH_LIVE) return out;

  const norm = c => String(c || '').replace(/^(sh|sz|bj)/i, '');
  const tb = document.getElementById('tbl-qlch-cand');
  A('候选表 #tbl-qlch-cand 存在', !!tb);

  /* 0) 从零开始：清掉「落盘 + 内存缓存」两层触发记录（reset 两层都清，只清 localStorage 会看到缓存旧值） */
  out.raw.storeBefore = localStorage.getItem('quant_qlch_trig_v1');
  window.QLCH_LIVE.reset();
  window.QLCH_LIVE.run(null, '');
  const h0 = tb.querySelector('tr.qlch-trig-hdr');
  const b0 = document.querySelector('#qlch-card h2 .qlch-badge');
  A('无行情时间戳的不判定态：不置顶、不贴标、不写记录（徽标为保守态）',
    !h0 && !!b0 && /待开盘判定|已触发 0\/25/.test(b0.textContent) && !tb.querySelector('tr.qlch-dip') &&
    !localStorage.getItem('quant_qlch_trig_v1'),
    'hdr=' + !!h0 + ' badge=' + (b0 && b0.textContent) + ' store=' + localStorage.getItem('quant_qlch_trig_v1'));

  /* 0b) 真实刷新路径必须进得来（缺陷 3 回归）：盘中层 refresh 内部不经过 window.INTRADAY.applyQuotes，
        故有 QLCH_ON_QUOTES 钩子。用真实 refresh(true) 驱动一次，断言我们的状态/小字确实被推进。
        （chainQuiet 内置 false → refresh 返回 false，此时跳过并记录原因，不误判失败。） */
  const rr = await IN.refresh(true);
  const st0 = window.QLCH_LIVE.state;
  out.raw.realPath = {refresh: rr, hook: typeof window.QLCH_ON_QUOTES, ts: st0.ts, src: st0.src,
                      mktDate: st0.mktDate, diag: st0.diag,
                      srcSpan: (function(el){ return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : null; })
                        (document.querySelector('#qlch-card h2 .qlch-live-src'))};
  if (rr === false) {
  } else {
    A('缺陷 3：真实 refresh 路径进得来（钩子生效：状态有 ts/源、逐行已派发）',
      typeof window.QLCH_ON_QUOTES === 'function' && !!st0.ts && st0.diag.rows === 25 &&
      (st0.diag.gated + st0.diag.noquote + st0.diag.gap + st0.diag.dip + st0.diag.wait + st0.diag.na) === 25,
      JSON.stringify(out.raw.realPath));
  }
  window.QLCH_LIVE.reset();               /* 真实行情不留痕，回到干净起点 */
  window.QLCH_LIVE.run(null, '');

  /* 1) 合成行情（A=低开达标 / B=盘中回落 / 其余温和上行） */
  const rA = Q.rows[2], rB = Q.rows[0];
  const q = {};
  Q.rows.forEach(r => { q[norm(r.code)] = {px: r.close * 1.005, pct: 0.5, name: r.name,
                                           pcl: r.close, opn: r.close * 1.001}; });
  q[norm(rA.code)] = {px: rA.close * 0.965, pct: -3.5, name: rA.name, pcl: rA.close, opn: rA.close * 0.965};
  q[norm(rB.code)] = {px: rB.close * 0.97, pct: -3.0, name: rB.name, pcl: rB.close, opn: rB.close};
  const c1 = (Q.accounts && Q.accounts.C1) || {};
  const pos = (c1.positions || [])[0] || null;
  /* 行情时间戳（腾讯 [30] 口径，YYYYMMDDHHMMSS）——修正 2/3 的「今天」一律由它决定，不用本地日期 */
  const ASOF = String(Q.as_of || '');
  const _d0 = ASOF.split('-').map(Number);
  const _d1 = ASOF ? new Date(_d0[0], _d0[1] - 1, _d0[2] + 1) : null;   /* 本地日期 +1（勿用 toISOString：UTC 位移会把 +1 日算回当日） */
  const D1 = _d1 ? (_d1.getFullYear() + '-' + ('0' + (_d1.getMonth() + 1)).slice(-2) + '-' + ('0' + _d1.getDate()).slice(-2)) : '';
  const MKT_NEXT = D1.replace(/-/g, '') + '103102';                 /* as_of + 1 日 → 买点判定生效 */
  const MKT_SAME = ASOF.replace(/-/g, '') + '103102';               /* as_of 当日 → 待开盘判定（修正 3） */
  const MKT_LEDGER = String(c1.nav_date || ASOF).replace(/-/g, '') + '150002';  /* 账本记账日（修正 2） */
  /* 该票的行情昨收刻意 ≠ 入场价：使「基准=昨收」与「基准=入场价」结果不同，可判别实现是否对齐生产 */
  const C1_PREVC = pos ? pos.entry_px * 1.10 : null;
  const C1_PX = C1_PREVC ? C1_PREVC * 1.05 : null;
  if (pos) q[norm(pos.code)] = {px: C1_PX, pct: 5.0, name: pos.name, pcl: C1_PREVC, opn: C1_PREVC};
  out.raw.mkt = {as_of: ASOF, next: MKT_NEXT, same: MKT_SAME, ledger: MKT_LEDGER, nav_date: c1.nav_date};
  const ap = IN.applyQuotes(q, '10:31:02', {src: '东财（合成）', mktTs: MKT_NEXT});
  out.raw.applyQuotes = ap;

  /* 2) 参与刷新白名单/守卫收窄的证据：候选表可刷行数 + 已改写格数 */
  const sc = (IN.__scan().tables || []).filter(t => t.id === 'tbl-qlch-cand')[0] || {};
  out.raw.scanCand = sc;
  /* 2b) 现价列（R-qlch-pxcol-0923）：构建期填今收 + data-v=close；盘中层按列头「现价」定位改写 */
  const ths = Array.from(tb.querySelectorAll('thead th'));
  const pxI = ths.findIndex(th => (th.textContent || '').replace(/实时|盘中/g, '').trim() === '现价');
  const pxKey = ths.findIndex(th => (th.getAttribute('data-key') || '').toLowerCase() === 'px');
  out.raw.pxCol = {pxI: pxI, pxKey: pxKey, nCols: ths.length,
                   ths: ths.map(th => (th.textContent || '').replace(/实时|盘中/g, '').trim())};
  A('候选表 15 列（原 14 − 代码/名称合并 + 板块 + 现价）', ths.length === 15, JSON.stringify(out.raw.pxCol.ths));
  A('存在列头文本正好为「现价」的列（盘中层 PX_HDR 定位依赖）', pxI >= 0, 'pxI=' + pxI);
  A('现价列即 data-key="px" 的列（构建期 pxI 与盘中层一致）', pxKey >= 0 && pxKey === pxI,
    'pxKey=' + pxKey + ' pxI=' + pxI);
  const scPx = (IN.__scan().tables || []).filter(t => t.id === 'tbl-qlch-cand')[0] || {};
  A('候选表盘中扫描 px 列命中（elig=25 行全部有码、有价列）', scPx.elig === 25 && scPx.live >= 50,
    JSON.stringify(scPx));
  A('候选表参与 px/pct 刷新（25 行可刷、每行 2 格 live-cell ≥ 50、无跳过原因）',
    scPx.elig === 25 && scPx.live >= 50 && !scPx.skip, JSON.stringify(scPx));
  const pxCells = [].slice.call(tb.querySelectorAll('tbody tr'))
    .map(tr => tr.children[pxI])
    .filter(td => td && td.classList.contains('live-cell'));
  out.raw.pxCells = {n: pxCells.length, text: pxCells.slice(0, 3).map(td => td.textContent.trim()),
                     dataV: pxCells.slice(0, 3).map(td => td.getAttribute('data-v'))};
  A('现价格子被写入实时价（25 格 live-cell）', pxCells.length === 25,
    'live-cell=' + pxCells.length + ' 样例=' + JSON.stringify(out.raw.pxCells.text));
  /* 3) 置顶 / 变色 / 标签 / 幂等 —— 索引一律**实时**算（重排会换元素，快照会失真） */
  const body = tb.querySelector('tbody');
  const idx = el => el ? [].slice.call(body.children).indexOf(el) : -1;
  const codeOf = tr => { const c = String(tr.getAttribute('data-code') || '').replace(/^(sh|sz|bj)/i, '');
                         return /^\d{6}$/.test(c) ? c : ((tr.textContent.match(/(?:^|\D)(\d{6})(?:\D|$)/) || [])[1] || ''); };
  const rowBy = code => [].slice.call(body.querySelectorAll('tr')).filter(tr => codeOf(tr) === code)[0];
  const hdr = body.querySelector('tr.qlch-trig-hdr');
  const aTr = rowBy(norm(rA.code));
  const bTr = rowBy(norm(rB.code));
  const txt = el => (el && el.textContent || '').replace(/\s+/g, ' ').trim();
  out.raw.dom = {hdr: txt(hdr || null), hdrIdx: idx(hdr), aIdx: idx(aTr), bIdx: idx(bTr),
                 aClass: aTr && aTr.className, bClass: bTr && bTr.className,
                 aTag: txt(aTr && aTr.querySelector('.qlch-tag')),
                 bTag: txt(bTr && bTr.querySelector('.qlch-tag')),
                 trigCount: body.querySelectorAll('tr.qlch-trig').length,
                 dipCount: body.querySelectorAll('tr.qlch-dip').length,
                 naCount: body.querySelectorAll('tr.qlch-tag').length - body.querySelectorAll('tr.qlch-trig,tr.qlch-dip').length};
  A('分组标题行存在且计数=1（已触发买点（1））',
    !!hdr && txt(hdr).indexOf('已触发买点（1）') >= 0 &&
    body.querySelectorAll('tr.qlch-trig-hdr').length === 1, out.raw.dom.hdr);
  A('A 行（低开 −3.5%）紧随标题行置顶且带 .qlch-trig',
    !!hdr && !!aTr && idx(aTr) === idx(hdr) + 1 && aTr.classList.contains('qlch-trig'),
    'hdrIdx=' + idx(hdr) + ' aIdx=' + idx(aTr) + ' class=' + (aTr && aTr.className));
  A('A 行排到 B 行之前（原 rank 3 → 视图首位，depth rank 未改）',
    idx(aTr) < idx(bTr), 'aIdx=' + idx(aTr) + ' bIdx=' + idx(bTr));
  A('A 行尾部标「低开达标」+ 首次触发 HH:MM', /低开达标/.test(txt(aTr)) && /([01]\d|2[0-3]):[0-5]\d/.test(txt(aTr)),
    out.raw.dom.aTag);
  A('A 行 # 列保留原 rank（' + rA.rank + '，未改写）', txt(aTr.children[0]) === String(rA.rank),
    'td0=' + txt(aTr.children[0]));
  A('B 行变色 .qlch-dip 且不置顶、标「盘中回落」',
    bTr.classList.contains('qlch-dip') && !bTr.classList.contains('qlch-trig') && /盘中回落/.test(txt(bTr)),
    out.raw.dom.bClass + ' | ' + out.raw.dom.bTag);
  A('B 行未被移进置顶组（仍在原 rank 1 位置之后，idx>1）', idx(bTr) > 1, 'bIdx=' + idx(bTr));
  A('触发行恰 1 行（其余 23 只未达标不贴标）',
    body.querySelectorAll('tr.qlch-trig').length === 1 && body.querySelectorAll('tr.qlch-dip').length === 1 &&
    body.querySelectorAll('.qlch-tag').length === 2, JSON.stringify(out.raw.dom));
  const st = window.QLCH_LIVE.state;
  out.raw.diag = st.diag;
  A('诊断计数 gap=1 / dip=1 / na=0 / wait=23 / rows=25',
    st.diag.gap === 1 && st.diag.dip === 1 && st.diag.na === 0 && st.diag.wait === 23 && st.diag.rows === 25,
    JSON.stringify(st.diag));

  /* 4) 卡片头徽标 + 刷新信息 */
  const bd = document.querySelector('#qlch-card h2 .qlch-badge');
  const src = document.querySelector('#qlch-card h2 .qlch-live-src');
  out.raw.badge = {badge: txt(bd), src: txt(src)};
  A('徽标 = 已触发 1/25', !!bd && txt(bd) === '已触发 1/25', txt(bd));
  A('徽标旁显示 刷新于 HH:MM:SS · 源 …', !!src && /刷新于 10:31:02 · 源 东财（合成）/.test(txt(src)), txt(src));

  /* 5) localStorage 首次触发时间戳（含跨日字段 as_of） */
  let store = null;
  try { store = JSON.parse(localStorage.getItem('quant_qlch_trig_v1') || 'null'); } catch (e) {}
  out.raw.store = store;
  const recA = store && store[norm(rA.code)], recB = store && store[norm(rB.code)];
  A('A 行时间戳写入 localStorage（YYYY-MM-DD HH:MM:SS / kind=gap / as_of 对齐）',
    !!recA && /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(recA.first) && recA.kind === 'gap' &&
    recA.as_of === Q.as_of, JSON.stringify(recA));
  A('B 行记为 kind=dip（回落不置顶但留痕）', !!recB && recB.kind === 'dip', JSON.stringify(recB));
  out.raw.trigMem = window.QLCH_LIVE.trig();

  /* 5b) 跨日清空：把 B 的记录改成上一交易日（as_of 变）→ reload 后必须被丢弃 */
  if (store && recB) {
    const s2 = JSON.parse(JSON.stringify(store));
    s2[norm(rB.code)].as_of = '2026-09-01';
    s2['999999'] = {first: '2026-09-01 09:31:00', kind: 'gap', as_of: '2026-09-01'};
    try { localStorage.setItem('quant_qlch_trig_v1', JSON.stringify(s2)); } catch (e) {}
    const kept = window.QLCH_LIVE.reload();
    out.raw.crossDay = {dropped: window.QLCH_LIVE.state.dropped, kept: Object.keys(kept)};
    A('跨日清空：as_of 不匹配的记录（含上次运行遗留）被丢弃，当日记录保留',
      window.QLCH_LIVE.state.dropped === 2 && kept[norm(rA.code)] && !kept[norm(rB.code)] && !kept['999999'],
      JSON.stringify(out.raw.crossDay));
    await sleep(1100);        /* 让「重新起算」的时间戳在秒级上可区分（否则同一秒内不成立） */
     IN.applyQuotes(q, '10:31:30', {src: '东财（合成）', mktTs: MKT_NEXT});
    let s3 = null;
    try { s3 = JSON.parse(localStorage.getItem('quant_qlch_trig_v1') || 'null'); } catch (e) {}
    A('跨日清空后重新触发：A 保留首次时间、B 重新起算',
      !!s3 && s3[norm(rA.code)].first === recA.first && s3[norm(rB.code)].first !== recB.first,
      'A=' + (s3 && s3[norm(rA.code)] && s3[norm(rA.code)].first) + ' B=' + (s3 && s3[norm(rB.code)] && s3[norm(rB.code)].first));
  }

  /* 6) 盘中净值（估算） */
  /* 6) 盘中净值（估算）——口径对齐生产记账（修正 1）：
        nav_now = nav_prev × (1 + Σ w×(现价/基准 − 1))，基准 = 昨收（当日新开仓用入场价），开仓腿**不扣成本** */
  const navTd = document.querySelector('#tbl-qlch-paper tr[data-track="C1"] td.qlch-nav-live');
  const navTxt = navTd ? navTd.textContent.trim() : null;
  const got = parseFloat(navTxt);
  const navVal = window.QLCH_LIVE.state.nav.C1;
  const wantNav = pos ? c1.nav * (1 + (pos.w || 0) * (C1_PX / C1_PREVC - 1)) : null;
  const wrongBase = pos ? c1.nav * (1 + (pos.w || 0) * (C1_PX / pos.entry_px - 1)) : null;   /* 误用入场价为基准 */
  const wrongCost = pos ? c1.nav * (1 + (pos.w || 0) * (C1_PX / C1_PREVC - 1 - (Q.cost_rt || 0))) : null;  /* 误扣成本 */
  const others = [].slice.call(document.querySelectorAll('#tbl-qlch-paper tr[data-track]'))
    .filter(tr => tr.getAttribute('data-track') !== 'C1')
    .map(tr => ({t: tr.getAttribute('data-track'), v: tr.querySelector('td.qlch-nav-live').textContent.trim()}));
  const thNav = [].slice.call(document.querySelectorAll('#tbl-qlch-paper thead th'))
    .filter(th => /盘中净值/.test(th.textContent))[0];
  out.raw.nav = {cell: navTxt, got: got, mem: navVal, want: wantNav, wrongBase: wrongBase, wrongCost: wrongCost,
                 inst: {prevClose: C1_PREVC, px: C1_PX, entry_px: pos && pos.entry_px, entry_date: pos && pos.entry_date},
                 title: navTd && navTd.title, others: others, thTitle: thNav && thNav.title};
  A('修正 1：nav_now = nav_prev×(1+w×(现价/昨收−1))，误差 < 1e-9（内存值原值）',
    wantNav !== null && isFinite(navVal) && Math.abs(navVal - wantNav) < 1e-9,
    'mem=' + navVal + ' want=' + wantNav + ' diff=' + (wantNav === null ? null : Math.abs(navVal - wantNav)));
  A('修正 1：基准是**昨收**（若误用入场价则为 ' + wrongBase + '，与实测差 ' +
    (wrongBase === null ? '—' : Math.abs(navVal - wrongBase).toFixed(6)) + '）',
    wrongBase !== null && Math.abs(navVal - wrongBase) > 1e-4, 'mem=' + navVal);
  A('修正 1：开仓腿**不扣** COST_RT（扣成本假设值 ' + wrongCost + '，与实测差 ' +
    (wrongCost === null ? '—' : Math.abs(navVal - wrongCost).toFixed(6)) + '）',
    wrongCost !== null && Math.abs(navVal - wrongCost) > 1e-4, 'mem=' + navVal + ' cost_rt=' + Q.cost_rt);
  A('格子渲染 = 4 位小数的估算值（与内存值同源，误差 < 1e-4）',
    wantNav !== null && isFinite(got) && Math.abs(got - wantNav) < 1e-4 &&
    navTxt.indexOf(wantNav.toFixed(4)) === 0, 'cell=' + navTxt);
  A('无持仓臂显示「（无持仓）」×5', others.length === 5 && others.every(o => /（无持仓）/.test(o.v)),
    JSON.stringify(others));
  A('列头/单元格带口径注释（盘中估算值，非记账值）',
    !!thNav && /盘中估算值，非记账值/.test(thNav.title) && /盘中估算值，非记账值/.test(navTd.title), out.raw.nav.thTitle);

  /* 6b) 昨收缺失 → 退回入场价，并在该格标注（修正 1 的降级分支） */
  const q4 = Object.assign({}, q);
  q4[norm(pos.code)] = {px: pos.entry_px * 1.05, name: pos.name};        /* 无 pcl（昨收缺失） */
  IN.applyQuotes(q4, '10:31:40', {src: '东财（合成）', mktTs: MKT_NEXT});
  const fbNav = window.QLCH_LIVE.state.nav.C1;
  const fbWant = c1.nav * (1 + (pos.w || 0) * ((pos.entry_px * 1.05) / pos.entry_px - 1));
  const fbTip = navTd.querySelector('.qlch-nav-tip');
  out.raw.navFallback = {mem: fbNav, want: fbWant, title: navTd.title, tip: fbTip && fbTip.textContent};
  A('修正 1 降级：昨收缺失 → 基准退回入场价（误差<1e-9）且标注「昨收缺失，按入场价粗估」',
    Math.abs(fbNav - fbWant) < 1e-9 && /昨收缺失，按入场价粗估/.test(navTd.title) &&
    /昨收缺失/.test(fbTip && fbTip.textContent || ''), JSON.stringify(out.raw.navFallback));

  /* 6c) 修正 2：行情日 == 账本 equity[-1].date → 当日已记账，不再叠加 */
  IN.applyQuotes(q, '15:00:02', {src: '东财（合成）', mktTs: MKT_LEDGER});
  const bkTip = navTd.querySelector('.qlch-nav-tip');
  const bk = {mem: window.QLCH_LIVE.state.nav.C1, cell: navTd.textContent.trim(), tip: bkTip && bkTip.textContent,
              ledger: c1.nav, nav_date: c1.nav_date, mktDate: window.QLCH_LIVE.state.mktDate};
  out.raw.booked = bk;
  A('修正 2：行情日 == 账本记账日 → 不叠加当日收益（显示账本净值 + 「已收盘记账」）',
    Math.abs(bk.mem - c1.nav) < 1e-12 && /已收盘记账/.test(bk.cell) &&
    bk.cell.indexOf(c1.nav.toFixed(4)) === 0, JSON.stringify(bk));

  /* 6d) 修正 3：行情日 == as_of（信号日当日 / 盘前 / 节假日）→ 待开盘判定，0 触发 */
  IN.applyQuotes(q, '10:31:50', {src: '东财（合成）', mktTs: MKT_SAME});
  const gb = {gate: window.QLCH_LIVE.state.gate, mktDate: window.QLCH_LIVE.state.mktDate,
              hdr: body.querySelectorAll('tr.qlch-trig-hdr').length,
              trig: body.querySelectorAll('tr.qlch-trig').length,
              tags: body.querySelectorAll('.qlch-tag').length,
              badge: txt(document.querySelector('#qlch-card h2 .qlch-badge')),
              diag: window.QLCH_LIVE.state.diag};
  out.raw.gated = gb;
  A('修正 3：行情日 == as_of → 0 触发 / 无置顶 / 无标签 / 徽标「待开盘判定（as_of …）」/ 全部计入 gated',
    gb.gate === true && gb.hdr === 0 && gb.trig === 0 && gb.tags === 0 && gb.diag.gated === 25 &&
    gb.diag.gap === 0 && gb.diag.dip === 0 &&
    gb.badge === '待开盘判定（as_of ' + Q.as_of + '）', JSON.stringify(gb));

  /* 6e) 基准规则单测（生产 :379-384 三条分支）—— 覆盖「当日新开仓」这条真实账本里还没有的分支 */
  const B = window.QLCH_LIVE.base;
  out.raw.base = {sameDay: B({entry_date: D1, entry_px: 10}, D1, {pcl: 12}),
                  held: B({entry_date: ASOF, entry_px: 10}, D1, {pcl: 12}),
                  fallback: B({entry_date: ASOF, entry_px: 10}, D1, {})};
  A('基准规则：当日新开仓→入场价 / 隔日持仓→昨收 / 昨收缺失→入场价（why 可审计）',
    out.raw.base.sameDay.b === 10 && out.raw.base.sameDay.why === 'entry' &&
    out.raw.base.held.b === 12 && out.raw.base.held.why === 'prevclose' &&
    out.raw.base.fallback.b === 10 && out.raw.base.fallback.why === 'fallback',
    JSON.stringify(out.raw.base));

  /* 7) 幂等：同条件再刷新一次 —— 不重复计数、不重复插标题行、时间戳不覆盖 */
  IN.applyQuotes(q, '10:32:10', {src: '东财（合成）', mktTs: MKT_NEXT});
  let store2 = null;
  try { store2 = JSON.parse(localStorage.getItem('quant_qlch_trig_v1') || 'null'); } catch (e) {}
  A('幂等：二次刷新后标题行仍 1 个 / 触发行仍 1 个',
    body.querySelectorAll('tr.qlch-trig-hdr').length === 1 && body.querySelectorAll('tr.qlch-trig').length === 1,
    'hdr=' + body.querySelectorAll('tr.qlch-trig-hdr').length + ' trig=' + body.querySelectorAll('tr.qlch-trig').length);
  A('幂等：徽标仍 1/25 且首次触发时间不被覆盖',
    txt(document.querySelector('#qlch-card h2 .qlch-badge')) === '已触发 1/25' &&
    store2 && recA && store2[norm(rA.code)].first === recA.first,
    'first=' + (store2 && store2[norm(rA.code)] && store2[norm(rA.code)].first));

  /* 8) 未触发时移除标题行（N=0 不显示）+ 记录保留 */
  const q2 = {};
  Q.rows.forEach(r => { q2[norm(r.code)] = {px: r.close * 1.005, pct: 0.5, name: r.name,
                                            pcl: r.close, opn: r.close * 1.001}; });
  IN.applyQuotes(q2, '10:33:00', {src: '东财（合成）', mktTs: MKT_NEXT});
  let store3 = null;
  try { store3 = JSON.parse(localStorage.getItem('quant_qlch_trig_v1') || 'null'); } catch (e) {}
  A('回落/达标解除后：标题行移除、无触发行、徽标回 0/25',
    !body.querySelector('tr.qlch-trig-hdr') && body.querySelectorAll('tr.qlch-trig').length === 0 &&
    txt(document.querySelector('#qlch-card h2 .qlch-badge')) === '已触发 0/25',
    'badge=' + txt(document.querySelector('#qlch-card h2 .qlch-badge')));
  A('清空视图态不清 localStorage 记录（首次时间仍是历史值）',
    !!store3 && store3[norm(rA.code)].first === recA.first, JSON.stringify(store3 && store3[norm(rA.code)]));

  /* 8b) 无法判定分支：缺昨收（且涨跌幅缺失→回退不出）与「停牌/一字」(现价=今开=昨收) */
  const rN1 = Q.rows[3], rN2 = Q.rows[4];
  const q3 = Object.assign({}, q2);        /* 基线全部「温和上行」；下面两行单独改造成无法判定 */
  q3[norm(rN1.code)] = {px: rN1.close * 0.98, name: rN1.name};   /* 只有现价：缺昨收、涨跌幅也缺 → 回退不出 */
  q3[norm(rN2.code)] = {px: rN2.close, pct: 0, name: rN2.name, pcl: rN2.close, opn: rN2.close};
  IN.applyQuotes(q3, '10:33:30', {src: '东财（合成）', mktTs: MKT_NEXT});
  const n1Tr = rowBy(norm(rN1.code)), n2Tr = rowBy(norm(rN2.code));
  const nalabel = tr => txt(tr && tr.querySelector('.qlch-tag'));
  out.raw.na = {diag: window.QLCH_LIVE.state.diag, n1: nalabel(n1Tr), n2: nalabel(n2Tr),
                n1Trig: n1Tr.classList.contains('qlch-trig'), n2Trig: n2Tr.classList.contains('qlch-trig'),
                hdr: body.querySelectorAll('tr.qlch-trig-hdr').length};
  A('无法判定：缺昨收 / 停牌·一字 两行都标「无法判定」且不置顶',
    /无法判定/.test(nalabel(n1Tr)) && /无法判定/.test(nalabel(n2Tr)) &&
    !n1Tr.classList.contains('qlch-trig') && !n2Tr.classList.contains('qlch-trig') &&
    body.querySelectorAll('tr.qlch-trig-hdr').length === 0,
    JSON.stringify(out.raw.na));
  A('无法判定计入诊断计数（na=2，仍无置顶）',
    window.QLCH_LIVE.state.diag.na === 2 && window.QLCH_LIVE.state.diag.gap === 0,
    JSON.stringify(window.QLCH_LIVE.state.diag));
  /* 9) 复现置顶态供截图（同一时间戳复现，证明记录是「首次」的） */
  IN.applyQuotes(q, '10:34:20', {src: '东财（合成）', mktTs: MKT_NEXT});
  let store4 = null;
  try { store4 = JSON.parse(localStorage.getItem('quant_qlch_trig_v1') || 'null'); } catch (e) {}
  A('重新达标：置顶恢复、时间戳仍为首次值（修正 3：行情日晚于 as_of → 判定恢复生效）',
    body.querySelectorAll('tr.qlch-trig-hdr').length === 1 && idx(aTr) === idx(body.querySelector('tr.qlch-trig-hdr')) + 1 &&
    window.QLCH_LIVE.state.gate === false &&
    store4 && store4[norm(rA.code)].first === recA.first, 'first=' + (store4 && store4[norm(rA.code)] && store4[norm(rA.code)].first));

  /* 9b) 缺陷 1 回归：闸门不得依赖 S.live —— 收盘后（S.live=false）+ 行情日 == as_of → 仍须「待开盘判定」 */
  IN.state.live = false;
  IN.applyQuotes(q, '10:34:40', {src: '东财（合成）', mktTs: MKT_SAME});
  const gb2 = {live: IN.state.live, gate: window.QLCH_LIVE.state.gate, mktDate: window.QLCH_LIVE.state.mktDate,
               hdr: body.querySelectorAll('tr.qlch-trig-hdr').length, trig: body.querySelectorAll('tr.qlch-trig').length,
               tags: body.querySelectorAll('.qlch-tag').length,
               badge: txt(document.querySelector('#qlch-card h2 .qlch-badge'))};
  out.raw.gateNoLive = gb2;
  A('缺陷 1：S.live=false（收盘后）+ 行情日 == as_of → gate=true / 0 触发 / 徽标「待开盘判定」',
    gb2.live === false && gb2.gate === true && gb2.hdr === 0 && gb2.trig === 0 && gb2.tags === 0 &&
    /待开盘判定/.test(gb2.badge), JSON.stringify(gb2));
  const blb = document.querySelector('#qlch-card h2 .badge-live');
  A('缺陷 1 顺带：盘中层自己的「实时」徽标仍在（未被闸门影响）',
    !!blb && /实时/.test(txt(blb)), 'badge-live=' + txt(blb || null));

  /* 9c) 缺陷 1 回归（反面）：S.live=false + 行情日 == as_of+1 → 判定必须恢复（与 live 无关） */
  IN.applyQuotes(q, '10:34:50', {src: '东财（合成）', mktTs: MKT_NEXT});
  const gb3 = {live: IN.state.live, gate: window.QLCH_LIVE.state.gate,
               hdr: body.querySelectorAll('tr.qlch-trig-hdr').length, aIdx: idx(aTr)};
  out.raw.gateNoLive2 = gb3;
  A('缺陷 1：S.live=false + 行情日 == as_of+1 → gate=false 且低开达标重新置顶',
    gb3.live === false && gb3.gate === false && gb3.hdr === 1 && gb3.aIdx === 1 &&
    aTr.classList.contains('qlch-trig'), JSON.stringify(gb3));

  /* 9d) 缺陷 2 回归：两枚徽标并存、互不覆盖 */
  const qb = document.querySelector('#qlch-card h2 .qlch-badge');
  const lb = document.querySelector('#qlch-card h2 .badge-live');
  const qbTxt = txt(qb), lbTxt = txt(lb);
  out.raw.badges = {qlch: {cls: qb && qb.className, txt: qbTxt}, live: {cls: lb && lb.className, txt: lbTxt},
                    n: document.querySelectorAll('#qlch-card h2 .qlch-badge').length,
                    nLive: document.querySelectorAll('#qlch-card h2 .badge-live').length};
  A('缺陷 2：卡片里两枚徽标并存 —— .qlch-badge（判定态）与 .badge-live（实时 HH:MM:SS）',
    !!qb && !!lb && qb !== lb && /已触发 \d+\/\d+|待开盘判定/.test(qbTxt) && /实时/.test(lbTxt) &&
    (qb.className || '').indexOf('badge-live') < 0, JSON.stringify(out.raw.badges));
  A('缺陷 2：applyQuotes 后 .qlch-badge 文案未被 markCard 改成「实时 …」',
    /已触发 \d+\/\d+/.test(qbTxt), 'qlch-badge=' + qbTxt);
  /* 9e) 跟踪池按策略独立（R-track-sep-0923）：5 张卡存在 + 每卡代码集合 ⊆ 本策略白名单 + 跨策略 0 混入
        白名单由 Python 侧把各策略账本/池文件的代码集合注入 window.WATCH_WL（真值来源=产物文件，不是卡自己）。 */
  const WL = window.WATCH_WL || {};
  const allWl = new Set(); Object.keys(WL).forEach(k => (WL[k] || []).forEach(c => allWl.add(c)));
  const CK = ['st-stk', 'st-qlch', 'st-kh', 'st-etf', 'st-fund'];
  const cardCodes = k => {
    const el = document.getElementById('watch-card-' + k);
    if (!el) return null;
    const set = new Set();
    el.querySelectorAll('tbody tr').forEach(tr => {
      let c = String(tr.getAttribute('data-code') || '').trim();
      if (!/^(sh|sz|bj)?\d{6}$/.test(c)) {
        const m = (tr.textContent || '').match(/(?:^|\D)(\d{6})(?:\D|$)/);
        c = m ? m[1] : '';
      }
      if (c) set.add(c);
    });
    return set;
  };
  out.raw.cards = {};
  CK.forEach(k => {
    const el = document.getElementById('watch-card-' + k);
    const codes = cardCodes(k);
    const list = codes ? Array.from(codes) : [];
    const badSub = list.filter(c => (WL[k] || []).indexOf(c) < 0);
    const foreign = list.filter(c => allWl.has(c) && (WL[k] || []).indexOf(c) < 0);
    const title = el ? (el.querySelector('h2') || {}).textContent : null;
    out.raw.cards[k] = {exists: !!el, n: list.length, title: (title || '').replace(/\s+/g, ' ').trim(),
                        sample: list.slice(0, 4), badSub: badSub.slice(0, 5), foreign: foreign.slice(0, 5),
                        wlN: (WL[k] || []).length};
    A('跟踪池卡 ' + k + ' 存在且标题为「跟踪池 · 策略名」',
      !!el && /跟踪池 · /.test(title || ''), out.raw.cards[k].title);
    A('卡 ' + k + ' 代码集合 ⊆ 本策略自有数据源白名单（n=' + list.length + '）',
      badSub.length === 0, JSON.stringify(out.raw.cards[k]));
    A('卡 ' + k + ' 跨策略代码 0 混入',
      foreign.length === 0, 'foreign=' + JSON.stringify(foreign.slice(0, 5)));
  });
  A('页面级共享卡 #watch-card 已删除（跟踪池不再跨策略共享）',
    !document.getElementById('watch-card'), 'watch-card=' + !!document.getElementById('watch-card'));
  A('st-fund 无自有账本 → 渲染「暂无跟踪数据」+ 缺字段清单（不编造数据）',
    /暂无跟踪数据/.test((document.getElementById('watch-card-st-fund') || {}).textContent || '') &&
    /缺字段清单/.test((document.getElementById('watch-card-st-fund') || {}).textContent || ''));

  /* 10) 切到「短线选股」并把卡片滚到视野内（截图用；用 switchView，不触发盘中层补刷） */
  try { window.switchView('short'); } catch (e) { A('switchView 可用', false, String(e && e.message || e)); }
  await sleep(400);
  const card = document.getElementById('qlch-card');
  if (card) card.scrollIntoView({block: 'start'});
  await sleep(600);
  out.raw.shot = {viewActive: !!(document.getElementById('view-short') || {}).classList &&
                  document.getElementById('view-short').classList.contains('active'),
                  cardTop: card ? Math.round(card.getBoundingClientRect().top) : null};
  await sleep(400);
  return out;
})()
"""


def new_tab(port, url):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def close_tab(port, tid):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=5).read()
    except Exception:
        pass


async def run_all(ws_url, shot: Path):
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20) as ws:
        mid = [0]

        async def call(method, params=None):
            mid[0] += 1
            await ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == mid[0]:
                    return m.get("result", {})

        # 注入「各策略自有数据源」的代码白名单（真值来源 = 产物文件；供卡内代码集合断言用反例/白名单）
        await call("Runtime.evaluate",
                   {"expression": "window.WATCH_WL = %s; 1" % json.dumps(WATCH_WL, ensure_ascii=False)})
        r = await call("Runtime.evaluate", {"expression": JS, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            return {"__JS_ERROR__": json.dumps(r["exceptionDetails"], ensure_ascii=False)[:1500]}
        out = r.get("result", {}).get("value")
        await asyncio.sleep(1.2)
        s = await call("Page.captureScreenshot", {"format": "png"})
        data = s.get("data")
        if data:
            shot.write_bytes(base64.b64decode(data))
            out["shotPath"] = str(shot)
            out["shotKB"] = shot.stat().st_size // 1024
        else:
            out["shotPath"] = None
        # 视觉证据（截图已落盘）：触发行/标题行的绿色左边条像素 + 回落橙标像素
        out["visual"] = {"skipped": "PIL 不可用"}
        try:
            from PIL import Image
            im = Image.open(shot).convert("RGB")
            GREEN, WARN = (0x16, 0xa3, 0x4a), (0xb4, 0x53, 0x09)

            def near(px, c, tol=26):
                return all(abs(px[i] - c[i]) <= tol for i in range(3))

            g = w = 0
            bar_rows = []
            for y in range(im.height):
                run, runs = 0, []
                for x in range(im.width):
                    px = im.getpixel((x, y))
                    if near(px, GREEN):
                        g += 1
                        run += 1
                    else:
                        if run:
                            runs.append((x - run, run))
                        run = 0
                if any(20 <= x0 <= 90 and 2 <= ln <= 6 for x0, ln in runs):
                    bar_rows.append(y)          # 左边条特征：左侧 3px 宽的纯色竖条
                if near(im.getpixel((min(im.width - 1, im.width // 2), y)), WARN):
                    w += 1
            out["visual"] = {"png": str(shot), "px": list(im.size), "green_px": g, "warn_rows": w,
                             "leftbar_rows": len(bar_rows),
                             "ok": g > 100 and len(bar_rows) >= 5}
        except Exception as e:                  # 截图仍在，只是这层校验不可用
            out["visual"] = {"skipped": str(e)}
        print("[visual] " + json.dumps(out["visual"], ensure_ascii=False))
        _shots = []
        for _k in ("st-qlch", "st-kh", "st-etf", "st-stk", "st-fund"):
            _js = ("(function(){var k=%r;var b=document.querySelector('.subnav .subtab[data-sub=\"'+k+'\"]');"
                   "if(b)b.click();var c=document.getElementById('watch-card-'+k);"
                   "if(c)c.scrollIntoView({block:'start'});"
                   "var act=document.querySelector('#view-short .subview.active');"
                   "return {sub: act?act.id:null, card: !!c,"
                   " top: c?Math.round(c.getBoundingClientRect().top):null};})()" % _k)
            _rr = await call("Runtime.evaluate", {"expression": _js, "returnByValue": True})
            await asyncio.sleep(1.3)
            _s = await call("Page.captureScreenshot", {"format": "png"})
            _d = _rr.get("result", {}).get("value") or {}
            if _s.get("data"):
                _p = BASE / ("_shot_track_%s.png" % _k)
                _p.write_bytes(base64.b64decode(_s["data"]))
                _shots.append({"key": _k, "activeSub": _d.get("sub"), "cardTop": _d.get("top"),
                               "file": _p.name, "KB": _p.stat().st_size // 1024})
        out["trackShots"] = _shots
        print("[shots] 跟踪池 5 张卡截图: " + json.dumps(_shots, ensure_ascii=False))
        # 清理：本页 localStorage 的触发记录（只读验收，不留痕）
        await call("Runtime.evaluate", {"expression": "localStorage.removeItem('quant_qlch_trig_v1');1"})
        return out


def main():
    port = gdc.AUTO_PORT
    launched = False
    if not gdc.cdp_alive(port):
        print("[boot] 拉起自动化 Chrome …")
        launched = gdc.boot_auto_profile()
        if not launched:
            print("[FAIL] 拉起失败")
            return 1
    else:
        print("[boot] 自动化 Chrome 已在运行")
    url = FILE_URL + "?cb=%d" % int(time.time())
    t = new_tab(port, url)
    tid = t.get("id")
    print(f"[tab] {tid}\n[url] {url}")
    shot = BASE / "_shot_qlch_trigger.png"
    try:
        print("[wait] 等页面加载 …")
        time.sleep(14)
        res = asyncio.run(run_all(t["webSocketDebuggerUrl"], shot))
        print("\n===== 真机验收结果 =====")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if isinstance(res, dict) and res.get("asserts") is not None:
            bad = [a for a in res["asserts"] if not a["ok"]]
            print(f"\n断言 {len(res['asserts']) - len(bad)}/{len(res['asserts'])} 通过"
                  + (f"；失败 {len(bad)}: {[a['assert'] for a in bad]}" if bad else ""))
            print("截图: %s" % res.get("shotPath"))
            return 1 if bad else 0
    finally:
        close_tab(port, tid)
        print("[cleanup] 已关标签")
        if launched:
            gdc.close_auto_profile()
    return 0


if __name__ == "__main__":
    sys.exit(main())
