# -*- coding: utf-8 -*-
"""公共 UI 层：主题(明暗) / 顶部导航(历史报告+明暗+qingju.me) / 左侧贴边导航 /
表格交互(搜索/筛选/排序/权限切换) / 详情弹层(K线+因子+交易历史)。
供 dual_system.html 与 index.html 共用（内联注入，无外部依赖）。"""

# ---------------- 主题 CSS ----------------
THEME_CSS = """
:root{
  --bg:#f3f4f6; --card:#ffffff; --card2:#f9fafb; --border:#e5e7eb; --line:#f0f1f3;
  --text:#111827; --sub:#6b7280; --faint:#9ca3af;
  --up:#dc2626; --down:#16a34a; --accent:#f59e0b; --accent2:#3b82f6;
  --nav-bg:#ffffff; --shadow:0 1px 3px rgba(0,0,0,.08);
}
[data-theme="dark"]{
  --bg:#0f1115; --card:#171a21; --card2:#1e222b; --border:#2a2f3a; --line:#232833;
  --text:#e5e7eb; --sub:#9ca3af; --faint:#6b7280;
  --up:#f87171; --down:#4ade80; --accent:#fbbf24; --accent2:#60a5fa;
  --nav-bg:#171a21; --shadow:0 1px 3px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);margin:0;transition:background .2s,color .2s}
.container{max-width:1560px;margin:0 auto;padding:0 24px 40px}

/* ---------- 顶部导航 ---------- */
.topbar{position:sticky;top:0;z-index:900;background:var(--nav-bg);border-bottom:1px solid var(--border);
  box-shadow:var(--shadow);display:flex;align-items:center;gap:14px;padding:10px 22px;flex-wrap:wrap}
.topbar .logo{font-size:17px;font-weight:700;display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
.topbar .logo .dot{width:10px;height:10px;border-radius:3px;background:linear-gradient(135deg,#f59e0b,#ef4444);display:inline-block}
.topbar .spacer{flex:1}
.tb-btn{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:20px;
  padding:6px 14px;font-size:13px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px}
.tb-btn:hover{border-color:var(--accent)}
.tb-btn.active{border-color:var(--accent);color:var(--accent)}
.community{display:inline-block;padding:6px 14px;border-radius:20px;
  background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;text-decoration:none;font-weight:600;font-size:13px}
/* 历史报告下拉 */
.dropdown{position:relative}
.dropdown-menu{position:absolute;right:0;top:calc(100% + 6px);background:var(--card);border:1px solid var(--border);
  border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.15);width:360px;max-height:440px;overflow-y:auto;
  padding:6px;display:none;z-index:950}
.dropdown.open .dropdown-menu{display:block}
.dropdown-menu a{display:block;padding:8px 12px;border-radius:8px;font-size:13px;color:var(--text);
  text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dropdown-menu a:hover{background:var(--card2);color:var(--accent)}
.dropdown-menu .head{font-size:12px;color:var(--faint);padding:6px 12px;border-bottom:1px solid var(--line);margin-bottom:4px}

/* ---------- 左侧宽侧边栏（图标+文字） ---------- */
.sidenav{position:fixed;left:0;top:0;bottom:0;width:190px;background:var(--nav-bg);border-right:1px solid var(--border);
  display:flex;flex-direction:column;padding:16px 10px;z-index:850;overflow-y:auto}
.sidenav .sn-logo{font-size:14px;font-weight:700;padding:2px 10px 14px;display:flex;align-items:center;gap:8px}
.sidenav .sn-logo .dot{width:10px;height:10px;border-radius:3px;background:linear-gradient(135deg,#f59e0b,#ef4444);display:inline-block}
.sidenav .sn-sep{height:1px;background:var(--line);margin:8px 6px}
.sidenav a{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;
  color:var(--sub);text-decoration:none;font-size:13px;margin-bottom:2px;transition:all .15s}
.sidenav a .ic{font-size:16px;width:20px;text-align:center}
.sidenav a:hover{background:var(--card2);color:var(--text)}
.sidenav a.active{background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(239,68,68,.15));color:var(--accent);font-weight:600}
.sidenav .sn-foot{margin-top:auto;display:flex;flex-direction:column;gap:6px}
body.sidenav-open .container{margin-left:190px}

/* ---------- 通用卡片 ---------- */
.card{background:var(--card);border-radius:16px;padding:22px;margin-bottom:22px;border:1px solid var(--border)}
.card h2{font-size:18px;margin:0 0 4px;display:flex;align-items:center;gap:10px}
.card .sub{color:var(--sub);font-size:12px;margin-bottom:14px}
.badge{font-size:11px;padding:2px 10px;border-radius:20px;font-weight:500}
.badge-auto{background:rgba(245,158,11,.15);color:#b45309}
[data-theme="dark"] .badge-auto{color:#fbbf24}
.badge-lite{background:rgba(59,130,246,.15);color:#1d4ed8}
[data-theme="dark"] .badge-lite{color:#60a5fa}

/* ---------- KPI ---------- */
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px}
.kpi{flex:1;min-width:128px;background:var(--card2);border-radius:12px;padding:12px 16px;border:1px solid var(--border)}
.kpi .l{font-size:12px;color:var(--sub)}
.kpi .v{font-size:22px;font-weight:700;margin-top:3px}
.kpi .s{font-size:11px;color:var(--faint);margin-top:2px}

/* ---------- 表格工具条 ---------- */
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.toolbar input[type=text]{background:var(--card2);border:1px solid var(--border);color:var(--text);
  border-radius:10px;padding:8px 12px;font-size:13px;width:220px;font-family:inherit}
.toolbar select{background:var(--card2);border:1px solid var(--border);color:var(--text);
  border-radius:10px;padding:8px 10px;font-size:13px;font-family:inherit}
.toolbar .perm-group{display:flex;gap:4px;background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:3px}
.toolbar .perm-group button{border:none;background:transparent;color:var(--sub);border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer;font-family:inherit}
.toolbar .perm-group button.active{background:var(--accent);color:#fff;font-weight:600}
.toolbar .count{font-size:12px;color:var(--faint);margin-left:auto}

/* ---------- 表格 ---------- */
table.tbl{width:100%;border-collapse:collapse;font-size:13px}
table.tbl th{background:var(--card2);color:var(--sub);font-size:12px;padding:10px 8px;border-bottom:2px solid var(--border);
  text-align:left;cursor:pointer;user-select:none;white-space:nowrap}
table.tbl th:hover{color:var(--accent)}
table.tbl th .arr{font-size:10px;margin-left:2px}
table.tbl td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
table.tbl tr{cursor:pointer}
table.tbl tbody tr:hover td{background:var(--card2)}
.up{color:var(--up)} .down{color:var(--down)}
.pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500}
.pill-full{background:rgba(220,38,38,.12);color:var(--up)}
.pill-add{background:rgba(234,88,12,.12);color:#ea580c}
.pill-watch{background:rgba(217,119,6,.12);color:#d97706}
.pill-cut{background:rgba(107,114,128,.15);color:var(--sub)}
.pill-clear{background:rgba(156,163,175,.15);color:var(--faint)}
.pill-chg-up{color:var(--up);font-size:11px}
.pill-chg-down{color:var(--down);font-size:11px}
.board-tag{font-size:11px;padding:1px 8px;border-radius:6px;background:var(--card2);border:1px solid var(--border);color:var(--sub)}

/* ---------- 详情弹层 ---------- */
.modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;display:none;align-items:flex-start;justify-content:center;overflow-y:auto;padding:40px 16px}
.modal-mask.open{display:flex}
.modal{background:var(--card);border-radius:16px;max-width:980px;width:100%;padding:24px;box-shadow:0 12px 48px rgba(0,0,0,.3)}
.modal .m-head{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.modal .m-head h3{margin:0;font-size:20px}
.modal .m-close{margin-left:auto;background:var(--card2);border:1px solid var(--border);color:var(--text);
  width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:16px}
.modal .m-kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.modal .m-kpis .kpi{min-width:104px;padding:10px 12px}
.factor-bars{display:flex;gap:14px;flex-wrap:wrap;margin:12px 0 16px}
.fbar{flex:1;min-width:150px}
.fbar .fl{font-size:12px;color:var(--sub);display:flex;justify-content:space-between;margin-bottom:4px}
.fbar .track{height:8px;background:var(--card2);border-radius:6px;overflow:hidden}
.fbar .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#3b82f6,#f59e0b)}
.modal h4{margin:14px 0 8px;font-size:14px;color:var(--sub)}
.modal svg{display:block;margin:0 auto}
.modal .legend{display:flex;gap:14px;font-size:12px;color:var(--sub);justify-content:center;margin-top:6px}
.trade-tabs{display:flex;gap:6px;margin-bottom:8px}
.trade-tabs button{border:1px solid var(--border);background:var(--card2);color:var(--sub);border-radius:8px;
  padding:5px 12px;font-size:12px;cursor:pointer;font-family:inherit}
.trade-tabs button.active{border-color:var(--accent);color:var(--accent)}
.modal table{width:100%;border-collapse:collapse;font-size:12px}
.modal table th{background:var(--card2);padding:7px 8px;text-align:left;font-size:11px;color:var(--sub);border-bottom:1px solid var(--border)}
.modal table td{padding:6px 8px;border-bottom:1px solid var(--line)}
.rule-box{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:13px 18px;margin-bottom:16px;font-size:13px;line-height:1.9;color:var(--sub)}
.rule-box b{color:var(--text)}
.note{color:var(--faint);font-size:12px;margin-top:8px}
"""

