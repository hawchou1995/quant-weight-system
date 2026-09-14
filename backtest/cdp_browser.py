# -*- coding: utf-8 -*-
"""向指定 CDP 端口的浏览器级 websocket 发送一条命令（默认 Browser.close）。
用法: python cdp_browser.py <port> [method]
"""
import asyncio
import json
import sys
import urllib.request

import websockets

PORT = sys.argv[1] if len(sys.argv) > 1 else "9222"
METHOD = sys.argv[2] if len(sys.argv) > 2 else "Browser.close"


async def main():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=8) as r:
        ws_url = json.load(r)["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": METHOD}))
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=5)
            print("resp:", m[:200])
        except Exception:
            print(f"[sent] {METHOD} → {PORT}（连接随之关闭属正常）")


asyncio.run(main())
