# -*- coding: utf-8 -*-
"""盘中通道 · 浏览器端梯度实测：找「浏览器里」真正可用的批量上限。

（curl 上限 ≠ 浏览器上限：curl 900 码通过，浏览器 Failed to fetch）
"""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

LOCAL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
         "quant-weight-system/dual_system.html")

PROBE = r"""
(async function(){
  var log=[];
  // 先取 1500 个代码（clist 分页）
  var codes=[];
  for(var pn=1;pn<=15;pn++){
    var r=await fetch('https://push2delay.eastmoney.com/api/qt/clist/get?pn='+pn+'&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12',{cache:'no-store'});
    var j=await r.json(); var d=(j.data&&j.data.diff)||[]; if(!d.length)break;
    d.forEach(function(x){codes.push((x.f12[0]==='6'||x.f12[0]==='5'||x.f12[0]==='9'?'sh':'sz')+x.f12);});
  }
  log.push('codes='+codes.length);
  function secid(c){var n=c.slice(2);return (n[0]==='6'||n[0]==='5'||n[0]==='9'?'1.':'0.')+n;}
  // ① 东财 ulist 梯度
  for (var k of [200,500,800]) {
    try{
      var u='https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f6,f12,f14,f20&secids='
            + codes.slice(0,k).map(secid).join(',');
      var t0=Date.now(); var rr=await fetch(u,{cache:'no-store'}); var jj=await rr.json();
      var dd=(jj.data&&jj.data.diff)||[];
      log.push('em_ulist n='+k+' status='+rr.status+' rows='+dd.length+' ms='+(Date.now()-t0));
    }catch(e){ log.push('em_ulist n='+k+' ERR '+String(e).slice(0,60)); }
  }
  // ② 腾讯 qt 梯度
  for (var k of [100,300,500,900]) {
    try{
      var t1=Date.now();
      var r2=await fetch('https://qt.gtimg.cn/q='+codes.slice(0,k).join(','),{cache:'no-store'});
      var b2=await r2.arrayBuffer(); var txt=new TextDecoder('gbk').decode(b2);
      log.push('tx_qt n='+k+' status='+r2.status+' lines='+txt.trim().split('\n').length+' kb='+Math.round(b2.byteLength/1024)+' ms='+(Date.now()-t1));
    }catch(e){ log.push('tx_qt n='+k+' ERR '+String(e).slice(0,60)); }
  }
  // ③ 东财 clist 全市场分页耗时（56 页）
  try{
    var t2=Date.now(); var got=0;
    for(var p=1;p<=56;p++){
      var r3=await fetch('https://push2delay.eastmoney.com/api/qt/clist/get?pn='+p+'&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f6,f12,f14,f20,f21',{cache:'no-store'});
      var j3=await r3.json(); var d3=(j3.data&&j3.data.diff)||[]; if(!d3.length)break; got+=d3.length;
    }
    log.push('em_clist 全市场 rows='+got+' ms='+(Date.now()-t2));
  }catch(e){ log.push('em_clist ERR '+String(e).slice(0,60)); }
  return JSON.stringify(log);
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await c.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": LOCAL}}))
        await asyncio.sleep(7)
        await c.send(json.dumps({"id": 20, "method": "Runtime.evaluate",
                                 "params": {"expression": PROBE, "awaitPromise": True,
                                            "returnByValue": True}}))
        for _ in range(120):
            m = json.loads(await c.recv())
            if m.get("id") == 20:
                v = m["result"]["result"].get("value")
                if v:
                    for line in json.loads(v):
                        print("  ", line)
                else:
                    print("  原始:", json.dumps(m["result"], ensure_ascii=False)[:500])
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
