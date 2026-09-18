# -*- coding: utf-8 -*-
"""短线股票池（今日 0 行）的合成行验证：注入一行 → 调真实 applyQuotes → 断言被改写。

只动自建的临时行（测完重载页面丢弃），不碰任何生产数据。
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
  var t = document.getElementById('tbl-short-stk');
  if(!t) return JSON.stringify({err:'表不存在'});
  var ths = [].slice.call(t.querySelectorAll('thead th'));
  var pxI = -1, pcI = -1;
  ths.forEach(function(th, j){
    var k = (th.getAttribute('data-key')||'').toLowerCase(), tx = (th.textContent||'').replace(/实时/g,'').trim();
    if(pxI<0 && (['px'].indexOf(k)>=0 || ['现价','收盘'].indexOf(tx)>=0)) pxI = j;
    if(pcI<0 && (['chg'].indexOf(k)>=0 || ['涨跌幅','涨跌'].indexOf(tx)>=0)) pcI = j;
  });
  if(pxI<0 || pcI<0) return JSON.stringify({err:'未找到 现价/涨跌幅 列', ths: ths.length});
  /* 只注入自建测试行（测完页面重载即丢弃） */
  var tr = document.createElement('tr');
  tr.setAttribute('data-code','sh600519');
  tr.setAttribute('data-search','贵州茅台 600519 食品饮料 主板');
  for(var i=0;i<ths.length;i++){
    var td = document.createElement('td');
    if(i===0) td.innerHTML = '<b>贵州茅台</b><br><span>600519</span>';
    else if(i===pxI) td.textContent = '1257.12';
    else if(i===pcI) { td.className='up'; td.setAttribute('data-v','-0.78'); td.textContent='-0.78%'; }
    else td.textContent = '—';
    tr.appendChild(td);
  }
  t.querySelector('tbody').appendChild(tr);
  var before = {px: tr.children[pxI].textContent.trim(), pct: tr.children[pcI].textContent.trim()};
  var r = INTRADAY.applyQuotes({'600519': {px: 1111.11, pct: 5.55, name: '贵州茅台'}}, '99:99:99');
  var after = {px: tr.children[pxI].textContent.trim(), pct: tr.children[pcI].textContent.trim(),
               cls: tr.children[pcI].className, dv: tr.children[pcI].getAttribute('data-v'),
               cellMarked: tr.children[pcI].classList.contains('live-cell')};
  var thTag = !!t.querySelector('.live-th');
  return JSON.stringify({pxI: pxI, pctI: pcI, before: before, after: after, thTag: thTag,
                         res: r, pass: after.pct === '+5.55%' && after.px === '1111.11' && thTag,
                         demo: tr.outerHTML.slice(0, 220)});
})()
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        print("[boot] 拉起自动化 Chrome…")
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=25) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await c.send(json.dumps({"id": 9, "method": "Page.navigate",
                                 "params": {"url": URL + "?t=" + str(int(time.time() * 1000))}}))
        await asyncio.sleep(9)
        await c.send(json.dumps({"id": 11, "method": "Runtime.evaluate",
                                 "params": {"expression": "window.switchView('short');1", "returnByValue": True}}))
        await asyncio.sleep(2)
        await c.send(json.dumps({"id": 30, "method": "Runtime.evaluate",
                                 "params": {"expression": EXPR, "returnByValue": True, "awaitPromise": False}}))
        for _ in range(60):
            m = json.loads(await c.recv())
            if m.get("id") == 30:
                v = m["result"]["result"].get("value")
                if not v:
                    print(json.dumps(m["result"], ensure_ascii=False)[:300]); break
                d = json.loads(v)
                for k, x in d.items():
                    print(f"  {k}: {json.dumps(x, ensure_ascii=False)}")
                print("\nRESULT:", "OK — 短线股票池有行时会被实时刷新" if d.get("pass") else "FAIL")
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
