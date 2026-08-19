# -*- coding: utf-8 -*-
"""index.html（五 tab 主看板）注入升级：顶部导航(历史报告/明暗/qingju.me) +
左侧贴边导航(tab 切换) + 交易表排序/搜索/行点击详情。不动模板 JS。"""
import os
import re
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

html = (BASE / "index.html").read_text(encoding="utf-8")

# 注入样式（模板 style 之后 → 我们的变量覆盖生效）
style_tag = f"<style>{THEME_CSS}</style>"
if "</head>" in html:
    html = html.replace("</head>", style_tag + "</head>")
else:
    html = style_tag + html

# 注入顶部导航 + 左侧导航（body 开头）
if "<body" in html:
    m = re.search(r"<body[^>]*>", html)
    html = html[:m.end()] + NAV_HTML + html[m.end():]
else:
    html = NAV_HTML + html

# 隐藏模板自带的 topbar（避免双顶栏）
html = re.sub(r'<div class="topbar"[^>]*id="topbar"[^>]*>.*?</div>', '', html, count=1, flags=re.S)

# 注入增强脚本（</body> 前）：sidenav 变 tab 切换 + 交易表增强 + 详情弹层
INJECT_JS = r"""
<script src="enhanced_data.js"></script>
<script>
/* ===== 五 tab 左侧导航（点击切换 tab） ===== */
(function(){
  /* 隐藏模板运行时渲染的 topbar（避免双顶栏） */
  var hideTb=function(){
    var tb=document.getElementById('topbar');
    if(tb){tb.style.display='none';}
  };
  document.addEventListener('DOMContentLoaded',hideTb);
  new MutationObserver(hideTb).observe(document.body,{subtree:true,childList:true});
  function renderTabNav(){
    var nav=document.getElementById('sidenav');if(!nav)return;
    var items=[['auto','🅰️','普适版'],['lite','🅱️','个人版'],['stock','📈','股票'],['etf','📊','ETF'],['fund','💰','基金']];
    var html='<div class="sn-logo"><span class="dot"></span>量化权重监控</div><div class="sn-sep"></div>';
    items.forEach(function(it){
      html+='<a href="javascript:void(0)" data-navtab="'+it[0]+'"><span class="ic">'+it[1]+'</span>'+it[2]+'</a>';});
    html+='<div class="sn-sep"></div><div class="sn-foot">'+
      '<a href="https://qingju.me/" target="_blank" rel="noopener"><span class="ic">💬</span>青橘社区</a></div>';
    nav.innerHTML=html;
    document.body.classList.add('sidenav-open');
    nav.querySelectorAll('a[data-navtab]').forEach(function(a){
      a.addEventListener('click',function(e){
        e.preventDefault();
        var t=a.getAttribute('data-navtab');
        var btn=document.querySelector('.tab[data-tab="'+t+'"]');
        if(btn){btn.click();}
        nav.querySelectorAll('a[data-navtab]').forEach(function(x){x.classList.toggle('active',x===a);});
      });});
  }
  /* 观察 tab 渲染后同步高亮 */
  var obs=new MutationObserver(function(){
    var active=document.querySelector('.tab.active');
    if(active){
      var t=active.getAttribute('data-tab');
      var nav=document.getElementById('sidenav');
      if(nav){nav.querySelectorAll('a[data-navtab]').forEach(function(a){
        a.classList.toggle('active',a.getAttribute('data-navtab')===t);});}
    }
  });
  obs.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
  renderTabNav();
})();

/* ===== 交易表增强：表头排序 + 搜索 + 行点击详情 ===== */
(function(){
  function enhanceTradesTable(){
    document.querySelectorAll('table.trades-table').forEach(function(tbl){
      if(tbl.dataset.enhanced)return;tbl.dataset.enhanced='1';
      var head=tbl.querySelector('thead');
      if(head){
        head.querySelectorAll('th').forEach(function(th,i){
          th.style.cursor='pointer';th.title='点击排序';
          th.addEventListener('click',function(){
            var tb=tbl.querySelector('tbody');if(!tb)return;
            var rows=Array.prototype.slice.call(tb.querySelectorAll('tr'));
            var dir=th.dataset.dir==='asc'?-1:1;th.dataset.dir=dir>0?'asc':'desc';
            head.querySelectorAll('th').forEach(function(x){x.textContent=x.textContent.replace(/[▲▼]/g,'');});
            th.textContent=th.textContent.trim()+(dir>0?' ▲':' ▼');
            rows.sort(function(a,b){
              var va=parseFloat((a.children[i]?a.children[i].textContent:'').replace(/[+,%—]/g,'')||'0');
              var vb=parseFloat((b.children[i]?b.children[i].textContent:'').replace(/[+,%—]/g,'')||'0');
              return (va-vb)*dir;});
            rows.forEach(function(r){tb.appendChild(r);});
          });});
      }
      /* 行点击 → 详情（从 symbol 单元格提取 6 位代码） */
      tbl.querySelectorAll('tbody tr').forEach(function(tr){
        tr.style.cursor='pointer';
        tr.addEventListener('click',function(){
          var txt=tr.textContent;
          var m=txt.match(/(?:sh|sz|bj)?(\d{6})/);
          if(m&&window.ENH&&window.ENH.details&&window.ENH.details[m[1]]){
            if(typeof openDetail==='function')openDetail(m[1]);
          }
        });
      });
    });
  }
  new MutationObserver(enhanceTradesTable).observe(document.body,{subtree:true,childList:true});
  enhanceTradesTable();
})();

/* ===== 详情弹层 ===== */
document.addEventListener('DOMContentLoaded',function(){
  var m=document.createElement('div');m.id='modal-mask';m.className='modal-mask';
  m.addEventListener('click',function(e){if(e.target===m)m.classList.remove('open');});
  document.body.appendChild(m);
});
</script>
"""

if "</body>" in html:
    html = html.replace("</body>", INJECT_JS + "</body>")
else:
    html += INJECT_JS

# 移除重复的 COMMON_JS 注入（此处用不到 COMMON_JS 全文，只用了 openDetail 等函数——把 COMMON_JS 注入进来）
# 需要 COMMON_JS 的函数：openDetail/renderKline/renderFactors/renderTrades/switchTradeTab/kpiHtml/tierPill/tierChg/fmtPct/toggleTheme/applyTheme/renderSidenav
common_script = f"<script>{COMMON_JS}</script>"
html = html.replace("</head>", common_script + "</head>", 1) if "</head>" in html else html

out = BASE / "index.html"
out.write_text(html, encoding="utf-8")
print(f"已注入升级: {out} ({out.stat().st_size/1024:.0f} KB)")