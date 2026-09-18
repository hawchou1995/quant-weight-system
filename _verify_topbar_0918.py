# -*- coding: utf-8 -*-
"""顶部横 tab 改版 · 结构 + 渲染态双重验证（修正上一版校验正则把子项当 tab 的错）。"""
import ast
import asyncio
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE + "/backtest")
import gushi_daily_collect as G  # noqa: E402

h = open(BASE + "/dual_system.html", encoding="utf-8").read()
m = re.search(r"window\.ENH\.nav = \[(.*?)\n\];", h, re.S)
# 主 tab 的判据：第 4 个元素必须是列表（子项数组）
tabs = re.findall(r'\["([\w-]+)","([^"]*)","([^"]+)",\[', m.group(1))
print("=== 主 tab（第 4 元素为子项数组者）===")
for i, (k, ic, n) in enumerate(tabs, 1):
    print(f"  {i}. {n:<6} key={k:<9} icon={ic}")
struct = [
    ("主 tab 数量 == 5", len(tabs) == 5),
    ("顺序 = 市场晴雨→三池→社区讨论",
     [n for _, _, n in tabs] == ["市场晴雨", "中长线池", "短线选股", "打板专区", "社区讨论"]),
    ("社区讨论为外链", 'href="https://qingju.me/" target="_blank"' in h),
    ("顶部横栏 CSS", "height:54px;background:#1b2130" in h),
    ("content 不再被占位", "body.sidenav-open .container{margin-left:0;" in h),
    ("徽章 CSS + 函数", ".mkt-badge{" in h and "function mktBadgeHtml()" in h),
    ("MKT_STATUS 已注入", "window.MKT_STATUS = {" in h),
    ("子项目标视图属性", 'data-view="' in h),
]
print()
for n, v in struct:
    print(f"  [{'ok' if v else 'FAIL'}] {n}")

URL = ("file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/"
       "quant-weight-system/dual_system.html")
MEASURE = r"""
JSON.stringify({
  navTag: (function(){var n=document.getElementById('sidenav');if(!n)return null;var r=n.getBoundingClientRect();
     var cs=getComputedStyle(n);
     return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
             pos:cs.position, dir:cs.flexDirection, bg:cs.backgroundColor};})(),
  tabs: [].slice.call(document.querySelectorAll('#sidenav > a')).filter(function(a){return a.textContent.trim();}).map(function(a){return a.textContent.replace(/[▾▸]/g,'').replace(/^[^一-龥A-Za-z]+/,'').trim();}),
  badge: (function(){var b=document.querySelector('.mkt-badge');if(!b)return null;
     return {txt:b.textContent.trim(), cls:b.className, title:b.getAttribute('title')};})(),
  contML: getComputedStyle(document.querySelector('.container')).marginLeft,
  contPT: getComputedStyle(document.querySelector('.container')).paddingTop,
  mktStatus: window.MKT_STATUS || null,
  views: [].slice.call(document.querySelectorAll('.view')).map(function(v){return v.id;})
})
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(4)
    d = json.loads(await G.ev(ws, MEASURE))
    print("\n=== 渲染态实测 ===")
    print("  #sidenav:", d.get("navTag"))
    print("  主 tab 文本:", d.get("tabs"))
    print("  开市徽章:", d.get("badge"))
    print("  MKT_STATUS:", d.get("mktStatus"))
    print("  container margin-left:", d.get("contML"), "| padding-top:", d.get("contPT"))
    print("  视图:", d.get("views"))
    nt = d.get("navTag") or {}
    bd = d.get("badge") or {}
    rend = [
        ("导航为全宽顶部横栏（宽>300、高≈54、flex-row、sticky）",
         nt.get("w", 0) > 300 and 50 <= nt.get("h", 0) <= 60
         and nt.get("dir") == "row" and nt.get("pos") == "sticky"),
        ("深色底 #1b2130", "27, 33, 48" in str(nt.get("bg"))),
        ("主 tab 5 个且文本正确",
         d.get("tabs") == ["市场晴雨", "中长线池", "短线选股", "打板专区", "社区讨论"]),
        ("徽章已渲染且有状态文案", bool(bd.get("txt"))),
        ("徽章 class 属五态之一",
         any(x in str(bd.get("cls")) for x in ("mkt-open", "mkt-mid", "mkt-rest", "mkt-pre"))),
        ("内容区不再左移", d.get("contML") == "0px"),
    ]
    print()
    for n, v in rend:
        print(f"  [{'ok' if v else 'FAIL'}] {n}")
    allok = all(v for _, v in struct) and all(v for _, v in rend)
    print("\nRESULT: " + ("OK — 顶部横 tab 改版生效" if allok else "FAIL"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
