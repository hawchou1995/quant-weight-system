# -*- coding: utf-8 -*-
"""看板四项改动的渲染态实测（CDP 9223）。

不只查 CSS 文本，而是量真实布局：导航折叠/悬浮宽度、标签透明度、建议列换行行数、拆分列数。
悬浮用 CDP `Input.dispatchMouseEvent` 真派发，不是靠猜。
"""
import asyncio
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")

MEASURE = r"""
JSON.stringify({
  navW: document.querySelector('.sidenav') ? document.querySelector('.sidenav').getBoundingClientRect().width : -1,
  contML: getComputedStyle(document.querySelector('.container')).marginLeft,
  lblOpacity: (function(){var e=document.querySelector('.sidenav .lbl');return e?getComputedStyle(e).opacity:'none';})(),
  navVisible: document.querySelectorAll('.sidenav a').length,
  v9Display: (function(){var e=document.getElementById('v9-retired-card');return e?getComputedStyle(e).display:'missing';})(),
  thScore: [].slice.call(document.querySelectorAll('th')).filter(function(t){return t.textContent.indexOf('权重总分')===0;}).length,
  thSub: [].slice.call(document.querySelectorAll('th')).filter(function(t){return t.textContent.indexOf('子项评分')===0;}).length,
  advCount: document.querySelectorAll('.adv-cell').length,
  advLines: (function(){
     var s=document.querySelector('#a5-zt .adv-cell')||document.querySelector('.adv-cell');
     if(!s) return null;
     var cs=getComputedStyle(s);
     var lh=parseFloat(cs.lineHeight)||14;
     return {w: Math.round(s.getBoundingClientRect().width), h: s.getBoundingClientRect().height,
             lines: Math.round(s.getBoundingClientRect().height/lh), ws: cs.whiteSpace};
  })(),
  order: (function(){
     var f=document.getElementById('fb3-pool-card'), u=document.getElementById('fund-paper-card');
     if(!f||!u) return null;
     return {fb3Top: Math.round(f.getBoundingClientRect().top), fundTop: Math.round(u.getBoundingClientRect().top)};
  })()
})
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        print("[boot] 拉起自动化 Chrome…")
        if not G.boot_auto_profile():
            print("[FAIL] Chrome 起不来"); return 1
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(3)

    print("=== ① 折叠态 ===")
    d = json.loads(await G.ev(ws, MEASURE))
    for k in ("navW", "contML", "lblOpacity", "navVisible", "v9Display", "thScore", "thSub",
              "advCount", "advLines", "order"):
        print(f"  {k}: {d.get(k)}")

    print("\n=== ② 真派发鼠标移入导航 → 悬浮态 ===")
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=10) as c:
        for t in ("mouseMoved", "mouseMoved", "mouseMoved"):
            await c.send(json.dumps({"id": 7, "method": "Input.dispatchMouseEvent",
                                     "params": {"type": t, "x": 30, "y": 320, "button": "none"}}))
            try:
                await asyncio.wait_for(c.recv(), timeout=3)
            except Exception:
                pass
            await asyncio.sleep(0.15)
    await asyncio.sleep(0.6)
    d2 = json.loads(await G.ev(ws, MEASURE))
    print(f"  navW: {d.get('navW')} → {d2.get('navW')}")
    print(f"  lblOpacity: {d.get('lblOpacity')} → {d2.get('lblOpacity')}")

    ok = [
        ("导航默认折叠 56px", abs(float(d.get("navW", -1)) - 56) < 1.5),
        ("container 常驻 56px", str(d.get("contML")) == "56px"),
        ("折叠态标签隐藏", str(d.get("lblOpacity")) == "0"),
        ("悬浮展开 190px", abs(float(d2.get("navW", -1)) - 190) < 1.5),
        ("悬浮态标签可见", float(d2.get("lblOpacity", 0)) > 0.9),
        ("v9-retired 已隐藏", d.get("v9Display") == "none"),
        ("权重总分列 =1", d.get("thScore") == 1),
        ("子项评分列 =1", d.get("thSub") == 1),
        ("建议列允许换行", (d.get("advLines") or {}).get("ws") == "normal"),
        ("建议列宽受限于 216px", (d.get("advLines") or {}).get("w", 999) <= 220),
        ("基金池在基金模拟盘上方", (d.get("order") or {}).get("fb3Top", 1) < (d.get("order") or {}).get("fundTop", 0)),
    ]
    print()
    for n, v in ok:
        print(f"  [{'ok' if v else 'FAIL'}] {n}")
    print("\nRESULT: " + ("OK" if all(v for _, v in ok) else "FAIL"))
    return 0 if all(v for _, v in ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
