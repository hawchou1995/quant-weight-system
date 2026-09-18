# -*- coding: utf-8 -*-
"""#10 皮肤层验证：静态（产物）+ 渲染态（真实 Chrome 计算样式 + hover 下拉实测）。

判据锚定"用户能看到的那一层"：卡片圆角/正文密度/表格数字对齐/下拉显形/页面文字是否还有 emoji。
"""
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE + "/backtest")
import gushi_daily_collect as G  # noqa: E402

H = (Path(BASE) / "dual_system.html").read_text(encoding="utf-8")
FAILS = []


def ck(name, cond, ev=""):
    print(("  PASS  " if cond else "  FAIL  ") + f"{name}  [{ev}]")
    if not cond:
        FAILS.append(name)


# ---------------- 静态层 ----------------
print("=== 静态层（产物文本）===")
KEEP = "✓✔✕✗"
EMO = re.compile("[\U0001F100-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u23E9-\u23FF\uFE0F]")
left = [c for c in EMO.findall(H) if c not in KEEP]
ck("emoji 残留 = 0（保留 ✓✕）", len(left) == 0, f"{len(left)} {Counter(left).most_common(5)}")
_lg = H.count("background:linear-gradient") + H.count("background: linear-gradient")
ck("chrome 渐变 = 0（CSS 用法）", _lg == 0, f"background:linear-gradient×{_lg}（正文提及不计）")
ck("圆角令牌 --r:6px", "--r:6px" in H and H.count("border-radius:var(--r)") >= 20, f"var(--r)×{H.count('border-radius:var(--r)')}")
ck("数字等宽 tabular-nums", H.count("font-variant-numeric:tabular-nums") >= 4, f"×{H.count('font-variant-numeric:tabular-nums')}")
ck("数值列右对齐", "table.tbl td.num,table.tbl th.num{text-align:right" in H, "ok")
ck("导航 .sn-grp 容器 + hover 规则", '.sn-grp{position:relative' in H and ".sn-grp:hover .sn-sub{display:flex}" in H, "ok")
ck("旧折叠死代码已清", "sn-sub.collapsed" not in H and "classList.toggle('collapsed')" not in H.replace("card.classList.toggle('collapsed')", ""), "ok")
ck("顶栏 52px", "height:52px;background:#1b2130" in H and "body{padding-top:52px}" in H, "ok")
ck("正文密度 13px", "font-size:13px;line-height:1.6" in H, "ok")

# ---------------- 渲染态 ----------------
URL = "file:///D:/Documents/Workbuddy/%E8%82%A1%E7%A5%A8%E5%9F%BA%E9%87%91/quant-weight-system/dual_system.html"
MEASURE = r"""
JSON.stringify((function(){
  var g=function(s,p){var e=document.querySelector(s);if(!e)return null;var c=getComputedStyle(e);return p.reduce(function(o,k){o[k]=c[k];return o;},{});};
  var tabs=[].slice.call(document.querySelectorAll('#sidenav .sn-grp > a')).map(function(a){return a.textContent.replace(/[▾▸]/g,'').trim();});
  var txt=document.body.innerText||'';
  var emo=(txt.match(/[\u{1F100}-\u{1F1FF}\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/gu)||[]);
  var tds=[].slice.call(document.querySelectorAll('table.tbl tbody td')).slice(0,400);
  var mono=tds.filter(function(t){return getComputedStyle(t).fontVariantNumeric==='tabular-nums';}).length;
  return {
    topbar:g('.topbar',['height','backgroundColor']),
    card:g('.card',['borderRadius','padding','marginBottom']),
    h2:g('.card h2',['fontSize','fontWeight']),
    body:g('body',['fontSize']),
    badge:g('.badge',['borderRadius']),
    tbl:g('table.tbl',['fontSize','fontVariantNumeric']),
    kpiV:g('.kpi .v',['fontSize','fontVariantNumeric']),
    tabs:tabs,
    groups:document.querySelectorAll('#sidenav .sn-grp').length,
    subsPerTab:[].slice.call(document.querySelectorAll('#sidenav .sn-grp')).map(function(x){return x.querySelectorAll('.sn-sub a').length;}),
    emojiInText:emo.length, emojiSample:emo.slice(0,8),
    monoRatio:tds.length?Math.round(mono/tds.length*100)+'%':'n/a',
    snSubDisplay:g('#sidenav .sn-sub',['display']),
    views:[].slice.call(document.querySelectorAll('.view')).map(function(v){return v.id;}),
    kxmmCards:document.querySelectorAll('#view-kxmm .card').length,
    errCount:(window.__errs||[]).length
  };})())
"""


