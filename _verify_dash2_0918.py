# -*- coding: utf-8 -*-
"""看板四项改动 · 渲染态实测 v2（修正 v1 的三处错误断言）。

v1 的三个错误断言（我的错，非代码错）：
  ① thScore/thSub 期望 1 → 实际 2（`system_block` 被中长线池与基金池各用一次，两表都该拆列）
  ② order 期望比较 top → 隐藏视图内 getBoundingClientRect 全 0，量不到
  ③ advLines 期望 w<=220 → 同理为 0，属假通过
v2：先强制 display:block 展开全部视图再量。
"""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
import gushi_daily_collect as G  # noqa: E402
import websockets  # noqa: E402

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")

REVEAL = "document.querySelectorAll('.view').forEach(function(v){v.style.display='block';}); 'revealed'"

MEASURE = r"""
JSON.stringify({
  navW: document.querySelector('.sidenav').getBoundingClientRect().width,
  contML: getComputedStyle(document.querySelector('.container')).marginLeft,
  lblOpacity: getComputedStyle(document.querySelector('.sidenav .lbl')).opacity,
  v9Display: (function(){var e=document.getElementById('v9-retired-card');return e?getComputedStyle(e).display:'missing';})(),
  thScore: [].slice.call(document.querySelectorAll('th')).filter(function(t){return t.textContent.replace(/\s/g,'').indexOf('权重总分')===0;}).length,
  thSub: [].slice.call(document.querySelectorAll('th')).filter(function(t){return t.textContent.replace(/\s/g,'').indexOf('子项评分')===0;}).length,
  adv: (function(){
     var s=document.querySelector('#a5-zt .adv-cell');
     if(!s) return null;
     var cs=getComputedStyle(s), lh=parseFloat(cs.lineHeight)||14, r=s.getBoundingClientRect();
     // 最长的一条建议（挑最宽行）用于验证换行是否真的发生
     var best=null;
     document.querySelectorAll('#a5-zt .adv-cell').forEach(function(e){
        var b=e.getBoundingClientRect();
        if(!best||b.height>best.h) best={h:b.height,w:b.width,txt:e.textContent.slice(0,40)};
     });
     return {ws: cs.whiteSpace, w: Math.round(r.width), lh: lh,
             maxLines: best? Math.round(best.h/lh):0, maxW: best? Math.round(best.w):0,
             sample: best? best.txt:''};
  })(),
  order: (function(){
     var f=document.getElementById('fb3-pool-card'), u=document.getElementById('fund-paper-card');
     return {fb3: Math.round(f.getBoundingClientRect().top), fund: Math.round(u.getBoundingClientRect().top)};
  })(),
  tblCls: (function(){var c=document.getElementById('ret20-paper-card'); if(!c) return 'no-card';
     var t=c.querySelector('table'); return t? (t.className||'(no class)') : 'no-table';})()
})
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(3)
    await G.ev(ws, REVEAL)
    await asyncio.sleep(0.6)

    print("=== ① 折叠态 ===")
    d = json.loads(await G.ev(ws, MEASURE))
    for k in ("navW", "contML", "lblOpacity", "v9Display", "thScore", "thSub", "adv", "order", "tblCls"):
        print(f"  {k}: {d.get(k)}")

    print("\n=== ② 真派发鼠标移入导航 → 悬浮态 ===")
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=10) as c:
        for _ in range(3):
            await c.send(json.dumps({"id": 7, "method": "Input.dispatchMouseEvent",
                                     "params": {"type": "mouseMoved", "x": 30, "y": 320, "button": "none"}}))
            try:
                await asyncio.wait_for(c.recv(), timeout=3)
            except Exception:
                pass
            await asyncio.sleep(0.15)
    await asyncio.sleep(0.8)
    d2 = json.loads(await G.ev(ws, MEASURE))
    print(f"  navW: {d.get('navW')} → {d2.get('navW')}")
    print(f"  lblOpacity: {d.get('lblOpacity')} → {d2.get('lblOpacity')}")

    adv = d.get("adv") or {}
    ok = [
        ("导航默认折叠 56px", abs(float(d.get("navW", -1)) - 56) < 1.5),
        ("container 常驻 56px", str(d.get("contML")) == "56px"),
        ("折叠态标签隐藏(opacity 0)", str(d.get("lblOpacity")) == "0"),
        ("悬浮展开 190px", abs(float(d2.get("navW", -1)) - 190) < 1.5),
        ("悬浮态标签可见(opacity>0.9)", float(d2.get("lblOpacity", 0)) > 0.9),
        ("v9-retired-card 已隐藏", d.get("v9Display") == "none"),
        ("权重总分列存在(两表各一)", d.get("thScore") == 2),
        ("子项评分列存在(两表各一)", d.get("thSub") == 2),
        ("建议列 white-space=normal", adv.get("ws") == "normal"),
        ("建议列宽 <=220px", 0 < adv.get("maxW", 999) <= 220),
        ("建议列确实发生换行(>=2 行)", adv.get("maxLines", 0) >= 2),
        ("基金池在基金模拟盘上方", d.get("order", {}).get("fb3", 1) < d.get("order", {}).get("fund", 0)),
        ("ret20 卡表格 class=tbl", "tbl" in str(d.get("tblCls"))),
    ]
    print()
    for n, v in ok:
        print(f"  [{'ok' if v else 'FAIL'}] {n}")
    print("\nRESULT: " + ("OK — 四项改动渲染态全部生效" if all(v for _, v in ok) else "FAIL"))
    return 0 if all(v for _, v in ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
