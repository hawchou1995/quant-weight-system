/* =====================================================================================
   横盘低开·两日（hpdk）「买日 09:25 买点判定 + 自动剔除」夹具（R-hpdk-live-0927）—— **node 直接跑真 JS**

   为什么用 node 而不是 Python 复刻：判定逻辑在浏览器端（ADR-0009），Python 复刻只能证明
   「我另写了一份逻辑」，证明不了线上那份。本夹具的做法是 ——
     · 从 intraday_live.py 用正则抽出 `HPDK_JS` 的**原文**；
     · 用 `vm` 把它跑在一个伪造的 window / document / localStorage 环境里（最小 DOM 桩），
       DOM 桩按真实卡片（hpdk_card.py）的表头：『# 标的 板块 行业 现价 涨跌幅 成交额20 量比 20日涨幅
       买入价 止盈价 +2% 卖出时点 建议股数 容量』（可选变体多一列「事件标签」）；
     · 喂入构造好的 window.HPDK 与假行情 q，断言表格行的增删、文本、排名顺序。
   跑的是 intraday_live.py 里的原文，不是复刻。

   运行：node backtest/hpdk_judge_fixture.js
   输出：HPDK_JUDGE_FIXTURE_OK n=<通过项数>   （任一断言失败 → 打印 FAIL 明细并 exit 1）
   口径来源：backtest/hengpan_fangliang_dikai_0925/hpdk_candidates.py
     gap = 今开/昨收 − 1 ∈ [−3%, −1%]（闭区间）· amt20 ≥ 2e7 · close ≥ 3.0 ·
     F = zs(−ln amt20) + zs(−ln volbr) + zs(−ret20)（存活子集内，zs 用总体标准差 = np.nanstd ddof=0）
   闸门（本夹具的核心断言）：**只有**「行情日 === buy_date 且 时刻 ≥ 09:25」才剔除；
     盘前 / 非买日 / 买日之后 / 无行情 → 一行都不剔除、且**不挂任何逐行标签**（相位由卡头徽章表达）；集合竞价 09:15–09:24 → 不剔除，但挂「竞价预判」逐行灰标（写进「状态」列）。
   ===================================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PY = path.join(__dirname, '..', 'intraday_live.py');
const src = fs.readFileSync(PY, 'utf8');
function grab(name) {
  const re = new RegExp(name + '\\s*=\\s*r"""([\\s\\S]*?)"""');
  const m = src.match(re);
  if (!m) { console.error('FATAL 抽不到 ' + name + '（intraday_live.py 结构变了？）'); process.exit(2); }
  return m[1];
}
const HP = grab('HPDK_JS');

/* ------------------------------ 最小 DOM 桩 ------------------------------ */
function partMatch(el, part) {
  const ps = String(part).split('.'), tag = ps.shift();
  if (tag && el.tag !== tag) return false;
  for (const c of ps) if (!el.classes.has(c)) return false;
  return true;
}
/* 支持 'tr.hpdk-buy' / '.hpdk-tag' / 'thead th' / 'tbody tr' 这类简单选择器（含后代组合） */
function match(el, sel) {
  const parts = String(sel).trim().split(/\s+/);
  if (!partMatch(el, parts[parts.length - 1])) return false;
  let anc = el.parentNode;
  for (let i = parts.length - 2; i >= 0; i--) {
    let ok = false;
    while (anc) { if (partMatch(anc, parts[i])) { ok = true; anc = anc.parentNode; break; } anc = anc.parentNode; }
    if (!ok) return false;
  }
  return true;
}
class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.parentNode = null;
    this.attrs = {}; this.classes = new Set();
    this._text = ''; this.title = ''; this._html = ''; this.style = {};
    const self = this;
    this.classList = {
      add: (c) => { self.classes.add(c); },
      remove: (c) => { self.classes.delete(c); },
      contains: (c) => self.classes.has(c),
      toggle: (c, on) => { if (on) self.classes.add(c); else self.classes.delete(c); }
    };
  }
  /* 真 DOM 语义：给 textContent 赋值会清空子节点 —— 夹具必须复现，否则「还原」断言是假证据 */
  set textContent(v) { this._text = String(v); this.children = []; }
  /* 有子元素时 textContent = 子节点文本拼接（真 DOM 语义）—— 否则「还原后结构是否完整」无法被证伪 */
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text; }
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
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) {
    let r = ref || null;
    if (r === c) r = this.children[this.children.indexOf(c) + 1] || null;
    if (r && r.parentNode !== this) r = null;
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    const i = r ? this.children.indexOf(r) : -1;
    if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) { this.children.splice(i, 1); c.parentNode = null; } return c; }
  removeAttribute(k) { delete this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const ch of n.children) { if (match(ch, sel)) out.push(ch); walk(ch); } };
    walk(this); return out;
  }
  querySelector(sel) { const a = this.querySelectorAll(sel); return a.length ? a[0] : null; }
  closest(sel) { let n = this; while (n) { if (partMatch(n, sel)) return n; n = n.parentNode; } return null; }
}

