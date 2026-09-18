# -*- coding: utf-8 -*-
"""#10 第二步盘点：UI 源码里的 emoji 位置 + 硬编码颜色/圆角/阴影。"""
import re, sys, collections
sys.stdout.reconfigure(encoding="utf-8")

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2190-\u21FF\u2705\u274C\u26A0]")
FILES = ["ui_components.py", "build_dual_system.py", "kxmm_card.py"]

for f in FILES:
    lines = open(f, encoding="utf-8").read().split("\n")
    hits = [(i+1, l) for i, l in enumerate(lines) if EMOJI.search(l)]
    cnt = collections.Counter()
    for i, l in hits:
        for e in EMOJI.findall(l):
            if e != "\ufe0f":
                cnt[e] += 1
    print(f"\n===== {f} : {len(hits)} 行含 emoji，去重 {len(cnt)} 种 =====")
    print("字符统计:", " ".join(f"{k}x{v}" for k, v in cnt.most_common(40)))
    for i, l in hits:
        s = l.strip()
        print(f"  {i:5d}| {s[:135]}")