# ---------------- 顶部导航 + 左侧导航 ----------------
NAV_HTML = """
<div class="topbar">
  <div class="logo" onclick="location.hash='#overview'"><span class="dot"></span>量化权重监控</div>
  <div class="spacer"></div>
  <div class="dropdown" id="report-dd">
    <button class="tb-btn" onclick="toggleDrop('report-dd')">📄 标的报告 ▾</button>
    <div class="dropdown-menu" id="report-menu"></div>
  </div>
  <button class="tb-btn" id="theme-btn" onclick="toggleTheme()">🌙 夜间</button>
  <a class="community" href="https://qingju.me/" target="_blank" rel="noopener">💬 青橘社区</a>
</div>
<div class="sidenav" id="sidenav"></div>
"""

SIDENAV_ITEMS = [
    ("overview", "📊", "监控总览"),
    ("sys-auto", "🅰️", "普适版"),
    ("sys-lite", "🅱️", "个人版"),
    ("table", "📋", "标的监控表"),
]

# ---------------- 公共 JS ----------------
COMMON_JS = r"""
/* ---------- 主题 ---------- */
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);
  var b=document.getElementById('theme-btn');if(b)b.textContent=t==='dark'?'☀️ 日间':'🌙 夜间';
  try{localStorage.setItem('qw-theme',t)}catch(e){}}
function toggleTheme(){var t=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';applyTheme(t)}
try{applyTheme(localStorage.getItem('qw-theme')||'light')}catch(e){applyTheme('light')}

/* ---------- 历史报告下拉（标的监控报告） ---------- */
function toggleDrop(id){var el=document.getElementById(id);el.classList.toggle('open');
  if(id==='report-dd'&&!document.getElementById('report-menu').innerHTML){
    var m=document.getElementById('report-menu');
    var h='<div class="head">标的监控报告（'+window.ENH.monitor_reports.length+' 只）</div>';
    window.ENH.monitor_reports.forEach(function(r){
      h+='<a href="monitor_reports.html#'+r.code+'" target="_blank">📈 '+r.name+'（'+r.code+'）· '+r.tier+'</a>';});
    m.innerHTML=h;}}
document.addEventListener('click',function(e){
  document.querySelectorAll('.dropdown.open').forEach(function(d){
    if(!d.contains(e.target))d.classList.remove('open');});});

/* ---------- 左侧导航（JS 点击滚动，不依赖 hash） ---------- */
function renderSidenav(){var nav=document.getElementById('sidenav');if(!nav)return;
  var html='<div class="sn-logo"><span class="dot"></span>量化权重监控</div><div class="sn-sep"></div>';
  window.ENH.nav.forEach(function(it){
    html+='<a href="javascript:void(0)" data-anchor="'+it[0]+'"><span class="ic">'+it[1]+'</span>'+it[2]+'</a>';});
  html+='<div class="sn-sep"></div><div class="sn-foot">'+
    '<a href="monitor_reports.html" target="_blank"><span class="ic">📄</span>标的报告</a>'+
    '<a href="https://qingju.me/" target="_blank" rel="noopener"><span class="ic">💬</span>青橘社区</a></div>';
  nav.innerHTML=html;
  document.body.classList.add('sidenav-open');
  nav.querySelectorAll('a[data-anchor]').forEach(function(a){
    a.addEventListener('click',function(e){
      e.preventDefault();
      var t=a.getAttribute('data-anchor');
      var el=document.getElementById(t);
      if(el){el.scrollIntoView({behavior:'auto',block:'start'});
        window.scrollBy(0,-70);}
      nav.querySelectorAll('a[data-anchor]').forEach(function(x){x.classList.toggle('active',x===a);});});});
  window.addEventListener('scroll',function(){
    var anchors=window.ENH.nav.map(function(it){return it[0];});
    var cur=anchors[0];
    anchors.forEach(function(a){
      var el=document.getElementById(a);
      if(el&&el.getBoundingClientRect().top<=150)cur=a;});
    nav.querySelectorAll('a[data-anchor]').forEach(function(a){
      a.classList.toggle('active',a.getAttribute('data-anchor')===cur);});});}

/* ---------- 工具函数 ---------- */
function fmtPct(v){if(v===null||v===undefined||isNaN(v))return '—';
  var s=v>0?'+':'';return s+v.toFixed(1)+'%';}
function tierPill(t){
  var map={'满仓加仓':'pill-full','轻仓加仓':'pill-add','观望':'pill-watch','减至半仓':'pill-cut','清仓':'pill-clear'};
  return '<span class="pill '+(map[t]||'pill-watch')+'">'+t+'</span>';}
function tierChg(cur,prev){
  if(!prev)return '';if(cur===prev)return '';
  var up=cur==='满仓加仓'||cur==='轻仓加仓';
  return '<span class="'+(up?'pill-chg-up':'pill-chg-down')+'">'+prev+'→'+cur+'</span>';}

/* ---------- 表格交互：搜索/筛选/排序/权限 ---------- */
function initTable(tblId, opts){
  var table=document.getElementById(tblId);if(!table)return;
  var state={q:'',perm:'all',tier:'all',sortKey:null,sortDir:1};
  var colIdx=opts.columns; // {score:3, name:1, ...}
  function rows(){return Array.prototype.slice.call(table.querySelectorAll('tbody tr'));}
  function apply(){
    var rs=rows();
    rs.forEach(function(tr){
      var txt=(tr.getAttribute('data-search')||'').toLowerCase();
      var board=tr.getAttribute('data-board')||'';
      var tier=tr.getAttribute('data-tier')||'';
      var show=(!state.q||txt.indexOf(state.q.toLowerCase())>=0)
        &&(state.perm==='all'||board.indexOf(state.perm)>=0)
        &&(state.tier==='all'||tier===state.tier);
      tr.style.display=show?'':'none';});
    var cnt=document.getElementById(tblId+'-count');
    if(cnt)cnt.textContent='显示 '+rs.filter(function(tr){return tr.style.display!=='none'}).length+' / '+rs.length+' 只';
  }
  // 搜索
  var q=document.getElementById(tblId+'-q');
  if(q)q.addEventListener('input',function(){state.q=q.value;apply();});
  // 权限
  document.querySelectorAll('[data-perm-group="'+tblId+'"] button').forEach(function(b){
    b.addEventListener('click',function(){
      document.querySelectorAll('[data-perm-group="'+tblId+'"] button').forEach(function(x){x.classList.remove('active');});
      b.classList.add('active');state.perm=b.getAttribute('data-perm');apply();});});
  // 档位筛选
  var tierSel=document.getElementById(tblId+'-tier');
  if(tierSel)tierSel.addEventListener('change',function(){state.tier=tierSel.value;apply();});
  // 排序
  table.querySelectorAll('th[data-key]').forEach(function(th){
    th.addEventListener('click',function(){
      var k=th.getAttribute('data-key');
      if(state.sortKey===k){state.sortDir*=-1}else{state.sortKey=k;state.sortDir=1;}
      table.querySelectorAll('th[data-key]').forEach(function(x){x.querySelector('.arr').textContent='';});
      th.querySelector('.arr').textContent=state.sortDir>0?'▲':'▼';
      var idx=colIdx[k];
      var rs=rows().filter(function(tr){return tr.style.display!=='none'});
      rs.sort(function(a,b){
        var va=parseFloat(a.children[idx].getAttribute('data-v')||a.children[idx].textContent.replace(/[+,%—]/g,'')||'0');
        var vb=parseFloat(b.children[idx].getAttribute('data-v')||b.children[idx].textContent.replace(/[+,%—]/g,'')||'0');
        return (va-vb)*state.sortDir;});
      var tb=table.querySelector('tbody');
      rs.forEach(function(tr){tb.appendChild(tr);});});});
  apply();
}

/* ---------- 详情弹层 ---------- */
function openDetail(code){
  var d=window.ENH.details[code];if(!d)return;
  var mask=document.getElementById('modal-mask');
  var f=d.factors;
  var bars='<div class="factor-bars">'+
    '<div class="fbar"><div class="fl"><span>动量(35%)</span><b>'+f.mom+'</b></div><div class="track"><div class="fill" style="width:'+f.mom+'%"></div></div></div>'+
    '<div class="fbar"><div class="fl"><span>趋势(25%)</span><b>'+f.trend+'</b></div><div class="track"><div class="fill" style="width:'+f.trend+'%"></div></div></div>'+
    '<div class="fbar"><div class="fl"><span>Aroon(20%)</span><b>'+f.aroon+'</b></div><div class="track"><div class="fill" style="width:'+f.aroon+'%"></div></div></div>'+
    '<div class="fbar"><div class="fl"><span>量价(20%)</span><b>'+f.vp+'</b></div><div class="track"><div class="fill" style="width:'+f.vp+'%"></div></div></div></div>';
  var kh=window.ENH.sys && window.ENH.sys.nav?'':'';
  var klineSVG=renderKline(d.kline);
  var facSVG=renderFactors(d.factor_hist);
  var tradesV9=renderTrades(d.trades.v9_auto);
  var tradesLite=renderTrades(d.trades.v8_lite);
  mask.innerHTML='<div class="modal"><div class="m-head"><h3>'+d.name+
    ' <span style="font-size:13px;color:#9ca3af;font-weight:400">'+d.code+'</span></h3>'+
    '<span class="board-tag">'+d.board+'</span><span class="board-tag">'+d.industry+'</span>'+
    '<button class="m-close" onclick="document.getElementById(\'modal-mask\').classList.remove(\'open\')">✕</button></div>'+
    '<div class="m-kpis">'+
      kpiHtml('现价', d.px.toFixed(2), ''),
      kpiHtml('当日', fmtPct(d.chg), '', d.chg>0?'up':'down'),
      kpiHtml('近一年', fmtPct(d.ret_1y), '', d.ret_1y>0?'up':'down'),
      kpiHtml('权重分', d.score.toFixed(1), tierPill(d.tier)),
      kpiHtml('RSI(14)', d.rsi.toFixed(0), ''),
      kpiHtml('档位变化', tierChg(d.tier,d.tier_prev)||'不变', ''),
    '</div>'+
    '<div class="rule-box"><b>主营</b>：'+d.biz+'</div>'+
    bars+
    '<h4>K线（近 250 日 · 红涨绿跌）</h4>'+klineSVG+
    '<h4>权重分与动量历史（近 250 日）</h4>'+facSVG+
    '<div class="trade-tabs">'+
      '<button class="active" onclick="switchTradeTab(this,\'v9\')">普适版 交易史（'+(d.trades.v9_auto||[]).length+' 笔）</button>'+
      '<button onclick="switchTradeTab(this,\'lite\')">个人版 交易史（'+(d.trades.v8_lite||[]).length+' 笔）</button></div>'+
    '<div id="trades-v9">'+tradesV9+'</div><div id="trades-lite" style="display:none">'+tradesLite+'</div>'+
    '</div>';
  mask.classList.add('open');
}
function switchTradeTab(btn, which){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  document.getElementById('trades-v9').style.display=which==='v9'?'':'none';
  document.getElementById('trades-lite').style.display=which==='lite'?'':'none';
}
function kpiHtml(l,v,s,cls){return '<div class="kpi"><div class="l">'+l+'</div><div class="v '+(cls||'')+'">'+v+'</div><div class="s">'+(s||'')+'</div></div>';}
function renderTrades(ts){
  if(!ts||!ts.length)return '<div class="note">该体系未交易过此标的</div>';
  var h='<table><tr><th>买入</th><th>卖出</th><th>收益</th><th>持有天数</th></tr>';
  ts.forEach(function(t){
    h+='<tr><td>'+t.e+'</td><td>'+t.x+'</td><td class="'+(t.pct>0?'up':'down')+'">'+fmtPct(t.pct)+'</td><td>'+t.days+'天</td></tr>';});
  return h+'</table>';
}
function renderKline(kl){
  if(!kl||!kl.length)return '<div class="note">无K线数据</div>';
  var W=900,H=240,P=6,n=kl.length;
  var x0=34, x1=W-10;
  var lo=Math.min.apply(null,kl.map(function(k){return k.l})), hi=Math.max.apply(null,kl.map(function(k){return k.h}));
  var pad=(hi-lo)*0.05||1;
  var y=function(v){return P+(H-P*2)*(1-(v-lo+pad)/(hi-lo+2*pad));};
  var cw=(x1-x0)/n;
  var bw=Math.max(2,cw*0.55);
  var g='';
  for(var gv=0;gv<4;gv++){
    var gy=y(lo+pad+(hi-lo)*(gv/3));
    g+='<line x1="'+x0+'" y1="'+gy+'" x2="'+x1+'" y2="'+gy+'" stroke="rgba(128,128,128,.15)"/>';
    g+='<text x="'+x0+'" y="'+(gy+4)+'" font-size="10" fill="#9ca3af">'+(lo+pad+(hi-lo)*(gv/3)).toFixed(1)+'</text>';}
  var body='';
  for(var i=0;i<n;i++){
    var k=kl[i], cx=x0+i*cw+cw/2;
    var up=k.c>=k.o;
    var col=up?'#dc2626':'#16a34a';
    var yo=y(k.o), yc=y(k.c);
    var bh=Math.max(1,Math.abs(yc-yo));
    body+='<line x1="'+cx+'" y1="'+y(k.h)+'" x2="'+cx+'" y2="'+y(k.l)+'" stroke="'+col+'" stroke-width="1"/>';
    body+='<rect x="'+(cx-bw/2)+'" y="'+Math.min(yo,yc)+'" width="'+bw+'" height="'+bh+'" fill="'+col+'" rx="1"/>';}
  var last=kl[n-1];
  return '<svg viewBox="0 0 '+W+' '+(H+8)+'" style="width:100%;max-width:900px">'+g+body+
    '<text x="'+(x1-4)+'" y="'+(y(last.c)-6)+'" font-size="12" font-weight="bold" fill="'+(last.c>=last.o?'#dc2626':'#16a34a')+'" text-anchor="end">'+last.c.toFixed(2)+'</text></svg>';}
function renderFactors(fh){
  if(!fh||!fh.length)return '<div class="note">无因子历史</div>';
  var W=900,H=180,P=6,n=fh.length;
  var x0=34,x1=W-10;
  var lo=Math.min(0,Math.min.apply(null,fh.map(function(f){return f.mom}))), hi=Math.max(100,Math.max.apply(null,fh.map(function(f){return f.score})));
  var y=function(v){return P+(H-P*2)*(1-(v-lo)/(hi-lo));};
  var x=function(i){return x0+(x1-x0)*i/Math.max(1,n-1);};
  var g='';
  for(var gv=0;gv<3;gv++){
    var gy=y(lo+(hi-lo)*(gv/2));
    g+='<line x1="'+x0+'" y1="'+gy+'" x2="'+x1+'" y2="'+gy+'" stroke="rgba(128,128,128,.15)"/>';
    g+='<text x="'+x0+'" y="'+(gy+4)+'" font-size="10" fill="#9ca3af">'+(lo+(hi-lo)*(gv/2)).toFixed(0)+'</text>';}
  var ps='', pm='';
  fh.forEach(function(f,i){
    ps+=x(i).toFixed(1)+','+y(f.score).toFixed(1)+' ';
    pm+=x(i).toFixed(1)+','+y(f.mom).toFixed(1)+' ';});
  return '<svg viewBox="0 0 '+W+' '+(H+8)+'" style="width:100%;max-width:900px">'+g+
    '<polyline points="'+ps+'" fill="none" stroke="#3b82f6" stroke-width="2"/>'+
    '<polyline points="'+pm+'" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4,3"/>'+
    '<text x="'+x0+'" y="'+P+8+'" font-size="11" fill="#3b82f6">权重分(0-100)</text>'+
    '<text x="'+(x0+110)+'" y="'+P+8+'" font-size="11" fill="#f59e0b">12-1月动量%</text></svg>';}

document.addEventListener('DOMContentLoaded',function(){
  renderSidenav();
  renderCurve();
  renderKlineBoxes();
  var m=document.createElement('div');m.id='modal-mask';m.className='modal-mask';
  m.addEventListener('click',function(e){if(e.target===m)m.classList.remove('open');});
  document.body.appendChild(m);});

/* ---------- 双体系净值曲线（JS 运行时渲染，容器 #curve-chart） ---------- */
function renderCurve(){
  var el=document.getElementById('curve-chart');if(!el)return;
  var S=window.ENH.systems;if(!S)return;
  var va=S.v9_auto.equity, vl=S.v8_lite.equity;
  var n=Math.max(va.length,vl.length);
  var W=1400,H=300,PAD_L=70,PAD_R=20,PAD_T=26,PAD_B=34;
  var x=function(i){return PAD_L+(W-PAD_L-PAD_R)*i/Math.max(1,n-1);};
  var all=va.concat(vl);
  /* 对数 Y 轴：v8 净值 100→4100 而 v9 仅到 940，线性坐标下 v9 会被压扁贴底、刻度挤成"皱纹"。
     用 log2 坐标 + 2 的幂次刻度（100/200/400/800/1.6k/3.2k），两条曲线都清晰可见 */
  var lo=Math.max(50, Math.min.apply(null, all)*0.9), hi=Math.max(200, Math.max.apply(null, all));
  var lmin=Math.log(lo), lmax=Math.log(hi);
  var y=function(v){return PAD_T+(H-PAD_T-PAD_B)*(1-(Math.log(v)-lmin)/(lmax-lmin));};
  function tickLabel(v){
    if(v>=1000)return (v/1000).toFixed(v%1000===0?0:1)+'k';
    return String(v);}
  var g='';
  for(var t=100;t<=hi*1.02;t*=2){
    if(t<lo*0.95)continue;
    g+='<line x1="'+PAD_L+'" y1="'+y(t)+'" x2="'+(W-PAD_R)+'" y2="'+y(t)+'" stroke="rgba(128,128,128,.15)"/>';
    g+='<text x="'+(PAD_L-8)+'" y="'+(y(t)+4)+'" font-size="12" fill="#9ca3af" text-anchor="end">'+tickLabel(t)+'</text>';}
  var prevYr=null;
  for(var i=0;i<n;i++){
    var yr=2016+Math.floor(i/252);
    if(yr!==prevYr){g+='<text x="'+x(i)+'" y="'+(H-PAD_B+18)+'" font-size="13" fill="#9ca3af" text-anchor="middle">'+yr+'</text>';prevYr=yr;}}
  var poly=function(vals,color,width){
    var pts='';
    for(var i=0;i<vals.length;i+=3){pts+=x(i).toFixed(1)+','+y(vals[i]).toFixed(1)+' ';}
    return '<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="'+width+'"/>';};
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+
    poly(vl,'#3b82f6',2)+poly(va,'#f59e0b',2.5)+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+18)+'" font-size="13" fill="#3b82f6">个人版 → +'+S.v8_lite.summary.total_return_pct+'%</text>'+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+36)+'" font-size="13" fill="#f59e0b">普适版 → +'+S.v9_auto.summary.total_return_pct+'%</text>'+
    '<text x="'+(W-PAD_R-6)+'" y="'+(PAD_T+8)+'" font-size="11" fill="#9ca3af" text-anchor="end">对数坐标 · 净值(100起)</text></svg>';
}

/* ---------- 报告页 K线容器（.kline-box[data-code]） ---------- */
function renderKlineBoxes(){
  document.querySelectorAll('.kline-box').forEach(function(box){
    var d=window.ENH.details[box.getAttribute('data-code')];
    if(d&&d.kline)box.innerHTML=renderKline(d.kline);});}
"""
