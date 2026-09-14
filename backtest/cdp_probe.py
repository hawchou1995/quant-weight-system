# -*- coding: utf-8 -*-
"""在指定 CDP 端口上对匹配页面执行一段 JS，打印返回值。
用法: python cdp_probe.py <port> <js表达式> [url关键字=i.gushi.in]
"""
import asyncio
import json
import sys
import urllib.request

import websockets

PORT = sys.argv[1] if len(sys.argv) > 1 else "9222"
JS = sys.argv[2] if len(sys.argv) > 2 else "document.title"
MATCH = sys.argv[3] if len(sys.argv) > 3 else "i.gushi.in"


async def main():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=8) as r:
        ts = json.load(r)
    pages = [t for t in ts if t.get("type") == "page" and MATCH in (t.get("url") or "")]
    if not pages:
        print("NO_TARGET")
        return
    async with websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=2 ** 26, open_timeout=10) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": JS, "returnByValue": True, "awaitPromise": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                if "exceptionDetails" in m.get("result", {}):
                    print("EXC:", json.dumps(m["result"]["exceptionDetails"], ensure_ascii=False)[:300])
                else:
                    print(m["result"]["result"].get("value"))
                return


asyncio.run(main())
