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
        /* R-hpdk-txchunk-0929：**腾讯兜底必须自己再分片**。原实现直接复用东财的 800 码 chunk
           拼 qt.gtimg 的 URL —— 浏览器对该长度会 **快速失败**（CFG.TX_CHUNK 注释有实测记录：
           400 码 OK / 800 码 TypeError: Failed to fetch）⇒ 兜底形同虚设：EM 失败 + TX 空返回
           = 整批 0 报价（实测 2215 只全池取报价 79.6s、只覆盖 64%）。 */
        var txParts = [];
        for (var ti = 0; ti < chunk.length; ti += CFG.TX_CHUNK) txParts.push(chunk.slice(ti, ti + CFG.TX_CHUNK));
        var tpi = 0;
        function txStep(){
          if (tpi >= txParts.length) return step();
          var part = txParts[tpi++];
          S.txBatches++;
          var u2 = 'https://qt.gtimg.cn/q=' + part.map(txCode).join(',');
          return getGBK(u2, 12000).then(function(txt){
            txt.trim().split('\n').forEach(function(l){
              var f = l.split('~'); if (f.length < 33) return;
              var px = num(f[3]), pct = num(f[32]);
              if (f[2] && !isNaN(px)) out[f[2]] = {px: px, pct: isNaN(pct) ? 0 : pct, name: f[1] || '',
                                                   pcl: num(f[4]), opn: num(f[5])};
            });
            return txStep();
          }, function(){ S.txFail++; return txStep(); });
        }
        return txStep();
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
    rows.push({c: c, n: f[1] || '', px: num(f[3]), p: isNaN(p) ? 0 : p,
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
    /* R-hpdk-marketq-0929：把**全市场快照**发布成报价表，供缩量超跌卡做「全池判定」。
       为什么这么做：池子报价接口按 chunk 拉 2215 只实测要 **79.6s 且只覆盖 64%**
       （东财失败 → 腾讯兜底，而浏览器对 800 码 URL 会快速失败，见 CFG.TX_CHUNK 注释）；
       而全市场快照本来就在拉（腾讯 400 码/片 · 覆盖 5200 只 · 每 3 分钟一次，字段含 [3]现价
       [4]昨收 [5]今开 [32]涨跌幅）⇒ 复用它是**零额外请求 + 全覆盖**。
       仅发布给卡内判定使用，不改任何 DOM、不落盘。 */
    var mq = {}, mc = 0, mi;
    for (mi = 0; mi < rows.length; mi++) {
      var r0 = rows[mi];
      if (!r0 || !r0.c) continue;
      if (!(num(r0.px) > 0)) continue;
      mq[r0.c] = {px: num(r0.px), pct: num(r0.p), pcl: num(r0.pcl), opn: num(r0.opn),
                  name: r0.n || ''};
      mc++;
    }
    S.marketQ = mq; S.marketN = mc; S.marketTs = hhmmss(new Date());
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
      /* R-hpdk-poolfallback-0929：全市场快照（S.marketQ）拿不到时（页面无 HEATMAP / 快照失败），
         把整个资格池并进池子报价请求 —— 有兜底路径（腾讯 400 码分片）。快照可用时**不再并池**，
         避免每轮多打 6 个请求。 */
      var _needExtra = !(S.marketQ && S.marketN >= 1000);
      if (_needExtra && typeof window.POOL_EXTRA_CODES === 'function') {
        try {
          var _ex = window.POOL_EXTRA_CODES() || [];
          for (var _ie = 0; _ie < _ex.length; _ie++) {
            if (_ex[_ie] && !seen[_ex[_ie]]) { seen[_ex[_ie]] = 1; codes.push(_ex[_ie]); }
          }
        } catch (e) {}
      }
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
      /* R-hpdk-marketq-0929：**不再把整个资格池塞进池子报价接口** —— 实测 2215 只要 79.6s 且只覆盖 64%
         （东财失败 → 腾讯兜底，浏览器对 800 码 URL 快速失败）。全池判定改用 R-hpdk-marketq-0929
         发布的全市场快照（S.marketQ，零额外请求、全覆盖）。池子接口只服务 DOM 行的实时刷新。 */
      var p = codes.length ? fetchPool(codes).then(function(q){
        var r = applyQuotes(q, hhmmss(new Date()));
        /* R-hpdk-marketq-0929：全池判定用「全市场快照 ∪ 池内报价」（池内更鲜 → 后者覆盖前者）。 */
        var qAll = q;
        if (S.marketQ) {
          qAll = {}; var _k;
          for (_k in S.marketQ) { if (Object.prototype.hasOwnProperty.call(S.marketQ, _k)) qAll[_k] = S.marketQ[_k]; }
          for (_k in q) { if (Object.prototype.hasOwnProperty.call(q, _k)) qAll[_k] = q[_k]; }
        }
        var _hookTs = (r && r.ts) || hhmmss(new Date());
        var _hookSrc = (S.marketQ ? ('全市场快照 ' + (S.marketN || 0) + ' 只' + (S.poolSrc ? (' · ' + S.poolSrc) : '')) : S.poolSrc);
        /* R-qlch-live-0923：报价落地的外部钩子。**必须显式留**：本 IIFE 内部调的是局部函数 applyQuotes，
           外部改写 window.INTRADAY.applyQuotes 拦不到这里（线上实测：包装版在真实刷新路径上一次都没跑）。
           无钩子时零开销，行为与原来完全一致；树图腿不经过这里。 */
        if (typeof window.QLCH_ON_QUOTES === 'function') {
          try { window.QLCH_ON_QUOTES(qAll, _hookTs, _hookSrc, S.mktTs); } catch(e) {}
        }
        /* R-a5-auction-0924：打板族（A5）竞价/开盘判定的**第二个**钩子。同理必须显式留在这里 ——
           IIFE 内部调的是局部 applyQuotes，外部包装拦不到；无钩子时零开销，行为与原来完全一致。 */
        if (typeof window.A5_ON_QUOTES === 'function') {
          try { window.A5_ON_QUOTES(q, (r && r.ts) || hhmmss(new Date()), S.poolSrc, S.mktTs); } catch(e) {}
        }
        /* R-hpdk-dash-0927：缩量超跌（原名「横盘低开·两日」，HPDK）竞价/开盘判定的**第三个**钩子。同理必须显式留在这里
           —— IIFE 内部调的是局部 applyQuotes，外部包装拦不到；无钩子时零开销，行为与原来完全一致。
           本钩子做三件事：09:25 后按真实今开算 gap，把 A/B/C 不满足的标的**从清单移除**，
           并对存活子集按冻结复合分定榜前置顶。零落盘（不写 json / 不碰账本 / 不发请求）。 */
        if (typeof window.HPDK_ON_QUOTES === 'function') {
          try { window.HPDK_ON_QUOTES(qAll, _hookTs, _hookSrc, S.mktTs); } catch(e) {}
        }
        S.lastPool = Date.now();
        return r;
      }) : Promise.resolve(null);
      /* R-treelive-0922：周期性树图刷新**仅开市时段**（S.live）—— 非交易时段只在页内补刷(force)拉一次快照，
         否则收盘后每 15 分钟仍会打 56 次 clist，与日链抢配额 */
      /* R-hpdk-marketq-0929：全池判定要「全市场快照」⇒ 只要缩量超跌卡在页面上，就按 TREE_MS
         周期拉一次（原条件只认热力图 #hm-chart，若用户没开热力图则该快照永不刷新）。 */
      var needTree = (!!document.getElementById('hm-chart') || !!document.getElementById('hpdk-live-top')) &&
                     (force || (S.live && (Date.now() - S.lastTree > CFG.TREE_MS)));
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


A5_JUDGE_JS = r"""
/* ============= 打板族 A5「竞价 / 开盘买点」判定 —— 纯函数（R-a5-auction-0924） =============
   为什么单独拆成纯函数（判据 C 的夹具要求）：
     ① 页面驱动块（A5_JS）与 node 夹具**跑同一份代码原文** —— 夹具不复制判定逻辑，杜绝「复刻式假证据」；
     ② 无 DOM / 无 window / 无 Date / 无 Math.random 依赖 → 同一输入必然同一输出，可确定性重放。
   判定口径 = 生产记账 backtest/a5_experiment/paper_daban_a5.py（L455-494 入场段）逐条对齐：
     gap = 今开/昨收 − 1 ∈ [gap_lo, gap_hi] = [−5%, −2%]   ← **闭区间**（端点判命中）
     rel_pos ≤ 0.5 · amt ≥ 5e7 元 · room_pct ≥ 20（F3 空间 = 首板日距前高）
     三项静态条件都取自「首板日收盘」（构建期内嵌），唯一盘中变量 = 今开 → 判定放浏览器端算（ADR-0009）。
   phase 由**交易所行情时间戳**分级（不用本地日期 → 节假日 / 补班不误判）：
     'auction' 09:15–09:25 集合竞价未成交 → 只有竞价参考价，**一律不出命中**（页面只挂灰标「竞价预判」）
     'open'    09:25–15:05 有真实今开 → 判命中（页面置顶）
     'pre'     行情日 ≤ 候选 as_of（盘前 / 信号日当日）或时刻不可定 → 待开盘判定，不判
     'closed'  收盘后 → 不判
   返回 {k, v, why}：k ∈ 'hit' | 'no' | 'pre'
   缺静态条件（rel_pos / amt / room_pct 任一为 NaN）→ **不判命中**（保守，宁可漏判不可误置顶）。 */
function a5Judge(row, d, thr, phase){
  var EPS = 1e-9;
  var R = row || {}, D = d || {}, T = thr || {};
  function N(v){ var x = (v === null || v === undefined || v === '') ? NaN : parseFloat(v); return isNaN(x) ? NaN : x; }
  var lo = N(T.gap_lo), hi = N(T.gap_hi);
  if (isNaN(lo)) lo = -0.05;
  if (isNaN(hi)) hi = -0.02;
  if (phase !== 'open') {
    /* 竞价预判：给「竞价参考价/昨收 − 1」作**预判值**，只展示、绝不置顶、绝不计命中 */
    var px0 = N(D.px), pc0 = N(D.pcl);
    var g0 = (px0 > 0 && pc0 > 0) ? (px0 / pc0 - 1) : NaN;
    return {k: 'pre', v: g0, why: (phase === 'auction') ? '集合竞价未成交（仅竞价参考价）' : '非开盘判定时段'};
  }
  var pcl = N(D.pcl);
  if (!(pcl > 0)) pcl = N(R.last_close);              /* 昨收缺失 → 退回首板日收盘 */
  var opn = N(D.opn);
  if (!(opn > 0)) return {k: 'pre', v: NaN, why: '无真实今开（09:25 前 / 行情缺失）'};
  if (!(pcl > 0)) return {k: 'pre', v: NaN, why: '无昨收，无法算 gap'};
  var gap = opn / pcl - 1;
  if (!(gap >= lo - EPS && gap <= hi + EPS))
    return {k: 'no', v: gap, why: 'gap ' + (gap * 100).toFixed(2) + '% 不在 ['
            + (lo * 100).toFixed(2) + '%, ' + (hi * 100).toFixed(2) + '%]'};
  var rp = N(R.rel_pos), amt = N(R.amt), room = N(R.room_pct);
  var rpMax = N(T.rel_pos_max); if (isNaN(rpMax)) rpMax = 0.5;
  var amtMin = N(T.amt_min);    if (isNaN(amtMin)) amtMin = 5e7;
  var roomMin = N(T.room_min);  if (isNaN(roomMin)) roomMin = 20.0;
  if (isNaN(rp))   return {k: 'no', v: gap, why: '缺相对位置数据，不判命中'};
  if (isNaN(amt))  return {k: 'no', v: gap, why: '缺成交额数据，不判命中'};
  if (isNaN(room)) return {k: 'no', v: gap, why: '缺 F3 空间数据，不判命中'};
  if (rp > rpMax + EPS)       return {k: 'no', v: gap, why: '相对位置 ' + rp.toFixed(2) + ' > ' + rpMax};
  if (amt < amtMin - EPS)     return {k: 'no', v: gap, why: '成交额 ' + (amt / 1e4).toFixed(0) + ' 万 < 5000 万'};
  if (room < roomMin - EPS)   return {k: 'no', v: gap, why: 'F3 空间 ' + room.toFixed(1) + '% < ' + roomMin + '%'};
  return {k: 'hit', v: gap, why: '命中'};
}
"""


A5_JS = r"""
/* ============= 打板族 A5 竞价 / 开盘判定**驱动块**（R-a5-auction-0924） =============
   对齐「超跌低开低吸」(QLCH_JS) 的交互范式（用户要求「就和超跌低开低吸所做的那样」）：
     09:15–09:25 集合竞价 → 每行挂**灰标「竞价预判」**（显示竞价参考价 gap，仅供观察），
                            **不置顶、不计命中**（契约 C 明确）；
     09:25 起       → 用**真实今开**跑 a5Judge，命中者加绿标 + 插入分组行并重排 DOM 到表顶；
     其它时段       → 「待开盘判定（as_of …）」，不判、不贴标。
   闸门与 QLCH 同一把：判定只在「行情日 > 候选 as_of」时生效，行情日取**交易所时间戳**（腾讯 [30]），
   不用本地日期 → 节假日 / 补班不误判。
   置顶 = **视图态**：只改 DOM 顺序，不改信号池、不动模拟盘账本、不写盘（ADR-0009）。
   幂等：每轮先按 ORDER 还原原始行序 + 摘掉上次的类 / 标签 / 分组行，再重新判定 → 重复刷新不叠加。 */
(function(){
  var A = window.A5_AUCTION;
  if (!A) return;                                   /* 无数据 → 完全不动页面 */
  var CFG = { TBL: 'a5-wl', CARD: 'a5-watchlist', EPS: 1e-9,
              TIP: '竞价/开盘判定是盘中瞬时视图态：不写盘、不改账本；记账以收盘链写入为准' };
  var THR = A.thr || {}, ASOF = String(A.as_of || '');
  var META = {}, ORDER = null;
  var S = {phase: '', hit: 0, n: 0, rows: 0, ts: '', src: '', mktDate: '', err: ''};

  function bare(c){ return String(c === null || c === undefined ? '' : c).replace(/^(sh|sz|bj)/i, ''); }
  function N(v){ var x = (v === null || v === undefined || v === '') ? NaN : parseFloat(v); return isNaN(x) ? NaN : x; }
  (function(){
    var rs = A.rows || [];
    for (var i = 0; i < rs.length; i++) { var r = rs[i]; if (r && r.code) META[bare(r.code)] = r; }
  })();

  /* 交易所行情时间戳（腾讯 [30]，形如 20260924103102）→ {date:'YYYY-MM-DD', min:分钟数|-1} */
  function mktOf(s){
    s = String(s || '');
    if (!/^[0-9]{8}/.test(s)) return null;
    var d = s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8);
    if (/^[0-9]{12}/.test(s)) {
      var hh = parseInt(s.slice(8, 10), 10), mm = parseInt(s.slice(10, 12), 10);
      if (isNaN(hh) || isNaN(mm)) return {date: d, min: -1};
      return {date: d, min: hh * 60 + mm};
    }
    return {date: d, min: -1};
  }
  /* 相位：09:15–09:25 竞价 / 09:25–15:05 开盘 / 其余 盘前|收盘；行情日 ≤ as_of 一律 'pre' */
  function phaseOf(mkt){
    if (!mkt || mkt.min < 0) return 'pre';
    if (ASOF && !(mkt.date > ASOF)) return 'pre';
    var m = mkt.min;
    if (m >= 9 * 60 + 15 && m < 9 * 60 + 25) return 'auction';
    if (m >= 9 * 60 + 25 && m <= 15 * 60 + 5) return 'open';
    return m < 9 * 60 + 15 ? 'pre' : 'closed';
  }
  function codeOf(tr){
    var c = bare(tr.getAttribute('data-code') || '');
    if (!/^[0-9]{6}$/.test(c)) {
      var mm = (tr.textContent || '').match(/(?:^|\D)([0-9]{6})(?:\D|$)/);
      c = mm ? mm[1] : '';
    }
    return /^[0-9]{6}$/.test(c) ? c : '';
  }
  function css(){
    if (document.getElementById('a5-live-css')) return;
    var st = document.createElement('style'); st.id = 'a5-live-css';
    st.textContent = [
      'tr.a5-hit{background:var(--card2);box-shadow:inset 3px 0 0 var(--down)}',
      'tr.a5-hit>td:first-child{color:var(--down);font-weight:600}',
      'tr.a5-pre{box-shadow:inset 2px 0 0 var(--warn)}',
      'tr.a5-hit-hdr>td{background:var(--card2);color:var(--down);font-weight:600;font-size:12px}',
      '.a5-tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;font-size:11px;white-space:nowrap}',
      '.a5-tag.hit{background:var(--down);color:#fff}',
      '.a5-tag.pre{background:transparent;border:1px dashed var(--faint);color:var(--faint)}',
      '.a5-auction-badge{font-weight:400}'
    ].join('\n');
    document.head.appendChild(st);
  }
  function badge(live){
    var card = document.getElementById(CFG.CARD);
    if (!card) return;
    var h2 = card.querySelector('h2');
    if (!h2) return;
    var bd = h2.querySelector('.a5-auction-badge');
    if (!bd) { bd = document.createElement('span'); bd.className = 'badge a5-auction-badge'; h2.appendChild(bd); }
    if (!live || S.phase === 'pre')       bd.textContent = '待开盘判定（as_of ' + (ASOF || '—') + '）';
    else if (S.phase === 'auction')       bd.textContent = '竞价预判中 · 09:25 后判命中';
    else if (S.phase === 'open')          bd.textContent = '已命中 ' + S.hit + '/' + S.n;
    else                                  bd.textContent = '今日判定结束（' + (S.mktDate || '—') + '）';
    bd.title = CFG.TIP
      + ' · 判定口径：今开/昨收−1 ∈ [' + ((N(THR.gap_lo) || -0.05) * 100).toFixed(2) + '%, '
      + ((N(THR.gap_hi) || -0.02) * 100).toFixed(2) + '%]（闭区间）'
      + ' + 相对位置 ≤ ' + (N(THR.rel_pos_max) || 0.5)
      + ' + 成交额 ≥ ' + ((N(THR.amt_min) || 5e7) / 1e4).toFixed(0) + ' 万'
      + ' + F3 空间 ≥ ' + (N(THR.room_min) || 20) + '%';
  }
  function render(q, ts, src, mktTs){
    var tb = document.getElementById(CFG.TBL);
    if (!tb) return null;
    var body = tb.querySelector('tbody');
    if (!body) return null;
    css();
    var live = false, k, i;
    for (k in q) { if (Object.prototype.hasOwnProperty.call(q, k)) { live = true; break; } }
    var mkt = mktOf(mktTs);
    S.ts = ts || ''; S.src = src || ''; S.mktDate = mkt ? mkt.date : '';
    S.phase = live ? phaseOf(mkt) : 'pre';
    S.hit = 0; S.n = 0; S.rows = 0;
    if (!ORDER) { ORDER = []; var all = body.querySelectorAll('tr'); for (var a = 0; a < all.length; a++) ORDER.push(all[a]); }
    /* ① 还原：摘分组行 / 摘类 / 摘标签 / 复位原始行序（幂等关键 —— 重复刷新不叠加） */
    var oldHdr = body.querySelector('tr.a5-hit-hdr');
    if (oldHdr && oldHdr.parentNode) oldHdr.parentNode.removeChild(oldHdr);
    for (var o = 0; o < ORDER.length; o++) {
      var tr0 = ORDER[o];
      body.appendChild(tr0);
      tr0.classList.remove('a5-hit'); tr0.classList.remove('a5-pre');
      var oldT = tr0.querySelectorAll('.a5-tag');
      for (var x = 0; x < oldT.length; x++) oldT[x].parentNode.removeChild(oldT[x]);
    }
    /* ② 判定（还没行情 → 只建徽标，不误贴「竞价预判」） */
    var res = [], hits = [];
    for (i = 0; i < ORDER.length; i++) {
      var tr = ORDER[i], code = codeOf(tr), m = META[code];
      if (!m) continue;
      S.rows++;
      if (!live || S.phase === 'pre' || S.phase === 'closed') continue;
      S.n++;
      var v = a5Judge(m, q[code], THR, S.phase);
      res.push({tr: tr, v: v});
      if (v.k === 'hit') { S.hit++; hits.push({tr: tr, v: v}); }
    }
    /* ③ 命中者置顶：分组行 colspan = 运行时列数（勿写死），按 gap 升序（越低开越靠前） */
    if (hits.length) {
      hits.sort(function(X, Y){ return X.v.v - Y.v.v; });
      var ncol = tb.querySelectorAll('thead th').length || 14;
      var hr = document.createElement('tr');
      hr.className = 'a5-hit-hdr';
      hr.innerHTML = '<td colspan="' + ncol + '">\u26a1 已命中买点（' + hits.length
        + '）· 置顶 = 价格条件满足的视图态，不改信号池与模拟盘账本</td>';
      body.insertBefore(hr, body.firstChild);
      var anchor = hr;
      for (i = 0; i < hits.length; i++) {
        hits[i].tr.classList.add('a5-hit');
        body.insertBefore(hits[i].tr, anchor.nextSibling);
        anchor = hits[i].tr;
      }
    }
    /* ④ 行尾标签：命中（绿，含 gap） / 竞价预判（灰，含预判 gap） */
    for (i = 0; i < res.length; i++) {
      var tds = res[i].tr.querySelectorAll('td');
      var td = tds.length ? tds[tds.length - 1] : null;
      if (!td) continue;
      var g = res[i].v.v, gs = isNaN(g) ? '—' : ((g * 100).toFixed(2) + '%');
      var isHit = res[i].v.k === 'hit', isPre = res[i].v.k === 'pre';
      var txt = isHit ? ('命中 ' + gs) : (isPre ? (S.phase === 'auction' ? ('竞价预判 ' + gs) : '待今开') : '');
      if (!txt) continue;
      var sp = document.createElement('span');
      sp.className = 'a5-tag ' + (isHit ? 'hit' : 'pre');
      sp.textContent = txt;
      sp.title = CFG.TIP + ' · ' + (res[i].v.why || '');
      if (isPre) res[i].tr.classList.add('a5-pre');
      td.appendChild(sp);
    }
    badge(live);
    return {phase: S.phase, hit: S.hit, n: S.n, rows: S.rows, mktDate: S.mktDate, err: S.err};
  }
  function run(q, ts, src, mktTs){
    try { return render(q || {}, ts || '', src || '', mktTs || ''); }
    catch(e) { S.err = String(e && e.message || e); return null; }
  }
  /* 接线（两条路都要接，缺一不可 —— 同 QLCH 的教训：IIFE 内部走局部函数，只包 applyQuotes 拦不到）：
     ① 盘中层 refresh 内部报价落地 → window.A5_ON_QUOTES（intraday_live.py 显式留的钩子）；
     ② 外部/验证脚本手动调 applyQuotes → 包装它（同一次调用不双跑）。 */
  window.A5_ON_QUOTES = function(q, ts, src, mktTs){ return run(q, ts, src, mktTs); };
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
  window.A5_LIVE = {run: run, state: S, meta: META, cfg: CFG, thr: THR, asOf: ASOF,
                    judge: a5Judge, phaseOf: phaseOf, mktOf: mktOf,
                    order: function(){ return ORDER; },
                    wrapped: !!(IN && IN.applyQuotes)};
  /* 首屏：先把样式/徽标建起来（还没行情 → 不判定、不贴标） */
  run(null, '');
})();
"""


# ============ 缩量超跌（原名「横盘低开·两日」，hpdk）盘中买点判定 + 不达标自动剔除（R-hpdk-live-0927） ============
# 单列一个注入块（与 INTRADAY_JS 分开）：树图层与 QLCH / A5 两块一行不动 —— 本块只消费「选股池报价」的结果
# （主盘中层 fetchPool → applyQuotes 的钩子）。注入点：build_dual_system.py 的 `<script>{HPDK_JS}</script>`
# （紧跟 A5_JS 之后；payload 由 `<script>window.HPDK = …</script>` 内嵌）。
HPDK_JS = r"""
/* ============ 缩量超跌（原名「横盘低开·两日」，hpdk）：买日 09:25 买点判定 + 不达标自动剔除（R-hpdk-live-0927） ============
   为什么放浏览器端（ADR-0009）：
     ① 零落盘：只读行情（主盘中层已拉好的选股池报价）与 window.HPDK，只改 DOM —— 不写 json / 不发请求 / 不碰账本；
     ② 复用已验证的盘中层（R-live-0918）：通道、防串码、开市判定、收盘链静默窗一律不重写；
     ③ 判定是盘中瞬时条件：gap = 今开/昨收−1 与「低开子集内的横截面排名」都要等 09:25 集合竞价撮合后才成立，
        服务端要「常驻进程 + 落盘 + 每日部署」才能给出同一信息，代价大于收益。
   代价：页面没开就没有判定（收盘链与冻结 OOS 台账照常，历史可回放）。
   判定口径（= 生产者 backtest/hengpan_fangliang_dikai_0925/hpdk_candidates.py；冻结 SHA 见 HPDK.frozen_sha256）：
     C 准入件：T 日 amt20 ≥ HPDK.minamt 且 close ≥ HPDK.minpx（构建期内嵌字段的防御性复核，静态，不需要行情）；
     B 可交易：现价 / 昨收 / 今开 三者 > 0，且不是停牌/一字（px == pcl == opn）
               —— **先于 A 判**（同 QLCH_JS judge 的顺序；否则一字板的 gap = 0 会被误报成「A 不在带内」）；
     A 低开带：gap = 今开/昨收 − 1 ∈ [HPDK.gap_lo, HPDK.gap_hi]（**闭区间**，端点算命中，容差 1e-9）；
     F 排名：在**存活子集**内做横截面 z 标准化，F = z(−ln amt20) + z(−ln volbr) + z(−ret20)（ret20 是小数，
              如 −0.065 表示跌 6.5%）—— 与生产者 :190-193 同式，标准差取总体口径（np.nanstd = ddof 0）；
     任一不满足 → 把该行**从表格移除**（不是置灰）；存活者按 F 降序取前 HPDK.k 只 → 置顶 + 标注当日买入候选。
   闸门（唯一开关；**不得依赖 S.live**：收盘后 S.live=false，若让闸门失效就会拿「当日已发生的开盘」去误剔）：
     只有「行情日 === HPDK.buy_date 且 时刻 ≥ 09:25」才执行剔除；盘前 / 集合竞价 09:15–09:24 / 非买日 /
     周末（行情时间戳不落在买日）/ 无行情 → **一行都不剔除**，只挂灰标「竞价预判」。
     行情日取**交易所时间戳**（腾讯 [30]，形如 20260928103012），不用本地日期 → 节假日 / 补班不误判。
   置顶 = 视图态：只改 DOM 顺序与文本，不改信号池、不改 depth rank、不碰任何账本；每轮先按 ORDER 还原 → 幂等且可逆。
   字段：现价 px / 昨收 pcl / 今开 opn（腾讯 [3][4][5]、东财 f2/f18/f17，见 INTRADAY_JS fetchPool）。
        现价 / 涨跌幅两列由主盘中层按列头文本定位改写，本块**不碰**（互不抢改）。
*/
(function(){
  'use strict';
  var H = window.HPDK;
  if (!H) { return; }                          /* 无 payload → 完全不动页面（与 QLCH_JS / A5_JS 同一约定） */
  var CFG = {
    TBL: 'tbl-hpdk-cand',
    LS: 'quant_hpdk_trig_v1',                  /* 首次判定时间戳（跨日按 HPDK.as_of 作废） */
    EPS: 1e-9,                                 /* 价格带端点容差（浮点比较） */
    AUC_MIN: 9 * 60 + 15,                      /* 09:15 集合竞价开始（只灰标，不剔除） */
    OPEN_MIN: 9 * 60 + 25,                     /* 09:25 集合竞价撮合：出现第一笔真实今开 */
    ADV_FRAC: 0.01,                            /* 单票上限 = 该股 20 日均额 × 1%（= 生产者 ADV_FRAC） */
    HDR_EVENT: ['状态', '事件标签', '事件', '买点', '信号'],   /* 2026-09-27 新增「状态」列 */
    HDR_BUY: ['买入价', '买价'],
    HDR_TP: ['止盈价', '止盈'],
    HDR_QTY: ['建议股数', '股数', '委托股数'],
    HDR_CAP: ['容量标记', '容量', '上限'],
    HDR_NAME: ['标的', '名称'],
    TIP: '盘中判定是视图态：只读行情、只改 DOM；不写盘、不发请求、不改账本 —— 记账以收盘链与冻结 OOS 台账为准'
  };
  var S = {ts: '', src: '', mktTs: '', mktDate: '', mmin: -1, phase: 'none', gate: false, live: false,
           rows: 0, pool: 0, removed: 0, hit: 0, kept: 0, noquote: 0, calls: 0, err: '', diag: []};
  var META = {}, ORDER = null, TV = null, COLS = null, NCOL = 0;
  var TOPCACHE = {buy: '', html: ''};   /* R-hpdk-keep-0929：上一帧清单（源抖动时不清空） */

  function num(v){ var x = (v === null || v === undefined || v === '') ? NaN : parseFloat(v); return isNaN(x) ? NaN : x; }
  function numOr(v, d){ var x = num(v); return isNaN(x) ? d : x; }
  function bare(c){ return String(c === null || c === undefined ? '' : c).replace(/^(sh|sz|bj)/i, ''); }
  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function ymd(d){ return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function hms(d){ return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }
  function fmtPct(v){ return isNaN(v) ? '—' : ((v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%'); }
  function fmtWan(v){ return isNaN(v) ? '—' : (v / 1e4).toFixed(0) + ' 万'; }
  function fmtQty(n){ return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + ' 股'; }

  /* 交易所行情时间戳（腾讯 [30]，形如 20260928103012）→ {date:'YYYY-MM-DD', min:分钟数|-1}；非法 → null */
  function mktOf(s){
    s = String(s || '');
    if (!/^[0-9]{8}/.test(s)) return null;
    var d = s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8);
    if (!/^[0-9]{12}/.test(s)) return {date: d, min: -1};
    var hh = parseInt(s.slice(8, 10), 10), mm = parseInt(s.slice(10, 12), 10);
    if (isNaN(hh) || isNaN(mm)) return {date: d, min: -1};
    return {date: d, min: hh * 60 + mm};
  }
  /* 相位只决定**文案**；是否剔除只由 render 里的 enforce 决定：
     none 无行情时间戳 / prebuy 行情日早于买日 / pre 买日盘前（<09:15）
     auction 买日集合竞价 09:15–09:24（只灰标） / open 买日 09:25 起（判定剔除） / past 行情日晚于买日 */
  function phaseOf(mkt, buy){
    if (!mkt || !mkt.date || !buy) return 'none';
    if (mkt.date < buy) return 'prebuy';
    if (mkt.date > buy) return 'past';
    if (mkt.min < 0) return 'pre';
    if (mkt.min < CFG.AUC_MIN) return 'pre';
    if (mkt.min < CFG.OPEN_MIN) return 'auction';
    return 'open';
  }
  /* 资格池 → 6 位码 → 元数据（列序取 H.cols，不写死下标；cols 缺失 → 退回内嵌约定顺序） */
  function colIdx(name, def){
    var cs = H.cols || [], i;
    for (i = 0; i < cs.length; i++) if (String(cs[i]) === name) return i;
    return def;
  }
  (function(){
    var C = colIdx('code', 0), N = colIdx('name', 1), I = colIdx('ind', 2), B = colIdx('board', 3),
        CL = colIdx('close', 4), A = colIdx('amt20', 5), V = colIdx('volbr', 6), R = colIdx('ret20', 7);
    var rs = H.rows || [], i;
    for (i = 0; i < rs.length; i++) {
      var r = rs[i];
      if (!r) continue;
      var c = bare(r[C]);
      if (!/^[0-9]{6}$/.test(c)) continue;
      META[c] = {code: c, name: r[N], ind: r[I], board: r[B], close: num(r[CL]),
                 amt20: num(r[A]), volbr: num(r[V]), ret20: num(r[R]), i: i};
    }
    S.pool = 0;
    for (i in META) { if (Object.prototype.hasOwnProperty.call(META, i)) S.pool++; }
  })();
  /* ---------- 样式（运行时注入；颜色一律走主题变量，不新增硬编码色值） ---------- */
  function css(){
    if (document.getElementById('hpdk-live-css')) return;
    var st = document.createElement('style'); st.id = 'hpdk-live-css';
    st.textContent = [
      /* 今日买入候选：绿色左边条 + 淡背景。注意本设计系统的「绿」= --down（A 股红涨绿跌），不另造色值 */
      'tr.hpdk-buy{background:var(--card2);box-shadow:inset 3px 0 0 var(--down)}',
      'tr.hpdk-buy>td:first-child{color:var(--down);font-weight:600}',
      /* 存活但 F 排名在 k 之后：只留细左条（视图提示，不置顶、不标注） */
      'tr.hpdk-keep{box-shadow:inset 2px 0 0 var(--border)}',
      'tr.hpdk-buy-hdr>td{background:var(--card2);color:var(--down);font-weight:600;padding:6px 8px;text-align:left;',
      'box-shadow:inset 3px 0 0 var(--down)}',
      '.hpdk-tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;font-size:11px;white-space:nowrap}',
      '.hpdk-tag.buy{background:var(--down);color:#fff;margin-left:0;margin-right:6px}',
      '.hpdk-tag.keep,.hpdk-tag.pre{background:transparent;border:1px dashed var(--faint);color:var(--faint)}',
      /* 自己的 pill 样式（**不带 badge-live**：盘中层 markCard 每轮把 .badge-live 的文案抢改为「实时 HH:MM:SS」，
         两枚徽标并存、互不覆盖 —— 与 QLCH_JS 的处理一致） */
      '.hpdk-badge{background:var(--card2);color:var(--down);border:1px solid var(--down);border-radius:var(--r-sm);',
      'padding:1px 6px;font-size:var(--fs-xs);font-weight:500;white-space:nowrap}',
      '.hpdk-live-src{margin-left:6px;font-size:var(--fs-xs);color:var(--faint);font-weight:400}',
      'td.hpdk-live-cell{color:var(--down);font-variant-numeric:tabular-nums}',
      /* R-hpdk-cancel-0929（用户批准 D）：竞价阶段「建议撤单」= 唯一需要动手的事 */
      'tr.hpdk-cancel{box-shadow:inset 3px 0 0 var(--warn);background:rgba(180,83,9,.07)}',
      '.hpdk-tag.cancel{background:var(--warn);color:#fff;margin-left:0;margin-right:6px;font-weight:600}',
      '.hpdk-tag.watch{background:transparent;border:1px dashed var(--warn);color:var(--warn)}'
    ].join('');
    document.head.appendChild(st);
  }

  /* ---------- 首次判定时间戳（localStorage，跨日按 HPDK.as_of 作废） ---------- */
  function loadRec(){
    var raw = null;
    try { raw = localStorage.getItem(CFG.LS); } catch(e) { return {}; }
    if (!raw) return {};
    var o = null;
    try { o = JSON.parse(raw); } catch(e) { return {}; }
    if (!o || typeof o !== 'object') return {};
    var out = {}, k, r;
    for (k in o) {
      if (!Object.prototype.hasOwnProperty.call(o, k)) continue;
      r = o[k];
      /* 跨日清空：资格池换信号日（as_of 变）→ 上一天的判定记录作废 */
      if (!r || typeof r !== 'object' || !r.first || r.as_of !== H.as_of) continue;
      out[k] = r;
    }
    return out;
  }
  function saveRec(t){ try { localStorage.setItem(CFG.LS, JSON.stringify(t)); } catch(e) {} }

  /* ---------- 列定位（按列头文本：整名优先、再包含 —— 同主盘中层 scan 的做法；找不到 → -1，退化为行内标签） ---------- */
  function hdrIdx(ths, names){
    var i, j, tx, hit = -1;
    for (i = 0; i < ths.length; i++) {
      tx = (ths[i].textContent || '').replace(/\s+/g, '');
      for (j = 0; j < names.length; j++) if (tx === names[j]) return i;
    }
    for (i = 0; i < ths.length; i++) {
      tx = (ths[i].textContent || '').replace(/\s+/g, '');
      for (j = 0; j < names.length; j++) if (tx.indexOf(names[j]) >= 0 && hit < 0) hit = i;
    }
    return hit;
  }
  function cols(tb){
    var ths = tb.querySelectorAll('thead th');
    NCOL = ths.length || 0;
    return {event: hdrIdx(ths, CFG.HDR_EVENT), buy: hdrIdx(ths, CFG.HDR_BUY),
            tp: hdrIdx(ths, CFG.HDR_TP), qty: hdrIdx(ths, CFG.HDR_QTY),
            cap: hdrIdx(ths, CFG.HDR_CAP), name: hdrIdx(ths, CFG.HDR_NAME)};
  }
  function colOf(key){ return (COLS && COLS[key] >= 0) ? COLS[key] : -1; }
  function cellAt(tr, idx){
    if (idx < 0 || !tr || !tr.children) return null;
    return tr.children[idx] || null;
  }
  /* 行内单元格：首次改写前快照原文 / 原排序键，之后每轮先还原（幂等 + 可逆的关键） */
  function snapCell(td){
    if (!td) return;
    if (td._hpdkOrig === undefined) {
      td._hpdkOrig = td.textContent || '';
      td._hpdkOrigV = td.getAttribute('data-v');
      td._hpdkOrigT = td.title || '';
      /* 构建期渲染的子节点（badge / div 结构）：整体留存，还原时放回 —— 只存 textContent 会把结构拍平 */
      td._hpdkKids = [];
      for (var i = 0; i < td.children.length; i++) td._hpdkKids.push(td.children[i]);
    }
  }
  function restoreCell(td){
    if (!td || td._hpdkOrig === undefined) return;
    if (td._hpdkKids && td._hpdkKids.length) {
      while (td.firstChild) td.removeChild(td.firstChild);      /* 清掉我们写的文本 / 标签 */
      for (var i = 0; i < td._hpdkKids.length; i++) td.appendChild(td._hpdkKids[i]);
    } else td.textContent = td._hpdkOrig;
    if (td._hpdkOrigV === null || td._hpdkOrigV === undefined) {
      if (td.removeAttribute) td.removeAttribute('data-v');
    } else td.setAttribute('data-v', td._hpdkOrigV);
    td.classList.remove('hpdk-live-cell');
  }
  function writeCell(tr, key, txt, title, dv){
    var td = cellAt(tr, colOf(key));
    if (!td) return null;
    snapCell(td);
    td.textContent = txt;
    if (title) td.title = title;
    if (dv !== undefined && dv !== null) td.setAttribute('data-v', String(dv));   /* 排序键同步（面板按 data-v 排） */
    if (!td.classList.contains('hpdk-live-cell')) td.classList.add('hpdk-live-cell');
    return td;
  }
  /* 行内小标签：事件列不存在时退化为标签（插到标的列行首；列也找不到 → 兜底插到本行末列） */
  function tagTo(tr, key, txt, cls, title, prepend){
    var td = cellAt(tr, colOf(key));
    if (!td && tr && tr.children && tr.children.length) td = tr.children[tr.children.length - 1];
    if (!td) return null;
    var sp = document.createElement('span');
    sp.className = 'hpdk-tag ' + (cls || '');
    sp.textContent = txt;
    if (title) sp.title = title;
    if (prepend && td.firstChild) td.insertBefore(sp, td.firstChild);
    else td.appendChild(sp);
    return sp;
  }
  /* 2026-09-27：行内标记统一入口 —— 有「状态」列就写列里（标的格保持干净），否则退回行内标签 */
  function tagInto(tr, txt, cls, tip){
    if (colOf('event') >= 0) return writeCell(tr, 'event', txt, tip, null);
    return tagTo(tr, 'name', txt, cls, tip, true);
  }
  function stripTags(tr){
    var ts = tr.querySelectorAll('.hpdk-tag'), i;
    for (i = 0; i < ts.length; i++) if (ts[i].parentNode) ts[i].parentNode.removeChild(ts[i]);
  }
  function resetRow(tr){
    tr.classList.remove('hpdk-buy'); tr.classList.remove('hpdk-keep'); tr.classList.remove('hpdk-cancel');
    if (tr.removeAttribute) tr.removeAttribute('data-hpdk');
    stripTags(tr);
    if (!COLS) return;
    var ks = ['event', 'buy', 'tp', 'qty', 'cap'], i;
    for (i = 0; i < ks.length; i++) restoreCell(cellAt(tr, colOf(ks[i])));
  }
  function codeOf(tr){
    var c = bare(tr.getAttribute('data-code') || '');
    if (!/^[0-9]{6}$/.test(c)) {
      var mm = (tr.textContent || '').match(/(?:^|\D)([0-9]{6})(?:\D|$)/);
      c = mm ? mm[1] : '';
    }
    return /^[0-9]{6}$/.test(c) ? c : '';
  }

  /* ---------- 判定：C（静态准入）→ B（可交易）→ A（低开带）→ F（排名字段） ----------
     返回 {k:'keep'|'drop'|'na', gate:'A'|'B'|'C'|'F'|'na', why, gap?}
     · k='na'（该码本次报价缺失 / 三个价格字段全无）→ **保守留存**：不剔除任何判不了的行（宁可漏剔，不可误剔）。 */
  function judge(m, d, refPx){
    /* R-hpdk-stlive-0929（勘误 E-20 · 用户批准 A 案）+ R-hpdk-name-0929（用户实测「002743 是 ST 也进了清单」）：
       **live frontier 按真名单剔 ST/退，且同时用「实时行情名」与「内嵌名」双源判定**。
       为什么双源：内嵌名来自 data_full_names.json，该文件长期不更新（实测停在 2026-08-17）
       ⇒ 002743 早已改名 **ST富煌**（东财 f14 / 腾讯 [1] 一致）却仍按「富煌钢构」放行。
       实时行情名 = 当下真名 ⇒ 任一源含 ST/退 即剔除（`_nmB`）。
       历史日没有点时名称数据 ⇒ 冻结判据仍只用代理 STP（E-19），本筛子只作用于 frontier，
       不改历史读数、不改冻结脚本 oos_run.py；与收盘链 hpdk_candidates.py 两侧同口径。 */
    var _nmB = String((m && m.name) || '') + '|' + String((d && d.name) || '');
    if (/ST/i.test(_nmB) || _nmB.indexOf('退') >= 0)
      return {k: 'drop', gate: 'ST', why: 'ST: 现行名称含 ST/退（' + _nmB.replace('|', ' / ') + '）'};
    var A20 = num(m && m.amt20), C = num(m && m.close);
    var minamt = numOr(H.minamt, 0), minpx = numOr(H.minpx, 0);
    if (!(A20 > 0 && A20 >= minamt - CFG.EPS))
      return {k: 'drop', gate: 'C', why: 'C: 20 日均额 ' + fmtWan(A20) + ' < ' + fmtWan(minamt)};
    if (!(C >= minpx - CFG.EPS))
      return {k: 'drop', gate: 'C', why: 'C: T 日收盘 ' + (isNaN(C) ? '缺失' : C.toFixed(2)) + ' < ' + minpx.toFixed(2)};
    var px = d ? num(d.px) : NaN, pcl = d ? num(d.pcl) : NaN, opn = d ? num(d.opn) : NaN;
    if (!(px > 0) && !(pcl > 0) && !(opn > 0)) return {k: 'na', gate: 'na', why: '无行情（保守留存）'};
    if (!(px > 0)) return {k: 'drop', gate: 'B', why: 'B: 无现价'};
    if (!(pcl > 0)) return {k: 'drop', gate: 'B', why: 'B: 无昨收'};
    /* R-hpdk-preauction-0930：竞价预备口径 —— 09:25 前没有真实今开，用「现价」= 集合竞价
       虚拟开盘参考价代 gap。只在 refPx=true（= preMode，09:15–09:25）时启用；**权威口径永远用
       真实今开**（refPx 为假时 _oeff === opn，逻辑与改动前逐字相同 ⇒ 零回归）。 */
    var _oeff = opn;
    if (refPx && !(opn > 0) && px > 0) _oeff = px;
    if (!(_oeff > 0)) return {k: 'drop', gate: 'B', why: 'B: 无今开（09:25 前 / 行情缺失）'};
    if ((opn > 0) && Math.abs(px - pcl) <= CFG.EPS && Math.abs(opn - pcl) <= CFG.EPS)
      return {k: 'drop', gate: 'B', why: 'B: 停牌/一字（现价=今开=昨收）'};
    if (refPx && !(opn > 0) && Math.abs(px - pcl) <= CFG.EPS)
      return {k: 'drop', gate: 'B', why: 'B: 参考价=昨收（无成交意愿/停牌）'};
    /* gap 用 **float32 复刻**冻结生产者的算术（2026-09-29 code review 修正，R-hpdk-gapf32-0929）：
       生产者面板 O/C 是 np.float32 ⇒ 其 gap 也是 float32 结果；前端拿到的是 float64 报价。
       直接相除会有 ~1e-7 级偏差，恰在带沿的标的会两侧判反（实测 2026-09-28：601020 华钰矿业
       gap 名义 −1.0000%：float32 得 −0.009999931（带外）、float64 得 −0.0099999…（带内））。
       上一版用「距上沿 < 1e-7 视为带外」是**猜测**且只补了上沿 ⇒ 改为逐字复刻：
         Math.fround(a)/Math.fround(b) 再 fround = float32 除法，随后 −1 在 float64 里做
         （与 numpy「float32 数组相除→float64 标量比较」一致）⇒ 两侧带沿都自动对齐。 */
    var gap = Math.fround(Math.fround(_oeff) / Math.fround(pcl)) - 1;
    var lo = numOr(H.gap_lo, -0.03), hi = numOr(H.gap_hi, -0.01);
    if (!(gap >= lo - CFG.EPS && gap <= hi + CFG.EPS))
      return {k: 'drop', gate: 'A', gap: gap,
              why: 'A: 今开/昨收−1 = ' + fmtPct(gap) + ' 不在 [' + fmtPct(lo) + ', ' + fmtPct(hi) + ']'};
    if (!(num(m.volbr) > 0)) return {k: 'drop', gate: 'F', gap: gap, why: 'F: 缺量比数据（算不出复合分）'};
    if (isNaN(num(m.ret20))) return {k: 'drop', gate: 'F', gap: gap, why: 'F: 缺 20 日涨幅数据（算不出复合分）'};
    return {k: 'keep', gap: gap};
  }
  /* ---------- 复合分：存活子集内横截面 z 标准化（生产者 :190-193 同式；np.nanstd = 总体标准差 ddof 0） ---------- */
  function score(keep){
    var i, n = keep.length, s1 = 0, s2 = 0, s3 = 0, d1 = 0, d2 = 0, d3 = 0, v, m1, m2, m3, sd1, sd2, sd3;
    for (i = 0; i < n; i++) {
      v = keep[i];
      v.x1 = -Math.log(num(v.m.amt20));        /* amt20 > 0 由判据 C 保证 */
      v.x2 = -Math.log(num(v.m.volbr));        /* volbr > 0 由判据 F 保证 */
      v.x3 = -num(v.m.ret20);                  /* ret20 是小数（−0.065 = 跌 6.5%）→ 取 z(−ret20) */
      s1 += v.x1; s2 += v.x2; s3 += v.x3;
    }
    m1 = n ? s1 / n : 0; m2 = n ? s2 / n : 0; m3 = n ? s3 / n : 0;
    for (i = 0; i < n; i++) {
      v = keep[i];
      d1 += (v.x1 - m1) * (v.x1 - m1);
      d2 += (v.x2 - m2) * (v.x2 - m2);
      d3 += (v.x3 - m3) * (v.x3 - m3);
    }
    sd1 = n ? Math.sqrt(d1 / n) : 0; sd2 = n ? Math.sqrt(d2 / n) : 0; sd3 = n ? Math.sqrt(d3 / n) : 0;
    for (i = 0; i < n; i++) {
      v = keep[i];
      v.z1 = sd1 > 0 ? (v.x1 - m1) / sd1 : 0;    /* 退化（子集内全同值）→ z = 0，与生产者 zs() 的 if sd>0 同口径 */
      v.z2 = sd2 > 0 ? (v.x2 - m2) / sd2 : 0;
      v.z3 = sd3 > 0 ? (v.x3 - m3) / sd3 : 0;
      v.F = v.z1 + v.z2 + v.z3;
    }
    return keep;
  }
  /* ---------- 卡片/表头徽标（自己的 pill；判定时段显示计数「已剔除 N 只 · 命中 M 只」） ---------- */
  function badge(live){
    var tb = document.getElementById(CFG.TBL);
    var card = (tb && tb.closest) ? tb.closest('.card') : null;
    var h2 = card ? card.querySelector('h2') : null;
    var bd = null;
    if (h2) {
      bd = h2.querySelector('.hpdk-badge');
      if (!bd) { bd = document.createElement('span'); bd.className = 'badge hpdk-badge'; h2.appendChild(bd); }
    } else {                                     /* 卡片结构不认识（模板改了）→ 退化为表前一条 pill */
      bd = document.getElementById('hpdk-live-badge');
      if (!bd) {
        bd = document.createElement('div'); bd.id = 'hpdk-live-badge'; bd.className = 'hpdk-badge';
        if (tb && tb.parentNode) tb.parentNode.insertBefore(bd, tb);
      }
    }
    var txt;
    if (!live)                       txt = '待行情（打开页面自动拉取）';
    else if (S.phase === 'open')     txt = '已剔除 ' + S.removed + ' 只 · 命中 ' + S.hit + ' 只';
    else if (S.phase === 'auction')  txt = '竞价预判中 · 09:25 后判定剔除';
    else if (S.phase === 'pre')      txt = '待今开判定（09:25 起）';
    else if (S.phase === 'past')     txt = '买日已过（' + (H.buy_date || '—') + '）';
    else                             txt = '待买日判定（买日 ' + (H.buy_date || '—') + '）';
    bd.textContent = txt;
    bd.title = CFG.TIP + ' · 口径：今开/昨收−1 ∈ [' + fmtPct(numOr(H.gap_lo, -0.03)) + ', ' + fmtPct(numOr(H.gap_hi, -0.01))
             + ']（闭区间）＋ 可交易（现价/昨收/今开 > 0 且非停牌一字）＋ 20 日均额 ≥ ' + fmtWan(numOr(H.minamt, 0))
             + ' ＋ 收盘 ≥ ' + numOr(H.minpx, 0).toFixed(2) + ' 元；取复合分 F 前 ' + numOr(H.k, 10) + ' 只（F 在**存活子集**内标准化）。';
    if (h2) {
      var srcEl = h2.querySelector('.hpdk-live-src');
      if (!srcEl) { srcEl = document.createElement('span'); srcEl.className = 'hpdk-live-src'; h2.appendChild(srcEl); }
      srcEl.textContent = live
        ? ('刷新于 ' + (S.ts || '—') + ' · 源 ' + (S.src || '—') + (S.mktDate ? ' · 行情日 ' + S.mktDate : '')
           + (H.buy_date ? ' · 买日 ' + H.buy_date : ''))
        : '待行情';
      srcEl.title = CFG.TIP;
    }
  }

  /* ---------- 主流程（幂等：每轮先还原再判定 → 重复刷新不叠加、不重复计数） ---------- */
  /* R-hpdk-pooltop-0929：把「盘前选股池」（明日买点准备清单整段）搬到卡片**最上方**并**默认折叠**。
     用户 2026-09-29：① 存档不要放在最上面，选股池放在最上面；② 批准默认折叠；③ 清单表头照旧。
     幂等：只在首次创建 #hpdk-pool-box；找不到池子段落时零动作（卡片改版也不会炸）。 */
  function poolTop(){
    var sec = document.getElementById('hpdk-pool-sec');
    var top = document.getElementById('hpdk-live-top');
    if (!sec || !top || !top.parentNode) return;
    if (document.getElementById('hpdk-pool-box')) return;
    var box = document.createElement('details');
    box.id = 'hpdk-pool-box';
    box.className = 'sub';
    box.style.margin = '8px 0 2px';
    var sm = document.createElement('summary');
    sm.style.cursor = 'pointer';
    var nrow = sec.querySelectorAll('tbody tr').length;
    sm.innerHTML = '<b>\u{1F4CB} 盘前选股池</b>（资格池 <b>' + ((H.rows || []).length) + '</b> 只 · 本表渲染 ' + nrow
      + ' 行 · 盘前代理分序 · <b>不是买入名单</b>）— 点开查看 / 搜索 / 排序';
    box.appendChild(sm);
    var note = document.getElementById('hpdk-pool-note');
    top.parentNode.insertBefore(box, top);      /* 池子放最上面：唯一买入清单紧随其后 */
    if (note) box.appendChild(note);
    box.appendChild(sec);
  }
  function render(q, ts, src, mktTs){
    var tb = document.getElementById(CFG.TBL);
    if (!tb) return null;                     /* 表不在本页（未渲染）→ 什么都不做（首屏也会走到这里） */
    var body = tb.querySelector('tbody');
    if (!body) return null;
    css();
    if (ts) S.ts = ts;
    if (src) S.src = src;
    if (mktTs) S.mktTs = mktTs;
    var live = false, k;
    for (k in q) { if (Object.prototype.hasOwnProperty.call(q, k)) { live = true; break; } }
    S.live = live;
    if (live) S.calls++;
    var mkt = mktOf(S.mktTs);
    S.mktDate = mkt ? mkt.date : ''; S.mmin = mkt ? mkt.min : -1;
    var buy = String(H.buy_date || '');
    /* 闸门 = 唯一开关（用**交易所时间戳**，不用本地日期）：只有「行情日 === 买日 且 时刻 ≥ 09:25」才剔除 */
    var enforce = !!(live && mkt && buy && mkt.date === buy && mkt.min >= CFG.OPEN_MIN);
    S.fallback = false;
    /* R-hpdk-fallback-0929：**交易所时间戳缺失时用本地时钟兜底**（日期=买日 且 本地 ≥09:26）。
       根因：探测接口（qt.gtimg 指数）偶发失败 ⇒ mktTs 空 ⇒ enforce 永假 ⇒ 清单**整个消失**（用户实测）。
       判据不变（gap 带 / 可交易 / 准入件），只是不再让「一个辅助请求失败」决定清单是否存在。
       09:26 这个下限保证开盘前（09:15–09:25 竞价）仍不剔除、不误判。 */
    if (!enforce && live && buy && !mkt) {
      var _now = new Date(), _lmin = _now.getHours() * 60 + _now.getMinutes();
      if (ymd(_now) === buy && _lmin >= (9 * 60 + 26)) { enforce = true; S.fallback = true; }
    }
    S.gate = enforce;
    S.phase = phaseOf(mkt, buy);
    S.rows = 0; S.removed = 0; S.hit = 0; S.kept = 0; S.noquote = 0; S.diag = []; S.err = '';
    if (!COLS) COLS = cols(tb);
    if (!ORDER) {                            /* 首次抓原始行序（= 盘前代理分序，勿动） */
      ORDER = [];
      var all = body.querySelectorAll('tr');
      for (var a = 0; a < all.length; a++) ORDER.push(all[a]);
    }
    /* ① 还原：摘置顶分组行 → 按 ORDER 复位行序 → 摘类 / 摘标签 / 复位写过的单元格 */
    var oldHdr = body.querySelector('tr.hpdk-buy-hdr');
    if (oldHdr && oldHdr.parentNode) oldHdr.parentNode.removeChild(oldHdr);
    for (var o = 0; o < ORDER.length; o++) { body.appendChild(ORDER[o]); resetRow(ORDER[o]); }
    /* ② 逐行判定（还没行情 → 只建徽标，不判不剔） */
    var rec = TV || (TV = loadRec()), changed = false;
    var keepRank = [], keepNa = [], drops = [], pend = [], i;
    for (i = 0; i < ORDER.length; i++) {
      var tr = ORDER[i], code = codeOf(tr), m = META[code];
      if (!m) continue;                      /* 不在资格池内嵌行（过滤器提示行等）→ 一行不动 */
      S.rows++;
      if (!live) { S.noquote++; continue; }
      if (!enforce) { pend.push({tr: tr, code: code}); continue; }   /* 盘前 / 竞价 / 非买日：只灰标，绝不剔除 */
      var v = judge(m, q[code]);
      if (!q[code]) S.noquote++;
      if (v.k === 'keep') keepRank.push({tr: tr, code: code, m: m, gap: v.gap});
      else if (v.k === 'na') keepNa.push({tr: tr, code: code, m: m});
      else drops.push({tr: tr, code: code, m: m, v: v});
    }
    /* ③ 剔除（只在 enforce 时）：把不达标行**从表格摘掉**，不是置灰 */
    for (i = 0; i < drops.length; i++) {
      var dr = drops[i];
      if (dr.tr.parentNode) dr.tr.parentNode.removeChild(dr.tr);
      S.diag.push({code: dr.code, gate: dr.v.gate, gap: (dr.v.gap === undefined ? null : dr.v.gap), why: dr.v.why});
      if (!rec[dr.code]) {                   /* 首次判定时间戳（此后永不覆盖） */
        rec[dr.code] = {first: ymd(new Date()) + ' ' + hms(new Date()), kind: 'drop', gate: dr.v.gate,
                        why: dr.v.why, as_of: H.as_of, buy_date: buy};
        changed = true;
      }
    }
    S.removed = drops.length;
    /* ④ 存活者排名（存活子集内 z 标准化）→ 取前 k 只置顶 + 写入单元格 */
    score(keepRank);
    keepRank.sort(function(X, Y){ return (Y.F !== X.F) ? (Y.F - X.F) : (X.m.i - Y.m.i); });  /* 同分按资格池原序 */
    /* K 真值源（2026-09-29 严审修正）：payload 顶层有 k（= 冻结 params.K 的镜像，实测 =10），
       但 params 本身被构建期裁剪掉了 ⇒ 本条改为「优先 params.K、回退顶层 k、最后 10」，
       避免任一来源被裁剪时静默用错名单长度（原写法只读 H.k，一旦裁剪即无保护）。 */
    var K = numOr((H.params && H.params.K), numOr(H.k, 10)); if (!(K >= 1)) K = 10;
    var slot = numOr(H.capital, 0) / Math.max(1, numOr(H.kslot, 1));    /* 单票分配上限 = 本金 / KSLOT */
    var top = keepRank.slice(0, K);
    for (i = 0; i < top.length; i++) {
      var it = top[i], dq = q[it.code] || {}, opn = num(dq.opn);
      var amt = num(it.m.amt20), capv = amt * CFG.ADV_FRAC, alloc = Math.min(slot, capv);
      var qty = (opn > 0 && alloc > 0) ? Math.floor(alloc / opn / 100) * 100 : 0;
      var tpPx = opn * (1 + numOr(H.tp, 0.02));
      var limited = capv < slot - CFG.EPS;                 /* 该股 ADV×1% 放不满单票分配 → 容量受限 */
      var tip = 'F = ' + it.F.toFixed(3) + '（z: ' + it.z1.toFixed(2) + ' / ' + it.z2.toFixed(2) + ' / ' + it.z3.toFixed(2)
              + '）· 今开/昨收−1 = ' + fmtPct(it.gap) + ' · 20 日均额 ' + fmtWan(amt)
              + ' · 单票分配 ' + alloc.toFixed(0) + ' 元（min(本金/KSLOT=' + slot.toFixed(0) + ', ADV×1%=' + capv.toFixed(0) + ')）'
              + ' · 买日 ' + (buy || '—') + '；' + CFG.TIP;
      /* R-hpdk-onelist-0929：**表内不再给序号、不再置顶**。
         用户 2026-09-29 实测：表内「✅今日买入候选 #1..#10」来自「窗内 600 行重排名」，
         与全池清单只重合 9/10、序号也不同 ⇒ 被读成**第三个买入口径**。序号只属于卡片最上方
         的「今日买入清单」（全池判定 · 唯一）。本表降级为**盘前准备视图**：只做过滤与字段回填。 */
      tagInto(it.tr, '\u2705 在清单内', 'buy', tip);
      if (colOf('buy') >= 0) writeCell(it.tr, 'buy', opn.toFixed(3), tip, opn);
      if (colOf('tp') >= 0) writeCell(it.tr, 'tp', tpPx.toFixed(3), tip, Math.round(tpPx * 1000) / 1000);
      if (colOf('qty') >= 0) writeCell(it.tr, 'qty', fmtQty(qty), tip, qty);
      if (colOf('cap') >= 0) writeCell(it.tr, 'cap', limited ? ('限至 ' + fmtWan(capv)) : '足额',
        '单票可买 = min(本金/KSLOT, 该股 20日均额×1%)。' + (limited
          ? '**标「限」不是不能买**：该股流动性只装得下 ' + fmtWan(capv) + '，装不满计划额 '
            + fmtWan(slot) + '，所以少买一点 —— 「建议股数」已按缩小后的规模折算好。'
          : '该股 20日均额×1% = ' + fmtWan(capv) + ' ≥ 计划额 ' + fmtWan(slot) + '，可按计划额足额买入。')
        + '；' + CFG.TIP, limited ? 0 : 1);
      it.tr.classList.add('hpdk-buy');
      it.tr.setAttribute('data-hpdk', 'buy');
      if (!rec[it.code]) {
        rec[it.code] = {first: ymd(new Date()) + ' ' + hms(new Date()), kind: 'keep', as_of: H.as_of, buy_date: buy};
        changed = true;
      }
    }
    /* ⑤ 存活但未入选（F 排名在 k 之后）：细左条 + 灰标签，不置顶 */
    for (i = K; i < keepRank.length; i++) {
      var it2 = keepRank[i];
      it2.tr.classList.add('hpdk-keep');
      tagInto(it2.tr, '留存（未入清单）', 'keep',
            'F = ' + it2.F.toFixed(3) + '，本日不在清单内：窗内代理分排位在 k=' + K + ' 之后。'
            + '仍留在表里，但**它不是买入候选**。' + CFG.TIP, true);
    }
    /* ⑥ 判定不明的行（本次报价缺失该码）：保守留存 + 灰标签（绝不因「没数据」剔除） */
    for (i = 0; i < keepNa.length; i++)
       tagInto(keepNa[i].tr, '待行情（保守留存）', 'pre',
             '本次报价缺该码 → 不剔除（宁可漏剔，不可误剔）。' + CFG.TIP, true);
    S.kept = keepRank.length + keepNa.length;
    S.hit = top.length;
    /* ⑦ 说明行（**不再置顶任何行**）：本表 = 盘前准备视图；唯一买入清单 = 卡片最上方 */
    var hr = document.createElement('tr');
    hr.className = 'hpdk-buy-hdr';
    hr.innerHTML = '<td colspan="' + (NCOL || 14) + '">\u26a1 盘前准备视图（本表只渲染 ' + S.rows + ' 行）'
      + ' · 盘中已按真实今开过滤：剔除 ' + S.removed + ' 只 · 留存 ' + (S.kept || 0) + ' 只'
      + ' · 其中在清单内 ' + top.length + ' 只'
      + '<br><b>买入口径只有一个：卡片最上方的「今日买入清单」</b>（全池 '
      + (S.pool ? S.pool + ' 只' : '—') + ' 判定 · 09:25 首算即冻结）。'
      + '本表行序是**盘前代理分**、只渲染 600 行、**不是买入口径**。</td>';
    body.insertBefore(hr, body.firstChild);
    /* ⑦b 全池口径复算（2026-09-28，R-hpdk-fullpool-0928）——**权威口径对照条**：
       DOM 只渲染 RENDER_N=600 行，②/④ 的判定与 F 排名都只能在这个窗内做 ⇒ 会少报：
       2026-09-28 实测全池命中 146 只、窗内仅 3 只；窗内重排名还把真 F#7 融捷股份排成 #1，
       而真 F#2 浙江自然因代理分排第 601 位掉出窗、连判定都没做（今开跳空 −1.07% 其实在带内）。
       META 覆盖**整个资格池**，这里用全池复算一遍，只把「命中数 + F 前 K 买入名单」写成表上
       方一条；**不动任何 DOM 行**（置顶/剔除/标灰行为与原来完全一致，零回归风险）。 */
    /* 2026-09-29 严审修正（用户报「9:25 后买入名单一直在变，3 只 / 10 只两套口径」）：
       ① 分母不同：本条的存活子集 = **整个资格池 META**，而下方表格 = 只渲染的 RENDER_N=600 行
          ⇒ 两个「命中数」天然不同（实测：本条 10 只 vs 表头 3 只）。现在把两者的口径写成同一句。
       ② 报价覆盖每轮变：盘中层只对「有报价的行」取到 px/pcl/opn，拿不到报价的行判为 na
          （保守留存、不计命中）⇒ 命中数与名单随刷新漂移。现在显式统计并展示「缺报价 X 只」。
       ③ 09:25 后开盘价已冻结 ⇒ 命中集合本应确定。本条在 enforce（= 买日且 ≥09:25）时**首算即冻结**
          （localStorage 按 buy_date 存），此后刷新只读冻结值 ⇒ 名单不再变；换日自动作废。
       （现价 px 仍参与 B 闸「停牌/一字」，这是冻结判据本身的口径，保留不动——但它只影响极少数票。）
    */
    /* 冻结键：09:25 后开盘价已定 ⇒ 命中集合确定，首算即冻结（按 buy_date 存），刷新只读冻结值。 */
    /* 冻结键**升版 v2**（2026-09-29）：v1 里可能存着「残缺报价冻结」的名单（且无价格快照 ⇒ 全「—」），
       升版即作废旧值，浏览器下次加载自动重算 —— 不再需要用户手动清缓存。 */
    var FPKEY = 'quant_hpdk_fp_v3';
    function loadFP(){
      try { var a = JSON.parse(localStorage.getItem(FPKEY));
            return (a && String(a.buy_date) === String(H.buy_date || '')) ? a : null; }
      catch (e) { return null; }
    }
    function saveFP(o){ try { localStorage.setItem(FPKEY, JSON.stringify(o)); } catch (e) {} }
    /* R-hpdk-preauction-0930：竞价预备清单独立键 —— **不参与权威冻结**，只用于 09:25 后的对拍
       （算现场参考价误差 σ）。与权威键分开，避免预判污染 09:25 那份必须稳定的名单。 */
    var PREKEY = 'quant_hpdk_pre_v1';
    function loadPRE(){
      try { var a = JSON.parse(localStorage.getItem(PREKEY));
            return (a && String(a.buy_date) === String(H.buy_date || '')) ? a : null; }
      catch (e) { return null; }
    }
    function savePRE(o){ try { localStorage.setItem(PREKEY, JSON.stringify(o)); } catch (e) {} }
    var FP = null, FPfrozen = false;
    /* R-hpdk-preauction-0930（用户 2026-09-29 批准 · C 案）：**09:15–09:25 竞价预备清单**。
       用户要求「09:15 起实时更新买入清单、不锁定，09:25 前从里面挑 TOP4 挂单」。
       口径：用行情「现价」= 集合竞价虚拟开盘参考价 代替今开算 gap ⇒ 带内预判集合 → F 前 K。
       它不是权威口径：不落 FPKEY 冻结、09:25 一到立即切回真实今开清单（并按 PREKEY 做对拍）。
       交易所时间戳缺失时用本地时钟兜底（与 enforce 的 fallback 同思路，见 R-hpdk-fallback-0929）。 */
    var _preMin = -1, _preDate = '';
    if (mkt) { _preMin = mkt.min; _preDate = mkt.date; }
    if (!(live && buy && _preDate === buy && _preMin >= (9 * 60 + 15) && _preMin < CFG.OPEN_MIN)) {
      var _n2 = new Date(), _l2 = _n2.getHours() * 60 + _n2.getMinutes();
      if (live && buy && ymd(_n2) === buy && _l2 >= (9 * 60 + 15) && _l2 < CFG.OPEN_MIN) {
        _preMin = _l2; _preDate = buy;
      }
    }
    var preMode = !!(live && buy && _preDate === buy && _preMin >= (9 * 60 + 15) && _preMin < CFG.OPEN_MIN);
    S.preMode = preMode;
    try {
      if (live && (enforce || preMode)) {
        /* R-hpdk-upgrade-0929：**覆盖率升级闸**。冻结值带 cov；若当前报价覆盖比冻结时
           **显著更好（> +10pp）**，说明冻结那份是「数据不全时算的」（线上实测：70% 覆盖就冻死 ⇒
           可能有票因缺报价而没进名单）⇒ 重算并覆盖；否则维持冻结（名单不再漂移）。
           收敛性：覆盖涨到饱和后差值 <10pp ⇒ 不再重算 ⇒ 稳定。 */
        var keys = [], kk;
        for (kk in META) { if (Object.prototype.hasOwnProperty.call(META, kk)) keys.push(kk); }
        var _hit0 = 0, _j0;
        for (_j0 = 0; _j0 < keys.length; _j0++) { var _q0 = q[keys[_j0]]; if (_q0 && num(_q0.px) > 0) _hit0++; }
        var _covNow = Math.round(100 * _hit0 / Math.max(1, keys.length));
        /* R-hpdk-preauction-0930：竞价预备口径**必须实时重算**（09:15–09:24 参考价逐秒在动），
           绝不复用 09:25 之后那份权威冻结值。 */
        FP = preMode ? null : loadFP();
        if (FP && (FP.cov === null || FP.cov === undefined || _covNow <= (FP.cov + 10))) {
          FPfrozen = true;                    /* 数据没有明显变好 → 用冻结值 */
        } else {
          FP = null;                          /* 没有冻结值 / 覆盖显著改善 → 重算 */
        }
        if (!FP) {
          var sur = [], miss = 0, j2;
          for (j2 = 0; j2 < keys.length; j2++) {
            var qq = q[keys[j2]];
            if (!qq) miss++;
            var vv = judge(META[keys[j2]], qq, preMode);
            if (vv.k === 'keep') sur.push({code: keys[j2], m: META[keys[j2]], gap: vv.gap});
          }
          score(sur);
          sur.sort(function(X, Y){ return (Y.F !== X.F) ? (Y.F - X.F) : (X.m.i - Y.m.i); });
          FP = {buy_date: String(H.buy_date || ''), pool: keys.length, hits: sur.length,
                k: K, prov: preMode, ref_ts: preMode ? S.mktTs : null,
                /* R-hpdk-top-0929：把**判定当时的报价快照**一并冻结进名单 —— 冻结帧读回时价格列
                   才是「首算那一刻」的值（否则会拿刷新后的实时价去配一份已冻结的名单，自相矛盾）。 */
                top: sur.slice(0, K).map(function(x){
                       var _d = q[x.code] || {};
                       return {code: x.code, name: x.m.name || '', px: num(_d.px), pct: num(_d.pct),
                               opn: num(_d.opn), pcl: num(_d.pcl), gap: x.gap}; }),
                cov: _covNow, ts: ymd(new Date()) + ' ' + hms(new Date())};
          /* R-hpdk-freeze-0929：**报价覆盖 ≥50% 才允许落冻结** —— 线上实测事故：首算发生在
             10:00:42、当时只拿到 17 条报价 ⇒ 把「命中 3 只」冻成了名单，报价到齐后也不再变
             （用户看到的就是 3 行全是「—」的清单）。覆盖不足 ⇒ 只用于本次渲染，不落盘。 */
          /* R-hpdk-preauction-0930：竞价预备口径**不落权威冻结**（它只是预判，09:25 会变）；
             改存 PREKEY，供 09:25 后做「预判 vs 实测」对拍。 */
          if (preMode) { if (_covNow >= 50) savePRE(FP); }
          else if (_covNow >= 50) { saveFP(FP); FPfrozen = true; }
        }
      }
    } catch (e) { FP = null; S.err = String(e && e.message || e); }
    /* R-hpdk-top-0929：把「今日买入清单」渲染到卡片**最上方**的专属容器 #hpdk-live-top。
       用户 2026-09-29 反馈：① 同屏两个买入口径（权威条 vs 表格）到底看哪个；② 要图3那种
       「只列买入清单」的看法且要置顶。⇒ 原内联「权威条」取消，全卡**只保留这一个买入口径**，
       并把清单以表格形式放到卡片顶部。冻结语义（09:25 首算即冻结）原样保留。 */
    var topEl = document.getElementById('hpdk-live-top');
    var escH = function(s){
      return String(s === null || s === undefined ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    };
    /* R-hpdk-persist-top-0930（用户 2026-09-30 要求清单常驻）：表头**单一真值源** ——
       常驻骨架（无清单时）与真实清单共用同一份，避免两处 thead 漂移。共 17 列。 */
    var TOPTHEAD = '<thead><tr>'
        + '<th style="text-align:center">#</th><th>标的</th>'
        + '<th style="text-align:center">状态</th><th>板块</th><th>行业</th>'
        + '<th data-key="px" style="text-align:right">现价 <span class="live-tag">实时</span></th>'
        + '<th data-key="chg" style="text-align:right">涨跌幅 <span class="live-tag">实时</span></th>'
        + '<th data-key="amt" style="text-align:right">成交额20</th>'
        + '<th data-key="vr" style="text-align:right">量比</th>'
        + '<th data-key="r20" style="text-align:right">20日涨幅</th>'
        + '<th data-key="pcl" style="text-align:right">昨收价</th>'
        + '<th data-key="buy" style="text-align:right">挂单价 <span class="live-tag">昨收×0.99</span></th>'
        + '<th style="text-align:right">成交价 <span class="live-tag">今开</span></th>'
        + '<th data-key="tp" style="text-align:right">止盈价 +2%</th>'
        + '<th style="text-align:center">卖出时点</th>'
        + '<th data-key="qty" style="text-align:right">建议股数</th>'
        + '<th data-key="cap" style="text-align:center">单票可买（上限）</th>'
        + '</tr></thead>';
    if (topEl) {
      if (FP) {
        var _k3 = FP.top.length, _i3, _h3 = '', _ADV = numOr(CFG.ADV_FRAC, 0.01);
        var _slot = numOr(H.capital, 0) / Math.max(1, numOr(H.kslot, 1));
        _h3 += '<div class="sub" style="border-left:3px solid var(--warn);padding-left:8px;margin:0 0 8px">'
            +  '<b>今日买入清单（全池判定 · 本卡唯一买入口径）</b> · 买日 <b>' + (H.buy_date || '—') + '</b>'
            +  '（信号日 ' + (H.as_of || '—') + '）· 资格池 <b>' + FP.pool + '</b> 只 → 命中 <b>' + FP.hits + '</b> 只'
            +  ' · <b>报价覆盖 ' + (FP.cov === null || FP.cov === undefined ? '—' : FP.cov + '%')
            +  '</b>（缺报价 ' + (FP.missing || 0) + ' 只未判定）'
            +  ' · 名单 = F 前 ' + FP.k + '（本次 ' + _k3 + ' 只）'
            +  (FPfrozen ? (' · <b>09:25 后已冻结</b>（' + escH(FP.ts) + ' 首算，名单不再变）') : '')
            +  (S.fallback ? ' · <span style="color:var(--warn)">时间戳源不可用：已按本地时钟兜底</span>' : '')
            +  '｜现行 ST/退 按名称剔除</div>';
        /* R-hpdk-preauction-0930（用户 2026-09-29 批准）：竞价预备口径的说明 + 09:25 后的「预判 vs 实测」对拍。
           对拍口径：PRE.top 的 px = 09:15–09:25 参考价，FP.top 的 opn = 09:25 真实开盘价；
           对**同时在两份名单里**的票算 |参考价/昨收 − 今开/昨收| —— 这就是现场测得的参考价误差 σ。 */
        if (FP.prov) {
          _h3 += '<div class="sub" style="color:var(--warn);margin-top:6px">'
              +  '\u26a1 <b>竞价预备口径</b>：09:15\u201309:25 还没有真实今开，本清单用行情「现价」'
              +  '（= 集合竞价虚拟开盘参考价）代替今开算 gap \u21d2 带内预判集合 \u2192 F 前 ' + FP.k + '。'
              +  '<b>它不是权威口径、不落冻结</b>；09:25 撮合出真实开盘价后立即切回权威清单，'
              +  '届时此处会显示「预判 vs 实测」的重合度与参考价平均偏差。</div>';
        } else {
          var _PL = loadPRE();
          if (_PL && String(_PL.buy_date) === String(H.buy_date || '') && _PL.top && _PL.top.length) {
            var _cf = {}, _ci, _ov = 0, _devs = [];
            for (_ci = 0; _ci < FP.top.length; _ci++) _cf[FP.top[_ci].code] = FP.top[_ci];
            for (_ci = 0; _ci < _PL.top.length; _ci++) {
              var _pk = _PL.top[_ci], _tf = _cf[_pk.code];
              if (_tf) _ov++;
              if (_tf && num(_pk.px) > 0 && num(_pk.pcl) > 0 && num(_tf.pcl) > 0 && num(_tf.opn) > 0)
                _devs.push(Math.abs(num(_pk.px) / num(_pk.pcl) - num(_tf.opn) / num(_tf.pcl)) * 100);
            }
            var _dev = _devs.length ? (_devs.reduce(function(a, b){ return a + b; }, 0) / _devs.length) : NaN;
            _h3 += '<div class="sub" style="color:var(--faint);margin-top:6px">'
                +  '\u2696 <b>竞价预判对拍</b>（09:15\u201309:25 参考价口径 vs 09:25 真实今开）：'
                +  '名单重合 <b>' + _ov + ' / ' + FP.k + '</b>'
                +  ' · 参考价平均偏差 <b>' + (isNaN(_dev) ? '\u2014' : _dev.toFixed(3) + '%') + '</b>'
                +  '（n=' + _devs.length + '）'
                +  ' · 预判命中 <b>' + (_PL.hits === null || _PL.hits === undefined ? '\u2014' : _PL.hits) + '</b> 只'
                +  '｜按实测 σ 查滑价曲线：\u22640.1% \u2248 损失 11%，\u22640.2% \u2248 损失 28%</div>';
          }
        }
        if (!_k3) {
          _h3 += '<div class="sub" style="color:var(--faint)">本次判定范围内无命中'
              +  (FP.missing ? ('（' + FP.missing + ' 只缺报价，未判定）') : '') + '。</div>';
          /* R-hpdk-persist-top-0930：无命中时也给出**完整表头**（0 行是正常结果，不是故障）。 */
          _h3 += '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-buylist" style="width:100%;font-size:12px">'
              +  TOPTHEAD
              +  '<tbody><tr><td colspan="17" style="color:var(--faint);padding:8px 0">'
              +  '（本次判定范围内无命中 \u2014 名单为空是正常结果）</td></tr></tbody></table></div>';
        } else {
          _h3 += '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-buylist" style="width:100%;font-size:12px">'
              +  TOPTHEAD + '<tbody>';
          for (_i3 = 0; _i3 < _k3; _i3++) {
            var _x3 = FP.top[_i3], _c3 = bare(_x3.code), _d3 = q[_c3] || {}, _m3 = META[_c3] || {};
            var _px = num(_d3.px);  if (!(_px > 0)) _px = num(_x3.px);
            var _pc = num(_d3.pct);
             var _op = num(_d3.opn); if (!(_op > 0)) _op = num(_x3.opn);
             /* 挂单价 = 昨收 × 0.99（冻结参数 P1=0.01 ⇒ 上沿）。优先用冻结快照里的昨收，
                否则退回实时报价的昨收。这就是「推荐买入价」—— 前一晚可挂、且自动把关上沿。
                变量名必须用 _ordpx：_lim 已被后面「限仓布尔」占用（曾撞名 ⇒ 显示 0.000）。 */
             var _pcl0 = num(_x3.pcl); if (!(_pcl0 > 0)) _pcl0 = num(_d3.pcl);
             var _ordpx = _pcl0 > 0 ? (_pcl0 * (1 + numOr(H.gap_hi, -0.01))) : NaN;
            var _amt = num(_m3.amt20), _vr = num(_m3.volbr), _r20 = num(_m3.ret20);
            var _tp = _op > 0 ? _op * (1 + numOr(H.tp, 0.02)) : NaN;
            var _capv = _amt > 0 ? _amt * _ADV : NaN;
            var _alloc = Math.min(_slot, _capv);
            var _qty = (_op > 0 && _alloc > 0) ? Math.floor(_alloc / _op / 100) * 100 : 0;
            var _lim = isFinite(_capv) && _capv < _slot - CFG.EPS;
            var _pcTxt = isNaN(_pc) ? '—' : ((_pc > 0 ? '+' : '') + Number(_pc).toFixed(2) + '%');
            var _pcCol = isNaN(_pc) ? 'var(--sub)' : (_pc > 0 ? 'var(--up)' : (_pc < 0 ? 'var(--down)' : 'var(--sub)'));
            var _r20Txt = isNaN(_r20) ? '—' : ((_r20 > 0 ? '+' : '') + (_r20 * 100).toFixed(2) + '%');
            _h3 += '<tr data-code="' + _c3 + '" data-search="' + escH((_x3.name || '') + ' ' + _c3 + ' '
                    + (_m3.board || '') + ' ' + (_m3.ind || '')) + '">'
                +  '<td style="text-align:center">' + (_i3 + 1) + '</td>'
                +  '<td><b>' + escH(_x3.name || _c3) + '</b><br><span style="color:var(--sub);font-size:var(--fs-xs)">'
                +  escH(_c3) + '</span></td>'
                +  '<td style="text-align:center"><span class="badge badge-auto">\u2705 买入候选</span></td>'
                +  '<td style="color:var(--sub)">' + escH(_m3.board || '—') + '</td>'
                +  '<td style="color:var(--sub)">' + escH(_m3.ind || '—') + '</td>'
                +  '<td data-key="px" class="live-cell" style="text-align:right;font-variant-numeric:tabular-nums">'
                +  (_px > 0 ? Number(_px).toFixed(2) : '—') + '</td>'
                +  '<td data-key="chg" class="live-cell" data-v="' + (isNaN(_pc) ? '' : _pc.toFixed(2))
                +  '" style="text-align:right;color:' + _pcCol + ';font-variant-numeric:tabular-nums">' + _pcTxt + '</td>'
                +  '<td data-key="amt" data-v="' + (isNaN(_amt) ? '' : _amt) + '" style="text-align:right">'
                +  fmtWan(_amt) + '</td>'
                +  '<td data-key="vr" data-v="' + (isNaN(_vr) ? '' : _vr) + '" style="text-align:right">'
                +  (isNaN(_vr) ? '—' : Number(_vr).toFixed(2)) + '</td>'
                +  '<td data-key="r20" data-v="' + (isNaN(_r20) ? '' : _r20) + '" style="text-align:right;color:'
                +  (isNaN(_r20) ? 'var(--faint)' : (_r20 > 0 ? 'var(--up)' : 'var(--down)')) + '">' + _r20Txt + '</td>'
                 /* R-hpdk-ordpx-0929（用户 2026-09-29 明确要求）：**推荐买入价 = 昨收×0.99** ——
                    那才是你前一晚能挂进券商的下单价（也是上沿自动把关的那条限价）。
                    「成交价」另列 = 今开（09:25 撮合价），它才是止盈的基准（冻结规则：止盈 = 实际成交价×1.02）。
                    两列并列的原因：挂单价 = 你控制的；成交价 = 市场给的（≤ 挂单价）。 */
                  +  '<td data-key="pcl" data-v="' + (isNaN(_pcl0) ? '' : _pcl0) + '" style="text-align:right;font-variant-numeric:tabular-nums">'
                  +  (isNaN(_pcl0) ? '—' : Number(_pcl0).toFixed(3)) + '</td>'
                  +  '<td data-key="buy" data-v="' + (isNaN(_ordpx) ? '' : _ordpx) + '" style="text-align:right;font-variant-numeric:tabular-nums">'
                 +  (isNaN(_ordpx) ? '—' : Number(_ordpx).toFixed(3))
                 +  '<div style="margin-top:3px;font-size:var(--fs-xs);color:var(--faint)">限价（上沿）</div></td>'
                 +  '<td style="text-align:right;font-variant-numeric:tabular-nums">'
                 +  '<span class="badge badge-auto">● 今开成交</span>'
                 +  '<div style="margin-top:3px"><b>' + (_op > 0 ? Number(_op).toFixed(3) : '—') + '</b></div></td>'
                +  '<td data-key="tp" style="text-align:right;color:var(--up);font-variant-numeric:tabular-nums">'
                +  (isNaN(_tp) ? '—' : Number(_tp).toFixed(4)) + '</td>'
                +  '<td style="text-align:center;color:var(--sub)">T+2<br>' + escH(H.exit_date || '—') + ' 尾盘</td>'
                +  '<td data-key="qty" data-v="' + _qty + '" style="text-align:right;font-variant-numeric:tabular-nums">'
                +  fmtQty(_qty) + '</td>'
                +  '<td data-key="cap" style="text-align:center">'
                +  (_lim ? ('<span style="color:var(--warn)">限至 ' + fmtWan(_capv) + '</span>') : '足额') + '</td>'
                +  '</tr>';
          }
          _h3 += '</tbody></table>'
              +  '<div class="sub" style="color:var(--faint);margin-top:4px">'
               +  '<b>挂单价 = 昨收 × 0.99</b>（前一晚可挂；<b>上沿由限价自动把关</b> —— '
               +  '开盘高于它的本就不成交）· <b>成交价 = 今开</b>（09:25 撮合价，必定 ≤ 挂单价）· '
               +  '<b>止盈 = 成交价 ×1.02</b>（冻结规则：基准 = <b>实际成交价</b>，不是挂单价）· '
               +  '单票可买 = min(本金/KSLOT=' + fmtWan(_slot) + ', 20日均额×1%)'
               +  '<br><span style="color:var(--warn)">⚠ 下单：挂单价按分位<b>向上取整</b>（宁可高一分，'
               +  '否则会漏掉刚好在带内的票；实测上沿略放宽反而略优）· '
               +  '<b>09:25 撮合后立刻撤掉未成交挂单</b>（否则盘中跌到挂单价会意外成交）</span></div></div>';
        }
        topEl.innerHTML = _h3;
        TOPCACHE.buy = String(H.buy_date || ''); TOPCACHE.html = _h3;
      } else if (TOPCACHE.buy && TOPCACHE.buy === String(H.buy_date || '')) {
        /* R-hpdk-keep-0929：FP 本轮为 null（探测失败 / 报价源抖动 / 相位未到）→
           **保留上一帧清单，绝不清空**（用户 2026-09-29 报「买入清单动不动就消失」）。 */
        if (topEl.innerHTML.indexOf('tbl-hpdk-buylist') < 0 && TOPCACHE.html) topEl.innerHTML = TOPCACHE.html;
      } else {
        /* R-hpdk-persist-top-0930（用户 2026-09-30 要求：「竞价预备清单/买入清单要常驻显示，至少有个表头」）：
           原先这里只有一行灰字、**无表头** ⇒ 用户无法区分「还没到时段 / 非买日 / 行情坏了」。
           现在常驻渲染：状态行 + 买日/信号日 + **完整表头**（0 行 + 一行说明）。 */
        var _st, _nw = new Date(), _nm2 = _nw.getHours() * 60 + _nw.getMinutes(), _td0 = ymd(_nw);
        var _isBuy = !!(buy && _td0 === buy);
        if (!buy) _st = '本卡未带买日（产物为占位 / 未生成）';
        else if (!live) _st = '等待行情 —— 页面打开后自动拉取；行情源无响应时保持本状态（不是故障）';
        else if (_isBuy && _nm2 < (9 * 60 + 15))
          _st = '买日 ' + buy + ' · 尚未到集合竞价（09:15 开启预备清单；09:25 出权威清单）';
        else if (_isBuy && _nm2 >= (9 * 60 + 15) && _nm2 < CFG.OPEN_MIN)
          _st = '买日 ' + buy + ' · 竞价时段 09:15\u201309:25 —— 预备清单按参考价实时判定';
        else if (_isBuy)
          _st = '买日 ' + buy + ' · 等待 09:25 撮合出真实今开（该时段不剔除、不判定）';
        else _st = '非买日（买日 ' + buy + '）—— 本清单只在买日 09:25 后出结果';
        topEl.innerHTML = '<div class="sub" style="border-left:3px solid var(--faint);padding-left:8px;margin:0 0 8px">'
            + '<b>今日买入清单（全池判定 · 本卡唯一买入口径）</b> · 买日 <b>' + (buy || '\u2014') + '</b>'
            + '（信号日 ' + (H.as_of || '\u2014') + '）· 状态：<b>' + _st + '</b>'
            + (S.mktTs ? (' · 行情时间戳 ' + escH(S.mktTs)) : ' · 尚未取到行情时间戳')
            + '</div>'
            + '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-buylist" style="width:100%;font-size:12px">'
            + TOPTHEAD
            + '<tbody><tr><td colspan="17" style="color:var(--faint);padding:8px 0">'
            + '（暂无清单 \u2014 ' + _st + '）</td></tr></tbody></table></div>';
      }
    }
    /* ⑧ 非判定时段：一行都不剔除。**只有集合竞价 09:15–09:24 挂逐行灰标**（那时 gap 预判有信息量）；
       盘前 / 非买日 / 买日已过 / 无行情 → **不挂任何逐行标签**，相位一律由卡头徽章表达。
       2026-09-27 用户反馈：在「标的」格里每行重复「非买日」很蠢 ⇒ 改为只在有信息量时标记，
       并把标记写进「状态」列（标的格保持干净）。 */
    if (live && !enforce && S.phase === 'auction') {
      /* R-hpdk-cancel-0929（用户批准 D · 2026-09-29）：竞价阶段（09:15–09:24）**唯一需要动手的事 = 撤下沿的单**。
         机制：挂单价 = 0.99×昨收 是**固定上限** —— 开盘价高于它（gap > −1%）的**本就不会成交**
         ⇒ 上沿由限价自动把关（实测：带内 83% 的票挤在上沿附近，但它们全都不需要判断）。
         真正要撤的是 gap < −3%（跌幅过大）：这些票开盘价在限价**之下** ⇒ 挂单**必成交** ⇒ 必须手动撤。
         容错：实测下沿放宽到 −4% 几乎无成本（年化 46.85 vs 46.40）、−5% 才痛（42.73）⇒ 阈值附近不必纠结。
         输出：逐行四档可操作标记 + 汇总行附「撤单短名单」。**仅提示，不剔除任何行**（竞价不判命中）。 */
      var _up = numOr(H.gap_hi, -0.01), _lo = numOr(H.gap_lo, -0.03), _soft = _lo + 0.002;
      var _can = [], _wat = [], _inb = 0, _abv = 0, _nq = 0;
      for (i = 0; i < pend.length; i++) {
        var d2 = q[pend[i].code] || {}, px2 = num(d2.px), pcl2 = num(d2.pcl), op2 = num(d2.opn);
        var base2 = (op2 > 0) ? op2 : px2;                  /* 优先虚拟开盘价；竞价早期可能只有参考价 */
        var g2 = (base2 > 0 && pcl2 > 0) ? (base2 / pcl2 - 1) : NaN;
        var m2 = META[pend[i].code] || {}, nm2 = m2.name || pend[i].code;
        var lim2 = pcl2 > 0 ? (pcl2 * 0.99) : NaN;          /* 你要挂的限价 = 昨收×0.99 */
        var t2, c2, why2;
        if (isNaN(g2)) {
          t2 = '竞价预判 —'; c2 = 'pre'; _nq++; why2 = '本次无竞价参考价（保守留存）';
        } else if (g2 < _lo) {
          t2 = '⚠ 建议撤单 ' + fmtPct(g2); c2 = 'cancel'; _can.push({code: pend[i].code, name: nm2, g: g2});
          why2 = '跌幅已破下沿：开盘价会在你的限价 ' + (isNaN(lim2) ? '—' : lim2.toFixed(3))
               + ' 之下 ⇒ 挂单**必成交**，必须手动撤';
          pend[i].tr.classList.add('hpdk-cancel');
        } else if (g2 < _soft) {
          t2 = '留意下沿 ' + fmtPct(g2); c2 = 'watch'; _wat.push({code: pend[i].code, name: nm2, g: g2});
          why2 = '贴近下沿：若继续走弱将进入撤单区（实测容错约 1 个点，不必纠结）';
        } else if (g2 <= _up + CFG.EPS) {
          t2 = '带内 · 待成交 ' + fmtPct(g2); c2 = 'pre'; _inb++;
          why2 = '在 [' + fmtPct(_lo) + ', ' + fmtPct(_up) + '] 内 ⇒ 09:25 以开盘价成交';
        } else {
          t2 = '高于上沿 · 不会成交 ' + fmtPct(g2); c2 = 'pre'; _abv++;
          why2 = '开盘价高于你的限价 ' + (isNaN(lim2) ? '—' : lim2.toFixed(3)) + ' ⇒ 买单不成交，无需处理';
        }
        tagInto(pend[i].tr, t2, c2,
          CFG.TIP + ' · 集合竞价（09:15–09:24）：虚拟开盘价 '
          + (base2 > 0 ? base2.toFixed(3) : '—') + ' / 昨收 ' + (pcl2 > 0 ? pcl2.toFixed(3) : '—') + '　'
          + why2 + '。你的挂单价固定 = 0.99×昨收 = ' + (isNaN(lim2) ? '—' : lim2.toFixed(3))
          + '（**上沿由限价自动把关**，不需要你判断）。');
      }
      if (hr) {
        var _lst = _can.length
          ? ('：' + _can.map(function(x){ return escH(x.name) + ' ' + bare(x.code) + '（' + fmtPct(x.g) + '）'; }).join('、'))
          : '（无）';
        hr.innerHTML += '<br><b style="color:var(--warn)">⚡ 竞价（09:15–09:24）：建议撤单 '
          + _can.length + ' 只</b>' + _lst
          + (_wat.length ? ('　｜ <span style="color:var(--warn)">留意下沿 ' + _wat.length + ' 只</span>') : '')
          + '　｜ 带内待成交 <b>' + _inb + '</b> 只'
          + '　｜ 高于上沿（不成交·无需处理）' + _abv + ' 只'
          + (_nq ? ('　｜ 无报价 ' + _nq + ' 只') : '')
          + '<br><span style="color:var(--faint)">挂单价固定 = <b>0.99×昨收</b>：上沿由限价自动把关，'
          + '所以你**只需撤下沿**。09:25 撮合后：<b>立刻撤掉未成交挂单</b>'
          + '（否则盘中跌到 0.99×昨收 会意外成交，而规则只允许「开盘价买入」）。</span>';
      }
    }
    if (changed) saveRec(rec);
    badge(live);
    return {phase: S.phase, gate: S.gate, rows: S.rows, pool: S.pool, removed: S.removed, hit: S.hit,
            kept: S.kept, noquote: S.noquote, mktDate: S.mktDate, mmin: S.mmin, diag: S.diag, err: S.err};
  }
  function run(q, ts, src, mktTs){
    if (!document.getElementById(CFG.TBL)) return null;   /* 表不存在 → 零开销 */
    try { poolTop(); } catch (e) {}      /* R-hpdk-pooltop-0929：把选股池搬到最上方并折叠（幂等） */
    try { return render(q, ts, src, mktTs); }
    catch(e) { S.err = String(e && e.message || e); return null; }
  }

  /* 接线（两条路都要接，缺一不可 —— 同 QLCH_JS 的线上教训：IIFE 内部调的是局部函数 applyQuotes，
     只包 window.INTRADAY.applyQuotes 在**真实刷新路径**上一次都拦不到；真实路径靠 intraday_live.py
     applyQuotes 调用点显式留的 window.HPDK_ON_QUOTES 钩子）： */
  window.HPDK_ON_QUOTES = function(q, ts, src, mktTs){ return run(q, ts, src, mktTs); };
  /* R-hpdk-fullpool-0929：把**整个资格池**的代码暴露给盘中层 —— 让判定与「今日买入清单」
     覆盖全池（2227 只），而不是只有 DOM 渲染的 600 行（线上实测：DOM 可判定仅 336 行 ⇒
     买入名单一度只剩 3 只、且随刷新漂移）。盘中层无此钩子时行为与原来完全一致（只判 DOM 行）。 */
  window.POOL_EXTRA_CODES = function(){ try { return Object.keys(META); } catch (e) { return []; } };
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
  /* 导出（供 _verify_* 脚本断状态；判定 / 排名 / 列定位都可单独驱动） */
  window.HPDK_LIVE = {run: run, state: S, meta: META, cfg: CFG, judge: judge, score: score, cols: cols,
                      mktOf: mktOf, phaseOf: phaseOf, order: function(){ return ORDER; },
                      rec: function(){ return TV; },
                      reload: function(){ TV = loadRec(); return TV; },
                      reset: function(){ TV = {}; try { localStorage.removeItem(CFG.LS); } catch(e) {} },
                      wrapped: !!(IN && IN.applyQuotes)};
  /* 首屏：先把样式 / 徽标建起来（还没行情 → 不判定、不剔除、不贴标） */
  run(null, '');
})();
"""
