# -*- coding: utf-8 -*-
"""覆盖率实测：切遍所有视图后，**直接读模块自己的扫描结果**（INTRADAY.__scan()）逐表汇报。

为什么不自己判：诊断脚本复制一份判据 = 改完源码数字不变（本会话踩过两次），
故真源只有 intraday_live.py 的 scan()，本脚本只做排版。
"""
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

SCAN = r"""
(function(){
  var r = INTRADAY.__scan();
  var cards = [].slice.call(document.querySelectorAll('.card')).filter(function(c){
    return c.querySelector('.badge-live');
  }).map(function(c){
    var h = c.querySelector('h2');
    return h ? h.textContent.replace(/实时 [0-9:]+/, '').trim().slice(0, 26) : '?';
  });
  return JSON.stringify({tables: r.tables, nTargets: r.targets.length, badged: cards});
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await c.send(json.dumps({"id": 9, "method": "Page.navigate",
                                 "params": {"url": URL + "?t=" + str(int(time.time() * 1000))}}))
        await asyncio.sleep(10)

        async def ev(expr, await_p=False, wait=90):
            await c.send(json.dumps({"id": 30, "method": "Runtime.evaluate",
                                     "params": {"expression": expr, "returnByValue": True,
                                                "awaitPromise": await_p}}))
            t1 = time.time()
            while time.time() - t1 < wait:
                m = json.loads(await c.recv())
                if m.get("id") == 30:
                    return m["result"]["result"].get("value")
            return None

        for v in ("kxmm", "sys-auto", "short", "a5"):
            await ev(f"window.switchView('{v}');1")
            await asyncio.sleep(1.6)
        await ev("INTRADAY.refresh(true)", await_p=True)
        await asyncio.sleep(1)
        d = json.loads(await ev(SCAN))

        ts = [t for t in d["tables"] if t["rows"] or t["elig"] or t.get("live")]
        ts.sort(key=lambda x: (-x["elig"], -x["rows"]))
        print(f"{'表':<22}{'行':>6}{'可刷行':>7}{'已改写格':>9}  判定 / 跳过原因")
        print("-" * 94)
        for t in ts:
            verdict = t["skip"] or ("实时刷新" if t.get("live") else "有可刷行但未改写")
            print(f"{t['id'][:22]:<22}{t['rows']:>6}{t['elig']:>7}{t.get('live', 0):>9}  {verdict}")
        print("-" * 94)
        print(f"目标格合计 {d['nTargets']} ｜ 上表明细 {len(ts)} 个")
        print(f"带实时徽章的卡片 {len(d['badged'])} 张: {d['badged']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
