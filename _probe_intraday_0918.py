# -*- coding: utf-8 -*-
"""盘中实时通道 · 浏览器端实测（file:// 与 https 两种 Origin 都要过）。

判据：① HTTP 200 ② 能解析出价格/涨跌幅 ③ 全市场批量（腾讯 900 码）能拿全
     ④ 值合理（与收盘价同量级）
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
LIVE = "https://hawchou1995.github.io/quant-weight-system/?v=probe"

# 在页面里跑：东财 ulist（少量码）+ 腾讯 qt（900 码，GBK）
PROBE = r"""
(async function(){
  var out={};
  // ① 东财 ulist
  try{
    var u='https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f6,f12,f14,f20&secids=1.600519,0.000001,0.300750';
    var r=await fetch(u,{cache:'no-store'}); var j=await r.json();
    var d=(j.data&&j.data.diff)||[];
    out.em={status:r.status,n:d.length,sample:d.slice(0,2).map(function(x){return x.f12+':'+x.f2+'/'+x.f3+'%';})};
  }catch(e){ out.em={err:String(e)}; }
  // ② 腾讯 qt 单码（GBK 解码）
  try{
    var r2=await fetch('https://qt.gtimg.cn/q=sh600519,sz000001,sz300750',{cache:'no-store'});
    var buf=await r2.arrayBuffer();
    var txt=new TextDecoder('gbk').decode(buf);
    var rows=txt.trim().split('\n').map(function(l){var f=l.split('~');return {code:f[2],name:f[1],px:f[3],pct:f[32],amt:f[37],ts:f[30]};});
    out.tx={status:r2.status,n:rows.length,rows:rows.slice(0,3)};
  }catch(e){ out.tx={err:String(e)}; }
  // ③ 腾讯 900 码批量（全市场分片实测）
  try{
    var codes=[];
    for(var pn=1;pn<=9;pn++){
      var r3=await fetch('https://push2delay.eastmoney.com/api/qt/clist/get?pn='+pn+'&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12',{cache:'no-store'});
      var j3=await r3.json(); var d3=(j3.data&&j3.data.diff)||[]; if(!d3.length)break;
      d3.forEach(function(x){codes.push((x.f12[0]==='6'||x.f12[0]==='5'||x.f12[0]==='9'?'sh':'sz')+x.f12);});
    }
    out.codes=codes.length;
    var t0=Date.now();
    var r4=await fetch('https://qt.gtimg.cn/q='+codes.slice(0,900).join(','),{cache:'no-store'});
    var buf4=await r4.arrayBuffer(); var txt4=new TextDecoder('gbk').decode(buf4);
    var n4=txt4.trim().split('\n').length;
    out.txBig={status:r4.status,n:n4,ms:Date.now()-t0,kb:Math.round(buf4.byteLength/1024)};
  }catch(e){ out.txBig={err:String(e)}; }
  // ④ Origin / 是否 https
  out.env={origin:location.origin,proto:location.protocol};
  return JSON.stringify(out);
})()
"""


async def main():
    ws = G.page_ws(G.AUTO_PORT)
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 1, "method": "Page.enable"}))
        for name, url in (("file://", LOCAL), ("线上 https", LIVE)):
            await c.send(json.dumps({"id": 9, "method": "Page.navigate", "params": {"url": url}}))
            await asyncio.sleep(7)
            await c.send(json.dumps({"id": 20, "method": "Runtime.evaluate",
                                     "params": {"expression": PROBE, "awaitPromise": True,
                                                "returnByValue": True}}))
            got = None
            for _ in range(60):
                m = json.loads(await c.recv())
                if m.get("id") == 20:
                    got = m["result"]["result"].get("value")
                    if got is None:
                        got = json.dumps(m["result"], ensure_ascii=False)[:400]
                    break
            print(f"\n===== {name} =====")
            try:
                d = json.loads(got)
                print("  env:", d.get("env"))
                print("  东财 ulist:", json.dumps(d.get("em"), ensure_ascii=False)[:200])
                print("  腾讯单批  :", json.dumps(d.get("tx"), ensure_ascii=False)[:260])
                print("  代码池    :", d.get("codes"), " 腾讯900码:", json.dumps(d.get("txBig"), ensure_ascii=False)[:160])
            except Exception:
                print("  原始返回:", got)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
