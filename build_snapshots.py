# -*- coding: utf-8 -*-
"""历史收盘监控快照：把 Obsidian data-标的快照-*.md 转成轻量 HTML 快照页
（monitor/snapshots/<YYYY-MM-DD>.html），并生成 snapshots_index.js
供看板右上角「标的报告」下拉按月分类引用（点击当前页内切换显示，不新开窗口）。"""
import json
import re
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
SNAP_DIR = BASE / "monitor" / "snapshots"
OBS_DIR = Path("D:/Documents/Obsidian/WorkBuddy/wiki/02-投资研究-Investment")
SNAP_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOTS = ["20260812", "20260813", "20260814"]   # 现有历史快照（按需扩展）

def parse_table(md_text):
    """解析 md 表格 → [{code,name,board,px,chg,score,tier,conf}]"""
    rows = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8 or not cells[0].isdigit():
            continue
        code, name, board, px, chg, score, tier, conf = cells[:8]
        rows.append({
            "code": code, "name": name, "board": board, "px": px,
            "chg": chg, "score": score.replace("**", ""), "tier": tier, "conf": conf,
        })
    return rows

def tier_cls(t):
    return {"满仓加仓": "full", "轻仓加仓": "add", "观望": "watch",
            "减至半仓": "cut", "清仓": "clear"}.get(t, "watch")

