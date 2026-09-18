# -*- coding: utf-8 -*-
"""R-live-0918 接线补丁：① 树图 HM_APPLY 导出 ② {INTRADAY_JS} 占位符
                       ③ 残留 hex 值型颜色 → 主题令牌（消除同一页两种红/三种绿）。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
FAIL = []


def rep(txt, old, new, cnt=1, tag=""):
    n = txt.count(old)
    if n != cnt:
        FAIL.append(f"[{tag}] 期望 {cnt} 实际 {n}: {old[:60]!r}")
        return txt
    return txt.replace(old, new)


# ---------- ① 树图：导出 HM_APPLY ----------
p = ROOT / "kxmm_card.py"
s = p.read_text(encoding="utf-8")
s = rep(s, """  function activate(){
    if(built) { if(chart) chart.resize(); return; }
    if(render()) built = true;
  }""",
        """  /* 盘中实时（R-live-0918）：外部注入全市场快照 → 就地改值 → 复用 render() 重渲染。
     rows = [{c:代码, p:涨跌幅%, a:成交额亿, m:总市值亿, f:流通市值亿}] */
  window.HM_APPLY = function(rows, ts){
    if(!HD || !HD.tree || !rows || !rows.length) return 0;
    var idx = {};
    HD.tree.forEach(function(sec){ (sec.children || []).forEach(function(x){ idx[x.c] = x; }); });
    var hit = 0;
    rows.forEach(function(r){
      var x = idx[r.c]; if(!x) return;
      if(r.p != null && !isNaN(r.p)) x.p = r.p;
      if(r.a > 0) x.a = r.a;
      if(r.m > 0) x.m = r.m;
      if(r.f > 0) x.f = r.f;
      hit++;
    });
    if(hit && chart) render();
    var a = el('hm-asof');
    if(a && ts) a.textContent = '截至 ' + ts + ' · 盘中实时';
    return hit;
  };

  function activate(){
    if(built) { if(chart) chart.resize(); return; }
    if(render()) built = true;
  }""", 1, "HM_APPLY")
p.write_text(s, encoding="utf-8")
print("kxmm_card.py: HM_APPLY 已导出")

# ---------- ② 构建侧接线 + ③ 颜色令牌 ----------
p2 = ROOT / "build_dual_system.py"
s2 = p2.read_text(encoding="utf-8")
s2 = rep(s2, "from kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS",
         "from kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS\nfrom intraday_live import INTRADAY_JS", 1, "import")
s2 = rep(s2, "<script>{KXMM_JS}</script>", "<script>{KXMM_JS}</script>\n<script>{INTRADAY_JS}</script>", 1, "placeholder")

# 值型 hex（col="#xxxxxx" → 插进 style="color:{col}"）收敛到令牌；#3b82f6 是曲线序列色，保留
MAP = [('"#ef4444"', '"var(--up)"'), ('"#dc2626"', '"var(--up)"'), ('"#f87171"', '"var(--up)"'),
       ('"#10b981"', '"var(--down)"'), ('"#16a34a"', '"var(--down)"'), ('"#22c55e"', '"var(--down)"'),
       ('"#34d399"', '"var(--down)"'), ('"#1f8a4c"', '"var(--down)"'),
       ('"#94a3b8"', '"var(--faint)"'), ('"#9ca3af"', '"var(--faint)"'),
       ('"#f59e0b"', '"var(--warn)"'), ('"#d97706"', '"var(--warn)"'), ('"#ea580c"', '"var(--warn)"')]
tot = 0
for a, b in MAP:
    c = s2.count(a)
    if c:
        s2 = s2.replace(a, b)
        tot += c
        print(f"  {a:<12} → {b:<16} ×{c}")
p2.write_text(s2, encoding="utf-8")
print(f"build_dual_system.py: 值型颜色收敛 {tot} 处")
print("\n=== 失败项 ===" if FAIL else "\n✅ 接线补丁全部命中")
for f in FAIL:
    print(" ", f)
sys.exit(1 if FAIL else 0)
