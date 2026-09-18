# -*- coding: utf-8 -*-
"""诊断：哪些目标没拿到行情（避免"挂着实时标签却是旧值"）。"""
import asyncio
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%A1%A3%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")
URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html?v=1789738922")

EXPR = r"""
(function(){
  var tgs = INTRADAY.targets();
  var seen={}, codes=[];
  tgs.forEach(function(t){ if(!seen[t.code]){seen[t.code]=1;codes.push(t.code);} });
  return INTRADAY.__fetchPool(codes).then(function(q){
    var miss=[];
    tgs.forEach(function(t){
      var d=q[t.code];
      if(!d){ miss.push({code:t.code,name:t.name,tbl:t.tb.getAttribute('data-t')||t.tb.id||'',mk:t.tr.getAttribute('data-market')||''}); return; }
      if(t.name && d.name && t.name.slice(0,2)!==String(d.name).slice(0,2))
        miss.push({code:t.code,name:t.name,vend:d.name,tbl:t.tb.getAttribute('data-t')||t.tb.id||'',why:'name'});
    });
    var byTbl={}; miss.forEach(function(m){ var k=(m.tbl||'?')+'|'+(m.why||'nodata')+'|'+(m.mk||''); byTbl[k]=(byTbl[k]||0)+1; });
    return JSON.stringify({total:tgs.length, unique:codes.length, miss:miss.length,
                           groups:byTbl, all:miss.slice(0,6), all:miss.slice(0,3), samples:miss.filter(function(m){return m.why==="name";}).map(function(m){return {c:m.code,p:m.name,v:m.vend,t:m.tbl,ds:null};}).slice(0,20)});
  });
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await c.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": URL}}))
        await asyncio.sleep(8)
        await c.send(json.dumps({"id": 30, "method": "Runtime.evaluate",
                                 "params": {"expression": EXPR, "returnByValue": True, "awaitPromise": True}}))
        for _ in range(60):
            m = json.loads(await c.recv())
            if m.get("id") == 30:
                v = m["result"]["result"].get("value")
                print(json.dumps(json.loads(v), ensure_ascii=False, indent=1) if v else json.dumps(m["result"], ensure_ascii=False)[:400])
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
