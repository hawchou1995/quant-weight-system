/* =====================================================================================
   打板族 A5「竞价 / 开盘买点」判定夹具（判据 C · R-a5-auction-0924）—— **node 直接跑真 JS**

   为什么用 node 而不是 Python 复刻：判定逻辑在浏览器端（ADR-0009），Python 复刻只能证明
   「我另写了一份逻辑」，证明不了线上那份。本夹具的做法是 ——
     · 从 intraday_live.py 用正则抽出 `A5_JUDGE_JS` 与 `A5_JS` 的**原文**，
     · 在同一个作用域里 eval（于是 A5_JS 的 IIFE 能看见 a5Judge），
     · 用一套最小 DOM 桩把它真的跑起来，断言「命中置顶 / 竞价不置顶 / 幂等 / 还原」。

   运行：node backtest/a5_auction_judge_fixture.js
   输出：A5_JUDGE_FIXTURE_OK n=<通过项数>   （任一断言失败 → 打印 FAIL 行并 exit 1）
   口径来源：backtest/a5_experiment/paper_daban_a5.py L455-494（gap = o/pc − 1 闭区间 · ROOM_MIN=0.20）
   边界（契约明确要求）：gap = −5.00% 与 −2.00% **都判命中**。
   ===================================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const PY = path.join(__dirname, '..', 'intraday_live.py');
const src = fs.readFileSync(PY, 'utf8');
function grab(name) {
  const re = new RegExp(name + '\\s*=\\s*r"""([\\s\\S]*?)"""');
  const m = src.match(re);
  if (!m) { console.error('FATAL 抽不到 ' + name + '（intraday_live.py 结构变了？）'); process.exit(2); }
  return m[1];
}
const judgeSrc = grab('A5_JUDGE_JS');
const driverSrc = grab('A5_JS');

/* ------------------------------ 最小 DOM 桩 ------------------------------ */
function match(el, sel) {
  sel = String(sel).trim();
  if (sel === 'thead th') {
    const tr = el.parentNode;
    return el.tag === 'th' && !!tr && !!tr.parentNode && tr.parentNode.tag === 'thead';
  }
  /* 通用选择器：tag[.cls[.cls...]]（规范语义，支持 tr.a5-hit / .a5-tag.hit 这类复合选择器） */
  const parts = sel.split('.'), tag = parts.shift();
  if (tag && el.tag !== tag) return false;
  for (const c of parts) if (!el.classes.has(c)) return false;
  return true;
}
class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.parentNode = null;
    this.attrs = {}; this.classes = new Set();
    this.textContent = ''; this.title = ''; this._html = '';
    const self = this;
    this.classList = {
      add: function (c) { self.classes.add(c); },
      remove: function (c) { self.classes.delete(c); },
      contains: function (c) { return self.classes.has(c); },
      toggle: function (c, on) { if (on) self.classes.add(c); else self.classes.delete(c); }
    };
  }
  set className(v) { String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classes.add(c)); }
  get className() { return Array.from(this.classes).join(' '); }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  get firstChild() { return this.children[0] || null; }
  get nextSibling() {
    if (!this.parentNode) return null;
    const i = this.parentNode.children.indexOf(this);
    return this.parentNode.children[i + 1] || null;
  }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.children.push(c); return c;
  }
  insertBefore(c, ref) {
    /* DOM 规范：child is node → child = node.nextSibling（自插入是 no-op，不是搬到末尾） */
    let r = ref || null;
    if (r === c) r = this.children[this.children.indexOf(c) + 1] || null;
    if (r && r.parentNode !== this) r = null;
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    const i = r ? this.children.indexOf(r) : -1;
    if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) {
    const i = this.children.indexOf(c);
    if (i >= 0) { this.children.splice(i, 1); c.parentNode = null; }
    return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const ch of n.children) { if (match(ch, sel)) out.push(ch); walk(ch); } };
    walk(this); return out;
  }
  querySelector(sel) { const a = this.querySelectorAll(sel); return a.length ? a[0] : null; }
}

const doc = {
  _byId: {}, head: new El('head'),
  getElementById: function (id) { return doc._byId[id] || null; },
  createElement: function (t) { return new El(t); },
  querySelectorAll: function () { return []; }
};
global.document = doc;
global.window = { INTRADAY: null };      /* 不提供 applyQuotes → 只走 window.A5_ON_QUOTES 钩子路径 */

