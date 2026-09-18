# -*- coding: utf-8 -*-
"""修复包渲染态验证：单条固定顶栏 / 时钟走字 / 徽章 / 评分列。"""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE + "/backtest")
import gushi_daily_collect as G  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")

Q = r"""
JSON.stringify({
  bars: [].slice.call(document.querySelectorAll('.topbar,.sidenav')).map(function(e){
     var r=e.getBoundingClientRect(), cs=getComputedStyle(e);
     return {cls:e.className, x:Math.round(r.x), y:Math.round(r.y), h:Math.round(r.height),
             pos:cs.position, z:cs.zIndex};}),
  navInTopbar: !!document.querySelector('.topbar .sidenav#sidenav'),
  bodyPT: getComputedStyle(document.body).paddingTop,
  clk: (function(){var c=document.querySelector('.clk');return c?c.textContent:null;})(),
  badge: (function(){var b=document.querySelector('.mkt-badge');return b?{txt:b.textContent.trim(),cls:b.className}:null;})(),
  tabs: [].slice.call(document.querySelectorAll('.topbar .sidenav > a')).map(function(a){return a.textContent.trim();})
})
"""

SCROLL = "window.scrollTo(0, 800); 'scrolled'"


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(4)
    d = json.loads(await G.ev(ws, Q))
    print("[bars]", json.dumps(d.get("bars"), ensure_ascii=False))
    print("[nav 在 topbar 内]", d.get("navInTopbar"), "| body padding-top:", d.get("bodyPT"))
    print("[tabs]", d.get("tabs"))
    print("[badge]", d.get("badge"))
    c1 = d.get("clk")
    await asyncio.sleep(2.2)
    c2 = json.loads(await G.ev(ws, Q)).get("clk")
    print(f"[clock] {c1} → {c2}")
    await G.ev(ws, SCROLL)
    await asyncio.sleep(0.8)
    d3 = json.loads(await G.ev(ws, Q))
    print("[滚动后 bars]", json.dumps(d3.get("bars"), ensure_ascii=False))

    bars = d.get("bars") or []
    tb = [b for b in bars if "topbar" in str(b.get("cls"))]
    sc = [b for b in bars if b.get("cls") == "sidenav"]
    y_after = [b["y"] for b in (d3.get("bars") or []) if "topbar" in str(b.get("cls"))]
    ck = [
        ("只有一条顶栏（topbar 1 个 + sidenav 已内联 0 高度）",
         len(tb) == 1 and (not sc or sc[0]["h"] <= 60)),
        ("顶栏 fixed", bool(tb) and tb[0].get("pos") == "fixed"),
        ("顶栏贴顶 y=0", bool(tb) and tb[0].get("y") == 0),
        ("滚动后仍贴顶（固定生效）", bool(y_after) and y_after[0] == 0),
        ("nav 已并入 topbar", bool(d.get("navInTopbar"))),
        ("body 预留 56px", str(d.get("bodyPT")) == "56px"),
        ("5 个 tab 文本正确",
         d.get("tabs") == ["📊市场晴雨▾", "🛰️中长线池▾", "⚡短线选股▾", "🎯打板专区▾", "💬社区讨论"]
         or [str(t).replace("▾", "") for t in (d.get("tabs") or [])][:5]
         == ["📊市场晴雨", "🛰️中长线池", "⚡短线选股", "🎯打板专区", "💬社区讨论"]),
        ("时钟走字（1 秒刷新）", bool(c1 and c2 and c1 != c2)),
        ("徽章有状态", bool((d.get("badge") or {}).get("txt"))),
    ]
    print()
    for n, v in ck:
        print(f"  [{'ok' if v else 'FAIL'}] {n}")
    print("\nRESULT: " + ("OK" if all(v for _, v in ck) else "FAIL"))
    return 0 if all(v for _, v in ck) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
