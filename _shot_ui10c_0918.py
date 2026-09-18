# -*- coding: utf-8 -*-
"""#10 皮肤层：浅色/深色对照 + 打板专区 截图。"""
import asyncio, base64, json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE + "/backtest")
import gushi_daily_collect as G
import websockets
URL = "file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/quant-weight-system/dual_system.html"
OUT = Path(r"D:/Tools")
async def shot(c, name):
    await c.send(json.dumps({"id": 5, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    for _ in range(30):
        m = json.loads(await c.recv())
        if m.get("id") == 5:
            (OUT / f"{name}.png").write_bytes(base64.b64decode(m["result"]["data"]))
            print(f"  [saved] {name}.png"); return
async def main():
    if not G.cdp_alive(G.AUTO_PORT): G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL); await asyncio.sleep(5)
    async with websockets.connect(ws, max_size=256*1024*1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"})); await asyncio.sleep(0.5)
        await G.ev(ws, "window.switchView('sys-auto');window.scrollTo(0,0);1"); await asyncio.sleep(2.5)
        await shot(c, "ui10c_auto_light")
        await G.ev(ws, "window.toggleTheme&&toggleTheme();window.scrollTo(0,0);1"); await asyncio.sleep(2.5)
        await shot(c, "ui10c_auto_dark")
        st = await G.ev(ws, "JSON.stringify({theme:document.documentElement.getAttribute('data-theme'),card:getComputedStyle(document.querySelector('.card')).backgroundColor,txt:getComputedStyle(document.body).color})")
        print("  深色态:", st)
        await G.ev(ws, "window.toggleTheme&&toggleTheme();window.switchView('a5');window.scrollTo(0,0);1"); await asyncio.sleep(2.5)
        await shot(c, "ui10c_a5")
    print("done"); return 0
sys.exit(asyncio.run(main()))