function makeEnv() {
  const doc = {
    _byId: {}, head: new El('head'),
    getElementById(id) { return doc._byId[id] || null; },
    createElement(t) { return new El(t); },
    querySelectorAll() { return []; }
  };
  const store = new Map(), writes = [];
  const ls = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { writes.push(k); store.set(k, String(v)); },
    removeItem: (k) => { store.delete(k); },
    _store: store, _writes: writes
  };
  const sandbox = { document: doc, localStorage: ls, console: { log() {}, warn() {}, error() {} } };
  sandbox.window = sandbox;                      /* 浏览器语义：window 就是全局对象 */
  vm.createContext(sandbox);
  return { sandbox: sandbox, doc: doc, ls: ls, writes: writes };
}
function mount(env, payload) {
  if (payload !== undefined) env.sandbox.window.HPDK = payload;
  vm.runInContext(HP, env.sandbox, { filename: 'HPDK_JS(intraday_live.py)' });
  return env.sandbox.window.HPDK_LIVE;
}

/* ------------------------- 夹具数据（12 只资格池 · 3 只必然被剔） ------------------------- */
const COLS = ['code', 'name', 'ind', 'board', 'close', 'amt20', 'volbr', 'ret20'];
const AS_OF = '2026-09-24', BUY_DATE = '2026-09-28', EXIT_DATE = '2026-09-29';
const CAPITAL = 1000000, KSLOT = 4, MINAMT = 2e7, MINPX = 3.0, TP = 0.02, GAP_LO = -0.03, GAP_HI = -0.01;
const EPS = 1e-9;
/* [code, name, amt20, volbr, ret20, kind]  kind: ok | high（高开，A 不满足）| halt（一字，B 不满足）| lowamt（C 不满足）*/
const ROWS = [
  ['600001', '甲', 5.0e7, 1.60, 0.02, 'ok'],
  ['600002', '乙', 1.2e8, 0.95, -0.15, 'ok'],
  ['600003', '丙', 4.0e7, 1.20, 0.05, 'high'],
  ['600004', '丁', 1.0e6, 0.80, -0.30, 'lowamt'],
  ['600005', '戊', 6.0e7, 1.10, -0.05, 'halt'],
  ['600006', '己', 3.0e7, 2.50, 0.09, 'ok'],
  ['600007', '庚', 8.0e7, 0.70, -0.18, 'ok'],
  ['600008', '辛', 2.2e7, 1.90, -0.02, 'ok'],
  ['600009', '壬', 1.5e8, 1.05, 0.01, 'ok'],
  ['600010', '癸', 3.5e7, 0.60, -0.12, 'ok'],
  ['600011', '子', 9.0e7, 1.40, -0.08, 'ok'],
  ['600012', '丑', 2.5e7, 0.90, 0.03, 'ok']
];
const KIND = {}; ROWS.forEach((r) => { KIND[r[0]] = r[5]; });
const DROP_EXPECT = { '600003': 'A', '600004': 'C', '600005': 'B' };
const SURV = ROWS.map((r, i) => i).filter((i) => !DROP_EXPECT[ROWS[i][0]]);

/* 假行情：昨收一律 10.00；低开档今开 9.80（= −2.00%，带内） */
function quoteOf(code) {
  const k = KIND[code];
  if (k === 'high')  return { px: 10.10, pcl: 10.00, opn: 10.05, pct: 1.00, name: 'N' };   /* 高开 +0.50% → A */
  if (k === 'halt')  return { px: 9.80, pcl: 9.80, opn: 9.80, pct: 0.00, name: 'N' };      /* 一字/停牌 → B */
  return { px: 9.85, pcl: 10.00, opn: 9.80, pct: -1.50, name: 'N' };                       /* 低开 −2.00% → 带内 */
}
function quotesAll() { const o = {}; ROWS.forEach((r) => { o[r[0]] = quoteOf(r[0]); }); return o; }

