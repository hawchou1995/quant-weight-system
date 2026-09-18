# -*- coding: utf-8 -*-
"""#10 第二步（皮肤层）补丁 B：build_dual_system 卡片内联样式扁平化
   + 渲染期统一去 emoji（源字符串与数据层一起覆盖）。

去 emoji 为什么放渲染期：实测渲染产物含 ✅458/⚠341/🔴117/🟢107/⚪49…，
其中绝大多数来自**数据层**（pool JSON / 复盘 md / 验证 JSON），
逐行改源码既改不完、也会被每日链重新写入 —— 故在最终 HTML 落盘前做一次净化。
保留 ✓✕（本补丁新引入的判定符号）与 ↑↓→ 箭头、①②③、▲▼ 等排版符号。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
FAIL = []
p = ROOT / "build_dual_system.py"
s = p.read_text(encoding="utf-8")
o = s


def rep(txt, old, new, cnt=1, tag=""):
    n = txt.count(old)
    if n != cnt:
        FAIL.append(f"[{tag}] 期望 {cnt} 处，实际 {n} 处：{old[:70]!r}")
        return txt
    return txt.replace(old, new)


# ---------- B1 徽章类：药丸 → 小方标 ----------
s = rep(s, ".view-badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;margin-left:8px;vertical-align:middle}}",
        ".view-badge{{display:inline-block;padding:1px 7px;border:1px solid transparent;border-radius:var(--r-sm);font-size:11px;"
        "background:var(--card2);color:var(--sub);margin-left:8px;vertical-align:middle}}", 1, "B1-vbadge")
s = rep(s, ".view-badge.auto{{background:rgba(245,158,11,.15);color:#b45309}}",
        ".view-badge.auto{{background:rgba(245,158,11,.12);color:#b45309;border-color:rgba(245,158,11,.25)}}", 1, "B1-vbadge-auto")
s = rep(s, ".view-badge.lite{{background:rgba(59,130,246,.15);color:#1d4ed8}}",
        ".view-badge.lite{{background:var(--card2);color:var(--sub);border-color:var(--border)}}", 1, "B1-vbadge-lite")
s = rep(s, '[data-theme="dark"] .view-badge.lite{{color:#60a5fa}}',
        '[data-theme="dark"] .view-badge.lite{{background:var(--card2);color:var(--sub);border-color:var(--border)}}', 1, "B1-vbadge-lite-dark")
s = rep(s, ".rel-date{{color:var(--faint);font-size:12px;background:var(--card);border:1px solid var(--border);padding:2px 10px;border-radius:20px}}",
        ".rel-date{{color:var(--faint);font-size:11.5px;background:var(--card);border:1px solid var(--border);padding:1px 7px;border-radius:var(--r-sm)}}", 1, "B1-reldate")

# ---------- B2 工具条/标题字号 ----------
s = rep(s, ".toolbar .flt{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:7px 10px;font-size:13px;font-family:inherit}}",
        ".toolbar .flt{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:var(--r);padding:6px 9px;font-size:12.5px;font-family:inherit}}", 1, "B2-flt")
s = rep(s, ".toolbar input[type=text]{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:7px 12px;font-size:13px;width:200px;font-family:inherit}}",
        ".toolbar input[type=text]{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:var(--r);padding:6px 11px;font-size:12.5px;width:200px;font-family:inherit}}", 1, "B2-input")
s = rep(s, ".bt-card .bt-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:15px}}",
        ".bt-card .bt-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;font-size:13.5px;font-weight:600}}", 1, "B2-bthead")
s = rep(s, ".bt-short h3{{margin:0 0 8px;color:var(--sub);font-size:15px}}",
        ".bt-short h3{{margin:0 0 6px;color:var(--sub);font-size:13.5px}}", 1, "B2-btshort")
s = rep(s, ".etf-sec{{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}}",
        ".etf-sec{{font-size:12.5px;font-weight:600;color:var(--accent);margin-bottom:6px}}", 1, "B2-etfsec")
s = rep(s, ".pool-sec b{{font-size:14.5px;font-weight:700;color:var(--text)}}",
        ".pool-sec b{{font-size:13.5px;font-weight:600;color:var(--text)}}", 1, "B2-poolsec-b")
s = rep(s, ".pool-sec{{display:flex;align-items:baseline;gap:10px;margin:26px 2px 10px;padding-bottom:8px;",
        ".pool-sec{{display:flex;align-items:baseline;gap:10px;margin:20px 2px 8px;padding-bottom:7px;", 1, "B2-poolsec")
s = rep(s, ".rev-cum-title{{font-size:16px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:10px;margin-bottom:6px}}",
        ".rev-cum-title{{font-size:14px;font-weight:600;color:var(--accent);display:flex;align-items:center;gap:8px;margin-bottom:6px}}", 1, "B2-revcumtitle")
s = rep(s, ".stock-card h3{{margin:0 0 6px;font-size:15px}}", ".stock-card h3{{margin:0 0 6px;font-size:14px}}", 1, "B2-stockcard-h3")
s = rep(s, ".op b{{font-size:15px}}", ".op b{{font-size:13.5px}}", 1, "B2-opb")
s = rep(s, ".rev-item summary,.rel-item summary{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;font-size:13px;",
        ".rev-item summary,.rel-item summary{{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;font-size:12.5px;", 1, "B2-revsummary")

# ---------- B3 去渐变（评测卡累计总览） ----------
s = rep(s, ".rev-cum{{background:linear-gradient(135deg,var(--card2),var(--card));border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:14px}}",
        ".rev-cum{{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;margin-bottom:12px}}", 1, "B3-revcum")

# ---------- B4 判定列：整格 emoji → ✓/✕（净化器会保留这两个符号） ----------
s = rep(s, '        flag = "✅" if g.get("status") == "PASS" else "⛔"',
        '        flag = "✓" if g.get("status") == "PASS" else "✕"', 1, "B4-flag1")
s = rep(s, '>✅</span>', '>✓</span>', 1, "B4-flag2")
s = rep(s, '    _flag = "🔴" if _r.get("defects", 0) > 0 else "✅"',
        '    _flag = "✕" if _r.get("defects", 0) > 0 else "✓"', 1, "B4-flag3")
s = rep(s, '    _flag = "✅" if _arg.get("verdict", "").startswith("✅") else ("⏳" if _arg.get("verdict", "").startswith("信号不足") else "⛔")',
        '    _flag = "✓" if _arg.get("verdict", "").startswith("✅") else ("…" if _arg.get("verdict", "").startswith("信号不足") else "✕")', 1, "B4-flag4")
s = rep(s, '<div class="card" id="a5-avoid" style="border-color:rgba(217,119,6,.35)">',
        '<div class="card" id="a5-avoid" style="border-left:3px solid rgba(217,119,6,.55)">', 1, "B4-avoid-border")

# ---------- B5 渲染期净化器（emoji → 空；保留 ✓✕ + 箭头/序号/几何符号） ----------
s = rep(s, """out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")""",
        """# --- #10 皮肤层（2026-09-18）：渲染期统一去 emoji ---
# 扁平控制台视觉语言：pictograph 一律清掉；保留 ✓✕（判定符号）、↑↓→ 箭头、①②③ 序号、▲▼ 与 ● 等排版符号。
# 放渲染期而非逐行改源码：实测产物里 90% 的 emoji 来自数据层（pool JSON / 复盘 md / 验证 JSON），
# 逐行改源码改不完、且会被每日链重新写入。
import re as _re_ui
_UI_EMOJI = ("\\U0001F100-\\U0001F1FF\\U0001F300-\\U0001FAFF\\u2600-\\u27BF"
             "\\u2B00-\\u2BFF\\u23E9-\\u23FF\\uFE0F")
_UI_KEEP = "\\u2713\\u2714\\u2715\\u2717"
_ui_re = _re_ui.compile("(?![%s])[%s][ \\t\\u00a0\\u2002\\u2003]?" % (_UI_KEEP, _UI_EMOJI))
_ui_n = len(_ui_re.findall(html))
html = _ui_re.sub("", html)
print(f"UI 净化（#10 皮肤层）：清除 {_ui_n} 个 emoji")

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")""", 1, "B5-sanitizer")

# ---------- B6 通用圆角收敛（CSS 行内 10/12/14/16/20px → 令牌） ----------
def _r(m):
    return "border-radius:var(--r)" if m.group(1) in ("10", "12", "14", "16") else "border-radius:var(--r-sm)"
s, n1 = re.subn(r"border-radius:(10|12|14|16|20)px", _r, s)
print(f"通用圆角收敛：{n1} 处")

p.write_text(s, encoding="utf-8")
print(f"build_dual_system.py: {len(o)} → {len(s)} chars")
print("\n=== 失败项 ===" if FAIL else "\n✅ 补丁 B 全部命中")
for f in FAIL:
    print(" ", f)
sys.exit(1 if FAIL else 0)
