/* ============================================================
 * 市场情绪晴雨表 · 前端渲染 + 30s 实时轮询（2026-08-29）
 * 数据三层：
 *   1) 静态精算 window.MARKET_BREADTH（本地守护/收盘管道生成，含 timeline 历史）
 *   2) 实时直连：腾讯 qt.gtimg.cn 指数（CORS=*）+ 东财涨停/跌停/炸板池（CORS 允许 github.io）
 *   3) 前端本地采样点（localStorage 持久当日，合并进曲线）
 * 纯展示 · 不构成任何交易信号
 * ============================================================ */
(function () {
  'use strict';
  var MB = window.MARKET_BREADTH || null;
  var LIVE_INTERVAL = 30000;          // 30s
  var IDX_CODES = 'sh000001,sz399001,sz399006,sh000300,sh000905,sh000852,sh000688,sh000016';
  var IDX_NAMES = { sh000001: '上证指数', sz399001: '深证成指', sz399006: '创业板指', sh000300: '沪深300', sh000905: '中证500', sh000852: '中证1000', sh000688: '科创50', sh000016: '上证50' };
  var POOLS = {
    zt:  { url: 'https://push2ex.eastmoney.com/getTopicZTPool', key: 'limit_up' },
    dt:  { url: 'https://push2ex.eastmoney.com/getTopicDTPool', key: 'limit_down' },
    zb:  { url: 'https://push2ex.eastmoney.com/getTopicZBPool', key: 'broken_limit' }
  };
  var state = { idx: null, pools: null, breadth: null, live: [], ts: null };

  /* ---------- 工具 ---------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (html != null) n.innerHTML = html;
    return n;
  }
  function isTrading() {
    var d = new Date();
    if (d.getDay() === 0 || d.getDay() === 6) return false;
    var m = d.getHours() * 60 + d.getMinutes();
    return (m >= 570 && m <= 690) || (m >= 780 && m <= 900); // 9:30-11:30 / 13:00-15:00
  }
  function todayKey() { var d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function loadLocalTimeline() {
    try { return JSON.parse(localStorage.getItem('mw_tl_' + todayKey()) || '[]'); } catch (e) { return []; }
  }
  function saveLocalTimeline() {
    try {
      var tl = state.live.slice(-480);
      localStorage.setItem('mw_tl_' + todayKey(), JSON.stringify(tl));
    } catch (e) { /* quota */ }
  }
  function fetchText(url) {
    return fetch(url + (url.indexOf('?') > -1 ? '&' : '?') + '_=' + Date.now(), { mode: 'cors' }).then(function (r) { return r.text(); });
  }
  function fetchGBK(url) {
    return fetch(url + (url.indexOf('?') > -1 ? '&' : '?') + '_=' + Date.now(), { mode: 'cors' })
      .then(function (r) { return r.arrayBuffer(); })
      .then(function (buf) { return new TextDecoder('gbk').decode(buf); });
  }
  function fmtNum(v, d) { var n = Number(v); return isFinite(n) ? n.toFixed(d == null ? 2 : d) : '—'; }
  function fmtYi(v) { var n = Number(v); return isFinite(n) ? fmtNum(n, 0) + '亿' : '—'; }

  /* ---------- 实时拉取 ---------- */
  function fetchIndices() {
    return fetchGBK('https://qt.gtimg.cn/q=' + IDX_CODES).then(function (body) {
      var out = [];
      var re = /v_([a-z]{2}\d{6})="([^"]*)"/g, m;
      while ((m = re.exec(body))) {
        var f = m[2].split('~');
        if (f.length < 35) continue;
        var code = m[1], name = IDX_NAMES[code] || f[1] || code;
        out.push({ code: code, name: name, px: Number(f[3]), chg: Number(f[32]), prev: Number(f[4]) });
      }
      return out;
    });
  }
  function fetchPool(key) {
    var p = POOLS[key];
    return fetchText(p.url + '?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=1&sort=fbt%3Aasc&date=' + todayKey().replace(/-/g, ''))
      .then(function (t) {
        try { return Number(JSON.parse(t).data.tc) || 0; } catch (e) { return null; }
      });
  }
  var _breadthFailAt = 0;                 // 涨跌家数接口失败时间戳（退避用）
  var BREADTH_RETRY_MS = 5 * 60 * 1000;   // 失败后 5 分钟不再重试（避免控制台刷 ERR_EMPTY_RESPONSE）
  var BREADTH_URLS = [
    // push2delay：实测可达且返回完整 CORS 头（github.io 可直连）；push2 主站被拦（ERR_EMPTY_RESPONSE）
    'https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f104,f105,f106&fltt=2',
    'https://push2delay.eastmoney.com/api/qt/stock/get?secid=0.399001&fields=f43,f104,f105,f106&fltt=2',
    'https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f104,f105,f106&fltt=2',
    'https://push2.eastmoney.com/api/qt/stock/get?secid=0.399001&fields=f43,f104,f105,f106&fltt=2'
  ];
  function fetchBreadth() {
    // 非交易时段：不请求实时涨跌家数（直接用静态精算），避免无效请求与报错
    if (!isTrading()) return Promise.resolve(null);
    // 失败退避：5 分钟内不再尝试
    if (_breadthFailAt && Date.now() - _breadthFailAt < BREADTH_RETRY_MS) return Promise.resolve(null);
    var urls = BREADTH_URLS;
    return Promise.all(urls.map(function (u) { return fetchText(u).then(function (t) { try { return JSON.parse(t).data; } catch (e) { return null; } }).catch(function () { return null; }); }))
      .then(function (arr) {
        // 多源：push2delay 优先（sh=arr[0], sz=arr[1]），主站作 fallback（sh=arr[2], sz=arr[3]）
        var pairs = [[arr[0], arr[1]], [arr[2], arr[3]]];
        for (var p = 0; p < pairs.length; p++) {
          var sh = pairs[p][0], sz = pairs[p][1];
          if (sh && sz && isFinite(Number(sh.f104)) && isFinite(Number(sz.f104))) {
            var red = Number(sh.f104) + Number(sz.f104);
            var green = Number(sh.f105) + Number(sz.f105);
            var flat = Number(sh.f106) + Number(sz.f106);
            // 合理性闸：全市场红绿平总数应 ≥3000（防接口非交易时段返回占位值覆盖精算数据）
            if (red + green + flat >= 3000) { _breadthFailAt = 0; return { red: red, green: green, flat: flat, src: 'eastmoney' }; }
          }
        }
        _breadthFailAt = Date.now();
        if (MB && MB.latest) return { red: MB.latest.red, green: MB.latest.green, flat: MB.latest.flat, src: 'static' };
        return null;
      });
  }
  function snapshot() {
    var d = new Date(), t = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    var pools = state.pools || {}, b = state.breadth || { red: 0, green: 0, flat: 0 };
    var idx = state.idx || [];
    var turnover = null, sh = null;
    for (var i = 0; i < idx.length; i++) { if (idx[i].code === 'sh000001') sh = idx[i]; }
    var s = {
      t: t, red: b.red, green: b.green, flat: b.flat,
      limit_up: pools.limit_up || 0, limit_down: pools.limit_down || 0, broken_limit: pools.broken_limit || 0,
      turnover_yi: sh ? Math.round(sh.px * 0) : null, src: 'live'
    };
    // 量能：静态精算的当日累计成交额（直连无两市聚合成交额接口时用静态）
    if (MB && MB.latest && MB.latest.turnover_yi) s.turnover_yi = MB.latest.turnover_yi;
    // 情绪：透传静态精算的 sentiment（涨停封单强度等）；缺失则 undefined
    if (MB && MB.latest && MB.latest.sentiment) s.sentiment = MB.latest.sentiment;
    state.ts = { t: t, pools: pools, breadth: b, idx: idx, sentiment: s.sentiment };
    // 仅交易时段写入曲线点（非交易时段采样点会污染时间轴/造成直线）
    if (isTrading()) { state.live.push(s); saveLocalTimeline(); }
    render();
  }
  var _everPolled = false;
  function poll() {
    // 首次加载必拉一次（非交易时段也定格最新收盘值）；之后仅交易时段 30s 轮询
    if (!isTrading() && _everPolled) { render(); return; }
    _everPolled = true;
    Promise.all([
      fetchIndices().then(function (v) { state.idx = v; }),
      Promise.all([fetchPool('zt'), fetchPool('dt'), fetchPool('zb')]).then(function (v) {
        state.pools = { limit_up: v[0], limit_down: v[1], broken_limit: v[2] };
      }),
      fetchBreadth().then(function (v) { if (v) state.breadth = v; })
    ]).then(snapshot).catch(function () { /* 单次失败不打断 */ });
  }

  /* ---------- 渲染 ---------- */
  function render() {
    renderBadge();
    renderSummary();
    renderIndices();
    renderChart();
  }
  function renderBadge() {
    var b = $('mw-badge'), t = isTrading() ? '30s 实时' : '静态';
    if (b) b.textContent = t + (MB && MB.meta ? ' · 精算 ' + (MB.meta.ts || '') : '');
  }
  function sentimentLevel(red, green, zt) {
    if (red >= green * 1.5 && zt >= 30) return { lv: '进攻', color: '#dc2626' };
    if (green > red * 1.5) return { lv: '防御', color: '#16a34a' };
    if (red >= green && zt >= 15) return { lv: '偏强', color: '#ea580c' };
    if (green > red) return { lv: '偏弱', color: '#65a30d' };
    return { lv: '轮动', color: '#2563eb' };
  }
  function renderSummary() {
    var b = $('mw-summary');
    if (!b) return;
    var src = state.breadth || (MB && MB.latest) || null;
    var pools = state.pools || {};
    var stat = MB && MB.latest ? MB.latest : null;
    if (!src && !stat) { b.innerHTML = '<span style="color:var(--faint)">等待数据…</span>'; return; }
    var red = src.red || 0, green = src.green || 0, flat = src.flat || 0;
    // 池数据：非交易时段/失败时回退静态（避免周六显示 0）
    var zt = (pools.limit_up > 0) ? pools.limit_up : (stat ? stat.limit_up : 0);
    var dt = (pools.limit_down > 0) ? pools.limit_down : (stat ? stat.limit_down : 0);
    var zb = (pools.broken_limit > 0) ? pools.broken_limit : (stat ? stat.broken_limit : 0);
    var tz = stat ? stat.turnover_yi : null;
    var sl = sentimentLevel(red, green, zt);
    // 情绪特征：涨停封单强度（取自静态精算 MB.latest.sentiment / MB.sentiment）
    var sent = (stat && stat.sentiment) ? stat.sentiment : (MB && MB.sentiment ? MB.sentiment : null);
    var sZone = sent ? (sent.zone || sent.sentiment_zone) : null;
    var sZt = sent ? sent.zt_ratio : null;
    var sBr = sent ? sent.broken_rate : null;
    var sSeal = sent ? sent.total_seal_yi : null;
    var sLb = sent ? sent.lianban_max : null;
    var html = '<span class="mw-big" style="color:' + sl.color + '">情绪 ' + sl.lv + '</span>' +
      '<span class="mw-item">红盘 <b style="color:#dc2626">' + red + '</b></span>' +
      '<span class="mw-item">绿盘 <b style="color:#16a34a">' + green + '</b></span>' +
      '<span class="mw-item">平盘 ' + flat + '</span>' +
      '<span class="mw-item">涨停 <b style="color:#ef4444">' + zt + '</b></span>' +
      '<span class="mw-item">跌停 <b style="color:#22c55e">' + dt + '</b></span>' +
      '<span class="mw-item">炸板 ' + zb + '</span>' +
      (tz != null ? '<span class="mw-item">量能 <b>' + fmtYi(tz) + '</b></span>' : '') +
      '<span class="mw-item mw-note">' + (src.src ? (src.src === 'eastmoney' ? '东财实时' : '静态精算') : '精算') + ' · 仅展示非信号</span>';
    // 情绪统计条（数值型变量，缺失显示 —；无 HTML 注入面）
    html += '<br><span class="mw-item">情绪分区 <b>' + (sZone || '—') + '</b></span>' +
      '<span class="mw-item">涨停比 ' + (sZt != null ? fmtNum(sZt, 2) : '—') + '%</span>' +
      '<span class="mw-item">炸板率 ' + (sBr != null ? fmtNum(sBr, 2) : '—') + '%</span>' +
      '<span class="mw-item">封单 ' + (sSeal != null ? fmtNum(sSeal, 2) : '—') + '亿</span>' +
      '<span class="mw-item">连板高度 ' + (sLb != null ? sLb : '—') + '板</span>';
    b.innerHTML = html;
  }
  function renderIndices() {
    var c = $('mw-idx');
    if (!c) return;
    var idx = state.idx;
    if (!idx || !idx.length) {
      if (MB && MB.meta) { c.innerHTML = '<span style="color:var(--faint)">指数行情未获取（非交易时段/直连失败，显示后台数据）</span>'; }
      return;
    }
    c.innerHTML = '';
    idx.forEach(function (x) {
      var up = x.chg >= 0;
      c.appendChild(el('div', { class: 'mw-idx-item' }, '<span class="n">' + x.name + '</span><span class="p">' + fmtNum(x.px) + '</span><span class="c" style="color:' + (up ? '#dc2626' : '#16a34a') + '">' + (up ? '+' : '') + fmtNum(x.chg) + '%</span>'));
    });
  }
  function tMin(t) { var p = String(t).split(':'); return (+p[0]) * 60 + (+p[1]); }
  function chartData() {
    var staticTl = (MB && MB.timeline) ? MB.timeline : [];
    var liveTl = loadLocalTimeline();
    var map = {};
    staticTl.forEach(function (e) { map[e.t] = e; });
    liveTl.forEach(function (e) { map[e.t] = e; });
    // 只保留交易时段内（09:30-15:00）的点，按时间排序
    return Object.keys(map)
      .map(function (t) { return map[t]; })
      .filter(function (e) { var m = tMin(e.t); return m >= 570 && m <= 900; })
      .sort(function (a, b) { return tMin(a.t) - tMin(b.t); });
  }
  function renderChart() {
    var box = $('mw-chart');
    if (!box) return;
    var tl = chartData();
    if (!tl.length) { box.innerHTML = '<div style="color:var(--faint);padding:12px">暂无日内曲线（开盘后自动采集 / 后台精算）</div>'; return; }
    var W = 680, H = 300, padL = 44, padR = 40, padT = 14, padB = 26;
    var iw = W - padL - padR;
    var mainH = H - padT - padB - 56;      // 主区（家数+涨跌停）
    var volH = 46;                          // 量能区
    var volTop = padT + mainH + 10;
    var maxCnt = 1, maxLt = 1, maxVol = 1;
    tl.forEach(function (e) {
      maxCnt = Math.max(maxCnt, (e.red || 0) + (e.green || 0));
      maxLt = Math.max(maxLt, e.limit_up || 0, e.limit_down || 0, e.broken_limit || 0);
      maxVol = Math.max(maxVol, e.turnover_yi || 0);
    });
    maxCnt = Math.ceil(maxCnt * 1.1 / 500) * 500;
    maxLt = Math.ceil(maxLt * 1.4 / 10) * 10;
    maxVol = Math.ceil(maxVol * 1.15 / 1000) * 1000;
    // x 轴 = 真实交易时间线性映射（09:30→左缘, 15:00→右缘），不依赖点数 → tick 永不重叠
    var T0 = 570, T1 = 900; // 9:30 / 15:00 分钟
    function x(t) { return padL + ((tMin(t) - T0) / (T1 - T0)) * iw; }
    var yCnt = function (v) { return padT + mainH - (v / maxCnt) * mainH; };
    var yLt = function (v) { return padT + mainH - (v / maxLt) * mainH; };
    var yVol = function (v) { return volTop + volH - (v / maxVol) * volH; };
    function poly(pts) { return pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '); }
    function line(series, yfn, color, w) {
      var pts = tl.map(function (e, i) { return [x(e.t), yfn(e[series] || 0)]; });
      return '<polyline fill="none" stroke="' + color + '" stroke-width="' + (w || 1.6) + '" points="' + poly(pts) + '"/>';
    }
    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto;display:block">';
    // 网格
    for (var g = 1; g <= 4; g++) {
      var gy = padT + mainH * g / 5;
      svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" stroke="var(--border,#e2e8f0)" stroke-width="0.5" stroke-dasharray="3 3"/>';
    }
    // Y 轴刻度（家数）
    for (var k = 0; k <= 4; k++) {
      var vv = Math.round(maxCnt * k / 4 / 100) * 100;
      svg += '<text x="' + (padL - 6) + '" y="' + (yCnt(vv) + 4) + '" text-anchor="end" font-size="9" fill="var(--faint,#94a3b8)">' + vv + '</text>';
    }
    // 量能刻度
    svg += '<text x="' + padL + '" y="' + (volTop + volH + 10) + '" font-size="9" fill="var(--faint,#94a3b8)">量能(亿) ' + Math.round(maxVol / 1000) + 'k</text>';
    // 主区曲线
    if (tl.length === 1) {
      // 单点（非交易时段仅收盘精算点）：画圆点标记 + 说明，避免空图/误读为直线
      var e0 = tl[0];
      var px0 = x(e0.t), py0 = yCnt(e0.red || 0);
      svg += '<circle cx="' + px0.toFixed(1) + '" cy="' + py0.toFixed(1) + '" r="3.5" fill="#dc2626"/>';
      svg += '<text x="' + px0.toFixed(1) + '" y="' + (py0 - 8).toFixed(1) + '" text-anchor="middle" font-size="9" fill="var(--faint,#94a3b8)">收盘精算 ' + (e0.red || 0) + '红</text>';
      svg += '<text x="' + padL + '" y="' + (padT + mainH + 14) + '" font-size="9" fill="var(--faint,#94a3b8)">非交易时段 · 曲线将在交易日 09:30 起每 30s 自动采集</text>';
    } else {
      svg += line('red', yCnt, '#dc2626', 1.8);
      svg += line('green', yCnt, '#16a34a', 1.8);
      svg += line('limit_up', yLt, '#ef4444', 1.4);
      svg += line('limit_down', yLt, '#22c55e', 1.4);
      svg += line('broken_limit', yLt, '#f59e0b', 1.2);
    }
    // 量能面积 + 线
    var vpts = tl.map(function (e, i) { return [x(e.t), yVol(e.turnover_yi || 0)]; });
    var area = vpts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); });
    svg += '<polygon fill="rgba(59,130,246,.18)" points="' + area.join(' ') + ' ' + padL + ',' + (volTop + volH) + ' ' + (W - padR) + ',' + (volTop + volH) + '"/>';
    svg += '<polyline fill="none" stroke="#3b82f6" stroke-width="1.4" points="' + poly(vpts) + '"/>';
    // 时间轴：固定 6 个刻度直接映射到固定位置（09:30/10:30/11:30/13:30/14:30/15:00），永不重叠
    var ticks = ['09:30', '10:30', '11:30', '13:30', '14:30', '15:00'];
    ticks.forEach(function (tt) {
      svg += '<text x="' + x(tt).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="9" fill="var(--faint,#94a3b8)">' + tt + '</text>';
    });
    // hover 点
    svg += '<rect x="' + padL + '" y="' + padT + '" width="' + iw + '" height="' + (mainH + volH + 10) + '" fill="transparent"/>';
    svg += '</svg>';
    box.innerHTML = svg;
  }

  /* ---------- 启动 ---------- */
  function init() {
    var card = $('mkt-weather');
    if (!card) return;
    state.live = loadLocalTimeline();
    render();
    poll();
    setInterval(poll, LIVE_INTERVAL);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
