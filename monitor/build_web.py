# -*- coding: utf-8 -*-
"""
监控报告网页构建：把最新报告发布为 dist/index.html，历史报告归档到
dist/archive/<YYYY-MM>/，生成按月份归档的 history.html，并更新导航。
用法：monitor.py 生成当日报告后运行本脚本，再执行 cloudstudio 部署。

2026-08-11：归档 copy 后自动注入「返回入口 + 青橘社区 + 表头排序」，防止覆盖注入版。
"""
import os, re, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(BASE, "reports")
DIST = r"D:/Documents/Workbuddy/股票基金/dist"
ARCHIVE = os.path.join(DIST, "archive")

# ---------- 归档报告注入（返回入口 + 青橘社区 + 表头排序；幂等） ----------
BACK_HTML = """<div style="max-width:1000px;margin:0 auto 10px;font-size:13px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<a href="../../index.html" style="display:inline-block;padding:5px 14px;border-radius:20px;background:#2b6cb0;color:#fff;text-decoration:none">← 返回最新看板</a>
<a href="../../history.html" style="display:inline-block;padding:5px 14px;border-radius:20px;background:#eef2f7;color:#2b6cb0;text-decoration:none">📚 历史报告</a>
<a href="https://qingju.me/" target="_blank" rel="noopener" style="display:inline-block;padding:5px 14px;border-radius:20px;background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;text-decoration:none;font-weight:600;margin-left:auto">💬 青橘社区 · 加标的 / 自由讨论 →</a>
</div>"""

SORT_JS = """<script>
(function () {
  if (window.__btReportSorted) return;
  window.__btReportSorted = true;
  var tables = document.querySelectorAll("table");
  tables.forEach(function (t) {
    var head = t.querySelector("tr");
    if (!head) return;
    Array.prototype.forEach.call(head.children, function (th, ci) {
      th.style.cursor = "pointer"; th.title = "点击排序";
      var asc = null;
      th.addEventListener("click", function () {
        var tb = t.tBodies[0]; if (!tb) return;
        var rows = Array.prototype.slice.call(tb.rows);
        asc = asc === null ? true : !asc;
        rows.sort(function (a, b) {
          var va = a.children[ci] ? a.children[ci].innerText.trim() : "";
          var vb = b.children[ci] ? b.children[ci].innerText.trim() : "";
          var na = parseFloat(String(va).replace(/[+,%]/g, ""));
          var nb = parseFloat(String(vb).replace(/[+,%]/g, ""));
          var r = (!isNaN(na) && !isNaN(nb)) ? na - nb : String(va).localeCompare(String(vb), "zh");
          return asc ? r : -r;
        });
        rows.forEach(function (r) { tb.appendChild(r); });
        Array.prototype.forEach.call(head.children, function (h) { h.textContent = h.textContent.replace(/[▲▼]$/, ""); });
        th.textContent += (asc ? " ▲" : " ▼");
      });
    });
  });
})();
</script>"""

def inject_archive(path):
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    changed = False
    if "返回最新看板" not in s:
        if "<body>" in s:
            s = s.replace("<body>", "<body>\n" + BACK_HTML, 1); changed = True
        elif "<h1" in s:
            s = s.replace("<h1", BACK_HTML + "\n<h1", 1); changed = True
    if "__btReportSorted" not in s and "</body>" in s:
        s = s.replace("</body>", SORT_JS + "\n</body>", 1); changed = True
    if changed:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(s)
    return changed

# ---------- 1. 同步历史报告到 archive/<YYYY-MM>/ ----------
# 注：dist/index.html 由 render_dashboard.py 生成（权重看板），此处不再覆盖。
if not os.path.isdir(REPORTS):
    raise SystemExit(f"reports 目录不存在: {REPORTS}")
reports = sorted(f for f in os.listdir(REPORTS) if f.endswith("_监控报告.html"))
moved = []
for f in reports:
    m = re.match(r"(\d{4})-(\d{2})-\d{2}_监控报告\.html$", f)
    if not m:
        continue
    ym = f"{m.group(1)}-{m.group(2)}"
    d = os.path.join(ARCHIVE, ym)
    os.makedirs(d, exist_ok=True)
    shutil.copy2(os.path.join(REPORTS, f), os.path.join(d, f))
    inject_archive(os.path.join(d, f))  # copy 后立即注入返回+社区+排序
    moved.append(f)
