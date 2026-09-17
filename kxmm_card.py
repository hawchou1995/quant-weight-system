# -*- coding: utf-8 -*-
"""看板「市场情绪」卡（kxmm）—— CSS / 视图骨架 / 渲染 JS（R-kxmm-0917）

数据由 backtest/fetch_kxmm.py 每日链抓取 → kxmm_data.js（window.KXMM_DATA）
本模块只提供静态骨架 + 客户端渲染（ECharts 本地化 echarts.min.js）。
注入方式：build_dual_system.py 以 {KXMM_CSS} / {KXMM_VIEW_HTML} / {KXMM_JS} 三个占位符引入。
"""

KXMM_CSS = """
/* ============ 市场情绪（kxmm）2026-09-17 ============ */
.kx-badges{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 6px}
.kx-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border:1px solid var(--border);
  border-radius:20px;font-size:12px;background:var(--card)}
.kx-badge b{font-weight:600}
.kx-badge .v{font-weight:700;font-size:14px}
.kx-badge em{font-style:normal;color:var(--faint);font-size:11px}
.kx-fg-top{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin:6px 0 4px}
.kx-gauge{width:300px;height:210px;flex:0 0 auto}
.kx-gauge-labels{display:flex;justify-content:space-between;width:300px;margin:-34px 0 0;font-size:11px;color:var(--faint)}
.kx-cur-num{font-size:40px;font-weight:800;line-height:1.1}
.kx-cur-status{font-size:16px;font-weight:700;margin-left:10px}
.kx-cur-head{display:flex;align-items:baseline;gap:4px}
.kx-cur-title{font-size:12px;color:var(--sub);margin-bottom:2px}
.kx-arch{display:flex;gap:18px;margin-top:12px;flex-wrap:wrap}
.kx-arch-item{text-align:center;min-width:64px}
.kx-arch-item .lb{font-size:11px;color:var(--faint)}
.kx-arch-item .st{font-size:11px;font-weight:600}
.kx-sec{margin-top:16px;border-top:1px dashed var(--border);padding-top:12px}
.kx-sec-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.kx-select{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;
  padding:4px 8px;font-size:12px;max-width:190px}
.kx-chart{width:100%}
.kx-ind-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:8px 0}
.kx-ind-card{border:1px solid var(--border);border-radius:10px;padding:8px 10px;cursor:pointer;
  background:var(--card);transition:border-color .15s}
.kx-ind-card:hover{border-color:var(--accent)}
.kx-ind-card.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.kx-ind-card .n{font-size:13px;font-weight:600;display:flex;justify-content:space-between;align-items:center}
.kx-ind-card .st{font-size:11px;font-weight:600}
.kx-ind-card .t{font-size:11px;color:var(--sub);margin-top:3px;line-height:1.35}
.kx-ind-card .d{font-size:10px;color:var(--faint);margin-top:3px}
.kx-heat-ctrl{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:8px 0}
.kx-tabs,.kx-subtabs{display:inline-flex;border:1px solid var(--border);border-radius:10px;overflow:hidden}
.kx-tab,.kx-subtab{padding:5px 14px;font-size:13px;cursor:pointer;background:var(--card);color:var(--sub);
  border-right:1px solid var(--border);user-select:none}
.kx-tab:last-child,.kx-subtab:last-child{border-right:none}
.kx-tab.active,.kx-subtab.active{background:var(--accent);color:#fff;font-weight:600}
.kx-subtab{font-size:12px;padding:4px 11px}
.kx-selects{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--sub);margin-left:auto}
"""

