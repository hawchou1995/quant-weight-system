# -*- coding: utf-8 -*-
"""历史报告总览页 history_reports.html：按月分类列出全部历史收盘监控快照，
右上角「标的报告」→ 历史报告总览 进入（当前窗口打开）；每份快照点击当前页 iframe 内嵌展示；
顶部带「← 返回主页面」按钮。"""
import json
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

idx = json.loads((BASE / "monitor" / "snapshots_index.js").read_text(encoding="utf-8")[len("window.SNAPSHOTS = "):-1])

groups_html = ""
for g in idx["months"]:
    items = "".join(
        f'<a class="snap-btn" href="javascript:void(0)" onclick="openSnap(\'{s["file"]}\',\'{s["date"]}\')">📊 {s["date"]}（{s["count"]} 只）</a>'
        for s in g["items"])
    groups_html += f'<div class="month-group"><h3>📅 {g["month"]}</h3><div class="snap-btns">{items}</div></div>'

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>历史收盘监控报告</title>
<style>{THEME_CSS}
.back-bar{{display:flex;align-items:center;gap:10px;margin-bottom:16px}}
.back-btn{{display:inline-block;padding:7px 18px;border-radius:20px;background:var(--card2);border:1px solid var(--border);color:var(--text);text-decoration:none;font-size:13px}}
.back-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.month-group{{margin-bottom:18px}}
.month-group h3{{font-size:15px;margin:0 0 10px;color:var(--sub)}}
.snap-btns{{display:flex;flex-wrap:wrap;gap:10px}}
.snap-btn{{display:inline-block;padding:9px 16px;border-radius:10px;background:var(--card2);border:1px solid var(--border);color:var(--text);text-decoration:none;font-size:13px;cursor:pointer}}
.snap-btn:hover{{border-color:var(--accent);color:var(--accent)}}
#snap-viewer{{display:none;margin-top:18px}}
#snap-viewer.active{{display:block}}
#snap-viewer iframe{{width:100%;height:760px;border:1px solid var(--border);border-radius:12px;background:#0f1115}}
/* 到顶/到底 */
.scroll-fab{{position:fixed;right:22px;bottom:22px;display:flex;flex-direction:column;gap:8px;z-index:950}}
.scroll-fab button{{width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:inherit}}
</style></head><body>
{NAV_HTML}
<div class="container">
<div class="card">
<div class="back-bar">
<a class="back-btn" href="dual_system.html">← 返回主页面</a>
<h2 style="margin:0">📚 历史收盘监控报告 <span class="badge badge-auto">{len(idx["snapshots"])} 份</span></h2>
</div>
<div class="sub">按月分类 · 点击任意快照在下方当前页展示（不新开窗口）· 主页面右上角「标的报告」也可直达</div>
{groups_html}
</div>
<div class="card" id="snap-viewer">
<h2 id="snap-viewer-title">📊 快照预览</h2>
<div id="snap-viewer-body"></div>
</div>
</div>
<!-- 到顶/到底 -->
<div class="scroll-fab">
<button title="回到顶部" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<button title="滚到底部" onclick="window.scrollTo({{top:document.body.scrollHeight,behavior:'smooth'}})">↓</button>
</div>
<script src="monitor/snapshots_index.js"></script>
<script>
/* 历史页导航：指向主页面各视图（点击回到主页面对应视图） */
window.ENH = window.ENH || {{}};
window.ENH.nav = [["overview","📊","监控总览"],["sys-auto","🅰️","全量池中/长线"],["sys-lite","🅱️","固定池中/长线"],["short","⚡","短线(占位)"]];
window.ENH.NAV_SWITCH = true;
window.switchView = function(key){{
  // 历史页不内嵌视图：跳回主页面并直接定位到对应视图（hash 驱动，主页面加载时自动切换）
  window.location.href = 'dual_system.html#' + key;
}};
function openSnap(file, date){{
  document.getElementById('snap-viewer').classList.add('active');
  document.getElementById('snap-viewer-title').textContent = '📊 快照 '+date;
  document.getElementById('snap-viewer-body').innerHTML =
    '<iframe src="monitor/snapshots/'+file+'" style="width:100%;height:760px;border:1px solid var(--border);border-radius:12px;background:#0f1115"></iframe>';
  document.getElementById('snap-viewer').scrollIntoView({{behavior:'smooth',block:'start'}});
}}
</script>
<script>
{COMMON_JS}
</script>
</body></html>"""

(BASE / "history_reports.html").write_text(html, encoding="utf-8")
print(f"历史报告页已生成: history_reports.html ({len(html)//1024} KB)")
