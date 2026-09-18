# -*- coding: utf-8 -*-
"""盘中实时数据层（R-live-0918 · 用户需求 #4b 热力树图盘中实时 + 选股池涨跌幅盘中更新）。

为什么这样做（三个设计决定，都有实测依据）：
  1. **纯浏览器端，不做定时部署**：静态页面打开后由浏览器直连行情源。
     实测（2026-09-18 晚，真实 Chrome，file:// 与 https://hawchou1995.github.io 双 Origin）：
       · 东财 push2delay `ulist.np`：`Access-Control-Allow-Origin: *`，800 码单请求 26ms
       · 东财 push2delay `clist`：单页硬上限 100 行 → 全市场 5560 只 56 次请求、共 1.1 秒
       · 腾讯 `qt.gtimg.cn`：ACAO `*`、对 Referer 无要求；浏览器端 500 码/请求可用（900 码被拒）
     → 不需要本机常开、不需要盘中定时重建/部署（原 update_intraday_dashboard.py 路线每次
       刷新一个 gh-pages 提交）。代价：只有打开页面时才有实时数据（这正是"盘中实时"的语义）。
  2. **只补价格类字段**：现价/收盘、涨跌幅（当日涨跌/涨幅）。评分、档位、RSI、近一年、
     MACD、KDJ 是日线派生（上一交易日收盘口径），盘中无法重算 —— 一律不碰，
     页面上以「盘中」小标签 + 卡片徽章区分口径。
  3. **双重校验防串码**：行代码（`data-code` 优先，其次行内首个 6 位数字）+ 行情返回的
     名称前缀比对；不一致跳过。防的是场外基金代码（如 004026）被同号 A 股顶替 —— 实测
     short_pool 基金池行带 `data-market="基金"`，直接跳过；其余靠名称比对兜底。

  实测记录见 `backtest/报告-盘中实时数据层-20260918.md`。
"""

