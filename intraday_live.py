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
    /* R-qlch-live-0923：必须参与 px/pct 刷新的表白名单（其行代码来自构建期内嵌 candidates）。
       qlch 候选表的「市值分位」曾命中整表估值守卫 → 整表跳过；收窄守卫 + 白名单双保险。 */
    WL_TBL: {'tbl-qlch-cand': 1},
    TIP: '盘中实时（价格/涨跌幅）；评分/档位/RSI/近一年/MACD/KDJ 仍为上一交易日收盘口径'
  };
  var S = { on: null, quotes: {}, name: {}, ts: '', live: false, mktTs: '', idx: null,
            lastPool: 0, lastTree: 0, lastProbe: 0, busy: false, patched: 0, miss: 0, err: '',
            txBatches: 0, txFail: 0, treeSrc: '' };

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
      'font-size:var(--fs-sm);color:var(--sub);box-shadow:var(--shadow-float);cursor:pointer;user-select:none;white-space:nowrap}',
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
    var out = {}, i = 0, srcEm = 0, srcTx = 0;
    function step(){
      if (i >= codes.length) {
        /* R-qlch-live-0923：登记本批报价的来源（东财主源 / 腾讯兜底）—— qlch 徽标要显示「源 东财/腾讯」，
           不靠猜。任一片走兜底即如实标注（东财|腾讯）。 */
        S.poolSrc = srcTx ? (srcEm ? '东财|腾讯' : '腾讯') : (srcEm ? '东财' : '');
        return Promise.resolve(out);
      }
      var chunk = codes.slice(i, i + CFG.EM_CHUNK); i += CFG.EM_CHUNK;
      var host = CFG.HOSTS[0];
      /* R-qlch-live-0923：fields 增 f17（今开）/f18（昨收）—— qlch 买点判定要 gap = 今开/昨收−1，
         原 fields 只有 f2 现价 / f3 涨跌幅，跳空判不了。pcl=昨收、opn=今开（下游 QLCH_LIVE 消费）。 */
      var u = 'https://' + host + '/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f12,f14,f17,f18&secids='
            + chunk.map(mktCode).join(',') + '&_=' + Date.now();
      return getJSON(u, 12000).then(function(j){
        srcEm++;
        ((j.data && j.data.diff) || []).forEach(function(x){
          var px = num(x.f2), pct = num(x.f3);
          if (!isNaN(px)) out[x.f12] = {px: px, pct: isNaN(pct) ? 0 : pct, name: x.f14 || '',
                                        pcl: num(x.f18), opn: num(x.f17)};
        });
        return step();
      }, function(){ /* 本片失败：腾讯兜底 */
        srcTx++;
        var u2 = 'https://qt.gtimg.cn/q=' + chunk.map(txCode).join(',');
        return getGBK(u2, 12000).then(function(txt){
          txt.trim().split('\n').forEach(function(l){
            var f = l.split('~'); if (f.length < 33) return;
            var px = num(f[3]), pct = num(f[32]);
            if (f[2] && !isNaN(px)) out[f[2]] = {px: px, pct: isNaN(pct) ? 0 : pct, name: f[1] || '',
                                                 pcl: num(f[4]), opn: num(f[5])};
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
         故仅在「无涨跌幅列」时才把 权重 视为估值列（模拟盘持仓表就是这种）。
         R-qlch-live-0923 收窄：原实现把**整表表头文本拼成一个串**再判 /浮盈|盈亏|市值|净值/ ——
         qlch 候选表的「市值分位」被误命中 → 候选表**整表跳过**、涨跌幅永不刷新
         （实测：产物 93 张表里唯一被误伤的就是它）。改为**逐列**判定：
         仅当某列列名整名等于 浮盈/盈亏/市值/净值，或含 浮盈/盈亏/净值 时才跳过。 */
      var hdrAll = '', estCol = '';
      for (var z = 0; z < ths.length; z++) {
        var hz = (ths[z].textContent || '').replace(/\s+/g, '');
        hdrAll += hz;
        if (!estCol && (/^(浮盈|盈亏|市值|净值)$/.test(hz) || /浮盈|盈亏|净值/.test(hz))) estCol = hz;
      }
      /* 白名单表（qlch 候选表）：行代码来自构建期内嵌 candidates，不靠单元格猜 → 即便命中也照刷 */
      if (estCol && !CFG.WL_TBL[tb.id]) {
        info.push({id: tid, rows: nRows, elig: 0, live: 0, skip: '估值表(' + estCol + ')'}); continue;
      }
      if (pcI < 0 && /权重/.test(hdrAll) && !CFG.WL_TBL[tb.id]) {
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
  /* R-treelive-0922：原实现只走东财 clist（全市场 56 请求）。2026-09-22 实测该端点在本机被
     **端点级拦截**（TLS 重协商后连接重置；三主机、任意 fs 皆然，而同主机 ulist 正常）
     → 树图刷新静默返回 0 行（注记与树图都不更新）。
     改法：代码表取自构建期已内嵌的 window.HEATMAP（全市场 5210 只）→ **腾讯 q= 分批
     （800 码/请求 = 7 个请求）为主**，东财 clist 保留兜底。实测腾讯上限：800 码 OK，1200 → HTTP 414。
     收益：① 单一源被封不再静默死 ② 请求数 56 → 7，且优先不占东财配额
     （与用户约束「不影响收盘全量池拉取」一致 —— 收盘链靠的正是东财）。 */
  function marketCodes(){
    var H = window.HEATMAP;
    var tree = (H && (H.tree || (H.data && H.data.tree))) || [];
    var out = [], seen = {};
    for (var i = 0; i < tree.length; i++) {
      var ch = (tree[i] && tree[i].children) || [];
      for (var j = 0; j < ch.length; j++) {
        var c = ch[j] && ch[j].c;
        if (c && !seen[c]) { seen[c] = 1; out.push(c); }
      }
    }
    return out;
  }
  function txRow(f, rows){
    /* 腾讯 q= 字段：[1]名称 [2]代码 [3]现价 [4]昨收 [5]今开 [32]涨跌幅% [37]成交额(万元)
       [44]总市值(亿) [45]流通市值(亿)
       ⚠ 44/45 顺序经实测对拍（长鑫科技 688825：腾讯[44]=2605.46/[45]=39277.74 == heatmap f=2605.5/m=39277.7）
       —— [44]=流通市值(亿) [45]=总市值(亿)。单票探针（浦发）两值相等看不出差异，一度写反。
       R-qlch-live-0923：补 pcl=[4] 昨收 / opn=[5] 今开 —— 原实现只取现价与涨跌幅，
       买点判定（gap = 今开/昨收−1）需要的两个字段被直接丢弃。树图路径不消费这两个字段。 */
    if (f.length < 46) return;
    var c = f[2], p = num(f[32]), a = num(f[37]), fl = num(f[44]), m = num(f[45]);
    if (!c || c.length !== 6) return;
    rows.push({c: c, n: f[1] || '', p: isNaN(p) ? 0 : p,
               a: isNaN(a) ? 0 : a / 1e4, m: isNaN(m) ? 0 : m, f: isNaN(fl) ? 0 : fl,
               pcl: num(f[4]), opn: num(f[5])});
  }
  function fetchMarketTx(codes){
    var rows = [], i = 0;
    function step(){
      if (i >= codes.length) return Promise.resolve(rows);
      /* R-treelive-0922：批大小必须用 CFG.TX_CHUNK —— 浏览器实测 400 码 OK、800 码 TypeError:
         Failed to fetch（41ms 快速失败）；curl 能容忍 800（7.2KB URL）但浏览器栈不能。
         教训：用 curl 测出的上限不可直接搬到浏览器。5210 只 → 14 个请求（仍远少于 clist 的 56）。 */
      var chunk = codes.slice(i, i + CFG.TX_CHUNK); i += CFG.TX_CHUNK;
      S.txBatches++;
      function attempt(left){
      return getGBK('https://qt.gtimg.cn/q=' + chunk.map(txCode).join(','), 12000)
        .then(function(txt){
          txt.trim().split('\n').forEach(function(l){
            var q = l.indexOf('="'); if (q < 0) return;
            txRow(l.slice(q + 2).replace(/";?\s*$/, '').split('~'), rows);
          });
          return step();
        }, function(){
          if (left > 0) {                                 /* 单批失败：退避 400ms 重试一次 */
            return new Promise(function(r){ setTimeout(r, 400); })
              .then(function(){ return attempt(left - 1); });
          }
          S.txFail++;                                     /* 仍失败：宁缺不瘫，但计数可见 */
          return step();
        });
      }
      return attempt(1);
    }
    return step();
  }
  function fetchMarketEm(){
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
          var p = num(x.f3), a = num(x.f6), m = num(x.f20), fl = num(x.f21);
          if (!x.f12) return;
          rows.push({c: x.f12, n: x.f14 || '', p: isNaN(p) ? 0 : p,
                     a: isNaN(a) ? 0 : a / 1e8, m: isNaN(m) ? 0 : m / 1e8, f: isNaN(fl) ? 0 : fl / 1e8});
        });
      }, function(){ done = true; });
    }
    function pump(){
      if (done) return Promise.resolve();
      var batch = [];
      for (var k = 0; k < conc; k++) batch.push(one(pn++));
      return Promise.all(batch).then(function(){ return pump(); });
    }
    return pump().then(function(){ return rows; });
  }
  function marketDone(rows){
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
                         ' · 更新于 ' + ts + '（全市场 ' + rows.length + ' 只 · ' + (S.treeSrc || '—') + ' 源'
                         + (S.treeSrc === '腾讯' ? ' · 批 ' + (S.txBatches - S.txFail) + '/' + S.txBatches : '')
                         + (S.txFail ? ' · 失败批 ' + S.txFail : '') + '）';
      note.title = CFG.TIP;
      note.style.color = '#b45309';
    }
    S.lastTree = Date.now();
    return hit;
  }
  function fetchMarket(){
    S.txBatches = 0; S.txFail = 0;
    var codes = marketCodes();
    var prim = codes.length ? fetchMarketTx(codes) : Promise.resolve([]);
    return prim.then(function(rows){
      if (rows && rows.length) { S.treeSrc = '腾讯'; return marketDone(rows); }
      return fetchMarketEm().then(function(r2){ S.treeSrc = '东财'; return marketDone(r2); });
    });
  }

  /* ---------- 刷新与调度 ---------- */
  function refresh(force){
    if (chainQuiet()) { S.quiet = true; pill(); return Promise.resolve(false); }  /* R-treelive-0922 */
    S.quiet = false;
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
        /* R-qlch-live-0923：报价落地的外部钩子。**必须显式留**：本 IIFE 内部调的是局部函数 applyQuotes，
           外部改写 window.INTRADAY.applyQuotes 拦不到这里（线上实测：包装版在真实刷新路径上一次都没跑）。
           无钩子时零开销，行为与原来完全一致；树图腿不经过这里。 */
        if (typeof window.QLCH_ON_QUOTES === 'function') {
          try { window.QLCH_ON_QUOTES(q, (r && r.ts) || hhmmss(new Date()), S.poolSrc, S.mktTs); } catch(e) {}
        }
        S.lastPool = Date.now();
        return r;
      }) : Promise.resolve(null);
      /* R-treelive-0922：周期性树图刷新**仅开市时段**（S.live）—— 非交易时段只在页内补刷(force)拉一次快照，
         否则收盘后每 15 分钟仍会打 56 次 clist，与日链抢配额 */
      var needTree = !!document.getElementById('hm-chart') &&
                     (force || (S.live && kxmmActive() && (Date.now() - S.lastTree > CFG.TREE_MS)));
      var t = needTree ? fetchMarket() : Promise.resolve(null);
      return Promise.all([p, t]);
    }).then(function(rs){
      S.busy = false; pill();
      return {pool: rs[0], tree: rs[1], live: S.live, ts: S.ts};
    }, function(e){ S.busy = false; S.err = String(e && e.message || e); pill(); return {err: S.err}; });
  }

  /* 收盘链静默窗（R-treelive-0922 · 用户约束「不影响收盘全量池拉取」）：
     日链 15:30 起密集打东财（em_bulk / fullpool_guard / fetch_val_*），此时浏览器**一律不发行情请求**，
     避免与收盘全量池拉取抢配额（近几日 em_bulk 0/3 全败 = RemoteDisconnected）。
     窗口 15:05–16:45 覆盖收盘后到日链结束；开市时段（09:15–15:05）行为不变。
     d 可选，仅用于测试。 */
  function chainQuiet(d){
    var t = d || new Date();
    var m = t.getHours() * 60 + t.getMinutes();
    return m >= 15 * 60 + 5 && m <= 16 * 60 + 45;
  }
  function kxmmActive(){
    var v = document.getElementById('view-kxmm');
    return !!(v && v.classList.contains('active'));
  }
  function due(){
    if (S.on === false || S.busy) return false;
    if (chainQuiet()) return false;          /* R-treelive-0922：收盘链静默窗内不轮询 */
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
                     chainQuiet: chainQuiet,
                     __scan: scan, __fetchPool: fetchPool,
                     setOn: setOn, cfg: CFG};
})();
"""


# ============ 超跌低开低吸（qlch）盘中买点判定 + 达标置顶 + 盘中净值（R-qlch-live-0923） ============
# 单列一个注入块（与 INTRADAY_JS 分开）：树图层（热力树图 / HM_APPLY / chainQuiet）一行不动 ——
# 本块只消费「选股池报价」的结果（fetchPool → applyQuotes 的包装），出事可单独摘掉。
# 注入点：build_dual_system.py 的 `<script>{QLCH_JS}</script>`（紧跟 INTRADAY_JS 之后）。
QLCH_JS = r"""
/* ============ 超跌低开低吸（qlch）：盘中买点判定 + 达标置顶 + 盘中净值（R-qlch-live-0923） ============
   为什么放浏览器端（ADR-0009）：
     ① 零落盘：只读行情、只改 DOM —— 不写任何 json / 不碰账本，收盘链的记账口径完全不受影响；
     ② 复用已验证的盘中层（#4b）：通道、防串码、开市判定、收盘链静默窗一律不重写；
     ③ 买点是盘中瞬时条件（当日 gap = 今开/昨收−1 盘中恒定；盘中回落 = 现价/昨收−1 逐笔变），
        服务端要「常驻进程 + 落盘 + 每日部署」才能提供同一信息，代价大于收益。
   代价：页面没开就没有判定（收盘链照常写候选与账本，历史可回放）。
   字段：昨收 = 腾讯 [4] / 东财 f18；今开 = 腾讯 [5] / 东财 f17（见 fetchPool / txRow）。
   置顶 = 价格条件满足的**视图态**：不改 depth rank、不改候选取样、不写任何数据。
*/
(function(){
  'use strict';
  var Q = window.QLCH;
  if (!Q) { return; }
  var CFG = {
    LS: 'quant_qlch_trig_v1',                    /* 首次触发时间戳（跨日按 QLCH.as_of 作废） */
    CAND: 'tbl-qlch-cand', PAPER: 'tbl-qlch-paper',
    EPS: 1e-9,                                   /* 价格带端点容差（浮点比较） */
    TIP: '盘中估算值，非记账值；记账以收盘链写入为准'
  };
  var S = {ts: '', src: '', mktTs: '', mktDate: '', gate: false, hit: 0, n: 0,
           diag: {}, nav: {}, dropped: 0, err: ''};
  var META = {}, ORDER = null, TV = null;        /* META: 6 位码→候选元数据；ORDER: 原始行序；TV: 触发记录 */

  function bare(c){ return String(c === null || c === undefined ? '' : c).replace(/^(sh|sz|bj)/i, ''); }
  function num(v){ var x = (v === null || v === undefined || v === '') ? NaN : parseFloat(v); return isNaN(x) ? NaN : x; }
  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function ymd(d){ return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function hms(d){ return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }
  /* 行情时间戳（腾讯 [30]，形如 20260923103102）→ 'YYYY-MM-DD'；非法返回 ''（调用方保守处理）。 */
  function mktDateOf(s){
    s = String(s || '');
    return /^[0-9]{8}/.test(s) ? (s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8)) : '';
  }
  /* 开仓腿基准（对齐生产记账 qlch_paper_20260921.py:379-384）：
     entry_date == 行情日 → 入场价（当日新开仓）；否则 → 昨收（行情 pcl）；昨收缺失 → 退回入场价。
     返回 why 供调用方标注口径（'entry' / 'prevclose' / 'fallback'）。 */
  function posBase(p, qd, d){
    var ep = num(p && p.entry_px);
    if (p && p.entry_date && qd && String(p.entry_date) === qd) return {b: ep, why: 'entry'};
    var pc = d ? num(d.pcl) : NaN;
    if (!isNaN(pc) && pc > 0) return {b: pc, why: 'prevclose'};
    return {b: ep, why: 'fallback'};
  }
  function hm(s){ return (s && s.length >= 16) ? s.slice(11, 16) : ''; }
  (function(){
    var rs = Q.rows || [];
    for (var i = 0; i < rs.length; i++) { var r = rs[i]; if (r && r.code) META[bare(r.code)] = r; }
  })();

  /* ---------- 样式（运行时注入；颜色一律走主题变量，不新增硬编码色值） ---------- */
  function css(){
    if (document.getElementById('qlch-live-css')) return;
    var st = document.createElement('style'); st.id = 'qlch-live-css';
    st.textContent = [
      /* 触发行：绿色左边条 + 淡背景。注意本设计系统的「绿」= --down（A股红涨绿跌），不另造色值 */
      'tr.qlch-trig{background:var(--card2);box-shadow:inset 3px 0 0 var(--down)}',
      'tr.qlch-trig>td:first-child{color:var(--down);font-weight:600}',
      /* 盘中回落达标：仅变色（左边条 --warn），不置顶 */
      'tr.qlch-dip{box-shadow:inset 2px 0 0 var(--warn)}',
      'tr.qlch-trig-hdr>td{background:var(--card2);color:var(--sub);font-size:var(--fs-sm);',
      'padding:6px 8px;text-align:left;box-shadow:inset 3px 0 0 var(--down)}',
      '.qlch-tag{margin-left:6px;font-size:var(--fs-xs);border:1px solid var(--border);',
      'border-radius:var(--r-sm);padding:0 4px;color:var(--sub);background:var(--card);white-space:nowrap}',
      'tr.qlch-trig .qlch-tag{color:var(--down);border-color:var(--down)}',
      'tr.qlch-dip .qlch-tag{color:var(--warn);border-color:var(--warn)}',
      /* 自己的 pill 样式（**不带 badge-live**：盘中层 markCard 会抢改 .badge-live 的文案为「实时 HH:MM:SS」，
         线上实测把「已触发 N/25」冲掉了 → 两枚徽标并存、互不覆盖） */
      '.qlch-badge{background:var(--card2);color:var(--down);border:1px solid var(--down);',
      'border-radius:var(--r-sm);padding:1px 6px;font-size:var(--fs-xs);font-weight:500;white-space:nowrap}',
      '.qlch-live-src{margin-left:6px;font-size:var(--fs-xs);color:var(--faint);font-weight:400}',
      '.qlch-nav-live{font-variant-numeric:tabular-nums}',
      '.qlch-nav-tip{margin-left:4px;font-size:var(--fs-xs);color:var(--faint)}'
    ].join('');
    document.head.appendChild(st);
  }

  /* ---------- 首次触发时间戳（localStorage，跨日清空） ---------- */
  function loadTrig(){
    var raw = null;
    try { raw = localStorage.getItem(CFG.LS); } catch(e) { return {}; }
    if (!raw) return {};
    var o = null;
    try { o = JSON.parse(raw); } catch(e) { return {}; }
    if (!o || typeof o !== 'object') return {};
    var out = {}, k, r, drop = 0;
    for (k in o) {
      if (!Object.prototype.hasOwnProperty.call(o, k)) continue;
      r = o[k];
      /* 跨日清空：候选集换日（as_of 变）→ 上一天的触发记录作废（比对 window.QLCH.as_of） */
      if (!r || typeof r !== 'object' || !r.first || r.as_of !== Q.as_of) { drop++; continue; }
      out[k] = r;
    }
    S.dropped = drop;
    return out;
  }
  function saveTrig(t){
    try { localStorage.setItem(CFG.LS, JSON.stringify(t)); } catch(e) {}
  }

  /* ---------- 判定 ---------- */
  function judge(m, d){
    var C = num(m && m.close);
    if (isNaN(C) || C <= 0) return {k: 'na', why: '候选无基准收盘'};
    if (!d) return {k: 'na', why: '无行情'};
    var px = num(d.px), pcl = num(d.pcl), opn = num(d.opn), pct = num(d.pct);
    if (isNaN(px) || px <= 0) return {k: 'na', why: '无现价'};
    if (isNaN(pcl) || pcl <= 0) {                       /* 回退：昨收 ← 现价/(1+涨跌幅) */
      if (!isNaN(pct) && pct > -99.9) pcl = px / (1 + pct / 100);
    }
    if (isNaN(pcl) || pcl <= 0) return {k: 'na', why: '无昨收'};
    if (Math.abs(px - pcl) <= CFG.EPS && !isNaN(opn) && Math.abs(opn - pcl) <= CFG.EPS)
      return {k: 'na', why: '停牌/一字（现价=今开=昨收）'};
    var lo = num(Q.gap_lo), hi = num(Q.gap_hi);
    if (!isNaN(opn) && opn > 0) {                       /* ① 低开达标（置顶） */
      var gap = opn / pcl - 1;
      if (gap >= lo - CFG.EPS && gap <= hi + CFG.EPS) return {k: 'gap', v: gap};
    }
    var r = px / pcl - 1;                               /* ② 盘中回落达标（仅变色） */
    if (r >= lo - CFG.EPS && r <= hi + CFG.EPS) return {k: 'dip', v: r};
    return {k: 'wait', v: r};
  }
  function codeOf(tr){
    var c = bare(tr.getAttribute('data-code') || '');
    if (!/^[0-9]{6}$/.test(c)) {
      var mm = (tr.textContent || '').match(/(?:^|\D)([0-9]{6})(?:\D|$)/);
      c = mm ? mm[1] : '';
    }
    return /^[0-9]{6}$/.test(c) ? c : '';
  }

  /* ---------- 卡片头徽标 ---------- */
  function badge(ts, live, gated){
    var card = document.getElementById('qlch-card');
    if (!card) return;
    var h2 = card.querySelector('h2');
    if (!h2) return;
    var bd = h2.querySelector('.qlch-badge');
    if (!bd) {
      bd = document.createElement('span');
      bd.className = 'badge qlch-badge';
      h2.appendChild(bd);
    }
    /* 每轮都重写**本枚**徽标的文案与提示（markCard 只动它自己新建的 .badge-live，互不干扰）；
       本块在 applyQuotes 之后运行（包装），故每轮都重设。两态（待开盘判定 / 已触发）由 gated 决定。 */
    if (gated) {
      bd.textContent = '待开盘判定（as_of ' + (Q.as_of || '—') + '）';
      bd.title = '超跌低开低吸：候选信号日（as_of ' + (Q.as_of || '—') + '）当日及之前不判买点 —— '
               + '只在行情日期晚于信号日时判定（行情时间戳取自交易所，节假日/补班不误判）。';
    } else {
      bd.textContent = '已触发 ' + S.hit + '/' + S.n;
      bd.title = '超跌低开低吸：盘中「开盘跳空达标」候选数（= 置顶口径）。达标 ≠ 会买：名额 K=3，候选多于空位时随机抽。';
    }
    var src = h2.querySelector('.qlch-live-src');
    if (!src) { src = document.createElement('span'); src.className = 'qlch-live-src'; h2.appendChild(src); }
    src.textContent = live ? ('刷新于 ' + (ts || '—') + ' · 源 ' + (S.src || '—')
                             + (S.mktDate ? ' · 行情日 ' + S.mktDate : '')) : '待行情（打开页面自动拉取）';
  }

  /* ---------- 候选表：判定 + 置顶（幂等：重复触发不重复计数、不重复插入标题行） ---------- */
  function render(q, ts){
    var tb = document.getElementById(CFG.CAND);
    if (!tb) return;
    var body = tb.querySelector('tbody');
    if (!body) return;
    var k, live = false;
    for (k in q) { if (Object.prototype.hasOwnProperty.call(q, k)) { live = true; break; } }
    /* 修正 3：买点判定只在「行情日晚于候选 as_of」时生效 —— 盘前 / 竞价 / 信号日当日 / 收盘后（S.live=false）
       一律视为待开盘判定。**闸门不得依赖 S.live**：收盘后 S.live=false，若让闸门失效就会拿「当日已发生的开盘」
       去比对「次日买入带」→ 跨日错判、误置顶（线上实测缺陷）。
       「行情日」取行情时间戳（腾讯 [30] → S.mktTs，来源交易所），不用本地日期，节假日/补班不误判。 */
    S.mktDate = mktDateOf(S.mktTs);
    var gated = !S.mktDate || !Q.as_of || !(S.mktDate > String(Q.as_of));
    S.gate = !!gated;
    if (!ORDER) {                                  /* 首次抓原始行序（展示序，勿动 rank） */
      ORDER = [];
      var all = body.querySelectorAll('tr');
      for (var a = 0; a < all.length; a++) ORDER.push(all[a]);
    }
    /* ① 还原原始行序 + 摘掉上次的标题行/类/标签 —— 保证重复刷新不叠加 */
    var oldHdr = body.querySelector('tr.qlch-trig-hdr');
    if (oldHdr && oldHdr.parentNode) oldHdr.parentNode.removeChild(oldHdr);
    for (var o = 0; o < ORDER.length; o++) {
      var tr0 = ORDER[o];
      body.appendChild(tr0);
      tr0.classList.remove('qlch-trig'); tr0.classList.remove('qlch-dip');
      tr0.removeAttribute('data-qlch');
      var oldT = tr0.querySelectorAll('.qlch-tag');
      for (var x = 0; x < oldT.length; x++) oldT[x].parentNode.removeChild(oldT[x]);
    }
    /* ② 判定（还没行情时只建徽标，不误贴「无法判定」） */
    var trig = TV || (TV = loadTrig()), hits = [], res = [], changed = false, i;
    S.diag = {rows: 0, gap: 0, dip: 0, wait: 0, na: 0, noquote: 0, gated: 0};
    for (i = 0; i < ORDER.length; i++) {
      var tr = ORDER[i], code = codeOf(tr), m = META[code];
      if (!m) continue;
      S.diag.rows++;
      if (!live) { S.diag.noquote++; continue; }        /* 还没行情：只建徽标，不误判 */
      if (gated) { S.diag.gated++; continue; }          /* 修正 3：待开盘判定 → 不判定/不记录/不贴标 */
      var d = q[code];
      if (!d) S.diag.noquote++;
      var v = judge(m, d);
      if (v.k === 'gap') S.diag.gap++;
      else if (v.k === 'dip') S.diag.dip++;
      else if (v.k === 'na') S.diag.na++;
      else S.diag.wait++;
      if (v.k === 'gap' || v.k === 'dip') {
        var rec = trig[code];
        if (!rec) {                                /* 首次触发：记下时间与类型；此后永不覆盖时间 */
          rec = trig[code] = {first: ymd(new Date()) + ' ' + hms(new Date()), kind: v.k, as_of: Q.as_of};
          changed = true;
        } else if (v.k === 'gap' && rec.kind !== 'gap') { rec.kind = 'gap'; changed = true; }
      }
      res.push({tr: tr, v: v, rec: trig[code] || null});
    }
    if (changed) saveTrig(trig);
    /* ③ 置顶：只对「低开达标」，按首次触发时间升序；N=0 时无标题行 */
    for (i = 0; i < res.length; i++) if (res[i].v.k === 'gap') hits.push(res[i]);
    hits.sort(function(A, B){
      var fa = A.rec ? A.rec.first : '', fb = B.rec ? B.rec.first : '';
      return (fa === fb) ? 0 : (fa < fb ? -1 : 1);
    });
    if (hits.length) {
      /* 置顶分组行 colspan = 运行时列数（R-qlch-pxcol-0923：候选表改 15 列，勿写死） */
      var ncol = tb.querySelectorAll('thead th').length || 15;
      var hr = document.createElement('tr');
      hr.className = 'qlch-trig-hdr';
      hr.innerHTML = '<td colspan="' + ncol + '">\u26a1 已触发买点（' + hits.length
        + '）· 置顶=价格条件满足的视图态，不改变 depth rank 与随机取样</td>';
      body.insertBefore(hr, body.firstChild);
      var anchor = hr;
      for (i = 0; i < hits.length; i++) {
        hits[i].tr.classList.add('qlch-trig');
        hits[i].tr.setAttribute('data-qlch', 'gap');
        body.insertBefore(hits[i].tr, anchor.nextSibling);
        anchor = hits[i].tr;
      }
    }
    /* ④ 行尾标签：时间 + 类型（低开达标 / 盘中回落 / 无法判定） */
    for (i = 0; i < res.length; i++) {
      var it = res[i], vv = it.v, lab = '';
      if (vv.k === 'gap') lab = (it.rec ? hm(it.rec.first) + ' ' : '') + '低开达标';
      else if (vv.k === 'dip') { it.tr.classList.add('qlch-dip'); lab = (it.rec ? hm(it.rec.first) + ' ' : '') + '盘中回落'; }
      else if (vv.k === 'na') lab = '无法判定';
      if (!lab) continue;
      var cells = it.tr.children;
      if (!cells.length) continue;
      var sp = document.createElement('span');
      sp.className = 'qlch-tag'; sp.textContent = lab;
      sp.title = (vv.k === 'na')
        ? '无法判定：' + (vv.why || '')
        : ((vv.k === 'gap' ? '开盘跳空 ' : '现价/昨收 ') + (isNaN(vv.v) ? '—' : (vv.v * 100).toFixed(2) + '%')
           + ' ∈ [' + (num(Q.gap_lo) * 100).toFixed(2) + '%, ' + (num(Q.gap_hi) * 100).toFixed(2) + '%]（盘中口径）');
      cells[cells.length - 1].appendChild(sp);
    }
    S.hit = hits.length; S.n = Q.n || (Q.rows || []).length;
    badge(ts, live, gated);
  }

  /* ---------- 模拟盘：盘中净值（估算，只读；不写回任何账本） ----------
     口径**对齐生产记账**（backtest/qlch_paper_20260921.py:371-418）：
       · 开仓腿当日收益 = w × (现价/基准 − 1)，COST_RT **不作用于开仓腿**（生产只在出场腿 :391 扣）
       · 基准（:379-384）：entry_date == 行情日 → 入场价（当日新开仓）；否则 = **上一交易日收盘**
         （盘中取行情昨收 pcl；昨收缺失才退回入场价，并在该格标注「昨收缺失，按入场价粗估」）
       · nav_now = nav_prev × (1 + Σ w_i × (现价_i/基准_i − 1))，nav_prev = 账本 equity[-1].nav
     修正 2：账本 equity[-1].date == 行情日 → 当日已由收盘链记账，**不再叠加**（显示账本净值 + 「已收盘记账」） */
  function navUpdate(q){
    var tb = document.getElementById(CFG.PAPER);
    if (!tb || !Q.accounts) return;
    var live = false, kk;
    for (kk in q) { if (Object.prototype.hasOwnProperty.call(q, kk)) { live = true; break; } }
    if (!live) return;                       /* 还没行情：保留构建期占位（nav + 「—」），不写「时间戳缺失」噪音 */
    var qd = mktDateOf(S.mktTs);
    var trs = tb.querySelectorAll('tbody tr');
    for (var i = 0; i < trs.length; i++) {
      var tr = trs[i], tk = tr.getAttribute('data-track');
      var td = tr.querySelector('td.qlch-nav-live');
      if (!td) continue;
      td.title = CFG.TIP;
      var a = (tk && Q.accounts[tk]) || null;
      if (!a) continue;
      var prev = num(a.nav); if (isNaN(prev)) prev = 1;
      var ps = a.positions || [], j;
      if (!ps.length) { td.textContent = prev.toFixed(3) + '（无持仓）'; S.nav[tk] = prev; continue; }
      /* 修正 2：当日已记账 / 无法判断行情日 → 一律不叠加（宁可少算，绝不把已记账的收益再算一遍） */
      var booked = (a.nav_date && qd) ? (String(a.nav_date) === qd) : null;
      if (booked !== false) {
        td.textContent = prev.toFixed(4);
        var t1 = document.createElement('span');
        t1.className = 'qlch-nav-tip';
        t1.textContent = (booked === true) ? '已收盘记账' : '行情时间戳缺失·未叠加';
        t1.title = (booked === true) ? (CFG.TIP + ' · 当日（' + a.nav_date + '）已由收盘链记账') : CFG.TIP;
        td.appendChild(t1);
        S.nav[tk] = prev;
        continue;
      }
      var sum = 0, miss = 0, fb = 0;
      for (j = 0; j < ps.length; j++) {
        var p = ps[j], d = q[bare(p.code)] || null;
        var px = d ? num(d.px) : NaN;
        var bs = posBase(p, qd, d);
        if (!(bs.b > 0) || isNaN(px) || px <= 0) { miss++; continue; }
        if (bs.why === 'fallback') fb++;
        sum += (isNaN(num(p.w)) ? 0 : num(p.w)) * (px / bs.b - 1);     /* 开仓腿不扣成本 */
      }
      if (miss) { td.textContent = prev.toFixed(4) + ' —'; S.nav[tk] = null; continue; }
      var nav = prev * (1 + sum);
      td.textContent = nav.toFixed(4);
      var tip = document.createElement('span');
      tip.className = 'qlch-nav-tip';
      tip.textContent = fb ? '估算（昨收缺失）' : '估算';
      tip.title = CFG.TIP;
      td.appendChild(tip);
      if (fb) { td.title = CFG.TIP + ' · 昨收缺失，按入场价粗估'; tip.title = td.title; }
      S.nav[tk] = nav;
    }
  }

  /* ---------- 入口（每次行情落地后重算一次；幂等） ---------- */
  /* ---------- 入口（每次行情落地后重算一次；幂等） ---------- */
  /* mktTs = 行情时间戳（腾讯 [30]：YYYYMMDDHHMMSS）—— 修正 2/3 的「今天」一律以它为准，不用本地日期
     （节假日/补班时本地日期会误判；行情时间戳来自交易所）。 */
  function run(q, ts, src, mktTs){
    if (!document.getElementById(CFG.CAND)) return null;
    css();
    if (ts) S.ts = ts;
    if (src) S.src = src;
    if (mktTs) S.mktTs = mktTs;
    try { render(q, ts); } catch(e) { S.err = 'render:' + (e && e.message || e); }
    try { navUpdate(q); } catch(e) { S.err = (S.err ? S.err + ' | ' : '') + 'nav:' + (e && e.message || e); }
    return {hit: S.hit, n: S.n, gate: S.gate, mktDate: S.mktDate, diag: S.diag, nav: S.nav, err: S.err};
  }

  /* 接线（两条路都要接，缺一不可）：
     ① 盘中层 refresh 的**内部**报价落地 → window.QLCH_ON_QUOTES（intraday_live.py 显式留的钩子；
        线上实测：只包 applyQuotes 的话真实刷新路径一次都进不来，因为 IIFE 内部调的是局部函数）；
     ② 外部/验证脚本手动调 applyQuotes → 包装它（同一次调用不会双跑：内部路径不经过属性）。 */
  window.QLCH_ON_QUOTES = function(q, ts, src, mktTs){ return run(q, ts, src, mktTs); };
  var IN = window.INTRADAY;
  if (IN && typeof IN.applyQuotes === 'function') {
    var orig = IN.applyQuotes;
    IN.applyQuotes = function(q, ts, opt){
      var out = orig(q, ts, opt);
      opt = opt || {};
      run(q, ts, opt.src || (IN.state && IN.state.poolSrc), opt.mktTs || (IN.state && IN.state.mktTs));
      return out;
    };
  }
  /* 导出（含诊断口：trig/reload/reset —— 触发记录是 localStorage + 内存缓存双层，
     验证脚本要能把「缓存」与「落盘」分开断，否则清空 localStorage 后仍会看到缓冲里的旧记录） */
  window.QLCH_LIVE = {run: run, state: S, meta: META, cfg: CFG, judge: judge, store: loadTrig,
                      base: posBase, mktDateOf: mktDateOf,
                      trig: function(){ return TV; },
                      reload: function(){ TV = loadTrig(); return TV; },
                      reset: function(){ TV = {}; try { localStorage.removeItem(CFG.LS); } catch(e) {} },
                      order: function(){ return ORDER; }, wrapped: !!(IN && IN.applyQuotes)};
  /* 首屏：先把徽标/样式建起来（还没行情 → 不判定、不贴标签） */
  run(null, '');
})();
"""
