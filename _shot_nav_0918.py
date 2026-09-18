# -*- coding: utf-8 -*-
"""顶栏修复截图（2x 放大，仅顶栏区域）。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html?v=nav")


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(9)
    async with websockets.connect(ws, max_size=256 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        box = json.loads(await G.ev(ws, """JSON.stringify((function(){
      var o = document.querySelector('.topbar').getBoundingClientRect();
      return {width: Math.round(o.width), height: Math.round(o.height)};
    })())"""))
        clip = {"x": 0, "y": 0, "width": box["width"], "height": box["height"], "scale": 2}
        await c.send(json.dumps({"id": 5, "method": "Page.captureScreenshot",
                                 "params": {"format": "png", "clip": clip}}))
        for _ in range(40):
            m = json.loads(await c.recv())
            if m.get("id") == 5:
                Path(r"D:/Tools/nav_fixed.png").write_bytes(base64.b64decode(m["result"]["data"]))
                print("  [saved] D:/Tools/nav_fixed.png", box)
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
