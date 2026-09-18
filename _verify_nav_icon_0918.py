# -*- coding: utf-8 -*-
"""顶栏图标位修复验证 + 全站 CSS 选择器合法性扫描。

① 顶栏：5 个 tab 无图标占位（.ic 数=0）、宽度一致、hover 下拉仍可用
② 全站：逐条选择器用 querySelector 试解析 —— 抛 SyntaxError 的即"非法选择器"
   （非法项会让**整条规则被浏览器丢弃**，本轮就是 :blank 造成空占位一直存在）
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

CHECK = r"""
(function(){
  var out = {tabs: [], icCount: document.querySelectorAll('#sidenav .ic').length,
             subIc: document.querySelectorAll('#sidenav .sn-sub .ic').length,
             badgeIc: document.querySelectorAll('.sn-foot-slot .ic').length, bad: []};
  document.querySelectorAll('#sidenav .sn-grp > a').forEach(function(a){
    var r = a.getBoundingClientRect();
    out.tabs.push({t: a.textContent.replace(/\s+/g,''), w: Math.round(r.width),
                   pad: getComputedStyle(a).paddingLeft + '/' + getComputedStyle(a).paddingRight});
  });
  /* 选择器合法性扫描（含 media/支持规则内层） */
  function walk(rules, tag){
    for (var i = 0; i < rules.length; i++){
      var r = rules[i];
      if (r.cssRules) { walk(r.cssRules, tag + '>' + (r.conditionText || r.media && r.media.mediaText || 'grp')); continue; }
      if (!r.selectorText) continue;
      r.selectorText.split(',').forEach(function(sel){
        var s = sel.trim(); if (!s) return;
        try { document.querySelector(s); }
        catch (e) { out.bad.push(tag + ' :: ' + s); }
      });
    }
  }
  for (var i = 0; i < document.styleSheets.length; i++){
    try { walk(document.styleSheets[i].cssRules, 'sheet' + i); } catch (e) {}
  }
  return JSON.stringify(out);
})()
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL + "?t=" + str(int(time.time() * 1000)))
    await asyncio.sleep(8)
    # 等首屏实时层就绪，避免输入事件排队干扰 hover 判定
    for _ in range(20):
        try:
            if json.loads(await G.ev(ws, "JSON.stringify(!!(window.INTRADAY && INTRADAY.state.lastTree))")):
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    d = json.loads(await G.ev(ws, CHECK))

    print("=== 顶栏 ===")
    for t in d["tabs"]:
        print(f"  {t['t']:<12} 宽={t['w']:>4}px  padding={t['pad']}")
    print(f"  导航内 .ic 数量 = {d['icCount']} （应为 0）｜ 下拉子项 .ic = {d['subIc']} ｜ 右槽 .ic = {d['badgeIc']}")
    widths = [t["w"] for t in d["tabs"]]
    print(f"\n  宽度: {widths}  极差={max(widths)-min(widths)}px")
    print("\n=== 非法选择器扫描 ===")
    if d["bad"]:
        for b in d["bad"]:
            print("  ✗", b)
    else:
        print("  无（全部选择器可被浏览器解析）")

    # hover 下拉仍可用
    box = json.loads(await G.ev(ws, """JSON.stringify((function(){
      var a=document.querySelectorAll('#sidenav .sn-grp > a')[1];var r=a.getBoundingClientRect();
      return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})())"""))
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=20) as c:
        await c.send(json.dumps({"id": 91, "method": "Input.dispatchMouseEvent",
                                 "params": {"type": "mouseMoved", "x": box["x"], "y": box["y"], "buttons": 0}}))
        await asyncio.sleep(2.5)
    sub = json.loads(await G.ev(ws, """JSON.stringify((function(){
      var s=document.querySelectorAll('#sidenav .sn-grp')[1].querySelector('.sn-sub');
      return {d:getComputedStyle(s).display, items:s.querySelectorAll('a').length};})())"""))
    print(f"\n=== hover 下拉 ===\n  display={sub['d']} 子项={sub['items']}")
    print("\nRESULT:", "OK" if (d["icCount"] == 0 and not d["bad"] and sub["d"] == "flex") else "FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