/* ------------------------- 装配夹具页面（3 行观察清单） ------------------------- */
function buildDom() {
  const tbody = new El('tbody');
  const thead = new El('thead');
  const trh = new El('tr');
  ['标的', '板块', '行业', '首板日', '滤网池', '相对位置', '成交额(万)', '过闸', '涨跌幅',
   '近一年', 'RSI', '量比', 'MA5偏离', '明日买点'].forEach(function (h) {
    const th = new El('th'); th.textContent = h; trh.appendChild(th);
  });
  thead.appendChild(trh);
  const tbl = new El('table'); tbl.appendChild(thead); tbl.appendChild(tbody);
  const CARD = ['A', 'B', 'C'];
  CARD.forEach(function (c) {
    const tr = new El('tr');
    tr.setAttribute('data-code', 'sh60000' + (CARD.indexOf(c) + 1));
    tr.setAttribute('data-search', 'X' + c);
    for (let i = 0; i < 14; i++) { const td = new El('td'); td.textContent = (i === 0 ? '标的' + c : 'v'); tr.appendChild(td); }
    tbody.appendChild(tr);
  });
  const h2 = new El('h2'); h2.textContent = '📋 观察清单';
  const card = new El('div'); card.appendChild(h2);
  doc._byId['a5-wl'] = tbl; doc._byId['a5-watchlist'] = card;
  return { tbody: tbody, tbl: tbl, card: card };
}

let n = 0, bad = 0;
function ok(name, cond, extra) {
  n++;
  if (cond) { console.log('  ok   ' + name); }
  else { bad++; console.log('  FAIL ' + name + (extra ? '  → ' + extra : '')); }
}
function order(tbody) {   /* 只数数据行（行首可能插入置顶分组行 a5-hit-hdr，它没有 data-code） */
  return tbody.children.map((t) => t.getAttribute('data-code')).filter(Boolean).join(',');
}
function tags(tr) { return tr.querySelectorAll('.a5-tag').map((s) => s.textContent); }

/* ============================ 1) 纯函数边界断言 ============================ */
const THR = { gap_lo: -0.05, gap_hi: -0.02, rel_pos_max: 0.5, amt_min: 5e7, room_min: 20.0 };
const BASE = { code: 'sh600001', name: 'X', last_close: 10.0, rel_pos: 0.3, amt: 7e8, room_pct: 30.0 };
function q(opn, pcl) { return { px: opn, pcl: pcl, opn: opn }; }

/* strict 模式下 eval 内声明不外泄 → judge 与 driver 必须放进同一 bundle 一起 eval，
   再把需要的符号显式导出到 globalThis。跑的是 intraday_live.py 里的原文，不是复刻。 */
let a5Judge = null;
function loadA5Bundle(withDriver) {
  globalThis.__A5_EXPORT = null;
  eval(judgeSrc + '\n' + (withDriver ? driverSrc : '') + '\n'
     + 'globalThis.__A5_EXPORT = { judge: a5Judge };');
  return globalThis.__A5_EXPORT;
}
const __A5A = loadA5Bundle(false);   /* 只装纯函数，供下面 [1][2] 断言 */
a5Judge = __A5A.judge;
if (typeof a5Judge !== 'function') { console.error('FATAL 抽到的 A5_JUDGE_JS 未定义 a5Judge'); process.exit(2); }

console.log('[1] 纯函数边界（gap = 今开/昨收 − 1，闭区间）');
ok('gap = −5.00% → 命中（闭区间下界）', a5Judge(BASE, q(9.50, 10.00), THR, 'open').k === 'hit',
   JSON.stringify(a5Judge(BASE, q(9.50, 10.00), THR, 'open')));
ok('gap = −2.00% → 命中（闭区间上界）', a5Judge(BASE, q(9.80, 10.00), THR, 'open').k === 'hit');
ok('gap = −5.01% → 不命中', a5Judge(BASE, q(9.499, 10.00), THR, 'open').k === 'no');
ok('gap = −1.99% → 不命中', a5Judge(BASE, q(9.801, 10.00), THR, 'open').k === 'no');
ok('rel_pos = 0.5（端点）→ 命中', a5Judge(Object.assign({}, BASE, { rel_pos: 0.5 }), q(9.60, 10.00), THR, 'open').k === 'hit');
ok('rel_pos = 0.6 → 不命中', a5Judge(Object.assign({}, BASE, { rel_pos: 0.6 }), q(9.60, 10.00), THR, 'open').k === 'no');
ok('amt = 5e7（端点）→ 命中', a5Judge(Object.assign({}, BASE, { amt: 5e7 }), q(9.60, 10.00), THR, 'open').k === 'hit');
ok('amt = 4e7 → 不命中', a5Judge(Object.assign({}, BASE, { amt: 4e7 }), q(9.60, 10.00), THR, 'open').k === 'no');
ok('room_pct = 20（端点）→ 命中', a5Judge(Object.assign({}, BASE, { room_pct: 20 }), q(9.60, 10.00), THR, 'open').k === 'hit');
ok('room_pct = 19 → 不命中', a5Judge(Object.assign({}, BASE, { room_pct: 19 }), q(9.60, 10.00), THR, 'open').k === 'no');
ok('room_pct 缺失 → 不命中（保守，不放宽）', a5Judge(Object.assign({}, BASE, { room_pct: undefined }), q(9.60, 10.00), THR, 'open').k === 'no');

