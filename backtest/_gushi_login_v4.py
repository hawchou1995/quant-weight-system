# -*- coding: utf-8 -*-
"""gushi 登录 v4：可靠的 LINUX DO OAuth 自助登录（量化站 i.gushi.in + 论坛 gushi.in）

为什么有 v4（2026-10-09）：
  v3 的「弹窗是否已打开」判据只认 `input[type=password]`，而本站登录模态**默认落在
  「使用 LINUX DO 登录」标签**，密码框在 DOM 里宽高为 0（要切到「本站账号」标签才有尺寸）。
  ⇒ v3 每次都把「已打开的模态」误判成「未打开」，点完入口就 `return`，从未真正登录。
  实测 2026-10-09：v3 输出「[1] 弹窗未打开 → 截图」后退出，而同一时刻 `#authModal`
  的 computed display 已是 `flex`（模态明明开着）。本脚本改用**结构性判据**。

用法：
  python -X utf8 backtest/_gushi_login_v4.py            # 确保登录（guest 才动手）；exit 0=vip / 2=非vip / 3=仍 guest
  python -X utf8 backtest/_gushi_login_v4.py --check    # 只查状态，不点任何东西
  python -X utf8 backtest/_gushi_login_v4.py --force    # 无视当前登录态，重走一遍 OAuth
退出码：0 = role=vip（可采全字段）｜2 = 已登录但非 VIP（数据脱敏）｜3 = 仍是 guest（未登录）
       ｜1 = 环境/脚本异常
"""
import argparse
import asyncio
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gushi_daily_collect as G  # noqa: E402

PORT = G.AUTO_PORT
QUANT_URL = "https://i.gushi.in/factor.html"
SHOT_DIR = HERE / "gushi_data"

# 结构性选择器（实测 2026-10-09 有效），不依赖文案
SEL_LOGIN_ENTRY = "button.role-btn"        # 头部「登录」
SEL_AUTH_MODAL = "#authModal"              # 登录模态容器
SEL_LD_BUTTON = "button.auth-connect"      # 「LD · 使用 LINUX DO 登录」
AUTH_TEXT_RE = r"^(允许|授权|Authorize|同意|继续|Continue|Accept)$"


# ---------------- CDP 基础 ----------------