KXMM_VIEW_HTML = """
<!-- ============ 视图 F：市场情绪（kxmm 恐贪指数 + 热力图）· R-kxmm-0917 ============ -->
<div class="view" id="view-kxmm">

<div class="card" id="kxmm-fg">
  <h2>😨 恐贪指数 <span class="badge badge-auto">数据源：kxmm.online（开心檬檬）</span></h2>
  <div class="sub" id="kxmm-fg-meta">加载中…</div>
  <div class="kx-badges" id="kxmm-badges"></div>

  <div class="kx-fg-top">
    <div>
      <div class="kx-gauge" id="kxmm-gauge"></div>
      <div class="kx-gauge-labels"><span>极度恐惧</span><span>逆向</span><span>极度贪婪</span></div>
    </div>
    <div>
      <div class="kx-cur-title">当前指数</div>
      <div class="kx-cur-head">
        <span class="kx-cur-num" id="kxmm-cur-num">—</span>
        <span class="kx-cur-status" id="kxmm-cur-status"></span>
      </div>
      <div class="kx-arch" id="kxmm-arch"></div>
    </div>
  </div>

  <div class="kx-sec">
    <div class="kx-sec-head">
      <b>恐惧贪婪指数 · 历史走势</b>
      <span>对比指数 <select class="kx-select" id="kxmm-market-sel"></select></span>
    </div>
    <div class="kx-chart" id="kxmm-history" style="height:330px"></div>
  </div>

  <div class="kx-sec">
    <div class="kx-sec-head"><b>六大指标 · 综合研判市场贪婪与恐惧</b><span style="font-size:11px;color:var(--faint)">点击卡片查看分项走势</span></div>
    <div class="kx-ind-grid" id="kxmm-ind-grid"></div>
    <div class="kx-chart" id="kxmm-ind-detail" style="height:280px"></div>
    <div class="sub" id="kxmm-ind-desc"></div>
  </div>
</div>

<div class="card" id="kxmm-heat">
  <h2>🔥 市场热力图 <span class="badge badge-auto">矩形树图 · 面积/颜色可切换</span></h2>
  <div class="sub" id="kxmm-heat-meta">加载中…</div>
  <div class="kx-heat-ctrl">
    <span class="kx-tabs" id="kxmm-tabs">
      <span class="kx-tab active" data-tab="board">板块</span>
      <span class="kx-tab" data-tab="etf">ETF</span>
      <span class="kx-tab" data-tab="stock">股票</span>
    </span>
    <span class="kx-subtabs" id="kxmm-subtabs">
      <span class="kx-subtab active" data-kind="industry">行业</span>
      <span class="kx-subtab" data-kind="region">地域</span>
      <span class="kx-subtab" data-kind="concept">概念</span>
    </span>
    <span class="kx-selects">
      <span>面积</span><select class="kx-select" id="kxmm-size-sel"></select>
      <span>颜色</span><select class="kx-select" id="kxmm-color-sel"></select>
    </span>
  </div>
  <div class="kx-chart" id="kxmm-heatmap" style="height:600px"></div>
  <div class="sub" id="kxmm-heat-note"></div>
</div>

</div>
"""