console.log('[2] 相位（契约：09:15–09:25 一律不计命中）');
const auc = a5Judge(BASE, q(9.60, 10.00), THR, 'auction');
ok('phase=auction 且 gap 在带内 → 绝不 hit', auc.k !== 'hit' && auc.k === 'pre', JSON.stringify(auc));
ok('phase=auction 预判值 = 竞价参考价/昨收−1 = −4.00%', Math.abs(auc.v - (-0.04)) < 1e-9, String(auc.v));
ok('phase=closed → pre', a5Judge(BASE, q(9.60, 10.00), THR, 'closed').k === 'pre');
ok('phase=pre → pre', a5Judge(BASE, q(9.60, 10.00), THR, 'pre').k === 'pre');
ok('phase=open 但无今开 → pre（不误判）', a5Judge(BASE, { px: 9.60, pcl: 10.0, opn: undefined }, THR, 'open').k === 'pre');
ok('phase=open 无昨收 → 退回首板日收盘 last_close=10 → 命中', 
   a5Judge(BASE, { px: 9.60, pcl: undefined, opn: 9.60 }, THR, 'open').k === 'hit');

/* ======================= 2) 驱动块：DOM 置顶 / 竞价 / 幂等 ======================= */
console.log('[3] 驱动块 DOM 行为（真实重排）');
const dom = buildDom();
const tbody = dom.tbody;

doc._byId['a5-wl']._byId = undefined;   /* no-op，保持结构清晰 */
window.A5_AUCTION = {
  as_of: '2026-09-24', rows: [
    { code: 'sh600001', name: 'A', last_close: 10.0, rel_pos: 0.30, amt: 7e8, room_pct: 30.0 },  /* 会命中 */
    { code: 'sh600002', name: 'B', last_close: 10.0, rel_pos: 0.30, amt: 7e8, room_pct: 30.0 },  /* gap 出带 */
    { code: 'sh600003', name: 'C', last_close: 10.0, rel_pos: 0.90, amt: 7e8, room_pct: 30.0 }   /* 相对位置超 */
  ],
  thr: THR
};
/* 重新加载驱动块（此时 A5_AUCTION 已就位；上一次 eval 时 window.A5_AUCTION 还不存在 → 直接 return） */
const __A5B = loadA5Bundle(true);   /* 同一 bundle：judge + driver，driver 内可见 a5Judge */
const L = window.A5_LIVE;
ok('window.A5_LIVE 已导出', !!L && typeof L.run === 'function');
ok('ORDER 已捕获 3 行', !!L.order() && L.order().length === 3, String(L.order() && L.order().length));
const ORIG = order(tbody);
ok('原始行序 = A,B,C', ORIG === 'sh600001,sh600002,sh600003', ORIG);

/* 3a) 集合竞价（09:20）：只挂灰标「竞价预判」，不置顶、不计命中 */
const qsAuc = {
  '600001': { px: 9.70, pcl: 10.0, opn: 0 },   /* 竞价参考价 −3% */
  '600002': { px: 9.70, pcl: 10.0, opn: 0 },
  '600003': { px: 9.70, pcl: 10.0, opn: 0 }
};
let r = L.run(qsAuc, '09:20:00', 'auto', '20260925092000');
ok('phase = auction', r && r.phase === 'auction', JSON.stringify(r));
ok('竞价：hit = 0（不置顶、不计命中）', r && r.hit === 0);
ok('竞价：无置顶分组行', tbody.querySelectorAll('tr.a5-hit-hdr').length === 0);
ok('竞价：无 a5-hit 类', tbody.querySelectorAll('tr.a5-hit').length === 0);
ok('竞价：行序未变', order(tbody) === ORIG, order(tbody));
const aucTags = tbody.children.map(tags);
ok('竞价：3 行各挂 1 个灰标', aucTags.every((t) => t.length === 1), JSON.stringify(aucTags));
ok('竞价：文案以「竞价预判」开头', aucTags.every((t) => t[0].indexOf('竞价预判') === 0), JSON.stringify(aucTags));
ok('竞价：灰标类 = .a5-tag.pre', tbody.querySelectorAll('tr.a5-pre').length === 3);
ok('竞价：徽标文案 = 竞价预判中', dom.card.querySelector('h2').querySelector('.a5-auction-badge').textContent.indexOf('竞价预判中') === 0);

