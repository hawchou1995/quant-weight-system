# -*- coding: utf-8 -*-
"""#10 皮肤层：四个视图 + 导航下拉 截图（目视验收用）。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE + "/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = "file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/quant-weight-system/dual_system.html"
OUT = Path(r"D:/Tools")
SHOTS = [("kxmm", "ui10_kxmm"), ("sys-auto", "ui10_auto"), ("short", "ui10_short"), ("a5", "ui10_a5")]


async def shot(c, path, name):
    await c.send(json.dumps({"id": 5, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    for _ in range(30):
        m = json.loads(await c.recv())
        if m.get("id") == 5:
            (OUT / f"{name}.png").write_bytes(base64.b64decode(m["result"]["data"]))
            print(f"  [saved] {name}.png")
            return
    print(f"  [FAIL] {name} 截图未拿到")


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(5)
    async with websockets.connect(ws, max_size=256 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await asyncio.sleep(0.5)
        for key, name in SHOTS:
            await G.ev(ws, f"window.switchView('{key}');window.scrollTo(0,0);1")
            await asyncio.sleep(2.5)
            await shot(c, None, name)
        # 导航下拉展开态
        box = json.loads(await G.ev(ws, """JSON.stringify((function(){
          var a=document.querySelectorAll('#sidenav .sn-grp > a')[1];var r=a.getBoundingClientRect();
          return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})())"""))
        await c.send(json.dumps({"id": 7, "method": "Input.dispatchMouseEvent",
                                 "params": {"type": "mouseMoved", "x": box["x"], "y": box["y"], "buttons": 0}}))
        await asyncio.sleep(1.2)
        await shot(c, None, "ui10_nav")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
