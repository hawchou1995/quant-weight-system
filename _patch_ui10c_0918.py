# -*- coding: utf-8 -*-
"""#10 第二步补丁 C：内联语义色收敛到主题令牌（同一张表里两种红、三种绿的漂移清掉）。

映射：
  红 #ef4444/#dc2626/#f87171 → var(--up)    绿 #10b981/#16a34a/#22c55e/#34d399 → var(--down)
  三种琥珀 #f59e0b/#d97706/#b45309 → var(--warn)（新增令牌，浅底可读性从 2.2:1 提到 5.9:1）
  紫 序列色 → 琥珀/石板（LILA BAN：图表序列也不留紫）
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")

# ---------- C1 :root 增加 --warn（浅底可读 + 深色自适应） ----------
p = ROOT / "ui_components.py"
s = p.read_text(encoding="utf-8")
s = s.replace("  --r:6px; --r-sm:4px; --accent-ink:#20160a;",
              "  --r:6px; --r-sm:4px; --accent-ink:#20160a; --warn:#b45309;", 1)
s = s.replace('  --up:#f87171; --down:#4ade80; --accent:#fbbf24; --accent2:#60a5fa;',
              '  --up:#f87171; --down:#4ade80; --accent:#fbbf24; --accent2:#60a5fa; --warn:#fbbf24;', 1)
assert "--warn:#b45309" in s and "--warn:#fbbf24" in s, "warn 令牌未写入"
p.write_text(s, encoding="utf-8")
print("ui_components.py: --warn 令牌已加（浅 #b45309 / 深 #fbbf24）")

# ---------- C2 内联色收敛 ----------
p2 = ROOT / "build_dual_system.py"
s2 = p2.read_text(encoding="utf-8")
n = 0
for old, new in [
    ("color:#ef4444", "color:var(--up)"),
    ("color:#dc2626", "color:var(--up)"),
    ("color:#f87171", "color:var(--up)"),
    ("color:#10b981", "color:var(--down)"),
    ("color:#16a34a", "color:var(--down)"),
    ("color:#22c55e", "color:var(--down)"),
    ("color:#34d399", "color:var(--down)"),
    ("color:#94a3b8", "color:var(--faint)"),
    ("color:#f59e0b", "color:var(--warn)"),
    ("color:#d97706", "color:var(--warn)"),
    ("color:#b45309", "color:var(--warn)"),
    ('color="#8b5cf6"', 'color="#d97706"'),     # 卫星 SUPER 曲线：紫 → 琥珀
    ('color="#7c3aed"', 'color="#64748b"'),     # 激进版曲线：紫 → 石板
]:
    c = s2.count(old)
    if c:
        s2 = s2.replace(old, new)
        n += c
        print(f"  {old:<22} → {new:<22} ×{c}")
p2.write_text(s2, encoding="utf-8")
print(f"build_dual_system.py: 共收敛 {n} 处内联色")
print("\n✅ 补丁 C 完成")
