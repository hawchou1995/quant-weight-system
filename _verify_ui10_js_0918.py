# -*- coding: utf-8 -*-
"""#10 皮肤层：真实 JS 异常捕获 + 功能抽查（净化器动过全部 JS 字符串，必须排除静默报错）。"""
import asyncio
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")
EVAL = """JSON.stringify({
  title: document.title,
  cards: document.querySelectorAll('.card').length,
  rows: document.querySelectorAll('table.tbl tbody tr').length,
  canvas: document.querySelectorAll('canvas').length,
  nav: document.querySelectorAll('#sidenav .sn-grp').length,
  emojiInText: (document.body.innerText.match(/[\\u{1F300}-\\u{1FAFF}\\u{2600}-\\u{27BF}]/gu) || []).length,
  curve: !!document.querySelector('#curve-chart'),
  kxmmFg: (document.getElementById('kxmm-fg') || {}).offsetHeight || 0
})"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    errs, logs = [], []
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await c.send(json.dumps({"id": 2, "method": "Page.enable"}))
        await asyncio.sleep(0.4)
        await c.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": URL}}))
        t0 = time.time()
        while time.time() - t0 < 14:
            try:
                m = json.loads(await asyncio.wait_for(c.recv(), timeout=2))
            except asyncio.TimeoutError:
                continue
            if m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                errs.append((d.get("text"), (d.get("exception") or {}).get("description", "")[:200]))
            elif m.get("method") == "Runtime.consoleAPICalled" and m["params"].get("type") == "error":
                logs.append(str(m["params"].get("args", [{}])[0].get("value"))[:160])
        await c.send(json.dumps({"id": 20, "method": "Runtime.evaluate",
                                 "params": {"expression": EVAL, "returnByValue": True}}))
        got = None
        t1 = time.time()
        while time.time() - t1 < 15:
            try:
                m = json.loads(await asyncio.wait_for(c.recv(), timeout=3))
            except asyncio.TimeoutError:
                break
            if m.get("id") == 20:
                got = m["result"]["result"].get("value")
                break
    print("页面身份 + 功能抽查:", got)
    print("JS 未捕获异常 =", len(errs), " console.error =", len(logs))
    for e in errs[:6]:
        print("   EXC:", e)
    for e in logs[:6]:
        print("   ERR:", e)
    d = json.loads(got) if got else {}
    ok = (not errs) and d.get("cards", 0) > 20 and d.get("rows", 0) > 50 and d.get("nav", 0) == 5 \
        and d.get("emojiInText", 1) == 0
    print("RESULT:", "OK — 无 JS 异常且功能完整" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
