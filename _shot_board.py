# -*- coding: utf-8 -*-
"""看板截图（视觉验收用）—— R-treelive-0922 附带
用法: python _shot_board.py [url] [out_prefix]
默认截本地构建产物；输出 _shot_1.png / _shot_2.png（顶部视图 + 超跌低开低吸卡）
"""
import asyncio
import base64
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

import websockets

BASE = Path(__file__).resolve().parent
sp = importlib.util.spec_from_file_location("gdc", BASE / "backtest" / "gushi_daily_collect.py")
gdc = importlib.util.module_from_spec(sp); sys.modules["gdc"] = gdc; sp.loader.exec_module(gdc)

DEFAULT_URL = "file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/quant-weight-system/dual_system.html"
URL = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
PRE = sys.argv[2] if len(sys.argv) > 2 else "_shot"


CLICK_TAB = "(()=>{var a=Array.from(document.querySelectorAll('a')).find(function(x){return (x.textContent||'').indexOf('短线选股')>=0});if(a)a.click();return 1})()"

async def shot(ws_url, name, steps=None):
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=15) as ws:
        mid = [0]

        async def call(method, params=None):
            mid[0] += 1
            await ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == mid[0]:
                    return m.get("result", {})

        for js in (steps or []):
            await call("Runtime.evaluate", {"expression": js, "awaitPromise": True})
            await asyncio.sleep(1.4)
        r = await call("Page.captureScreenshot", {"format": "png"})
        data = r.get("data")
        if not data:
            print(f"[FAIL] {name} 无截图数据"); return
        out = BASE / f"{PRE}_{name}.png"
        out.write_bytes(base64.b64decode(data))
        print(f"[OK] {out}  {out.stat().st_size//1024} KB")


def main():
    port = gdc.AUTO_PORT
    launched = False
    if not gdc.cdp_alive(port):
        print("[boot] 拉起自动化 Chrome …")
        launched = gdc.boot_auto_profile()
        if not launched:
            print("[FAIL] 拉起失败"); return 1
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{URL}", method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        t = json.load(r)
    try:
        print("[wait] 页面渲染 …")
        time.sleep(14)
        asyncio.run(shot(t["webSocketDebuggerUrl"], "1"))
        asyncio.run(shot(t["webSocketDebuggerUrl"], "2",
                         [CLICK_TAB, "(()=>{var e=document.getElementById('qlch-card');if(e)e.scrollIntoView({block:'start'});return 1})()"]))
    finally:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{t.get('id')}", timeout=5).read()
        except Exception:
            pass
        print("[cleanup] 已关标签")
        if launched:
            gdc.close_auto_profile()
    return 0


if __name__ == "__main__":
    sys.exit(main())