async def main():
    if not G.cdp_alive(G.AUTO_PORT):
        G.boot_auto_profile()
    ws = G.page_ws(G.AUTO_PORT)
    await G.navigate(ws, URL)
    await asyncio.sleep(5)
    # 等首屏实时层拉完（树图 56 请求）—— 否则输入事件排队会让 hover 判定抖动
    for _ in range(20):
        try:
            if json.loads(await G.ev(ws, 'JSON.stringify(!!(window.INTRADAY&&INTRADAY.state.lastTree))')) :
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    d = json.loads(await G.ev(ws, MEASURE))
    print("\n=== 渲染态（真实 Chrome 计算样式）===")
    print("  顶栏:", d.get("topbar"), "| body:", d.get("body"))
    print("  卡片:", d.get("card"), "| h2:", d.get("h2"), "| badge:", d.get("badge"))
    print("  表格:", d.get("tbl"), "| KPI 值:", d.get("kpiV"), "| 数值单元格等宽占比:", d.get("monoRatio"))
    print("  tabs:", d.get("tabs"), "| 定位容器:", d.get("groups"), " 子项数:", d.get("subsPerTab"))
    print("  页面文字 emoji:", d.get("emojiInText"), d.get("emojiSample"))
    print("  视图:", d.get("views"), "| 晴雨页卡片:", d.get("kxmmCards"), "| 初始下拉 display:", d.get("snSubDisplay"))

    tb = d.get("topbar") or {}
    card = d.get("card") or {}
    h2 = d.get("h2") or {}
    tbl = d.get("tbl") or {}
    kpi = d.get("kpiV") or {}
    print()
    ck("顶栏高 52px 且深色", tb.get("height") == "52px" and "27, 33, 48" in str(tb.get("backgroundColor")), str(tb))
    ck("卡片圆角 6px + 内边距 16px", card.get("borderRadius") == "6px" and str(card.get("padding")).startswith("16px"), str(card))
    ck("卡片标题 15px/600", h2.get("fontSize") == "15px" and h2.get("fontWeight") == "600", str(h2))
    ck("正文字号 13px", d.get("body", {}).get("fontSize") == "13px", str(d.get("body")))
    ck("徽章小方标 4px", (d.get("badge") or {}).get("borderRadius") == "4px", str(d.get("badge")))
    ck("表格 12.5px + 数字等宽", tbl.get("fontSize") == "12.5px" and tbl.get("fontVariantNumeric") == "tabular-nums", str(tbl))
    ck("KPI 数值 20px + 等宽", kpi.get("fontSize") == "20px" and kpi.get("fontVariantNumeric") == "tabular-nums", str(kpi))
    ck("数值单元格等宽覆盖 ≥90%", str(d.get("monoRatio")).rstrip("%").isdigit() and int(str(d.get("monoRatio")).rstrip("%")) >= 90, str(d.get("monoRatio")))
    ck("5 个 tab 无 emoji", d.get("tabs") == ["市场晴雨", "中长线池", "短线选股", "打板专区", "社区讨论"], str(d.get("tabs")))
    ck("页面可见文字 emoji = 0", d.get("emojiInText") == 0, str(d.get("emojiSample")))
    ck("下拉默认收起", (d.get("snSubDisplay") or {}).get("display") == "none", str(d.get("snSubDisplay")))

    # ---- hover 实测：真鼠标移动到「中长线池」tab ----
    box = await G.ev(ws, """JSON.stringify((function(){
      var a=document.querySelectorAll('#sidenav .sn-grp > a')[1];
      var r=a.getBoundingClientRect();
      return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), label:a.textContent.trim()};})())""")
    b = json.loads(box)
    await G.ev(ws, "1")  # 保持 evaluate 通道热
    import websockets
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=15) as c:
        await c.send(json.dumps({"id": 91, "method": "Input.dispatchMouseEvent",
                                 "params": {"type": "mouseMoved", "x": b["x"], "y": b["y"], "buttons": 0}}))
        await asyncio.sleep(2.5)
    after = json.loads(await G.ev(ws, """JSON.stringify((function(){
      var s=document.querySelectorAll('#sidenav .sn-grp')[1].querySelector('.sn-sub');
      var r=s.getBoundingClientRect(); var c=getComputedStyle(s);
      return {display:c.display,w:Math.round(r.width),h:Math.round(r.height),top:Math.round(r.y),
              items:s.querySelectorAll('a').length,first:s.querySelector('a')?s.querySelector('a').textContent.trim():null};})())"""))
    print("  hover 目标:", b.get("label"), "→ 下拉:", after)
    ck("hover「中长线池」下拉显形", after.get("display") == "flex" and after.get("w", 0) > 100 and after.get("h", 0) > 40, str(after))
    ck("下拉含子项链接", after.get("items", 0) >= 5, f"{after.get('items')} 项，首项 {after.get('first')}")

    # ---- 移开后收起 ----
    async with websockets.connect(ws, max_size=64 * 1024 * 1024, open_timeout=15) as c:
        await c.send(json.dumps({"id": 92, "method": "Input.dispatchMouseEvent",
                                 "params": {"type": "mouseMoved", "x": 960, "y": 900, "buttons": 0}}))
        await asyncio.sleep(2.5)
    off = json.loads(await G.ev(ws, """JSON.stringify({d:getComputedStyle(document.querySelectorAll('#sidenav .sn-grp')[1].querySelector('.sn-sub')).display})"""))
    ck("移开后自动收起", off.get("d") == "none", str(off))

    print("\nRESULT: " + ("OK — #10 皮肤层生效" if not FAILS else f"FAIL {len(FAILS)} 项: {FAILS}"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