function buildPayload(rows, k) {
  return {
    as_of: AS_OF, buy_date: BUY_DATE, exit_date: EXIT_DATE,
    gap_lo: GAP_LO, gap_hi: GAP_HI, tp: TP, k: k, kslot: KSLOT, capital: CAPITAL,
    minamt: MINAMT, minpx: MINPX, frozen_sha256: 'fixture'.repeat(9),
    cols: COLS.slice(),
    rows: rows.map((r) => [r[0], r[1], '软件服务', '主板', 10.0, r[2], r[3], r[4]])
  };
}

/* 真实卡片（hpdk_card.py）的表头；可选变体多一列『状态』（= 生产列名，2026-09-27 新增） */
const HEADS_BASE = ['#', '标的', '板块', '行业', '现价', '涨跌幅', '成交额20', '量比', '20日涨幅',
                    '买入价', '止盈价 +2%', '卖出时点', '建议股数', '单票可买（上限）'];
const HEADS_EVENT = ['#', '标的', '状态', '板块', '行业', '现价', '涨跌幅', '成交额20', '量比', '20日涨幅',
                     '买入价', '止盈价 +2%', '卖出时点', '建议股数', '单票可买（上限）'];
const PH_BUY = '● 低开 1%~3% 才买', PH_TP = '9.894 ~ 10.098', PH_QTY = '25,500 股', PH_CAP = '足额', PH_PX = '—';

