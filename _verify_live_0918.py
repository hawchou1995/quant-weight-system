# -*- coding: utf-8 -*-
"""R-live-0918 验证：① 模块就位 ② 合成报价注入（含防串码守卫）③ 真实端到端刷新 ④ JS 异常 0。"""
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

SYNTH = r"""
(function(){
  var out={};
  out.hasModule = !!window.INTRADAY;
  out.hasHM = typeof window.HM_APPLY === 'function';
  var tgs = window.INTRADAY ? window.INTRADAY.targets() : [];
  out.targets = tgs.length;
  out.sample = tgs.slice(0,3).map(function(t){return t.code + '|' + t.name + '|px:' + (!!t.px) + '|pct:' + (!!t.pct);});
  if(!tgs.length) return JSON.stringify(out);
  // 选一个同时有 px/pct 单元格的目标做合成注入
  var t = null;
  for (var i=0;i<tgs.length;i++){ if(tgs[i].px && tgs[i].pct){ t=tgs[i]; break; } }
  if(!t) return JSON.stringify(out);
  out.pick = t.code + '|' + t.name;
  out.before = {px: t.px.textContent.trim(), pct: t.pct.textContent.trim()};
  var good = t.name.slice(0,2);
  var r1 = window.INTRADAY.applyQuotes((function(){var o={};o[t.code]={px:1.23,pct:8.88,name:good+'XX'};return o;})(), '99:99:99');
  out.after1 = {px: t.px.textContent.trim(), pct: t.pct.textContent.trim(), res: r1};
  // 守卫：名字完全不符 → 不应改写
  var r2 = window.INTRADAY.applyQuotes((function(){var o={};o[t.code]={px:7.77,pct:-9.99,name:'ZZ错名'};return o;})(), '99:99:99');
  out.after2 = {px: t.px.textContent.trim(), pct: t.pct.textContent.trim(), res: r2};
  out.guardOK = (out.after1.pct === '+8.88%' && out.after2.pct === '+8.88%');
  out.thTag = !!document.querySelector('.live-th');
  out.cardBadge = !!document.querySelector('.badge-live');
  out.pill = (document.getElementById('live-pill')||{}).textContent || null;
  return JSON.stringify(out);
})()
"""

REAL = r"""
(function(){
  var out={};
  out.before = {patched: INTRADAY.state.patched, lastPool: INTRADAY.state.lastPool, lastTree: INTRADAY.state.lastTree};
  var t0=Date.now();
  return INTRADAY.refresh(true).then(function(){
    out.ms = Date.now()-t0;
    out.after = {patched: INTRADAY.state.patched, miss: INTRADAY.state.miss,
                 lastPool: !!INTRADAY.state.lastPool, lastTree: !!INTRADAY.state.lastTree,
                 live: INTRADAY.state.live, ts: INTRADAY.state.ts, err: INTRADAY.state.err};
    out.pill = (document.getElementById('live-pill')||{}).textContent || null;
    out.hmLive = (document.getElementById('hm-live')||{}).textContent || null;
    out.hmAsof = (document.getElementById('hm-asof')||{}).textContent || null;
    var tgs = INTRADAY.targets();
    out.sampleAfter = tgs.slice(0,4).map(function(t){return t.code+' px='+(t.px?t.px.textContent.trim():'-')+' pct='+(t.pct?t.pct.textContent.trim():'-');});
    out.thTags = document.querySelectorAll('.live-th').length;
    out.badges = document.querySelectorAll('.badge-live').length;
    out.liveCells = document.querySelectorAll('td.live-cell').length;
    return JSON.stringify(out);
  });
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    errs = []
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await c.send(json.dumps({"id": 2, "method": "Page.enable"}))
        await asyncio.sleep(0.4)
        await c.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": URL}}))
        t0 = time.time()
        while time.time() - t0 < 12:                      # 采集加载期异常（含自动刷新）
            try:
                m = json.loads(await asyncio.wait_for(c.recv(), timeout=1.5))
            except asyncio.TimeoutError:
                continue
            if m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                errs.append((d.get("text"), (d.get("exception") or {}).get("description", "")[:180]))

        async def ev(expr, await_p=False, tag="", wait=60):
            await c.send(json.dumps({"id": 30, "method": "Runtime.evaluate",
                                     "params": {"expression": expr, "returnByValue": True,
                                                "awaitPromise": await_p}}))
            t1 = time.time()
            while time.time() - t1 < wait:
                try:
                    m = json.loads(await asyncio.wait_for(c.recv(), timeout=3))
                except asyncio.TimeoutError:
                    continue
                if m.get("id") == 30:
                    v = m["result"]["result"].get("value")
                    if v is None:
                        v = json.dumps(m["result"], ensure_ascii=False)[:300]
                    print(f"\n--- {tag} ---")
                    try:
                        d = json.loads(v)
                        for k, x in d.items():
                            print(f"  {k}: {json.dumps(x, ensure_ascii=False)}")
                    except Exception:
                        print("  ", v)
                    return v
            return None

        await ev(SYNTH, False, "① 合成注入 + 防串码守卫")
        await ev(REAL, True, "② 真实端到端刷新（东财 ulist + 全市场 clist + 树图）", wait=90)
        # 等自动刷新一轮，确认无异常
        await asyncio.sleep(6)
    print(f"\nJS 未捕获异常 = {len(errs)}")
    for e in errs[:5]:
        print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