/* 3b) 开盘（09:30）：真实今开 → A 命中并置顶 */
const qsOpen = {
  '600001': { px: 9.60, pcl: 10.0, opn: 9.60 },   /* −4.00% → 命中 */
  '600002': { px: 9.95, pcl: 10.0, opn: 9.95 },   /* −0.50% → 不命中 */
  '600003': { px: 9.60, pcl: 10.0, opn: 9.60 }    /* 条件都过，但 rel_pos=0.90 → 不命中 */
};
r = L.run(qsOpen, '09:30:00', 'auto', '20260925093000');
ok('phase = open', r && r.phase === 'open', JSON.stringify(r));
ok('open：hit = 1 / n = 3', r && r.hit === 1 && r.n === 3, JSON.stringify(r));
ok('open：命中行被置顶到首位', order(tbody) === 'sh600001,sh600002,sh600003', order(tbody));
ok('open：插入 1 个置顶分组行', tbody.querySelectorAll('tr.a5-hit-hdr').length === 1);
ok('open：分组行 colspan = 14（运行时列数，非写死）',
   tbody.children[0].innerHTML.indexOf('colspan="14"') > 0, tbody.children[0].innerHTML);
ok('open：首行 = sh600001 且带 a5-hit', tbody.children[1].getAttribute('data-code') === 'sh600001'
   && tbody.children[1].classList.contains('a5-hit'));
ok('open：命中标签 = .a5-tag.hit 且文案含 −4.00%',
   tbody.children[1].querySelectorAll('.a5-tag.hit').length === 1
   && tags(tbody.children[1])[0].indexOf('-4.00%') > 0, JSON.stringify(tags(tbody.children[1])));
ok('open：徽标文案 = 已命中 1/3', dom.card.querySelector('h2').querySelector('.a5-auction-badge').textContent === '已命中 1/3');

/* 3c) 幂等：同一份行情再跑一遍，不叠加分组行/标签 */
L.run(qsOpen, '09:31:00', 'auto', '20260925093100');
ok('幂等：分组行仍只有 1 个', tbody.querySelectorAll('tr.a5-hit-hdr').length === 1);
ok('幂等：命中行标签仍只有 1 个', tbody.children[1].querySelectorAll('.a5-tag').length === 1);
ok('幂等：行序不变', order(tbody) === 'sh600001,sh600002,sh600003', order(tbody));
ok('幂等：a5-hit 行只有 1 个', tbody.querySelectorAll('tr.a5-hit').length === 1);

/* 3d) 回到竞价相位 → 必须完整还原（摘分组行/摘类/摘标签/复位行序） */
r = L.run(qsAuc, '09:20:00', 'auto', '20260925092000');
ok('还原：分组行被摘掉', tbody.querySelectorAll('tr.a5-hit-hdr').length === 0);
ok('还原：a5-hit 类被摘掉', tbody.querySelectorAll('tr.a5-hit').length === 0);
ok('还原：行序回到 A,B,C（置顶是视图态，可逆）', order(tbody) === 'sh600001,sh600002,sh600003', order(tbody));
ok('还原：每行恰好 1 个标签', tbody.children.map(tags).every((t) => t.length === 1), JSON.stringify(tbody.children.map(tags)));

/* 3e) 行情日 = as_of（信号日当日）→ 待开盘判定，不判不贴标 */
r = L.run(qsOpen, '09:30:00', 'auto', '20260924093000');
ok('行情日 == as_of → phase=pre', r && r.phase === 'pre', JSON.stringify(r));
ok('行情日 == as_of → hit=0 且不贴标', r.hit === 0 && tbody.children.map(tags).every((t) => t.length === 0),
   JSON.stringify(tbody.children.map(tags)));

/* 3f) 无行情（首屏）→ 不判不贴标，且不抛错 */
r = L.run(null, '', '', '');
ok('无行情：不抛错且 hit=0', r && r.hit === 0 && r.phase === 'pre', JSON.stringify(r));
ok('无行情：不贴任何标签', tbody.children.map(tags).every((t) => t.length === 0));

console.log('');
console.log((bad === 0 ? 'A5_JUDGE_FIXTURE_OK' : 'A5_JUDGE_FIXTURE_FAIL') + ' n=' + n + (bad ? ' bad=' + bad : ''));
process.exit(bad === 0 ? 0 : 1);
