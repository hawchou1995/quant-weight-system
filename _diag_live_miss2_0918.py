# -*- coding: utf-8 -*-
"""诊断（真实路径）：跑一次真 applyQuotes，列出「没被改写」的目标与原因。

判据用 DOM 痕迹（.live-cell）而不是复制一份守卫逻辑 —— 上一版就是复制了旧判据，
导致改完源码诊断数字不变（假无变化）。
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

EXPR = r"""
(function(){
  var tgs = INTRADAY.targets();
  var seen = {}, codes = [];
  tgs.forEach(function(t){ if(!seen[t.code]){ seen[t.code]=1; codes.push(t.code); } });
  return INTRADAY.__fetchPool(codes).then(function(q){
    var r = INTRADAY.applyQuotes(q, '99:99:99');
    var miss = [];
    tgs.forEach(function(t){
      var ok = (t.pct && t.pct.classList.contains('live-cell')) ||
               (t.px && t.px.classList.contains('live-cell'));
      if (ok) return;
      var d = q[t.code] || {};
      miss.push({c: t.code, page: t.name, vend: d.name || '(无行情)',
                 tbl: t.tb.getAttribute('data-t') || t.tb.id || '(无 id)',
                 mk: t.tr.getAttribute('data-market') || ''});
    });
    var grp = {};
    miss.forEach(function(m){ var k = m.tbl + (m.vend === '(无行情)' ? '|nodata' : '|name'); grp[k] = (grp[k] || 0) + 1; });
    return JSON.stringify({res: r, unique: codes.length, miss: miss.length, groups: grp, list: miss});
  });
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await c.send(json.dumps({"id": 9, "method": "Page.navigate",
                                 "params": {"url": URL + "?t=" + str(int(time.time() * 1000))}}))
        await asyncio.sleep(8)
        await c.send(json.dumps({"id": 30, "method": "Runtime.evaluate",
                                 "params": {"expression": EXPR, "returnByValue": True, "awaitPromise": True}}))
        for _ in range(80):
            m = json.loads(await c.recv())
            if m.get("id") == 30:
                v = m["result"]["result"].get("value")
                if not v:
                    print(json.dumps(m["result"], ensure_ascii=False)[:400]); break
                d = json.loads(v)
                print("applyQuotes 返回:", json.dumps(d["res"], ensure_ascii=False))
                print("唯一代码:", d["unique"], "｜未改写目标:", d["miss"])
                print("分组:", json.dumps(d["groups"], ensure_ascii=False))
                print("\n明细（最多 40 条）:")
                for x in d["list"][:40]:
                    print(f"  {x['c']}  页面名={x['page']:<22} 行情名={x['vend']:<22} 表={x['tbl']:<18} mk={x['mk']}")
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