def pages():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=8) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def _host_of(url):
    """取 URL 的 host（忽略端口）。"""
    try:
        from urllib.parse import urlparse
        return (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return ""


def is_quant(url):
    """是否是量化站页。
    ⚠ 必须用 host 判据，不能用子串：linux.do 的授权 URL 形如
      https://connect.linux.do/oauth2/authorize?...redirect_uri=https%3A%2F%2Fi.gushi.in%2F...
      其查询串里就含 'i.gushi.in' —— 子串判据会把「授权页」误认成「量化站页」
      （2026-10-09 实测：v4 --force 因此认错标签页，整轮扑空）。
    """
    return _host_of(url) == "i.gushi.in"


def quant_ws():
    for t in pages():
        if is_quant(t.get("url")):
            return t["webSocketDebuggerUrl"]
    return G.page_ws(PORT)


async def cmd(ws, method, params=None, _id=1):
    await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        m = json.loads(await ws.recv())
        if m.get("id") == _id:
            return m


async def js(ws, expr):
    m = await cmd(ws, "Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "awaitPromise": True})
    r = m.get("result", {})
    if "exceptionDetails" in r:
        return "JS_ERR " + json.dumps(r["exceptionDetails"], ensure_ascii=False)[:200]
    return r.get("result", {}).get("value")


async def click(ws, x, y):
    for t in ("mousePressed", "mouseReleased"):
        await cmd(ws, "Input.dispatchMouseEvent",
                  {"type": t, "x": int(x), "y": int(y), "button": "left", "clickCount": 1}, _id=2)
    await asyncio.sleep(0.8)


async def shot(ws, name):
    try:
        m = await cmd(ws, "Page.captureScreenshot", {"format": "png"}, _id=3)
        if "result" in m and "data" in m["result"]:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            (SHOT_DIR / name).write_bytes(base64.b64decode(m["result"]["data"]))
            print(f"   [shot] gushi_data/{name}")
    except Exception as e:
        print(f"   [shot] 失败（忽略）：{str(e)[:80]}")


ME_JS = ("(async()=>{try{const r=await fetch('/api.php?action=me',{credentials:'same-origin'});"
         "const j=await r.json();const q=j.result||{};return JSON.stringify({role:q.role,group:q.group_name,"
         "user:q.username,expires:q.expires_at,expired:q.expired})}catch(e){return 'ERR '+e}})()")

# 结构性判据：模态 display 不为 none，**或** LD 按钮在 DOM 中已可见
MODAL_OPEN_JS = f"""(()=>{{
  const m=document.querySelector('{SEL_AUTH_MODAL}');
  const vis=m?getComputedStyle(m).display!=='none':false;
  const b=document.querySelector('{SEL_LD_BUTTON}');
  const br=b?b.getBoundingClientRect():null;
  const bvis=!!(br&&br.width>8&&br.height>8);
  return JSON.stringify({{modal:vis,ld:bvis}});
}})()"""

LD_RECT_JS = f"""(()=>{{const b=document.querySelector('{SEL_LD_BUTTON}');
  if(!b) return 'NONE';const r=b.getBoundingClientRect();
  return JSON.stringify({{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),
    t:(b.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30)}});}})()"""

ENTRY_RECT_JS = f"""(()=>{{const b=document.querySelector('{SEL_LOGIN_ENTRY}');
  if(!b) return 'NONE';const r=b.getBoundingClientRect();
  if(r.width<8) return 'NONE';
  return JSON.stringify({{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),
    t:(b.innerText||'').trim().slice(0,20)}});}})()"""

AUTH_BTN_JS = f"""(()=>{{const re=new RegExp({json.dumps(AUTH_TEXT_RE)});
  const es=[...document.querySelectorAll('button,a,input[type=submit],[role=button]')].filter(e=>{{
    const r=e.getBoundingClientRect();return r.width>8&&r.height>8;}});
  for(const e of es){{const t=(e.innerText||e.value||'').trim().replace(/\\s+/g,' ');
    if(re.test(t)){{const r=e.getBoundingClientRect();
      return JSON.stringify({{t:t,x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}});}}}}
  return 'NONE';}})()"""


ME_RAW_JS = ("(async()=>{try{const r=await fetch('/api.php?action=me',{credentials:'same-origin'});"
             "const t=await r.text();return JSON.stringify({s:r.status,b:t.slice(0,2000)});}"
             "catch(e){return JSON.stringify({s:0,b:'FETCH_ERR '+e})}})()")

# CF 挑战特征（页面标题 / 响应体）
CF_TITLE_MARKERS = ("請稍候", "请稍候", "Just a moment", "Checking your browser", "Attention Required")
CF_BODY_MARKERS = ("Just a moment", "<!DOCTYPE html", "cf-challenge", "cf_chl", "cloudflare")


def _looks_like_cf(title, body):
    t = str(title or "")
    b = str(body or "")
    return any(m in t for m in CF_TITLE_MARKERS) or any(m in b for m in CF_BODY_MARKERS)


async def read_me_raw(ws):
    """返回 (http_status, body_text)。用于区分「真会话」与「CF 403 挑战页」。
    2026-10-09 加：CF 挡 XHR 时页面 DOM 可能正常但 /api.php 返回 403 HTML，
    此时若把 role=None 当 guest 去重走 OAuth，会白点且更招 CF。"""
    try:
        d = json.loads(await js(ws, ME_RAW_JS) or "{}")
        return int(d.get("s") or 0), str(d.get("b") or "")
    except Exception:
        return 0, ""


def unwrap_me(body):
    """把 /api.php?action=me 的信封剥成扁平 dict。
    ⚠ 响应是 {"code":200,"msg":"OK","result":{...role...}}，role 在 result 里。
    2026-10-09 踩坑：改成读原始响应后忘了剥 result，导致 role 恒为 None →
    被误判「未登录/CF」，白跑多轮。
    """
    try:
        j = json.loads(body)
    except Exception:
        return {}
    res = j.get("result") if isinstance(j, dict) else None
    if not isinstance(res, dict):
        return {}
    return {"role": res.get("role"), "group": res.get("group_name") or res.get("group"),
            "user": res.get("username") or "", "expires": res.get("expires_at"),
            "expired": res.get("expired"), "caps": res.get("capabilities") or [],
            "trading_date": res.get("trading_date")}


async def read_me(ws):
    st, body = await read_me_raw(ws)
    if st != 200:
        return {}
    return unwrap_me(body)


async def role_of(ws):
    return (await read_me(ws)).get("role")


# ---------------- 登录主流程 ----------------

async def ensure_login(force=False, want_vip=True):
    """返回 exit code：0=vip，2=非 vip，3=guest，1=异常"""
    if not G.cdp_alive(PORT):
        print(f"[0] {PORT} 离线 → 拉起自动化 Chrome")
        if not G.boot_auto_profile():
            print("[FAIL] 自动化 Chrome 拉不起来（若已有该 profile 的窗口在跑但无调试端口，先关掉它再试）")
            return 1
        await asyncio.sleep(3)

    ws = await websockets.connect(quant_ws(), max_size=64 * 1024 * 1024, open_timeout=10)
    try:

        # [0] 归位：上一轮可能把标签页停在 linux.do 授权页（被中断 / 人工接管留下的），
        #     此时 /api.php?action=me 读不到，页面里也没有本站的登录按钮 → 会误判成
        #     「未登录」而重走 OAuth。先把当前页拉回量化站，保证脚本幂等。
        #     （2026-10-09 由 `--force` 实测暴露：标签页停在授权页 → 全流程扑空）
        cur = await js(ws, "location.href") or ""
        if not is_quant(cur):
            print(f"[0] 当前页不在量化站（{str(cur)[:80]}）→ 归位导航")
            await G.navigate(quant_ws(), QUANT_URL)
            await asyncio.sleep(6)
        print(f"[1] 量化站：{await js(ws, 'document.title')} | {await js(ws, 'location.href')}")

        # 先等 CF 放行 + 会话可读（2026-10-09 修两处）：
        #   ① 原顺序是「先读 me → 再等 CF」：刚拉起窗口时页面还在 CF 挑战页
        #      （title「請稍候...」），/api.php?action=me 返回 403 HTML → role=None
        #      → 被误判成「未登录」而去点登录按钮，白跑一轮。
        #   ② 更要紧：CF 挡 XHR 时页面 DOM 可能是正常的，但 API 一律 403。
        #      此时**绝不能**当 guest 去重走 OAuth —— 既白点，又更招 CF 加严。
        #      改为显式识别挑战（status=403 / title 或 body 含 CF 特征）并耐心等。
        #      （2026-10-09 实测：连续多轮自动化后站点加严，API 403 + title 請稍候）
        me = {}
        cf_hits = 0
        for i in range(60):          # 预算 ~180s：CF 有时要一两分钟才放行
            st, body = await read_me_raw(ws)
            title = str(await js(ws, "document.title") or "")
            if st == 200:
                try:
                    me = unwrap_me(body)
                except Exception:
                    me = {}
                if me.get("role"):
                    break
            if st == 403 or _looks_like_cf(title, body):
                cf_hits += 1
                if i % 5 == 0:
                    print(f"[2.{i}] CF 挑战中（status={st} title={title[:26]}）…等放行")
            elif i % 5 == 0:
                print(f"[2.{i}] status={st} title={title[:26]} role={(me or {}).get('role')}")
            await asyncio.sleep(3)
        print(f"[2] 会话：role={me.get('role')} group={me.get('group')} "
              f"user={me.get('user') or '-'} expired={me.get('expired')} cf_hits={cf_hits}")

        if not me.get("role"):
            if cf_hits >= 3:
                print("[!] Cloudflare 挑战未放行（API 403）→ 不重走 OAuth（白点且更招 CF）。"
                      " 稍后再试；若持续，请在该自动化窗口手工过一次挑战。")
            else:
                print("[!] 读不到 role（既非 vip 也非 guest，可能 CF/接口异常）→ 不贸然点登录。")
            return 1

        if me.get("role") == "vip" and not force:
            print("[OK] 已是 VIP，无需登录")
            return 0
        if me.get("role") and me.get("role") != "guest" and not force:
            print(f"[OK] 已登录（role={me.get('role')}）——非 VIP 由 --renew 续费处理")
            return 2

        # 起 OAuth：直接 JS 点 `#linuxdoLogin`（2026-10-09 二次修）
        #   为何不走「点入口 → 等模态 → 点 LD 按钮」三步：
        #   ① 模态可见性判据易随 UI 版本漂移（v3 就死在这上面）；
        #   ② 已登录时同一个位置按钮变成账号菜单（文案 "VIP 会员·HawChow"），
        #      点它只会展开菜单、永不开 `#authModal` ⇒ `--force` 必然失败（实测）。
        #   `#linuxdoLogin` 的 id 恒定、且**始终在 DOM 内**（父容器仅 display:none），
        #   直接触发其 click 处理器即可跳转 linux.do 授权页 —— 实测 2026-10-09 有效。
        #   保留原鼠标路径作兜底（万一将来改成非 click 触发）。
        started = False
        r = await js(ws, "(()=>{const b=document.getElementById('linuxdoLogin');"
                         "if(!b) return 'NONE'; b.click(); return 'clicked';})()")
        print(f"[3] JS 点 #linuxdoLogin：{r}")
        if r == "clicked":
            started = True
        if not started:
            print("[3] JS 点失败 → 回退鼠标路径（点入口 → 点 LD 按钮）")
            for attempt in range(4):
                st = await js(ws, MODAL_OPEN_JS)
                try:
                    d = json.loads(st)
                except Exception:
                    d = {"modal": False, "ld": False}
                if d.get("ld") or d.get("modal"):
                    break
                e = await js(ws, ENTRY_RECT_JS)
                print(f"[3.{attempt}] 登录入口：{e}")
                if e not in ("NONE", None) and not str(e).startswith("JS_ERR"):
                    ee = json.loads(e)
                    await click(ws, ee["x"], ee["y"])
                await asyncio.sleep(2.0)
            ld = await js(ws, LD_RECT_JS)
            print(f"[3] LD 按钮：{ld}")
            if ld in ("NONE", None):
                await shot(ws, "_tmp_gushi_login_v4_nold.png")
                print("[3] 找不到 LD 按钮 → 截图 _tmp_gushi_login_v4_nold.png")
                return 3
            dd = json.loads(ld)
            await click(ws, dd["x"], dd["y"])
            started = True
        await asyncio.sleep(3)

        # linux.do 授权页（**同标签页跳转**，需跟着 ws 走）
        approved = False
        for i in range(18):
            cur_ws = quant_ws()
            w2 = await websockets.connect(cur_ws, max_size=64 * 1024 * 1024, open_timeout=10)
            try:
                url = await js(w2, "location.href") or ""
                title = await js(w2, "document.title") or ""
                if i % 3 == 0:
                    print(f"[5.{i}] {str(url)[:100]} | {str(title)[:40]}")
                if "linux.do" in str(url):
                    b = await js(w2, AUTH_BTN_JS)
                    if b not in ("NONE", None):
                        bb = json.loads(b)
                        print(f"[5.{i}] 点授权：{bb}")
                        await click(w2, bb["x"], bb["y"])
                        approved = True
                        break  # 点过就跳出，避免重复点击/重复授权
                    if i % 3 == 0:
                        print(f"[5.{i}] linux.do 上暂无授权按钮（多半还在过 CF 挑战）…")
                if is_quant(url):
                    r = await role_of(w2)
                    if r and r != "guest":
                        print(f"[5.{i}] 已回站且 role={r}")
                        break
            finally:
                await w2.close()
            await asyncio.sleep(2)
        if approved:
            await asyncio.sleep(2)

        # 轮询确认
        final = {}
        for i in range(15):
            await asyncio.sleep(2)
            w3 = await websockets.connect(quant_ws(), max_size=64 * 1024 * 1024, open_timeout=10)
            try:
                final = await read_me(w3)
                print(f"[6.{i}] role={final.get('role')} group={final.get('group')} user={final.get('user') or '-'}")
                if final.get("role") and final.get("role") != "guest":
                    await shot(w3, "_tmp_gushi_login_v4_ok.png")
                    break
            finally:
                await w3.close()

        r = final.get("role")
        if r == "vip":
            print("[OK] 登录完成：VIP")
            return 0
        if r and r != "guest":
            print(f"[OK] 登录完成：role={r}（非 VIP，数据会脱敏；用 --renew 续 VIP）")
            return 2
        await shot(ws, "_tmp_gushi_login_v4_final.png")
        print("[!] 仍是 guest → 看截图 _tmp_gushi_login_v4_final.png")
        return 3
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只查登录态，不点任何东西")
    ap.add_argument("--force", action="store_true", help="无视当前态，重走 OAuth")
    ap.add_argument("--keep-open", action="store_true", help="结束后不关自动化窗口")
    a = ap.parse_args()

    if a.check:
        if not G.cdp_alive(PORT):
            print(f"[check] {PORT} 离线（量化站窗口未开）")
            sys.exit(3)
        async def _chk():
            ws = await websockets.connect(quant_ws(), max_size=64 * 1024 * 1024, open_timeout=10)
            try:
                st, body = await read_me_raw(ws)
                title = str(await js(ws, "document.title") or "")
                return st, body, title
            finally:
                await ws.close()
        st, body, title = asyncio.run(_chk())
        if st != 200 and (st == 403 or _looks_like_cf(title, body)):
            print(f"[check] Cloudflare 挑战中（status={st} title={title[:30]}）→ 会话读不到，"
                  f"不代表未登录")
            sys.exit(1)
        try:
            me = unwrap_me(body) if st == 200 else {}
        except Exception:
            me = {}
        print(f"[check] status={st} role={me.get('role')} group={me.get('group')} "
              f"user={me.get('user') or '-'} expired={me.get('expired')}")
        sys.exit(0 if me.get("role") == "vip" else (2 if me.get("role") and me.get("role") != "guest" else 3))

    launched = not G.cdp_alive(PORT)
    try:
        rc = asyncio.run(ensure_login(force=a.force))
    except Exception as e:
        print(f"[FAIL] 登录脚本异常：{type(e).__name__}: {str(e)[:200]}")
        rc = 1
    if launched and not a.keep_open:
        G.close_auto_profile()
    sys.exit(rc)


if __name__ == "__main__":
    main()