def build_snapshot_html(date_str, rows, title, note):
    trs = ""
    for i, r in enumerate(rows, 1):
        chg_cls = "up" if r["chg"].startswith("+") else "down"
        trs += f'''<tr><td class="rank">{i}</td><td><b>{r["name"]}</b><br><span class="sub">{r["code"]}</span></td>
<td><span class="tag">{r["board"]}</span></td>
<td class="num">{r["px"]}</td><td class="num {chg_cls}">{r["chg"]}</td>
<td class="num"><b class="score">{r["score"]}</b></td>
<td><span class="tier t-{tier_cls(r["tier"])}">{r["tier"]}</span></td>
<td><span class="tag">{r["conf"]}</span></td></tr>'''
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>标的快照 {date_str}</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0f1115;color:#e5e7eb;margin:0;padding:22px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b949e;font-size:12px;margin-bottom:16px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#171a21;border-radius:12px;overflow:hidden}}
th{{background:#1e222b;color:#9ca3af;text-align:left;padding:10px 10px;border-bottom:1px solid #2a2f3a}}
td{{padding:9px 10px;border-bottom:1px solid #232833;vertical-align:middle}}
.rank{{color:#6b7280;width:36px}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.up{{color:#f87171}} .down{{color:#4ade80}} .score{{color:#fbbf24;font-size:15px}}
.sub{{color:#6b7280;font-size:11px}} .tag{{display:inline-block;background:#232833;border-radius:6px;padding:2px 8px;font-size:12px}}
.tier{{padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500}}
.t-full{{background:rgba(248,113,113,.15);color:#f87171}} .t-add{{background:rgba(251,191,36,.15);color:#fbbf24}}
.t-watch{{background:rgba(148,163,184,.15);color:#cbd5e1}} .t-cut{{background:rgba(167,139,250,.15);color:#a78bfa}}
.t-clear{{background:rgba(107,114,128,.15);color:#9ca3af}}
.note{{color:#6b7280;font-size:12px;line-height:1.8;margin-top:14px;background:#171a21;border-radius:10px;padding:12px 16px}}
</style></head><body>
<h1>📊 标的快照 {date_str}</h1>
<div class="sub">{title}</div>
<table><tr><th>#</th><th>标的</th><th>板块</th><th>现价</th><th>涨跌幅</th><th>权重分</th><th>档位</th><th>置信度</th></tr>{trs}</table>
<div class="note">{note}</div>
</body></html>'''

# ---------------- 生成快照页 + 索引 ----------------
index = {"snapshots": []}

def build_dual_snapshot(date_str, v8_rows, v9_rows):
    """双体系当日快照：普适版表 + 个人版表（当前监控口径）"""
    def table(rows):
        trs = ""
        for i, r in enumerate(rows, 1):
            chg_cls = "up" if (r["chg"] or 0) > 0 else "down"
            chg_txt = f'{r["chg"]:+.2f}%' if r["chg"] is not None else "—"
            trs += f'''<tr><td class="rank">{i}</td><td><b>{r["name"]}</b><br><span class="sub">{r["code"]}</span></td>
<td><span class="tag">{r["board"]}</span></td><td><span class="tag">{r["industry"]}</span></td>
<td class="num">{r["px"]:.2f}</td><td class="num {chg_cls}">{chg_txt}</td>
<td class="num"><b class="score">{r["score"]:.1f}</b></td>
<td><span class="tier t-{tier_cls(r["tier"])}">{r["tier"]}</span></td></tr>'''
        return f'''<table><tr><th>#</th><th>标的</th><th>板块</th><th>行业</th><th>现价</th><th>涨跌幅</th><th>权重分</th><th>档位</th></tr>{trs}</table>'''
    h2 = '<h2 style="margin:22px 0 8px;font-size:16px">🅰️ 普适版（全市场自动池 · 分层）</h2>' + table(v9_rows)
    h2 += '<h2 style="margin:22px 0 8px;font-size:16px">🅱️ 个人版（用户固定池）</h2>' + table(v8_rows)
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>双体系监控快照 {date_str}</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0f1115;color:#e5e7eb;margin:0;padding:22px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b949e;font-size:12px;margin-bottom:16px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#171a21;border-radius:12px;overflow:hidden}}
th{{background:#1e222b;color:#9ca3af;text-align:left;padding:10px 10px;border-bottom:1px solid #2a2f3a}}
td{{padding:9px 10px;border-bottom:1px solid #232833;vertical-align:middle}}
.rank{{color:#6b7280;width:36px}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.up{{color:#f87171}} .down{{color:#4ade80}} .score{{color:#fbbf24;font-size:15px}}
.sub{{color:#6b7280;font-size:11px}} .tag{{display:inline-block;background:#232833;border-radius:6px;padding:2px 8px;font-size:12px}}
.tier{{padding:2px 10px;border-radius:20px;font-size:12px;font-weight:500}}
.t-full{{background:rgba(248,113,113,.15);color:#f87171}} .t-add{{background:rgba(251,191,36,.15);color:#fbbf24}}
.t-watch{{background:rgba(148,163,184,.15);color:#cbd5e1}} .t-cut{{background:rgba(167,139,250,.15);color:#a78bfa}}
.t-clear{{background:rgba(107,114,128,.15);color:#9ca3af}}
</style></head><body>
<h1>📊 双体系监控快照 {date_str}</h1>
<div class="sub">数据截至 {date_str} 收盘 · 普适版 = 全市场自动池分层（股票按权限 + ETF + 基金）｜ 个人版 = 用户固定池 · 档位 = 满仓加仓/轻仓加仓/观望/减至半仓/清仓</div>
{h2}
</body></html>'''

# 当前双体系快照（从 enhanced_data.js）
try:
    js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
    ENH = json.loads(js_src[len("window.ENH = "):-1])
    dt = ENH["meta"]["as_of"]
    v9_tiers = ENH["meta"]["v9_tiers"]
    v9_rows, v8_rows = [], []
    seen9 = set()
    for tier, codes in v9_tiers.items():
        for c in codes:
            if c in seen9:
                continue
            seen9.add(c)
            d = ENH["details"].get(c)
            if d:
                v9_rows.append(d)
    for d in ENH["details"].values():
        if d.get("pool", "v8") == "v8":
            v8_rows.append(d)
    v9_rows.sort(key=lambda d: -d["score"])
    v8_rows.sort(key=lambda d: -d["score"])
    ds = dt.replace("-", "")
    out = SNAP_DIR / f"{ds}_dual.html"
    out.write_text(build_dual_snapshot(dt, v8_rows, v9_rows), encoding="utf-8")
    index["snapshots"].append({"date": dt, "file": f"{ds}_dual.html",
                               "count": f"{len(v9_rows)}+{len(v8_rows)}", "dual": True})
    print(f"双体系快照 {dt}: 普适版 {len(v9_rows)} + 个人版 {len(v8_rows)} → {out.name}")
except Exception as e:
    print(f"双体系快照失败: {e}")

# 历史 md 快照
for ds in SNAPSHOTS:
    f = OBS_DIR / f"data-标的快照-{ds}.md"
    if not f.exists():
        print(f"skip {ds}: md 不存在")
        continue
    md = f.read_text(encoding="utf-8")
    rows = parse_table(md)
    if not rows:
        print(f"skip {ds}: 无表格行")
        continue
    # 标题/说明（从 md 头部提取）
    m = re.search(r"# 标的快照[^\n]*\n", md)
    title = m.group(0).strip().lstrip("# ").strip() if m else f"标的快照 {ds}"
    note_m = re.findall(r"> ([^\n]+)", md)
    note = "<br>".join(note_m[:3]) if note_m else ""
    date_str = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
    out = SNAP_DIR / f"{ds}.html"
    out.write_text(build_snapshot_html(date_str, rows, title, note), encoding="utf-8")
    index["snapshots"].append({"date": date_str, "file": f"{ds}.html", "count": len(rows)})
    print(f"快照 {date_str}: {len(rows)} 只 → {out.name}")

# 按月分类（按日期倒序）
index["snapshots"].sort(key=lambda x: x["date"], reverse=True)
months = {}
for s in index["snapshots"]:
    months.setdefault(s["date"][:7], []).append(s)
index["months"] = [{"month": m, "items": months[m]} for m in sorted(months, reverse=True)]

js = "window.SNAPSHOTS = " + __import__("json").dumps(index, ensure_ascii=False) + ";"
(BASE / "monitor" / "snapshots_index.js").write_text(js, encoding="utf-8")
print(f"索引: {len(index['snapshots'])} 个快照 / {len(index['months'])} 个月份 → snapshots_index.js")
