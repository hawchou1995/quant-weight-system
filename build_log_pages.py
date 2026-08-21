# -*- coding: utf-8 -*-
"""日志页生成：review_log.html（复盘日志）+ changelog.html（更新日志，GitHub release 风格）
================================================================================
复盘日志：review/review_index.json 驱动，按日期列表，点击当前页 iframe 展示 markdown 渲染
更新日志：changelog.md 驱动（版本/日期/更新内容，GitHub release 格式），静态渲染
导航：左侧导航「📋 复盘日志」「📝 更新日志」→ 独立页（当前窗口打开，带返回按钮）
"""
import os
import json, re
from pathlib import Path
import sys

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

FAB = """
<div class="scroll-fab">
<button title="回到顶部" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑</button>
<button title="滚到底部" onclick="window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'})">↓</button>
</div>"""


def build_review_log():
    idx_f = BASE / "review" / "review_index.json"
    idx = json.loads(idx_f.read_text(encoding="utf-8")) if idx_f.exists() else {"reviews": []}
    # 2026-08-18 晚：日期降序（最新在前）
    revs = sorted(idx.get("reviews", []), key=lambda r: r.get("date", ""), reverse=True)
    items = ""
    for r in revs:
        flag = "🔴" if r.get("defects", 0) > 0 else "✅"
        items += (f'<a class="rev-btn" href="javascript:void(0)" onclick="openRev(\'{r["file"]}\')">'
                  f'{flag} {r["date"]}（信号 {r["sig"]} · {r["n"]} 只 · 胜率 {r.get("win_rate",0)}% · 缺陷 {r.get("defects",0)} 项）</a>')
    empty = '<div class="sub" style="color:var(--faint)">暂无复盘记录 —— 每个交易日收盘后运行 <code>python review_daily.py</code> 生成</div>' if not items else ""
    # 累计总览独立卡片（2026-08-18 晚：只在此页顶部显示一份，data 来自 cumulative.json）
    cum_f = BASE / "review" / "cumulative.json"
    cum = json.loads(cum_f.read_text(encoding="utf-8")) if cum_f.exists() else None
    cum_html = ""
    if cum and cum.get("pools"):
        # 回测基准映射（与 review_daily.BENCH_WIN 同源；累计池名 → 基准%）
        BENCH_MAP = {
            "全量池中/长线": 48.1, "长线·基金": 48.1,
            "短线·主板": 46.8, "短线·创业板": 48.1, "短线·科创板": 57.8, "短线·基金": 55.5,
        }
        # 2026-08-21 用户要求：长线和长线的在一起、短线和短线的在一起
        _LT_ORDER = ["全量池中/长线", "长线·主板", "长线·创业板", "长线·科创板", "长线·基金"]
        _ST_ORDER = ["短线全量池", "短线·主板", "短线·创业板", "短线·科创板", "短线·基金"]
        _rank = {n: i for i, n in enumerate(_LT_ORDER + _ST_ORDER)}
        rows = []
        T = {"n": 0, "buy": 0, "wins": 0, "losses": 0, "flat": 0, "sum_pct": 0.0}
        for name, a in sorted(cum["pools"].items(), key=lambda kv: (_rank.get(kv[0], 99), kv[0])):
            wr = (a["wins"] / a["buy"] * 100) if a.get("buy") else 0
            avg = (a["sum_pct"] / a["buy"]) if a.get("buy") else 0
            bench = BENCH_MAP.get(name)
            bench_s = f"{bench:.1f}%" if bench is not None else "—"
            diff = f"（{(wr-bench):+0.1f}pct）" if bench is not None and a.get("buy") else ""
            rows.append(f"<tr><td>{name}</td><td>{a['n']}</td><td>{a['buy']}</td><td>{a['wins']}</td>"
                        f"<td>{a['losses']}</td><td>{a['flat']}</td><td>{wr:.0f}%</td><td>{bench_s} {diff}</td>"
                        f"<td>{avg:+.2f}%</td></tr>")
            for k in T:
                T[k] += a[k]
        if T["buy"]:
            rows.append(f"<tr style='font-weight:700'><td>合计</td><td>{T['n']}</td><td>{T['buy']}</td><td>{T['wins']}</td>"
                        f"<td>{T['losses']}</td><td>{T['flat']}</td><td>{T['wins']/T['buy']*100:.0f}%</td><td>—</td>"
                        f"<td>{T['sum_pct']/T['buy']:+.2f}%</td></tr>")
        cum_html = f"""
<div class="card">
<div class="back-bar" style="margin-bottom:8px">
<h2 style="margin:0">📈 累计总览 <span class="badge badge-auto">自 {cum.get('since','—')} · {cum.get('count',0)} 篇</span></h2>
</div>
<div class="sub">三池累计：所有已发复盘的信号标的合计（防重：同篇只累加一次；短线·基金 T+1 净值未出计 ⚪持平）· 回测基准 = 各池 2016-01 起回测胜率</div>
<div style="overflow-x:auto"><table class="cum-tbl">
<thead><tr><th>池</th><th>累计标的</th><th>累计买入</th><th>🟢吃到</th><th>🔴被套</th><th>⚪持平</th><th>累计胜率</th><th>回测基准</th><th>累计均收</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table></div>
</div>"""
    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>复盘日志</title>
