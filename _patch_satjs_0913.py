# -*- coding: utf-8 -*-
"""补丁 4（修正版）：SAT 表 toolbar 接 JS。目标文件为 f-string 模板，JS 花括号在 .py 中须为 {{ }}。"""
import io

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

if "function initSatTables" in t:
    print("已存在，跳过")
else:
    anchor = "function applyHash(){{"
    assert anchor in t, "applyHash anchor missing"
    js = """function initSatTables(){{  /* 双卫星表搜索/排序 */
  var tables=document.querySelectorAll('table.sat-tbl');if(!tables.length)return;
  Array.prototype.forEach.call(tables,function(tbl){{
    var t=tbl.getAttribute('data-t');
    var q=document.querySelector('.sat-q[data-t="'+t+'"]');
    var srt=document.querySelector('.sat-sort[data-t="'+t+'"]');
    var cnt=document.querySelector('.sat-count[data-t="'+t+'"]');
    function apply(){{
      var rows=Array.prototype.slice.call(tbl.querySelectorAll('tbody tr'));
      var qv=((q&&q.value)||'').trim().toLowerCase();
      rows.forEach(function(r){{r.style.display=(!qv||r.cells[0].textContent.toLowerCase().indexOf(qv)>=0)?'':'none';}});
      var tb=tbl.querySelector('tbody');
      if(srt&&srt.value==='code'){{rows.sort(function(a,b){{return a.cells[0].textContent.localeCompare(b.cells[0].textContent);}});rows.forEach(function(r){{tb.appendChild(r);}});}}
      if(srt&&srt.value==='lot'){{rows.sort(function(a,b){{return (parseFloat(a.cells[4].textContent.replace(/[^0-9.]/g,''))||0)-(parseFloat(b.cells[4].textContent.replace(/[^0-9.]/g,''))||0);}});rows.forEach(function(r){{tb.appendChild(r);}});}}
      var shown=rows.filter(function(r){{return r.style.display!=='none';}}).length;
      if(cnt)cnt.textContent=shown+' / '+rows.length+' 只';
    }}
    if(q)q.addEventListener('input',apply);
    if(srt)srt.addEventListener('change',apply);
    apply();
  }});
}}
"""
    t = t.replace(anchor, js + anchor, 1)
    call_anchor = "  renderSubCurve();   // 基金回测净值曲线"
    assert call_anchor in t, "renderSubCurve call missing"
    t = t.replace(call_anchor, call_anchor + "\n  initSatTables();   // 双卫星表搜索/排序", 1)
    io.open(SRC, "w", encoding="utf-8").write(t)
    print("initSatTables 已插入（转义修正版）")