KXMM_JS = r"""
/* ============ 市场情绪（kxmm）渲染 · R-kxmm-0917 ============ */
(function(){
  'use strict';
  var D = window.KXMM_DATA || null;
  var built = false, charts = {};
  var heatState = {tab:'board', kind:'industry', size:'amount', color:'pct', indId:null};

  function el(id){ return document.getElementById(id); }
  function hasEcharts(){ return typeof echarts !== 'undefined'; }
  function css(name, fb){ try{ var v=getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v||fb; }catch(e){ return fb; } }

  function fmtMoney(v){
    if(v==null||isNaN(v)) return '—';
    var a=Math.abs(v);
    if(a>=1e12) return (v/1e12).toFixed(2)+'万亿';
    if(a>=1e8) return (v/1e8).toFixed(2)+'亿';
    if(a>=1e4) return (v/1e4).toFixed(1)+'万';
    return String(Math.round(v));
  }
  function fmtPct(v){ return (v==null||isNaN(v))?'—':((v>0?'+':'')+Number(v).toFixed(2)+'%'); }
  function fmtNum(v, digits){
    if(v==null||isNaN(v)) return '—';
    var n=Number(v);
    if(digits!=null) return n.toFixed(digits);
    return Number.isInteger(n)? String(n) : String(Math.round(n*100)/100);
  }
  function dateFromTs(ts){
    var d=new Date(ts); if(isNaN(d)) return '—';
    return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  }
  /* ---- 颜色：红涨绿跌（A股惯例）+ 顺序蓝 ---- */
  function divergingColor(v, maxAbs){
    if(!maxAbs) return '#e2e8f0';
    var t=Math.min(1,Math.abs(v)/maxAbs);
    var c1=[241,245,249];
    var c2=(v>=0)?[214,39,40]:[26,152,80];
    return 'rgb('+[0,1,2].map(function(i){return Math.round(c1[i]+(c2[i]-c1[i])*t);}).join(',')+')';
  }
  function seqColor(v, maxV){
    if(maxV==null) return '#e2e8f0';
    var t=Math.min(1,Math.max(0,v)/(maxV||1));
    var c1=[224,242,254], c2=[7,72,153];
    return 'rgb('+[0,1,2].map(function(i){return Math.round(c1[i]+(c2[i]-c1[i])*t);}).join(',')+')';
  }
  function p95(vals){
    var a=vals.filter(function(x){return x!=null&&!isNaN(x);}).map(Math.abs).sort(function(x,y){return x-y;});
    if(!a.length) return 0;
    return a[Math.min(a.length-1, Math.floor(a.length*0.95))]||a[a.length-1];
  }
  function statusColor(c){ return c || '#1890FF'; }

  /* ================= 徽章条 ================= */
  function renderBadges(){
    var box=el('kxmm-badges'); if(!box) return;
    var bs=(D&&D.badges)||[];
    if(!bs.length){ box.innerHTML=''; return; }
    box.innerHTML=bs.map(function(b){
      var isTheme=(b.key||'').indexOf('kt')===0;
      var v=isTheme? Math.round(b.num) : fmtNum(b.num);
      return '<span class="kx-badge"><b>'+b.name+'</b><span class="v" style="color:'+statusColor(b.color)+'">'+v+'</span>'
        +'<span style="color:'+statusColor(b.color)+'">'+(b.status||'')+'</span><em>'+(b.date||'')+'</em></span>';
    }).join('');
  }

  /* ================= 往期 mini 弧 ================= */
  function arcItem(name, value, status, color){
    /* API 的往期值为 0-1 刻度（arcbar），展示换算成 0-100 */
    var v100=(value==null)?0:(value<=1.001? value*100 : value);
    var t=Math.min(1,Math.max(0,v100/100));
    var r=24, cx=32, cy=30, len=Math.PI*r;
    var hue=215-215*t;   /* 蓝(恐惧) → 红(贪婪) */
    var stroke='hsl('+hue.toFixed(0)+',82%,55%)';
    var d='M '+(cx-r)+' '+cy+' A '+r+' '+r+' 0 0 1 '+(cx+r)+' '+cy;
    return '<div class="kx-arch-item">'
      +'<svg width="64" height="38" viewBox="0 0 64 38">'
      +'<path d="'+d+'" fill="none" stroke="rgba(128,128,128,.25)" stroke-width="6" stroke-linecap="round"/>'
      +'<path d="'+d+'" fill="none" stroke="'+stroke+'" stroke-width="6" stroke-linecap="round"'
      +' stroke-dasharray="'+(len*t).toFixed(1)+' '+len.toFixed(1)+'"/>'
      +'<text x="32" y="30" text-anchor="middle" font-size="14" font-weight="700" fill="'+stroke+'">'+fmtNum(v100)+'</text>'
      +'</svg>'
      +'<div class="lb">'+name+'</div>'
      +'<div class="st" style="color:'+statusColor(color)+'">'+(status||'')+'</div>'
      +'</div>';
  }

  /* ================= 恐贪主卡 ================= */
  function buildFearGreed(){
    var fg=D.fear_greed||{}, base=fg.base||{};
    el('kxmm-fg-meta').innerHTML='交易日 <b>'+(base.current_time||'—')+'</b> · 抓取于 '+(D.fetched_at||'—')
      +' · 说明：恐贪值由数据源次晨发布，看板显示最近一个已发布交易日'
      +(base.explain?(' · 口径：'+base.explain):'');
    renderBadges();

    var num=base.num;
    /* 主仪表盘 */
    if(hasEcharts() && el('kxmm-gauge')){
      charts.gauge=echarts.init(el('kxmm-gauge'));
      charts.gauge.setOption({
        animationDuration:600,
        series:[{
          type:'gauge', startAngle:210, endAngle:-30, min:0, max:100, radius:'96%',
          center:['50%','62%'],
          axisLine:{lineStyle:{width:16,color:[[1,new echarts.graphic.LinearGradient(0,0,1,0,[
            {offset:0,color:'#1890FF'},{offset:.5,color:'#a855f7'},{offset:1,color:'#f5222d'}])]]}},
          pointer:{icon:'path://M2 0 L0 -58 L-2 0 Z', length:'58%', width:6, offsetCenter:[0,'2%'],
                   itemStyle:{color:statusColor(base.status_color===''?'#64748b':base.status_color)}},
          axisTick:{show:false}, splitLine:{show:false}, axisLabel:{show:false},
          detail:{fontSize:30,fontWeight:800,offsetCenter:[0,'-24%'],color:statusColor(base.status_color),
                  formatter:function(v){return Math.round(v);}},
          data:[{value:(num==null?0:num)}]
        }]
      });
    }
    var cn=el('kxmm-cur-num');
    if(cn){ cn.textContent=fmtNum(num); cn.style.color=statusColor(base.status_color); }
    var cs=el('kxmm-cur-status');
    if(cs){ cs.textContent=base.status_str||''; cs.style.color=statusColor(base.status_color); }

    var arch=el('kxmm-arch');
    if(arch){
      arch.innerHTML=(fg.base_archives||[]).map(function(a){return arcItem(a.name,a.value,a.status_str,a.status_color);}).join('');
    }

    /* 市场选择器 + 历史走势 */
    var sel=el('kxmm-market-sel'), markets=fg.markets||{}, codes=Object.keys(markets);
    if(sel){
      sel.innerHTML=codes.map(function(c){return '<option value="'+c+'">'+(markets[c].name||c)+'</option>';}).join('');
      sel.onchange=function(){ renderHistory(sel.value); };
    }
    if(codes.length) renderHistory(codes[0]);

    /* 六大指标 */
    var grid=el('kxmm-ind-grid');
    var types=fg.types||[];
    if(grid){
      grid.innerHTML=types.map(function(t){
        var ind=(fg.indicators||{})[String(t.id)]||{};
        var st=ind.status_name||'', scol=statusColor(ind.status_color);
        var last=lastSeriesDate(ind);
        var sub=stripTags(ind.status_html_name||'');
        return '<div class="kx-ind-card" data-id="'+t.id+'">'
          +'<div class="n"><span>'+t.name+'</span><span class="st" style="color:'+scol+'">'+(st?('● '+st):'')+'</span></div>'
          +'<div class="t">'+(ind.title||t.title||'')+'</div>'
          +'<div class="d">'+(sub?(sub+' · '):'')+'更新：'+(last||'—')+'</div>'
          +'</div>';
      }).join('');
      grid.querySelectorAll('.kx-ind-card').forEach(function(c){
        c.onclick=function(){
          grid.querySelectorAll('.kx-ind-card').forEach(function(x){x.classList.remove('active');});
          c.classList.add('active');
          renderIndicator(c.getAttribute('data-id'));
        };
      });
      if(types.length){ grid.querySelector('.kx-ind-card').classList.add('active'); renderIndicator(String(types[0].id)); }
    }
  }

  function lastSeriesDate(ind){
    var s=(ind.series||[])[0]; var data=(s&&s.data)||[];
    return data.length? dateFromTs(data[data.length-1][0]) : '';
  }
  function stripTags(s){ return (s||'').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim(); }

  function renderHistory(code){
    var m=(D.fear_greed.markets||{})[code]; if(!m||!hasEcharts()||!el('kxmm-history')) return;
    if(!charts.hist){ charts.hist=echarts.init(el('kxmm-history')); }
    var mkName=m.name||code;
    var vals=(m.series&&m.series[0]?m.series[0].data:[])||[];
    var closes=(m.series&&m.series[1]?m.series[1].data:[])||[];
    charts.hist.setOption({
      tooltip:{trigger:'axis'},
      legend:{data:['恐惧贪婪指数',mkName],bottom:0,textStyle:{fontSize:11}},
      grid:{left:44,right:56,top:16,bottom:44},
      xAxis:{type:'category',data:m.x_data||[],axisLabel:{fontSize:10,interval:Math.floor((m.x_data||[]).length/8)}},
      yAxis:[{type:'value',min:0,max:100,name:'恐贪',nameTextStyle:{fontSize:10}},
             {type:'value',scale:true,name:mkName,nameTextStyle:{fontSize:10}}],
      series:[
        {name:'恐惧贪婪指数',type:'line',data:vals,showSymbol:false,smooth:false,
         lineStyle:{color:'#FF2525',width:1.6},itemStyle:{color:'#FF2525'},
         areaStyle:{color:'rgba(255,37,37,.10)'}},
        {name:mkName,type:'line',yAxisIndex:1,data:closes,showSymbol:false,
         lineStyle:{color:'#94a3b8',width:1.3},itemStyle:{color:'#94a3b8'}}
      ]
    },true);
  }

  function renderIndicator(id){
    var ind=(D.fear_greed.indicators||{})[String(id)]; if(!ind||!hasEcharts()||!el('kxmm-ind-detail')) return;
    if(!charts.ind){ charts.ind=echarts.init(el('kxmm-ind-detail')); }
    var series=(ind.series||[]).map(function(s){
      return {name:s.name||ind.title||'', type:'line', showSymbol:false, data:s.data||[],
              lineStyle:{width:1.5}};
    });
    charts.ind.setOption({
      tooltip:{trigger:'axis'},
      legend:{bottom:0,textStyle:{fontSize:11}},
      grid:{left:48,right:20,top:14,bottom:44},
      xAxis:{type:'time',axisLabel:{fontSize:10}},
      yAxis:{type:'value',scale:true,name:ind.y_company||'',nameTextStyle:{fontSize:10}},
      series:series
    },true);
    var desc=el('kxmm-ind-desc');
    if(desc) desc.textContent=stripTags(ind.desc);
  }

  /* ================= 热力图 ================= */
  var M_BASE=[
    {k:'pct',l:'涨跌幅',t:'signed'},
    {k:'amount',l:'成交额',t:'seq'},
    {k:'total_mv',l:'总市值',t:'seq'},
    {k:'float_mv',l:'流通市值',t:'seq'},
    {k:'main_inflow',l:'主力净流入',t:'signed'},
    {k:'xl_inflow',l:'超大单净流入',t:'signed'},
    {k:'l_inflow',l:'大单净流入',t:'signed'},
    {k:'m_inflow',l:'中单净流入',t:'signed'},
    {k:'s_inflow',l:'小单净流入',t:'signed'},
    {k:'main_rate',l:'主力净流入率',t:'signed',calc:function(it){return it.amount? it.main_inflow/it.amount*100 : null;}},
    {k:'pct_60d',l:'60日涨跌幅',t:'signed'},
    {k:'pct_ytd',l:'今年涨跌幅',t:'signed'},
    {k:'turnover',l:'换手率',t:'seq'},
    {k:'volume_ratio',l:'量比',t:'seq'},
    {k:'amplitude',l:'振幅',t:'seq'},
    {k:'total_shares',l:'总股本',t:'seq'},
    {k:'float_shares',l:'流通股本',t:'seq'}
  ];
  var M_BOARD=M_BASE.concat([
    {k:'up_count',l:'上涨家数',t:'seq'},
    {k:'down_count',l:'下跌家数',t:'seq'},
    {k:'limit_up',l:'涨停家数',t:'seq'},
    {k:'limit_down',l:'跌停家数',t:'seq'},
    {k:'up_ratio',l:'上涨家数占比',t:'seq',calc:function(it){var s=(it.up_count||0)+(it.down_count||0)+(it.flat_count||0);return s? it.up_count/s*100 : null;}},
    {k:'ud_diff',l:'涨跌家数差',t:'signed',calc:function(it){return (it.up_count||0)-(it.down_count||0);}},
    {k:'lu_ratio',l:'涨停占比',t:'seq',calc:function(it){var s=(it.up_count||0)+(it.down_count||0)+(it.flat_count||0);return s? (it.limit_up||0)/s*100 : null;}}
  ]);
  function metricsFor(){ return heatState.tab==='board'? M_BOARD : M_BASE; }
  function valueOf(it, metric){
    if(!metric) return null;
    var v=metric.calc? metric.calc(it) : it[metric.k];
    return (v==null||isNaN(v))? null : Number(v);
  }
  function dataset(){
    var h=D.heat||{};
    if(heatState.tab==='board') return h['board_'+heatState.kind]||null;
    if(heatState.tab==='etf') return h.etf||null;
    return h.stock||null;
  }

  function heatLabel(){
    var d=dataset(); if(!d) return '暂无数据';
    var meta='数据日期 <b>'+(d.date||'—')+'</b>（收盘）'+(d.file_time?(' · 源文件 '+d.file_time):'')
      +' · 抓取于 '+(D.fetched_at||'—');
    return meta;
  }
  function heatNote(){
    var d=dataset(); if(!d) return '';
    var n='条目 '+((d.items||[]).length);
    if(heatState.tab==='stock'&&d.total_items) n+=' / 全市场 '+d.total_items+' 只（仅展示成交额 Top'+(d.shown||600)+'，裁剪以控制页面体积）';
    n+=' · 颜色口径：红涨绿跌（A股惯例）· 数据随每日链更新（收盘后）';
    return n;
  }

  function buildHeat(){
    var tabs=el('kxmm-tabs');
    if(tabs){
      tabs.querySelectorAll('.kx-tab').forEach(function(t){
        t.onclick=function(){
          tabs.querySelectorAll('.kx-tab').forEach(function(x){x.classList.remove('active');});
          t.classList.add('active'); heatState.tab=t.getAttribute('data-tab');
          el('kxmm-subtabs').style.display=(heatState.tab==='board')?'inline-flex':'none';
          rebuildMetricSelects(); renderHeat();
        };
      });
    }
    var subs=el('kxmm-subtabs');
    if(subs){
      subs.querySelectorAll('.kx-subtab').forEach(function(t){
        t.onclick=function(){
          subs.querySelectorAll('.kx-subtab').forEach(function(x){x.classList.remove('active');});
          t.classList.add('active'); heatState.kind=t.getAttribute('data-kind'); renderHeat();
        };
      });
    }
    rebuildMetricSelects();
    renderHeat();
  }

  function rebuildMetricSelects(){
    var ms=metricsFor();
    var ss=el('kxmm-size-sel'), cs=el('kxmm-color-sel');
    function fill(sel, def){
      if(!sel) return;
      sel.innerHTML=ms.map(function(m){return '<option value="'+m.k+'">'+m.l+'</option>';}).join('');
      sel.value=ms.some(function(m){return m.k===def;})? def : ms[0].k;
    }
    fill(ss, heatState.size); fill(cs, heatState.color);
    heatState.size=ss? ss.value : heatState.size;
    heatState.color=cs? cs.value : heatState.color;
    if(ss) ss.onchange=function(){ heatState.size=ss.value; renderHeat(); };
    if(cs) cs.onchange=function(){ heatState.color=cs.value; renderHeat(); };
  }

  function renderHeat(){
    var note=el('kxmm-heat-note'); if(note) note.innerHTML=heatNote();
    var meta=el('kxmm-heat-meta'); if(meta) meta.innerHTML=heatLabel();
    var box=el('kxmm-heatmap'); if(!box||!hasEcharts()) return;
    var d=dataset();
    if(!charts.heat){ charts.heat=echarts.init(box); }
    if(!d||!(d.items||[]).length){ charts.heat.clear(); charts.heat.setOption({title:{text:'暂无数据',left:'center',top:'middle',textStyle:{fontSize:14,color:'#94a3b8'}}}); return; }
    var ms=metricsFor();
    var mSize=null, mColor=null;
    ms.forEach(function(m){ if(m.k===heatState.size) mSize=m; if(m.k===heatState.color) mColor=m; });
    var items=d.items;
    var sizeVals=items.map(function(it){ return Math.abs(valueOf(it,mSize)||0); });
    var colorVals=items.map(function(it){ return valueOf(it,mColor); });
    var maxAbs=p95(colorVals.filter(function(v){return v!=null;}));
    var maxSeq=Math.max.apply(null, colorVals.map(function(v){return v==null?0:Math.abs(v);}).concat([0]));
    var rows=items.map(function(it,idx){
      var sv=sizeVals[idx];
      if(!(sv>0)) sv=Math.max(maxSeq*1e-6,1e-9);
      var cv=colorVals[idx];
      var col=(mColor&&mColor.t==='signed')? divergingColor(cv==null?0:cv, maxAbs) : seqColor(cv==null?0:cv, maxSeq);
      return {name:it.name, value:sv, raw:it, itemStyle:{color:col}};
    });
    charts.heat.setOption({
      tooltip:{
        formatter:function(p){
          var it=p.data.raw||{};
          var lines=['<b>'+it.name+'</b>'+(it.code?(' <span style="color:#94a3b8">'+it.code+'</span>'):'')];
          lines.push('涨跌幅：<b style="color:'+((it.pct||0)>=0?'#d62728':'#1a9850')+'">'+fmtPct(it.pct)+'</b>');
          lines.push('成交额：'+fmtMoney(it.amount)+' · 换手率：'+(it.turnover==null?'—':it.turnover.toFixed(2)+'%'));
          lines.push('主力净流入：'+fmtMoney(it.main_inflow)+' · 净流入率：'+(it.amount?((it.main_inflow/it.amount*100).toFixed(2)+'%'):'—'));
          lines.push('总市值：'+fmtMoney(it.total_mv)+' / 流通：'+fmtMoney(it.float_mv));
          if(it.up_count!=null) lines.push('上涨 '+it.up_count+' / 下跌 '+it.down_count+' / 涨停 '+it.limit_up+' · 领涨：'+(it.lead_stock||'—'));
          return lines.join('<br>');
        }
      },
      series:[{
        type:'treemap', roam:false, nodeClick:false, breadcrumb:{show:false},
        width:'100%', height:'100%',
        top:0, left:0, right:0, bottom:0,
        label:{show:true, formatter:'{b}', fontSize:12, color:'#1f2937', overflow:'truncate'},
        upperLabel:{show:false},
        itemStyle:{borderColor:'rgba(120,120,120,.35)', borderWidth:1, gapWidth:1},
        emphasis:{itemStyle:{borderColor:'#f59e0b',borderWidth:2}},
        data:rows
      }]
    }, true);
  }

  /* ================= 空态 / 视图钩子 ================= */
  function showEmpty(){
    var msg='暂无数据：等待每日链抓取（<code>backtest/fetch_kxmm.py</code>，或手动运行一次）';
    var a=el('kxmm-fg-meta'), b=el('kxmm-heat-meta');
    if(a) a.innerHTML=msg; if(b) b.innerHTML=msg;
  }
  function resizeAll(){
    Object.keys(charts).forEach(function(k){ try{ charts[k].resize(); }catch(e){} });
  }
  function activate(){
    if(!D){ showEmpty(); return; }
    if(!built){
      built=true;
      try{ if(hasEcharts()){ buildFearGreed(); buildHeat(); } else { showEmpty(); } }
      catch(e){
        var a=el('kxmm-fg-meta'); if(a) a.innerHTML='渲染失败：'+(e&&e.message?e.message:e);
      }
    }
    resizeAll();
  }
  ready(function(){
    if(el('view-kxmm') && el('view-kxmm').classList.contains('active')) activate();
    window.addEventListener('resize', function(){ 
      if(el('view-kxmm') && el('view-kxmm').classList.contains('active')) resizeAll(); });
    var _sw=window.switchView;
    if(typeof _sw==='function'){
      window.switchView=function(key){ _sw(key); if(key==='kxmm') activate(); };
      try{ switchView=window.switchView; }catch(e){}
    } else {
      /* 兜底：无 switchView（老结构）时用 hash 监听 */
      window.addEventListener('hashchange', function(){ if((location.hash||'').replace('#','')==='kxmm') activate(); });
    }
  });
  function ready(fn){
    if(document.readyState!=='loading'){ fn(); }
    else { document.addEventListener('DOMContentLoaded', fn); }
  }
})();
"""