function buildDom(payload, withEvent) {
  const heads = (withEvent ? HEADS_EVENT : HEADS_BASE).slice();
  const tbody = new El('tbody'), thead = new El('thead'), trh = new El('tr');
  heads.forEach((h) => { const th = new El('th'); th.textContent = h; th.setAttribute('data-key', h); trh.appendChild(th); });
  thead.appendChild(trh);
  const tbl = new El('table'); tbl.className = 'tbl'; tbl.setAttribute('id', 'tbl-hpdk-cand');
  tbl.appendChild(thead); tbl.appendChild(tbody);
  const h2 = new El('h2'); h2.textContent = '🎯 横盘低开·两日';
  const vb = new El('span'); vb.className = 'view-badge auto'; vb.textContent = '数据 as_of ' + payload.as_of;
  h2.appendChild(vb);
  const card = new El('div'); card.className = 'card'; card.setAttribute('id', 'hpdk-card'); card.appendChild(h2);
  /* 真实卡片结构：<div class="card" id="hpdk-card"><h2>…</h2><div class="tbl-wrap"><table id="tbl-hpdk-cand">… */
  const wrap = new El('div'); wrap.className = 'tbl-wrap'; wrap.appendChild(tbl); card.appendChild(wrap);
  payload.rows.forEach((r, n) => {
    const tr = new El('tr');
    tr.setAttribute('data-code', 'sh' + r[0]);          /* 真实卡片写的是 sym（sh600000），不是 6 位码 */
    tr.setAttribute('data-tier', 'main');
    tr.setAttribute('data-search', r[1] + ' ' + r[0] + ' 主板 软件服务');
    heads.forEach((h) => {
      const td = new El('td');
      td.setAttribute('data-key', h);
      if (h === '#') { td.textContent = String(n + 1); td.setAttribute('data-v', String(n + 1)); }
      else if (h === '标的') td.textContent = r[1] + ' ' + r[0];
      else if (h === '现价') td.textContent = PH_PX;
      else if (h === '涨跌幅') td.textContent = '';
      else if (h === '成交额20') td.textContent = (r[5] / 1e8).toFixed(2) + '亿';
      else if (h === '量比') td.textContent = Number(r[6]).toFixed(2);
      else if (h === '20日涨幅') td.textContent = (r[7] * 100).toFixed(2) + '%';
      else if (h === '买入价') {                        /* 构建期形态：badge + 区间 div 两层子节点 */
        td.textContent = PH_BUY;
        const sp = new El('span'); sp.className = 'badge badge-auto'; sp.textContent = PH_BUY;
        const dv = new El('div'); dv.textContent = '9.700 ~ 9.900';
        td.appendChild(sp); td.appendChild(dv);
        td.setAttribute('data-v', '9.7');
      }
      else if (h === '止盈价 +2%') { td.textContent = PH_TP; td.setAttribute('data-v', '9.894'); }
      else if (h === '卖出时点') td.textContent = 'T+2 ' + payload.exit_date + ' 尾盘';
      else if (h === '建议股数') { td.textContent = PH_QTY; td.setAttribute('data-v', '25500'); }
      else if (h === '单票可买（上限）') { td.textContent = PH_CAP; td.setAttribute('data-v', '1'); }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  return { tbody: tbody, tbl: tbl, card: card, h2: h2, heads: heads, col: (name) => heads.indexOf(name) };
}

/* ------------------------------- 断言与取值工具 ------------------------------- */
let n = 0, bad = 0;
function ok(name, cond, extra) {
  n++;
  if (cond) console.log('  ok   ' + name);
  else { bad++; console.log('  FAIL ' + name + (extra !== undefined && extra !== null ? '  → ' + extra : '')); }
}
const bare = (c) => String(c || '').replace(/^(sh|sz|bj)/i, '');
function rowEl(dom, code) {
  return dom.tbody.children.find((tr) => tr.getAttribute('data-code') && bare(tr.getAttribute('data-code')) === code) || null;
}
function dataCodes(dom) {
  return dom.tbody.children.filter((tr) => tr.getAttribute('data-code')).map((tr) => bare(tr.getAttribute('data-code')));
}
function candCodes(dom) {
  return dom.tbody.querySelectorAll('tr.hpdk-buy').map((tr) => bare(tr.getAttribute('data-code')));
}
function cell(dom, code, header) { const tr = rowEl(dom, code); return tr ? tr.children[dom.col(header)] : null; }
function cellText(dom, code, header) { const td = cell(dom, code, header); return td ? td.textContent : null; }
function tags(dom, code) { const tr = rowEl(dom, code); return tr ? tr.querySelectorAll('.hpdk-tag').map((s) => s.textContent) : []; }
function tagsAll(dom) { return dataCodes(dom).map((c) => tags(dom, c)); }
function hdrRow(dom) { return dom.tbody.children.find((tr) => tr.classes.has('hpdk-buy-hdr')) || null; }
function badgeText(dom) { const b = dom.card.querySelector('h2').querySelector('.hpdk-badge'); return b ? b.textContent : null; }
function recOf(L, code) { return (L.rec() || {})[code] || {}; }

/* 夹具独立重算复合分（与生产者 :190-193 同式；zs 用总体标准差 ddof=0）—— 用来逐位核对页面排名 */
function zs(v) {
  const m = v.length, mu = v.reduce((a, b) => a + b, 0) / m;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mu) * (b - mu), 0) / m);
  return v.map((x) => (sd > 0 ? (x - mu) / sd : 0));
}
function expectedF() {
  const amt = SURV.map((i) => -Math.log(ROWS[i][2]));
  const vbr = SURV.map((i) => -Math.log(ROWS[i][3]));
  const r20 = SURV.map((i) => -ROWS[i][4]);
  const za = zs(amt), zv = zs(vbr), zr = zs(r20);
  return SURV.map((i, k) => ({ i: i, code: ROWS[i][0], F: za[k] + zv[k] + zr[k] }))
             .sort((x, y) => (y.F !== x.F ? y.F - x.F : x.i - y.i));
}
/* 操作口径：alloc = min(本金/KSLOT, amt20×1%)；股数 = floor(alloc/买入价/100)×100 */
function planOf(code, opn) {
  const amt20 = ROWS.find((r) => r[0] === code)[2];
  const slot = CAPITAL / KSLOT, capv = amt20 * 0.01, alloc = Math.min(slot, capv);
  const qty = Math.floor(alloc / opn / 100) * 100;
  return { alloc: alloc, qty: qty, limited: capv < slot - EPS, tpPx: opn * (1 + TP),
           qtyText: String(qty).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + ' 股' };
}
function line() { console.log(''); }

/* ============================ 装配：真实卡片表头（无「事件标签」列） ============================ */
line();
console.log('[0] 装配（12 只资格池 · k=10 · 表头照 hpdk_card.py）');
const env = makeEnv();
const payload = buildPayload(ROWS, 10);
const dom = buildDom(payload, false);
env.doc._byId['tbl-hpdk-cand'] = dom.tbl;
env.doc._byId['hpdk-card'] = dom.card;
const L = mount(env, payload);
ok('window.HPDK_ON_QUOTES 已挂上（与 QLCH / A5 同一挂载方式）', typeof env.sandbox.window.HPDK_ON_QUOTES === 'function');
ok('window.HPDK_LIVE 已导出（run / state / meta / judge / score）',
   !!L && typeof L.run === 'function' && typeof L.judge === 'function' && typeof L.score === 'function');
ok('首屏（无行情）不判定、不剔除、不贴标', dataCodes(dom).length === 12 && tagsAll(dom).every((t) => t.length === 0));
ok('首屏徽标 = 待行情（打开页面自动拉取）', String(badgeText(dom)).indexOf('待行情') === 0, badgeText(dom));

/* ===================== [1] 买日 10:00：判定 / 保留 / 进入前 10 ===================== */
line();
console.log('[1] 买日 10:00（gap −2.00% 在带内 · 可交易 · amt20/close 达标 → 保留且进前 10）');
const q = quotesAll();
const r10 = L.run(q, '10:00:03', 'auto', '20260928100003');
ok('闸门开（行情日 = 买日 且 时刻 ≥ 09:25）→ phase = open', r10.gate === true && r10.phase === 'open', JSON.stringify(r10));
ok('12 只入表 → 剔除 3 只 / 存活 9 只', r10.rows === 12 && r10.removed === 3 && r10.kept === 9, JSON.stringify(r10));
ok('600001 保留（仍在表格里）', !!rowEl(dom, '600001'));
const exp1 = expectedF();
const rank1 = exp1.findIndex((e) => e.code === '600001') + 1;
ok('600001 进入前 10 且在候选名单里', candCodes(dom).indexOf('600001') >= 0, candCodes(dom).join(','));
ok('600001 事件标签 = 「✅ 今日买入候选 #' + rank1 + '」', tags(dom, '600001')[0] === '✅ 今日买入候选 #' + rank1, JSON.stringify(tags(dom, '600001')));
const p1 = planOf('600001', 9.80);
ok('600001 买入价 = 9.800（实际今开 · 三位小数）', cellText(dom, '600001', '买入价') === '9.800', cellText(dom, '600001', '买入价'));
ok('600001 止盈价 = 今开×(1+tp) = ' + p1.tpPx.toFixed(3), cellText(dom, '600001', '止盈价 +2%') === p1.tpPx.toFixed(3), cellText(dom, '600001', '止盈价 +2%'));
ok('600001 建议股数 = ' + p1.qtyText + '（min(本金/KSLOT, ADV×1%) ÷ 9.800 → 整手）',
   cellText(dom, '600001', '建议股数') === p1.qtyText, cellText(dom, '600001', '建议股数'));
ok('600001 单票可买 = 足额（ADV×1% = 50 万 ≥ 单票 25 万）', cellText(dom, '600001', '单票可买（上限）') === '足额', cellText(dom, '600001', '单票可买（上限）'));
ok('现价列未被本块改写（仍归主盘中层按列头「现价」改）', cellText(dom, '600001', '现价') === '—', cellText(dom, '600001', '现价'));
ok('排序键 data-v 同步为实际今开（面板按 data-v 排序）', cell(dom, '600001', '买入价').getAttribute('data-v') === '9.8', cell(dom, '600001', '买入价').getAttribute('data-v'));

/* ============================ [2][3][4] 三条判据各自剔除 ============================ */
line();
console.log('[2] 买日 10:00：高开 +0.50%（不在 [−3%, −1%]）→ 剔除（A 不满足）');
ok('600003 已被移出表格（不是置灰）', !rowEl(dom, '600003'));
ok('600003 剔除原因 = A', String(recOf(L, '600003').gate) === 'A', JSON.stringify(recOf(L, '600003')));
ok('600003 记录 kind = drop + 首次判定时间戳', recOf(L, '600003').kind === 'drop'
   && /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(String(recOf(L, '600003').first)), JSON.stringify(recOf(L, '600003')));

line();
console.log('[3] 买日 10:00：px == pcl == opn（停牌/一字）→ 剔除（B 不满足）');
ok('600005 已被移出表格', !rowEl(dom, '600005'));
ok('600005 剔除原因 = B（可交易判据先于 A：一字板 gap = 0，不该报成「A 不在带内」）',
   String(recOf(L, '600005').gate) === 'B', JSON.stringify(recOf(L, '600005')));

line();
console.log('[4] 买日 10:00：amt20 = 1,000,000 < minamt 20,000,000 → 剔除（C 不满足）');
ok('600004 已被移出表格', !rowEl(dom, '600004'));
ok('600004 剔除原因 = C（T 日 amt20 / close 防御性复核）', String(recOf(L, '600004').gate) === 'C', JSON.stringify(recOf(L, '600004')));
ok('三只剔除都在 state.diag 里（可诊断）',
   r10.diag.length === 3 && r10.diag.map((d) => d.code).sort().join(',') === '600003,600004,600005',
   JSON.stringify(r10.diag));
ok('表格里剩下的 9 行 = 存活子集', dataCodes(dom).slice().sort().join(',') === SURV.map((i) => ROWS[i][0]).sort().join(','), dataCodes(dom).join(','));

/* ==================== [5] 集合竞价 09:20（买日）：一只都不许剔除，只允许灰标 ==================== */
line();
console.log('[5] 集合竞价 09:20（买日）：一只都不许剔除，只允许灰标「竞价预判」');
const wAuc = env.writes.length;
const rAuc = L.run(q, '09:20:00', 'auto', '20260928092000');
ok('phase = auction 且闸门关（进不了判定分支）', rAuc.phase === 'auction' && rAuc.gate === false, JSON.stringify(rAuc));
ok('removed = 0（12 行全在）', rAuc.removed === 0 && dataCodes(dom).length === 12, dataCodes(dom).join(','));
ok('本该被剔的 600003 / 600004 / 600005 也都在（一只都没少）', ['600003', '600004', '600005'].every((c) => !!rowEl(dom, c)));
ok('行序回到原始资格池序（剔除是视图态，可逆）', dataCodes(dom).join(',') === ROWS.map((r) => r[0]).join(','), dataCodes(dom).join(','));
ok('12 行各挂 1 个灰标（.hpdk-tag.pre × 12）',
   tagsAll(dom).every((t) => t.length === 1) && dom.tbody.querySelectorAll('.hpdk-tag.pre').length === 12, JSON.stringify(tagsAll(dom)[0]));
ok('灰标文案以「竞价预判」开头（竞价参考价 px/pcl−1）', tagsAll(dom).every((t) => t[0].indexOf('竞价预判') === 0), JSON.stringify(tagsAll(dom)[0]));
ok('无候选 / 无置顶分组行 / 无 hpdk-keep',
   dom.tbody.querySelectorAll('tr.hpdk-buy').length === 0 && !hdrRow(dom) && dom.tbody.querySelectorAll('tr.hpdk-keep').length === 0);
ok('单元格已还原：买入价回到构建期 badge 文本 + 两个子节点（结构没被拍平）',
   cell(dom, '600001', '买入价').children.length === 2 && cell(dom, '600001', '买入价').children[1].textContent === '9.700 ~ 9.900', 'children=' + cell(dom, '600001', '买入价').children.length);
ok('单元格已还原：建议股数 / 单票可买 回到构建期文本', cellText(dom, '600001', '建议股数') === PH_QTY && cellText(dom, '600001', '单票可买（上限）') === PH_CAP,
   cellText(dom, '600001', '建议股数') + ' / ' + cellText(dom, '600001', '单票可买（上限）'));
ok('竞价不落盘（localStorage 无新增写）', env.writes.length === wAuc, env.writes.length + ' vs ' + wAuc);
ok('徽标 = 「竞价预判中 · 09:25 后判定剔除」', String(badgeText(dom)).indexOf('竞价预判中') === 0, badgeText(dom));

/* ============ [6] 盘前 / 非买日 / 周末 / 买日之后：一律不剔除 ============ */
line();
console.log('[6] 盘前 09:05（买日）/ 非买日 as_of 当天 10:00 / 周末 / 买日之后：一律不剔除');
const wPre = env.writes.length;
const rPre = L.run(q, '09:05:00', 'auto', '20260928090500');
ok('买日盘前 09:05：phase = pre，removed = 0，12 行全在', rPre.phase === 'pre' && rPre.removed === 0 && dataCodes(dom).length === 12, JSON.stringify(rPre));
ok('买日盘前 09:05：不挂任何逐行标签（相位由卡头徽章表达；标的格保持干净）', tagsAll(dom).every((t) => t.length === 0), JSON.stringify(tagsAll(dom).slice(0, 3)));
const rAsOf = L.run(q, '10:00:00', 'auto', '20260924100000');
ok('非买日（as_of = 2026-09-24 10:00）：phase = prebuy，removed = 0，12 行全在',
   rAsOf.phase === 'prebuy' && rAsOf.removed === 0 && dataCodes(dom).length === 12, JSON.stringify(rAsOf));
ok('非买日：不挂任何逐行标签（原「非买日 · 待 X」逐行重复已删——用户反馈很蠢）', tagsAll(dom).every((t) => t.length === 0), JSON.stringify(tagsAll(dom).slice(0, 3)));
const rWeekend = L.run(q, '10:00:00', 'auto', '20260926100000');
ok('周末（2026-09-26 周六）：removed = 0，12 行全在', rWeekend.removed === 0 && dataCodes(dom).length === 12);
const rPast = L.run(q, '10:00:00', 'auto', '20260929100000');
ok('买日之后（2026-09-29 · 了结日）：phase = past，removed = 0，12 行全在',
   rPast.phase === 'past' && rPast.removed === 0 && dataCodes(dom).length === 12, JSON.stringify(rPast));
ok('四个非判定时段都没写 localStorage（零落盘：除时间戳之外不碰任何东西）', env.writes.length === wPre, env.writes.length + ' vs ' + wPre);
ok('非判定时段不贴候选 / 不置顶', dom.tbody.querySelectorAll('tr.hpdk-buy').length === 0 && !hdrRow(dom));
ok('非判定时段不误报「已剔除」（徽标 != 已剔除）', String(badgeText(dom)).indexOf('已剔除') < 0, badgeText(dom));

/* ==================== [7] 复核：F 排名（逐位比对页面顺序） ==================== */
line();
console.log('[7] 复核：存活子集内 F = z(−ln amt20) + z(−ln volbr) + z(−ret20)，逐位比对页面顺序');
const exp = expectedF();
const r7 = L.run(q, '10:00:10', 'auto', '20260928100010');
const got = candCodes(dom);
ok('再次判定：12 入表 / 剔 3 / 存活 9', r7.removed === 3 && r7.kept === 9 && dataCodes(dom).length === 9, JSON.stringify(r7));
ok('候选数 = min(k=10, 存活 9) = 9', got.length === 9 && r7.hit === 9, got.length + ' / hit=' + r7.hit);
for (let i = 0; i < exp.length; i++) {
  ok('逐位：第 ' + (i + 1) + ' 名 = ' + exp[i].code + '（独立重算 F = ' + exp[i].F.toFixed(4) + '）',
     got[i] === exp[i].code, '页面实际 = ' + got[i]);
}
ok('存活子集里 F 最高的 ' + exp[0].code + ' = 页面第一候选', got[0] === exp[0].code, got[0]);
const pageF = Number(String(cell(dom, exp[0].code, '买入价').title).match(/F = (-?[0-9.]+)/)[1]);
ok('页面 #1 的 F 值 = 独立重算的最大值 ' + exp[0].F.toFixed(3), Math.abs(pageF - exp[0].F) < 0.0005, pageF);
ok('#1 行事件标签 = 「✅ 今日买入候选 #1」', tags(dom, exp[0].code)[0] === '✅ 今日买入候选 #1', JSON.stringify(tags(dom, exp[0].code)));
ok('置顶分组行在表首且 colspan = 运行时列数 14',
   !!hdrRow(dom) && dom.tbody.children[0].classes.has('hpdk-buy-hdr') && hdrRow(dom).innerHTML.indexOf('colspan="14"') > 0,
   hdrRow(dom) ? hdrRow(dom).innerHTML : 'no-hdr');
ok('分组行文案含「已剔除 3 只」与「置顶=视图态」',
   hdrRow(dom).innerHTML.indexOf('已剔除 3 只') > 0 && hdrRow(dom).innerHTML.indexOf('置顶=视图态') > 0);
ok('徽标 = 「已剔除 3 只 · 命中 9 只」', badgeText(dom) === '已剔除 3 只 · 命中 9 只', badgeText(dom));
ok('徽标类名自造（.hpdk-badge，不抢 .badge-live）', !!dom.h2.querySelector('.hpdk-badge') && !dom.h2.querySelector('.badge-live'));
L.run(q, '10:00:20', 'auto', '20260928100020');
ok('幂等：分组行仍 1 个 / 候选行仍 9 个 / 行序不变',
   dom.tbody.querySelectorAll('tr.hpdk-buy-hdr').length === 1 && dom.tbody.querySelectorAll('tr.hpdk-buy').length === 9
   && candCodes(dom).join(',') === got.join(','), candCodes(dom).join(','));
ok('幂等：每个候选行恰好 1 个行内 .hpdk-tag.buy（不叠加）',
   dom.tbody.querySelectorAll('tr.hpdk-buy').every((tr) => tr.querySelectorAll('.hpdk-tag.buy').length === 1));
ok('容量边界 600012（ADV×1% = 25 万 == 单票分配）→ 足额', exp.some((e) => e.code === '600012') && cellText(dom, '600012', '单票可买（上限）') === '足额', cellText(dom, '600012', '单票可买（上限）'));
ok('容量受限 600008（ADV×1% = 22 万 < 25 万）→ 「限至 22.0万」（**不是不能买**，只是买不满）', String(cellText(dom, '600008', '单票可买（上限）')).indexOf('限至') === 0, cellText(dom, '600008', '单票可买（上限）'));
ok('600008 股数按 ADV×1% 折算 = ' + planOf('600008', 9.80).qtyText, cellText(dom, '600008', '建议股数') === planOf('600008', 9.80).qtyText, cellText(dom, '600008', '建议股数'));

/* ============ [8] 变体：k=2（截断）+ 表头多一列「事件标签」 ============ */
line();
console.log('[8] 变体：k=2（前 2 名之外只能「留存」）+ 表头多一列「状态」');
const env2 = makeEnv();
const payload2 = buildPayload(ROWS, 2);
const dom2 = buildDom(payload2, true);
env2.doc._byId['tbl-hpdk-cand'] = dom2.tbl;
env2.doc._byId['hpdk-card'] = dom2.card;
const L2 = mount(env2, payload2);
const r2 = L2.run(quotesAll(), '10:00:03', 'auto', '20260928100003');
ok('k=2：剔 3 / 存活 9 / 命中 2', r2.removed === 3 && r2.kept === 9 && r2.hit === 2, JSON.stringify(r2));
ok('k=2：候选顺序 = F 前 2（' + exp.slice(0, 2).map((e) => e.code).join(',') + '）',
   candCodes(dom2).join(',') === exp.slice(0, 2).map((e) => e.code).join(','), candCodes(dom2).join(','));
ok('k=2：标记写进「状态」列（有该列时用单元格文本，不退化行内标签）',
   cellText(dom2, exp[0].code, '状态') === '✅ 今日买入候选 #1' && cellText(dom2, exp[1].code, '状态') === '✅ 今日买入候选 #2',
   JSON.stringify([cellText(dom2, exp[0].code, '状态'), cellText(dom2, exp[1].code, '状态')]));
ok('k=2：候选行不再挂行内 .hpdk-tag.buy',
   dom2.tbody.querySelectorAll('tr.hpdk-buy').every((tr) => tr.querySelectorAll('.hpdk-tag.buy').length === 0));
ok('k=2：第 3 名起的 7 只存活者挂「留存 · F 第 n 位」且不置顶',
   dom2.tbody.querySelectorAll('tr.hpdk-keep').length === 7 && cellText(dom2, exp[2].code, '状态') === '留存 · F 第 3 位',
   'keep=' + dom2.tbody.querySelectorAll('tr.hpdk-keep').length + ' / ' + JSON.stringify(tags(dom2, exp[2].code)));
ok('k=2：徽标计数 = 「已剔除 3 只 · 命中 2 只」', badgeText(dom2) === '已剔除 3 只 · 命中 2 只', badgeText(dom2));
ok('k=2：分组行 colspan = 15（运行时列数，非写死）', hdrRow(dom2).innerHTML.indexOf('colspan="15"') > 0, hdrRow(dom2).innerHTML);
ok('k=2：买入价/止盈价/股数/容量 同样按实际今开写入',
   cellText(dom2, exp[0].code, '买入价') === '9.800' && cellText(dom2, exp[0].code, '止盈价 +2%') === planOf(exp[0].code, 9.80).tpPx.toFixed(3));

/* ============ [9] 无行情（首屏 / 断网）：一律不剔除、不贴标 ============ */
line();
console.log('[9] 无行情 / 空报价：一律不剔除、不贴标（不判不剔）');
const rNoQ = L.run({}, '', '', '');
ok('空报价对象：removed = 0，12 行全在，无任何标签',
   rNoQ.removed === 0 && dataCodes(dom).length === 12 && tagsAll(dom).every((t) => t.length === 0), JSON.stringify(rNoQ));
const rNull = L.run(null, '', '', '');
ok('null 报价：不抛错、removed = 0、12 行全在', rNull && rNull.removed === 0 && dataCodes(dom).length === 12);

/* ============ [10] 无 payload（window.HPDK 缺失）：完全不动页面 ============ */
line();
console.log('[10] 无 payload（window.HPDK 缺失）：IIFE 直接 return，页面零改动');
const env3 = makeEnv();
const dom3 = buildDom(payload, false);
env3.doc._byId['tbl-hpdk-cand'] = dom3.tbl;
env3.doc._byId['hpdk-card'] = dom3.card;
const L3 = mount(env3);
ok('未导出 HPDK_LIVE / HPDK_ON_QUOTES', L3 === undefined && env3.sandbox.window.HPDK_ON_QUOTES === undefined);
ok('页面零改动（12 行 / 无标签 / 无徽标 / 无 localStorage 写）',
   dataCodes(dom3).length === 12 && tagsAll(dom3).every((t) => t.length === 0) && !badgeText(dom3) && env3.writes.length === 0);

/* ================================ 汇总 ================================ */
line();
console.log((bad === 0 ? 'HPDK_JUDGE_FIXTURE_OK' : 'HPDK_JUDGE_FIXTURE_FAIL') + ' n=' + n + (bad ? ' bad=' + bad : ''));
process.exit(bad === 0 ? 0 : 1);