<style>{THEME_CSS}
.back-bar{{display:flex;align-items:center;gap:10px;margin-bottom:16px}}
.back-btn{{display:inline-block;padding:7px 18px;border-radius:20px;background:var(--card2);border:1px solid var(--border);color:var(--text);text-decoration:none;font-size:13px}}
.back-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.rev-btns{{display:flex;flex-wrap:wrap;gap:10px}}
.rev-btn{{display:inline-block;padding:9px 16px;border-radius:10px;background:var(--card2);border:1px solid var(--border);color:var(--text);text-decoration:none;font-size:13px;cursor:pointer}}
.rev-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.cum-tbl{{width:100%;border-collapse:collapse;margin-top:6px;font-size:13px}}
.cum-tbl th,.cum-tbl td{{border:1px solid var(--border);padding:6px 10px;text-align:center}}
.cum-tbl th{{background:var(--card2);color:var(--sub);font-weight:600}}
.cum-tbl tbody tr:hover{{background:var(--card2)}}
#rev-viewer{{display:none;margin-top:18px}}
#rev-viewer.active{{display:block}}
#rev-viewer iframe{{width:100%;height:760px;border:1px solid var(--border);border-radius:12px;background:var(--card)}}
.scroll-fab{{position:fixed;right:22px;bottom:22px;display:flex;flex-direction:column;gap:8px;z-index:950}}
.scroll-fab button{{width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:inherit}}
</style></head><body>
{NAV_HTML}
<div class="container">
{cum_html}
<div class="card">
<div class="back-bar">
<a class="back-btn" href="dual_system.html">← 返回主页面</a>
<h2 style="margin:0">📋 复盘日志 <span class="badge badge-auto">{len(revs)} 篇</span></h2>
</div>
<div class="sub">每交易日复盘：信号标的哪些吃到 / 哪些被套 / 是否符合系统设计 / 缺陷检测（grill）· 点击日期展开当日详情（日期降序，最新在前）</div>
{empty}
<div class="rev-btns">{items}</div>
</div>
<div class="card" id="rev-viewer">
<h2 id="rev-viewer-title">📋 复盘详情</h2>
<div id="rev-viewer-body"></div>
</div>
</div>
{FAB}
<script>
function openRev(file){{
  var v=document.getElementById('rev-viewer');
  v.classList.add('active');
  document.getElementById('rev-viewer-title').textContent='📋 复盘 '+file.replace('.md','').replace('_sig','（信号 ');
  document.getElementById('rev-viewer-body').innerHTML=
    '<iframe src="review/'+file+'" style="width:100%;height:760px;border:1px solid var(--border);border-radius:12px;background:var(--card)"></iframe>';
  v.scrollIntoView({{behavior:'smooth',block:'start'}});
}}
window.switchView=function(key){{
  if(key==='review')window.location.href='review_log.html';
  else if(key==='changelog')window.location.href='changelog.html';
  else window.location.href='dual_system.html';
}};
</script>
<script>
{COMMON_JS}
</script>
</body></html>"""
    (BASE / "review_log.html").write_text(html, encoding="utf-8")
    print(f"review_log.html 生成（{len(revs)} 篇，累计总览独立卡片已加，日期降序）")


def md_to_html(md):
    """简易 markdown → HTML（标题/表格/列表/粗体）"""
    lines = md.split("\n")
    out, in_table = [], False
    for ln in lines:
        ln = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", ln)
        if ln.startswith("|") and "---" not in ln:
            if not in_table:
                out.append("<table>")
                in_table = True
            cells = "".join(f"<td>{c.strip()}</td>" for c in ln.strip("|").split("|"))
            out.append(f"<tr>{cells}</tr>")
            continue
        if in_table and not ln.startswith("|"):
            out.append("</table>")
            in_table = False
        if ln.startswith("### "):
            out.append(f"<h3>{ln[4:]}</h3>")
        elif ln.startswith("## "):
            out.append(f"<h2>{ln[3:]}</h2>")
        elif ln.startswith("# "):
            out.append(f"<h1>{ln[2:]}</h1>")
        elif ln.startswith("- "):
            out.append(f"<div class='lg-item'>{ln[2:]}</div>")
        elif ln.startswith("> "):
            out.append(f"<div class='lg-note'>{ln[2:]}</div>")
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{ln}</p>")
        else:
            out.append("")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def build_changelog():
    cl_f = BASE / "changelog.md"
    md = cl_f.read_text(encoding="utf-8") if cl_f.exists() else "# 更新日志\n\n暂无更新记录\n"
    # 按 ## v 版本拆分
    blocks = re.split(r"(?=^## )", md, flags=re.M)
    cards = ""
    for b in blocks:
        if not b.strip():
            continue
        title_m = re.match(r"## (.+)", b)
        title = title_m.group(1) if title_m else ""
        body = b[title_m.end():] if title_m else b
        cards += f'<div class="rel"><div class="rel-head">{title}</div><div class="rel-body">{md_to_html(body)}</div></div>'
    html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>更新日志</title>
<style>{THEME_CSS}
.back-bar{{display:flex;align-items:center;gap:10px;margin-bottom:16px}}
.back-btn{{display:inline-block;padding:7px 18px;border-radius:20px;background:var(--card2);border:1px solid var(--border);color:var(--text);text-decoration:none;font-size:13px}}
.back-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.rel{{background:var(--card2);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:14px}}
.rel-head{{font-size:16px;font-weight:700;color:var(--accent);margin-bottom:8px}}
.rel-body table{{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}}
.rel-body td{{border:1px solid var(--border);padding:5px 8px;color:var(--sub)}}
.rel-body .lg-item{{color:var(--sub);font-size:13px;padding:2px 0 2px 14px;position:relative}}
.rel-body .lg-item:before{{content:'·';position:absolute;left:2px;color:var(--accent)}}
.rel-body .lg-note{{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);border-radius:8px;padding:8px 12px;color:#f59e0b;font-size:12px;margin:6px 0}}
.rel-body h3{{font-size:14px;color:var(--sub);margin:10px 0 4px}}
.rel-body p{{color:var(--sub);font-size:13px;margin:4px 0}}
.scroll-fab{{position:fixed;right:22px;bottom:22px;display:flex;flex-direction:column;gap:8px;z-index:950}}
.scroll-fab button{{width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:inherit}}
</style></head><body>
{NAV_HTML}
<div class="container">
<div class="card">
<div class="back-bar">
<a class="back-btn" href="dual_system.html">← 返回主页面</a>
<h2 style="margin:0">📝 更新日志 <span class="badge badge-auto">GitHub Release 风格</span></h2>
</div>
<div class="sub">量化系统版本更新记录：复盘发现设计缺陷 → 启动系统更新 → 在此登记版本/日期/更新内容</div>
{cards}
</div>
</div>
{FAB}
<script>
window.switchView=function(key){{
  if(key==='review')window.location.href='review_log.html';
  else if(key==='changelog')window.location.href='changelog.html';
  else window.location.href='dual_system.html';
}};
</script>
<script>
{COMMON_JS}
</script>
</body></html>"""
    (BASE / "changelog.html").write_text(html, encoding="utf-8")
    print("changelog.html 生成")


if __name__ == "__main__":
    build_review_log()
    build_changelog()