INTRADAY_JS = r"""
/* ============ 盘中实时（R-live-0918）：价格/涨跌幅 overlay + 树图全市场快照 ============ */
(function(){
  'use strict';
  var CFG = {
    POOL_MS: 60000,        /* 选股池刷新周期 */
    TREE_MS: 180000,       /* 热力树图刷新周期 */
    IDLE_MS: 900000,       /* 非交易时段退避 */
    PROBE_MS: 60000,       /* 行情通道探测周期 */
    HOSTS: ['push2delay.eastmoney.com', 'push2.eastmoney.com', '82.push2.eastmoney.com'],
    EM_CHUNK: 800, TX_CHUNK: 400,
    PX_HDR: ['现价', '收盘', '最新价'],
    PCT_HDR: ['涨跌幅', '当日涨跌', '涨幅', '涨跌'],
    KEY_PX: ['px', 'price', 'close', 'last'],
    KEY_PCT: ['chg', 'pct'],
    LS: 'quant_live_v1',
    TIP: '盘中实时（价格/涨跌幅）；评分/档位/RSI/近一年/MACD/KDJ 仍为上一交易日收盘口径'
  };
  var S = { on: null, quotes: {}, name: {}, ts: '', live: false, mktTs: '', idx: null,
            lastPool: 0, lastTree: 0, lastProbe: 0, busy: false, patched: 0, miss: 0, err: '' };

  function lsGet(k){ try{ return localStorage.getItem(k); }catch(e){ return null; } }
  function lsSet(k, v){ try{ localStorage.setItem(k, v); }catch(e){} }
  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function hhmmss(d){ return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }
  function num(v){ var x = (v === null || v === undefined) ? NaN : parseFloat(v); return isNaN(x) ? NaN : x; }
  function fmtPct(p){ return (p > 0 ? '+' : '') + Number(p).toFixed(2) + '%'; }
  function fmtPx(p){ return Number(p).toFixed(2); }
  function colorOf(p){ return p > 0 ? 'var(--up)' : (p < 0 ? 'var(--down)' : 'var(--sub)'); }
  function mktCode(c){ return (c[0] === '6' || c[0] === '5' || c[0] === '9') ? '1.' + c : '0.' + c; }
  function txCode(c){ return (c[0] === '6' || c[0] === '5' || c[0] === '9') ? 'sh' + c : 'sz' + c; }
  function bump(){ try{ if(location.protocol !== 'file:'){ } }catch(e){} }

  /* ---------- 样式（运行时注入，避免改构建期模板） ---------- */
  function css(){
    if (document.getElementById('live-css')) return;
    var st = document.createElement('style'); st.id = 'live-css';
    st.textContent = [
      '#live-pill{position:fixed;left:18px;bottom:18px;z-index:940;display:flex;align-items:center;gap:7px;',
      'background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:6px 10px;',
      'font-size:12px;color:var(--sub);box-shadow:0 2px 10px rgba(0,0,0,.10);cursor:pointer;user-select:none;white-space:nowrap}',
      '#live-pill:hover{border-color:var(--accent)}',
      '#live-pill .dot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:none}',
      '#live-pill.on .dot{background:var(--accent)}',
      '#live-pill.on.live .dot{animation:livePulse 2s infinite}',
      '#live-pill b{color:var(--text);font-weight:600}',
      '#live-pill .sp{color:var(--faint)}',
      '.live-th{margin-left:4px;font-size:10px;font-weight:500;color:#b45309;border:1px solid rgba(245,158,11,.35);',
      'background:rgba(245,158,11,.10);border-radius:3px;padding:0 3px;vertical-align:1px}',
      'td.live-cell{box-shadow:inset 0 -2px 0 rgba(245,158,11,.45)}',
      '@keyframes livePulse{0%,100%{opacity:1}50%{opacity:.3}}'
    ].join('');
    document.head.appendChild(st);
  }

  /* ---------- 顶部小药丸（总开关 + 状态） ---------- */
  function pill(){
    var p = document.getElementById('live-pill');
    if (!p) { p = document.createElement('div'); p.id = 'live-pill'; p.title = CFG.TIP; document.body.appendChild(p); }
    var cls = 'live-pill';
    p.className = (S.on === false ? '' : 'on') + (S.live ? ' live' : '');
    var parts = [];
    parts.push('<span class="dot"></span><b>实时' + (S.on === false ? '：关' : '：开') + '</b>');
    if (S.on === false) parts.push('<span class="sp">点击开启</span>');
    else if (S.idx) {
      parts.push('<span>' + S.idx.idxName + ' ' + (S.idx.idxPct > 0 ? '+' : '') + S.idx.idxPct.toFixed(2) + '%</span>');
      var t = S.mktTs || '';
      var stamp = t ? (t.slice(4, 6) + '-' + t.slice(6, 8) + ' ' + t.slice(8, 10) + ':' + t.slice(10, 12)) : (S.ts || '—');
      parts.push('<span class="sp">' + (S.live ? '盘中 ' + (S.ts || '') : '非交易时段 · 数据 ' + stamp) + '</span>');
    } else parts.push('<span class="sp">' + (S.err ? '通道不可用' : '待刷新') + '</span>');
    p.innerHTML = parts.join('');
    p.onclick = function(){ setOn(S.on === false); };
  }

  /* ---------- 通道 ---------- */
  function getText(url, ms){
    return new Promise(function(res, rej){
      var ac = new AbortController(), t = setTimeout(function(){ ac.abort(); }, ms || 9000);
      fetch(url, {signal: ac.signal, cache: 'no-store', credentials: 'omit'}).then(function(r){
        clearTimeout(t);
        if (!r.ok) { rej(new Error('HTTP ' + r.status)); return; }
        r.arrayBuffer().then(function(b){ res(b); }, rej);
      }, function(e){ clearTimeout(t); rej(e); });
    });
  }
  function getJSON(url, ms){ return getText(url, ms).then(function(b){ return JSON.parse(new TextDecoder('utf-8').decode(b)); }); }
  function getGBK(url, ms){ return getText(url, ms).then(function(b){ return new TextDecoder('gbk').decode(b); }); }

  /* ---------- 探测：指数 + 行情源时间戳（判断是否盘中） ---------- */
  function probe(){
    var u = 'https://qt.gtimg.cn/q=sh000001,sh000300';
    return getGBK(u, 6000).then(function(txt){
      var rows = txt.trim().split('\n').map(function(l){ var f = l.split('~'); return {code: f[2], px: num(f[3]), pct: num(f[32]), ts: f[30] || ''}; });
      var sh = rows[0] || {}, hs = rows[1] || {};
      S.idx = {idxName: '上证', idxPct: sh.pct, hs300Pct: hs.pct};
      S.mktTs = sh.ts;                                   /* 形如 20260918161436 */
      var today = '' + new Date().getFullYear() + pad(new Date().getMonth() + 1) + pad(new Date().getDate());
      var hhmm = S.mktTs.slice(8, 12);
      S.live = S.mktTs.slice(0, 8) === today && hhmm >= '0915' && hhmm <= '1505';
      S.ts = S.live ? hhmmss(new Date()) : (S.mktTs.slice(8, 10) + ':' + S.mktTs.slice(10, 12));
      S.lastProbe = Date.now(); S.err = '';
      pill();
      return true;
    }, function(e){ S.err = 'probe:' + (e && e.message || e); pill(); return false; });
  }

  /* ---------- 选股池报价 ---------- */
  function fetchPool(codes){
    var out = {}, i = 0;
    function step(){
      if (i >= codes.length) return Promise.resolve(out);
      var chunk = codes.slice(i, i + CFG.EM_CHUNK); i += CFG.EM_CHUNK;
      var host = CFG.HOSTS[0];
      var u = 'https://' + host + '/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f12,f14&secids='
            + chunk.map(mktCode).join(',') + '&_=' + Date.now();
      return getJSON(u, 12000).then(function(j){
        ((j.data && j.data.diff) || []).forEach(function(x){
          var px = num(x.f2), pc = num(x.f3);
          if (!isNaN(px)) out[x.f12] = {px: px, pct: isNaN(pc) ? 0 : pc, name: x.f14 || ''};
        });
        return step();
      }, function(){ /* 本片失败：腾讯兜底 */
        var u2 = 'https://qt.gtimg.cn/q=' + chunk.map(txCode).join(',');
        return getGBK(u2, 12000).then(function(txt){
          txt.trim().split('\n').forEach(function(l){
            var f = l.split('~'); if (f.length < 33) return;
            var px = num(f[3]), pc = num(f[32]);
            if (f[2] && !isNaN(px)) out[f[2]] = {px: px, pct: isNaN(pc) ? 0 : pc, name: f[1] || ''};
          });
          return step();
        }, function(){ return step(); });
      });
    }
    return step();
  }

  /* ---------- DOM：找可更新的单元格 ---------- */
  /* 单一扫描出口：targets=可刷单元格；tables=逐表诊断信息（供覆盖率/排错脚本读取，
     避免诊断脚本自己复制一份判据 —— 那是本会话踩过两次的坑） */
  function scan(){
    var out = [], info = [], tbs = document.querySelectorAll('table.tbl');
    for (var i = 0; i < tbs.length; i++) {
      var tb = tbs[i], ths = tb.querySelectorAll('thead th');
      if (!ths.length) continue;
      var tid = tb.id || tb.getAttribute('data-t') || '(无id)';
      var nRows = tb.querySelectorAll('tbody tr').length;
      var pxI = -1, pcI = -1;
      for (var j = 0; j < ths.length; j++) {
        var th = ths[j], k = (th.getAttribute('data-key') || '').toLowerCase();
        var tx = (th.textContent || '').replace(/实时|盘中/g, '').trim();
        if (pxI < 0 && (CFG.KEY_PX.indexOf(k) >= 0 || CFG.PX_HDR.indexOf(tx) >= 0)) pxI = j;
        if (pcI < 0 && (CFG.KEY_PCT.indexOf(k) >= 0 || CFG.PCT_HDR.indexOf(tx) >= 0)) pcI = j;
      }
      if (pxI < 0 && pcI < 0) { info.push({id: tid, rows: nRows, elig: 0, live: 0, skip: '无价格/涨跌列'}); continue; }
      /* 组合估值表：行内有由价格派生的 浮盈/盈亏/市值/净值 列 → 只把价格换实时会让同一行自相矛盾，整表跳过。
         注意「权重」要限定条件：权重总分 / 权重分 是评分（不是持仓权重），短线选股池正是这种 —— 
         故仅在「无涨跌幅列」时才把 权重 视为估值列（模拟盘持仓表就是这种）。 */
      var hdrAll = '';
      for (var z = 0; z < ths.length; z++) hdrAll += (ths[z].textContent || '');
      if (/浮盈|盈亏|市值|净值/.test(hdrAll)) {
        info.push({id: tid, rows: nRows, elig: 0, live: 0, skip: '估值表(浮盈/盈亏/市值/净值)'}); continue;
      }
      if (pcI < 0 && /权重/.test(hdrAll)) {
        info.push({id: tid, rows: nRows, elig: 0, live: 0, skip: '估值表(权重列且无涨跌幅列)'}); continue;
      }
      var trs = tb.querySelectorAll('tbody tr');
      var nElig = 0;
      for (var r = 0; r < trs.length; r++) {
        var tr = trs[r];
        if (tr.getAttribute('data-market') === '基金') continue;      /* 场外基金：净值 T-1，无盘中 */
        var code = (tr.getAttribute('data-code') || '').replace(/^(sh|sz|bj)/i, '');
        if (!/^\d{6}$/.test(code)) code = (tr.textContent.match(/(?:^|\D)(\d{6})(?:\D|$)/) || [])[1] || '';
        if (!/^\d{6}$/.test(code)) continue;
        var tds = tr.children;
        if (!tds.length) continue;
        /* 名称：优先 data-search 首词；否则取「去掉 6 位代码后仍非空」的第一个单元格
           （卫星表第 0 列是代码列 → 必须跳到第 1 列的名称列，否则守卫拿到空名而失效） */
        var name = '';
        var ds = tr.getAttribute('data-search') || '';
        if (ds) name = ds.replace(/\d{6}[\s\S]*$/, '').replace(/[\s　]+/g, '') || ds.trim().split(/\s+/)[0];
        if (!name) {
          /* 名称候选必须含 ≥2 个中文/字母（kh-hits 表首列是序号「6」，当名称用会让守卫误拦） */
          for (var q = 0; q < tds.length && q < 4; q++) {
            var t2 = (tds[q].textContent || '').replace(/\d{6}/g, '').replace(/\s+/g, '');
            var mm = t2.match(/[一-龥A-Za-z]{2,}/);
            if (mm) { name = mm[0]; break; }
          }
        }
        out.push({tr: tr, tb: tb, code: code, name: name,
                  px: pxI >= 0 && tds[pxI] ? tds[pxI] : null,
                  pct: pcI >= 0 && tds[pcI] ? tds[pcI] : null});
        nElig++;
      }
      info.push({id: tid, rows: nRows, elig: nElig, live: tb.querySelectorAll('td.live-cell').length, skip: nElig ? '' : '行内无代码'});
    }
    return {targets: out, tables: info};
  }
  function targets(){ return scan().targets; }

  function setPx(td, v, ts){
    if (!td) return;
    var sp = td.querySelector('span');
    var txt = fmtPx(v);
    if (sp && sp.style && sp.style.color) sp.textContent = txt; else td.textContent = txt;
    td.title = CFG.TIP + '（更新 ' + ts + '）';
    if (!td.classList.contains('live-cell')) td.classList.add('live-cell');
  }
  function setPct(td, v, ts){
    if (!td) return;
    var sp = td.querySelector('span'), txt = fmtPct(v), col = colorOf(v);
    if (sp && sp.style && sp.style.color) { sp.textContent = txt; sp.style.color = col; }
    else td.textContent = txt;
    if (td.classList.contains('up') || td.classList.contains('down')) {
      td.classList.toggle('up', v > 0); td.classList.toggle('down', v < 0);
      if (!v) { td.classList.remove('up'); td.classList.remove('down'); }
    }
    if (td.hasAttribute('data-v')) td.setAttribute('data-v', v.toFixed(2));   /* 排序键同步 */
    td.title = CFG.TIP + '（更新 ' + ts + '）';
    if (!td.classList.contains('live-cell')) td.classList.add('live-cell');
  }

  /* 卡片徽章 + 表头「盘中」标签（每张卡只加一次） */
  function markCard(tb, ts){
    var card = tb.closest ? tb.closest('.card') : null;
    if (card) {
      var h2 = card.querySelector('h2'), bd = card.querySelector('.badge-live');
      if (h2) {
        if (!bd) { bd = document.createElement('span'); bd.className = 'badge badge-live'; h2.appendChild(bd); }
        bd.textContent = '实时 ' + ts;
        bd.title = CFG.TIP;
      }
    }
    var ths = tb.querySelectorAll('thead th');
    for (var j = 0; j < ths.length; j++) {
      var th = ths[j], k = (th.getAttribute('data-key') || '').toLowerCase();
      var tx = (th.textContent || '').replace(/实时|盘中/g, '').trim();
      if (CFG.KEY_PX.indexOf(k) >= 0 || CFG.PX_HDR.indexOf(tx) >= 0 ||
          CFG.KEY_PCT.indexOf(k) >= 0 || CFG.PCT_HDR.indexOf(tx) >= 0) {
        if (!th.querySelector('.live-th')) {
          var s2 = document.createElement('span'); s2.className = 'live-th'; s2.textContent = '实时'; s2.title = CFG.TIP;
          th.appendChild(s2);
        }
      }
    }
  }

  /* ---------- 应用报价（可外部调用：验证用） ---------- */
  function applyQuotes(q, ts, opt){
    opt = opt || {};
    ts = ts || hhmmss(new Date());
    var tgs = targets(), hit = 0, miss = 0, cards = {};
    for (var i = 0; i < tgs.length; i++) {
      var t = tgs[i], d = q[t.code];
      if (!d) { miss++; continue; }
      /* 名称校验：行情名与页面名前 2 字不一致 → 跳过（防串码） */
      if (!opt.skipGuard && t.name && d.name) {
        /* 归一：去空白 + 去交易前缀（除权 XD/XR/DR、新股 N/C、ST 族）——否则「XD新化股」会被误判为不同标的 */
        var norm = function(x){
          return String(x).replace(/[\s　]+/g, '')
                         .replace(/^(S\*ST|\*ST|SST|ST|XD|XR|DR|N|C|S)/i, '');
        };
        var a = norm(t.name).slice(0, 2), b = norm(d.name).slice(0, 2);
        if (a && b && a !== b) { miss++; continue; }
      }
      if (t.px && !isNaN(d.px)) setPx(t.px, d.px, ts);
      if (t.pct && !isNaN(d.pct)) setPct(t.pct, d.pct, ts);
      hit++; cards[t.tb.getAttribute('data-t') || i] = t.tb;
    }
    for (var k in cards) markCard(cards[k], ts);   /* cards 只收「有成功改写」的表 */
    S.patched = hit; S.miss = miss;
    return {patched: hit, skipped: miss, total: tgs.length};
  }

  /* ---------- 全市场快照 → 树图 ---------- */
  function fetchMarket(){
    var FS = 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23';
    var rows = [], conc = 5, pn = 1, done = false;
    function one(p){
      var u = 'https://' + CFG.HOSTS[0] + '/api/qt/clist/get?pn=' + p + '&pz=100&po=1&np=1'
            + '&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=' + encodeURIComponent(FS)
            + '&fields=f3,f6,f12,f14,f20,f21&_=' + Date.now();
      return getJSON(u, 12000).then(function(j){
        var d = (j.data && j.data.diff) || [];
        if (!d.length) { done = true; return; }
        d.forEach(function(x){
          var p = num(x.f3), a = num(x.f6), m = num(x.f20), f = num(x.f21);
          if (!x.f12) return;
          rows.push({c: x.f12, n: x.f14 || '', p: isNaN(p) ? 0 : p,
                     a: isNaN(a) ? 0 : a / 1e8, m: isNaN(m) ? 0 : m / 1e8, f: isNaN(f) ? 0 : f / 1e8});
        });
      }, function(){ done = true; });
    }
    function pump(){
      if (done) return Promise.resolve();
      var batch = [];
      for (var i = 0; i < conc; i++) batch.push(one(pn++));
      return Promise.all(batch).then(function(){ return pump(); });
    }
    return pump().then(function(){
      if (!rows.length) return 0;
      var ts = hhmmss(new Date());
      var hit = 0;
      if (typeof window.HM_APPLY === 'function') hit = window.HM_APPLY(rows, ts) || 0;
      var note = document.getElementById('hm-live');
      if (!note) {
        var bar = document.querySelector('#hm-card .hm-bar') || document.querySelector('#hm-card h2');
        if (bar) { note = document.createElement('span'); note.id = 'hm-live'; note.className = 'hm-hint'; bar.appendChild(note); }
      }
      if (note) {
        note.textContent = (S.live ? '盘中实时' : '实时快照（非交易时段）') +
                           ' · 更新于 ' + ts + '（全市场 ' + rows.length + ' 只）';
        note.title = CFG.TIP;
        note.style.color = '#b45309';
      }
      S.lastTree = Date.now();
      return hit;
    });
  }

  /* ---------- 刷新与调度 ---------- */
  function refresh(force){
    if (S.busy) return Promise.resolve(false);
    S.busy = true;
    var jobs = [];
    var needProbe = force || (Date.now() - S.lastProbe > CFG.PROBE_MS);
    if (needProbe) jobs.push(probe());
    return Promise.all(jobs).then(function(){
      var tgs = targets();
      var codes = [], seen = {};
      for (var i = 0; i < tgs.length; i++) { if (!seen[tgs[i].code]) { seen[tgs[i].code] = 1; codes.push(tgs[i].code); } }
      var p = codes.length ? fetchPool(codes).then(function(q){
        var r = applyQuotes(q, hhmmss(new Date()));
        S.lastPool = Date.now();
        return r;
      }) : Promise.resolve(null);
      var needTree = !!document.getElementById('hm-chart') &&
                     (force || (kxmmActive() && (Date.now() - S.lastTree > CFG.TREE_MS)));
      var t = needTree ? fetchMarket() : Promise.resolve(null);
      return Promise.all([p, t]);
    }).then(function(rs){
      S.busy = false; pill();
      return {pool: rs[0], tree: rs[1], live: S.live, ts: S.ts};
    }, function(e){ S.busy = false; S.err = String(e && e.message || e); pill(); return {err: S.err}; });
  }

  function kxmmActive(){
    var v = document.getElementById('view-kxmm');
    return !!(v && v.classList.contains('active'));
  }
  function due(){
    if (S.on === false || S.busy) return false;
    if (document.visibilityState === 'hidden') return false;
    var idle = !S.live ? CFG.IDLE_MS : CFG.POOL_MS;
    return (Date.now() - S.lastPool) > idle;
  }
  function tick(){ if (due()) refresh(false); }
  function setOn(v){
    S.on = !!v; lsSet(CFG.LS, v ? '1' : '0'); pill();
    if (v) refresh(true); else { S.live = false; }
  }

  /* ---------- 启动 ---------- */
  css();
  var saved = lsGet(CFG.LS);
  S.on = (saved === null) ? true : (saved === '1');
  pill();
  setTimeout(function(){ if (S.on) refresh(true); }, 900);
  setInterval(tick, 5000);
  document.addEventListener('visibilitychange', function(){
    if (document.visibilityState === 'visible' && S.on && (Date.now() - S.lastPool) > 30000) refresh(false);
  });
  /* 切到「市场晴雨」时若树图数据已过期则补刷（树图只在可见页刷新，省 56 次请求） */
  document.querySelectorAll('.sidenav a[data-anchor]').forEach(function(a){
    a.addEventListener('click', function(){
      setTimeout(function(){
        if (!S.on) return;
        if (kxmmActive() && Date.now() - S.lastTree > 60000) refresh(true);
        else refresh(false);
      }, 600);
    });
  });
  window.INTRADAY = {refresh: refresh, applyQuotes: applyQuotes, targets: targets, state: S,
                     __scan: scan, __fetchPool: fetchPool,
                     setOn: setOn, cfg: CFG};
})();
"""
