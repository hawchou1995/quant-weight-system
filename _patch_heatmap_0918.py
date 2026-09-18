# -*- coding: utf-8 -*-
"""把「股票实时热力树图」卡接进市场晴雨视图（用户需求 #4）。

规格（公众号原文，经自动化 Chrome 取正文）：
  根=A股全市场 → 中间=申万一级行业 → 叶=个股；面积=成交额/总市值/流通市值（可切）；
  颜色=涨跌幅；行业块颜色优先指数、取不到回退成分股加权（本实现 = 成分股按面积加权，
  payload 里标 color_src=weighted，接指数后替换）。

落点：KXMM_VIEW_HTML（= 市场晴雨视图 view-kxmm）末尾插入卡片；KXMM_JS 末尾追加渲染逻辑。
数据：heatmap_data.js（window.HEATMAP，由 backtest/build_heatmap.py 产出）。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
KX = BASE / "kxmm_card.py"
OK = True

CARD = '''
<div class="card" id="hm-card">
<h2>热力树图 <span class="badge badge-auto" id="hm-asof">—</span></h2>
<div class="sub">根=<b>A股全市场</b> → 中间=<b>申万一级行业</b> → 叶=<b>个股</b>；<b>面积</b>表示体量、<b>颜色</b>表示涨跌幅（红涨绿跌）。
行业块颜色 = 成分股按面积加权（指数口径待接）。开盘后可随盘中补丁刷新；当前为最近收盘口径。
<span class="hm-legend"><i class="hm-lg hm-lg-dn"></i>-10%<i class="hm-lg hm-lg-mid"></i>0<i class="hm-lg hm-lg-up"></i>+10%</span></div>
<div class="hm-bar">
  <span class="hm-seg" id="hm-metric">
    <button class="hm-btn active" data-m="m">总市值</button>
    <button class="hm-btn" data-m="a">成交额</button>
    <button class="hm-btn" data-m="f">流通市值</button>
  </span>
  <span class="hm-hint" id="hm-hint"></span>
</div>
<div class="hm-chart" id="hm-chart"></div>
<div class="sub" id="hm-note" style="color:var(--faint)"></div>
</div>
'''

JS = r"""
/* ============ 热力树图（R-heatmap-0918 · 用户需求 #4） ============ */
(function(){
  'use strict';
  var HD = window.HEATMAP || null;
  var built = false, metric = 'm', chart = null;
  function el(id){ return document.getElementById(id); }
  function cssv(n, fb){ try{ var v=getComputedStyle(document.documentElement).getPropertyValue(n).trim(); return v||fb; }catch(e){ return fb; } }

  /* 发散色阶：绿(-) → 浅灰(0) → 红(+)；中国习惯红涨绿跌 */
  function pctColor(p){
    var lim = 10, x = Math.max(-lim, Math.min(lim, p)) / lim;
    var up = [214,39,40], dn = [26,152,80], mid = [232,234,240];
    var c;
    if(x >= 0){ c = [0,1,2].map(function(i){ return Math.round(mid[i] + (up[i]-mid[i]) * x); }); }
    else{ c = [0,1,2].map(function(i){ return Math.round(mid[i] + (dn[i]-mid[i]) * (-x)); }); }
    return 'rgb(' + c.join(',') + ')';
  }
  function fmt(v, u){
    if(v == null || isNaN(v)) return '—';
    return (u === 'yi') ? (v.toFixed(v >= 100 ? 0 : 1) + ' 亿') : v.toFixed(2);
  }

  function build(){
    if(!HD || !HD.tree) return null;
    var key = metric;
    var lbl = ({m:'总市值', a:'成交额', f:'流通市值'})[key];
    var out = [];
    HD.tree.forEach(function(sec){
      var kids = [], wsum = 0, pw = 0;
      sec.children.forEach(function(s){
        var v = s[key];
        if(!(v > 0)) v = Math.max(s.m * 0.001, 0.01);
        kids.push({name: s.n, value: v, code: s.c, pct: s.p, m: s.m, a: s.a, f: s.f,
                   itemStyle: {color: pctColor(s.p)}});
        wsum += v; pw += v * s.p;
      });
      var secPct = wsum > 0 ? (pw / wsum) : 0;
      out.push({name: sec.name, value: wsum, pct: secPct, isSec: true,
                itemStyle: {color: pctColor(secPct)}, children: kids});
    });
    el('hm-hint').textContent = '面积 = ' + lbl + '（亿元）';
    return out;
  }

  function render(){
    if(!window.echarts || !HD){ return false; }
    var host = el('hm-chart');
    if(!host) return false;
    if(!chart) chart = echarts.init(host);
    var data = build();
    if(!data){ return false; }
    var card = cssv('--card', '#fff'), bord = cssv('--border', '#e5e7eb'), txt = cssv('--text', '#111827');
    chart.setOption({
      tooltip: {
        backgroundColor: card, borderColor: bord, borderWidth: 1,
        textStyle: {color: txt, fontSize: 12},
        extraCssText: 'box-shadow:0 8px 26px rgba(0,0,0,.14);border-radius:10px;padding:9px 12px;line-height:1.6',
        formatter: function(p){
          var d = p.data || {};
          if(d.isSec){
            return '<b>' + d.name + '</b>（申万一级）<br>加权涨跌：<b style="color:' +
              (d.pct >= 0 ? '#d62728' : '#1a9850') + '">' + (d.pct >= 0 ? '+' : '') + d.pct.toFixed(2) + '%</b>';
          }
          return '<b>' + d.name + '</b> <span style="color:#94a3b8">' + (d.code || '') + '</span><br>' +
            '涨跌幅：<b style="color:' + (d.pct >= 0 ? '#d62728' : '#1a9850') + '">' +
            (d.pct >= 0 ? '+' : '') + d.pct.toFixed(2) + '%</b><br>' +
            '总市值：' + fmt(d.m, 'yi') + ' · 流通：' + fmt(d.f, 'yi') + '<br>' +
            '成交额：' + fmt(d.a, 'yi');
        }
      },
      series: [{
        type: 'treemap', roam: false, nodeClick: false, breadcrumb: {show: false},
        width: '100%', height: '100%', top: 0, left: 0, right: 0, bottom: 0,
        leafDepth: 2,
        label: {show: true, formatter: '{b}', fontSize: 11, color: '#fff',
                textShadowColor: 'rgba(0,0,0,.45)', textShadowBlur: 2, overflow: 'truncate'},
        upperLabel: {show: true, height: 20, fontSize: 11, color: '#fff',
                     textShadowColor: 'rgba(0,0,0,.45)', textShadowBlur: 2},
        itemStyle: {borderColor: 'rgba(255,255,255,.55)', borderWidth: 1, gapWidth: 1},
        levels: [
          {itemStyle: {borderColor: bord, borderWidth: 2, gapWidth: 2}},
          {itemStyle: {borderColor: 'rgba(255,255,255,.5)', borderWidth: 1, gapWidth: 1}}
        ],
        data: data
      }]
    }, true);
    return true;
  }

  function activate(){
    if(built) { if(chart) chart.resize(); return; }
    if(render()) built = true;
  }

  function initBar(){
    var box = el('hm-metric');
    if(!box) return;
    box.addEventListener('click', function(e){
      var b = e.target.closest('.hm-btn');
      if(!b) return;
      [].forEach.call(box.querySelectorAll('.hm-btn'), function(x){ x.classList.toggle('active', x === b); });
      metric = b.getAttribute('data-m');
      render();
    });
  }

  function boot(){
    if(!HD){ var n = el('hm-note'); if(n) n.textContent = '暂无数据：运行 backtest/build_heatmap.py'; return; }
    var a = el('hm-asof'); if(a) a.textContent = '截至 ' + (HD.asof || '—') + ' · ' + (HD.color_src === 'weighted' ? '加权口径' : '指数口径');
    var n = el('hm-note');
    if(n) n.textContent = '行业 ' + (HD.tree || []).length + ' 个 · 个股 ' +
      (HD.tree || []).reduce(function(s, t){ return s + t.children.length; }, 0) + ' 只（不做北交所）';
    initBar();
    if(el('view-kxmm') && el('view-kxmm').classList.contains('active')) activate();
    document.querySelectorAll('.sidenav a[data-anchor]').forEach(function(a2){
      a2.addEventListener('click', function(){ setTimeout(activate, 60); });
    });
    window.addEventListener('resize', function(){ if(chart) chart.resize(); });
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
"""

CSS = '''
/* 热力树图（R-heatmap-0918） */
#hm-card .hm-bar{display:flex;align-items:center;gap:14px;margin:6px 0 10px;flex-wrap:wrap}
#hm-card .hm-seg{display:inline-flex;background:var(--card2);border:1px solid var(--border);border-radius:10px;overflow:hidden}
#hm-card .hm-btn{background:transparent;border:none;color:var(--sub);font-family:inherit;font-size:12.5px;
  padding:7px 14px;cursor:pointer;transition:background .15s,color .15s}
#hm-card .hm-btn:hover{color:var(--text)}
#hm-card .hm-btn.active{background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;font-weight:600}
#hm-card .hm-hint{font-size:12px;color:var(--faint)}
#hm-card .hm-chart{width:100%;height:640px}
#hm-card .hm-legend{display:inline-flex;align-items:center;gap:5px;margin-left:12px;color:var(--faint);font-size:11px}
#hm-card .hm-lg{width:16px;height:9px;border-radius:2px;display:inline-block}
#hm-card .hm-lg-dn{background:#1a9850}
#hm-card .hm-lg-mid{background:#e8eaf0;border:1px solid var(--border)}
#hm-card .hm-lg-up{background:#d62728}
'''


def main():
    global OK
    t = KX.read_text(encoding="utf-8")

    # ① 卡片插到 view-kxmm 末尾（最后一个 </div> 之前）
    anchor_tail = '  <div class="sub" id="kxmm-heat-note"></div>\n</div>\n\n</div>\n"""'
    new_tail = '  <div class="sub" id="kxmm-heat-note"></div>\n</div>\n' + CARD + '\n</div>\n"""'
    if new_tail in t:
        print("  [skip] 卡片（已插过）")
    elif t.count(anchor_tail) == 1:
        t = t.replace(anchor_tail, new_tail, 1)
        print("  [ok]   卡片已插入 view-kxmm")
    else:
        print(f"  [FAIL] 卡片锚点命中 {t.count(anchor_tail)} 次")
        OK = False

    # ② CSS 追加
    if "/* 热力树图（R-heatmap-0918） */" in t:
        print("  [skip] CSS（已加过）")
    else:
        marker = 'KXMM_JS = r"""'
        if t.count(marker) == 1:
            t = t.replace(marker, CSS + "\n" + marker, 1)
            print("  [ok]   CSS 已追加")
        else:
            print(f"  [FAIL] CSS 锚点命中 {t.count(marker)} 次")
            OK = False

    # ③ JS 追加到文件末尾的 IIFE 之后
    if "热力树图（R-heatmap-0918 · 用户需求 #4）" in t:
        print("  [skip] JS（已加过）")
    else:
        t = t.rstrip() + "\n\n" + JS
        print("  [ok]   JS 已追加")

    try:
        ast.parse(t)
        print("  [ok]   AST")
    except SyntaxError as e:
        print(f"  [FAIL] AST: line {e.lineno} {e.msg}")
        OK = False
        return
    KX.write_text(t, encoding="utf-8")
    print()
    print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