print("archived:", len(moved))

# ---------- 2. 按月份分组 ----------
groups = {}
for ym in sorted(os.listdir(ARCHIVE), reverse=True):
    d = os.path.join(ARCHIVE, ym)
    if not os.path.isdir(d):
        continue
    fs = sorted(f for f in os.listdir(d) if f.endswith(".html"))
    if fs:
        groups[ym] = fs

# ---------- 3. 生成 history.html ----------
def month_label(ym):
    y, m = ym.split("-")
    return f"{y} 年 {int(m)} 月"

secs = []
for ym, fs in groups.items():
    rows = []
    for f in reversed(fs):
        d = f.replace("_监控报告.html", "").replace("-", ".")
        rows.append(
            f'<li><a href="archive/{ym}/{f}">📊 {d} 监控报告</a></li>'
        )
    secs.append(
        f'<div class="group"><h2>{month_label(ym)}（{len(fs)} 份）</h2><ul>{"" .join(rows)}</ul></div>'
    )

history_html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>历史监控报告归档</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 24px auto; max-width: 860px; background: #f7f8fa; color: #222; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 16px; margin: 22px 0 8px; border-left: 4px solid #2b6cb0; padding-left: 8px; }}
.group {{ background: #fff; border-radius: 8px; padding: 6px 20px 14px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
ul {{ list-style: none; padding-left: 6px; }}
li {{ margin: 6px 0; }}
a {{ color: #2b6cb0; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.top {{ margin: 0 0 14px; }}
.back {{ display: inline-block; padding: 4px 12px; border-radius: 6px; background: #eef2f7; color: #2b6cb0; font-size: 13px; }}
.note {{ color: #666; font-size: 13px; }}
</style></head><body>
<div style="max-width:860px;margin:0 auto;display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap;margin-bottom:10px">
<a class="back" href="index.html">← 返回最新报告</a>
<a href="https://qingju.me/" target="_blank" rel="noopener" style="display:inline-block;padding:5px 14px;border-radius:20px;background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);color:#fff;text-decoration:none;font-weight:600;font-size:13px">💬 青橘社区 · 加标的 / 自由讨论 →</a>
</div>
<h1>📚 历史监控报告归档</h1>
<p class="note">按月份归档，每日 14:30 自动生成；仅供个人参考，不构成投资建议。</p>
{''.join(secs)}
</body></html>"""

with open(os.path.join(DIST, "history.html"), "w", encoding="utf-8") as f:
    f.write(history_html)
print("history.html:", len(groups), "个月份")

# ---------- 4. 更新 index.html 顶部导航 ----------
idx = os.path.join(DIST, "index.html")
s = open(idx, encoding="utf-8").read()
nav_old_1 = '<a href="2026-08-07_监控报告.html" style="color:#2b6cb0">📅 查看 08-07 历史报告</a>'
nav_old_2 = '<a href="2026-08-07_监控报告.html" style="color:#2b6cb0">📅 查看 08-07 历史报告</a> <span style="color:#8892a0">｜ 每日 14:30 自动更新</span>'
nav_new = '<a href="history.html" style="color:#2b6cb0">📚 查看历史报告</a> <span style="color:#8892a0">｜ 每日 14:30 自动更新</span>'
if nav_old_2 in s:
    s = s.replace(nav_old_2, nav_new)
elif nav_old_1 in s:
    s = s.replace(nav_old_1, '<a href="history.html" style="color:#2b6cb0">📚 查看历史报告</a>')
else:
    # 兜底：在 <body> 后注入（render_dashboard.py 已内置 .topbar 导航时跳过，避免重复）
    if "<body>" in s and "history.html" not in s:
        s = s.replace(
            "<body>",
            '<body><div style="max-width:1000px;margin:0 auto 8px;font-size:13px">'
            '<a href="history.html" style="color:#2b6cb0">📚 查看历史报告</a>'
            ' <span style="color:#8892a0">｜ 每日 14:30 自动更新</span></div>',
            1,
        )
with open(idx, "w", encoding="utf-8") as f:
    f.write(s)
print("index.html nav updated:", "📚 查看历史报告" in s)
