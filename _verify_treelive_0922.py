# -*- coding: utf-8 -*-
"""盘中实时层（#4b）浏览器实测 —— R-treelive-0922
用法: python _verify_treelive_0922.py
流程: 拉起自动化 Chrome(9223) → 新建标签打开线上看板 → 等加载 → 求值校验 JS → 关标签+关窗
"""
import asyncio
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

import websockets

BASE = Path(__file__).resolve().parent
sp = importlib.util.spec_from_file_location("gdc", BASE / "backtest" / "gushi_daily_collect.py")
gdc = importlib.util.module_from_spec(sp)
sys.modules["gdc"] = gdc
sp.loader.exec_module(gdc)

import time as _t
URL = "https://hawchou1995.github.io/quant-weight-system/index.html?cb=%d" % int(_t.time())
JS = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = {};
  out.title = document.title;
  out.hasINTRADAY = typeof window.INTRADAY;
  const pill = document.getElementById('live-pill');
  out.pill = !!pill;
  out.pillText = pill ? (pill.innerText || '').replace(/\s+/g, ' ').trim() : null;
  if (window.INTRADAY) {
    out.quiet = {
      t_0900: window.INTRADAY.chainQuiet(new Date('2026-09-22T09:00:00')),
      t_1030: window.INTRADAY.chainQuiet(new Date('2026-09-22T10:30:00')),
      t_1504: window.INTRADAY.chainQuiet(new Date('2026-09-22T15:04:00')),
      t_1505: window.INTRADAY.chainQuiet(new Date('2026-09-22T15:05:00')),
      t_1530: window.INTRADAY.chainQuiet(new Date('2026-09-22T15:30:00')),
      t_1645: window.INTRADAY.chainQuiet(new Date('2026-09-22T16:45:00')),
      t_1646: window.INTRADAY.chainQuiet(new Date('2026-09-22T16:46:00')),
      now:    window.INTRADAY.chainQuiet()
    };
  }
  out.hmChart = !!document.getElementById('hm-chart');
  /* 字段对拍断言：heatmap 的 m/f 应与腾讯 [45]/[44] 一致（长鑫科技 688825 两值不同，能判别） */
  try {
    const g = ((window.HEATMAP.tree.find(x => x.name === '电子') || {}).children || [])
                .find(x => x.c === '688825') || {};
    const r = await fetch('https://qt.gtimg.cn/q=sh688825');
    const txt = new TextDecoder('gbk').decode(await r.arrayBuffer());
    const f = txt.split('="')[1].split('~');
    out.fieldCheck = { code: '688825',
      hm_m: g.m, hm_f: g.f, hm_a: g.a,
      tx45: f[45], tx44: f[44], tx37_亿: (parseFloat(f[37]) / 1e4),
      m_ok: String(g.m) === String(f[45]), f_ok: String(g.f) === String(f[44]) };
  } catch (e) { out.fieldCheck = { err: String(e && e.message || e) }; }
  const H = window.HEATMAP;
  out.heatmap = { has: typeof H, keys: H ? Object.keys(H) : null,
                  treeLen: (H && H.tree) ? H.tree.length : null,
                  g0: (H && H.tree && H.tree[0]) ? { name: H.tree[0].name,
                        ch: (H.tree[0].children || []).length,
                        first: (H.tree[0].children || [])[0] || null } : null };
  out.jsVer = { newFetchMarket: document.documentElement.innerHTML.indexOf('treeSrc') >= 0,
                tencentPrimary: document.documentElement.innerHTML.indexOf('fetchMarketTx') >= 0 };
  try {
    const r = await fetch('https://qt.gtimg.cn/q=sh600000,sz000001');
    const b = await r.arrayBuffer();
    const txt = new TextDecoder('gbk').decode(b);
    out.txDirect = { status: r.status, len: txt.length, head: txt.slice(0, 70) };
  } catch (e) { out.txDirect = { err: String(e && e.message || e) }; }
  const v = document.getElementById('view-kxmm');
  out.kxmmActive = !!(v && v.classList.contains('active'));
  if (window.INTRADAY) {
    const t0 = Date.now();
    const r = await window.INTRADAY.refresh(true);
    out.refreshMs = Date.now() - t0;
    out.refreshRet = r;
    await sleep(1500);
    const S = window.INTRADAY.state;
    out.state = { live: S.live, ts: S.ts, patched: S.patched, err: S.err,
                  lastTreeSet: !!S.lastTree, idx: S.idx };
    const note = document.getElementById('hm-live');
    out.hmLiveNote = note ? note.textContent : null;
    out.highlightCells = document.querySelectorAll('td.live-cell').length;
  }
  return out;
})()
"""


def new_tab(port, url):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def close_tab(port, tid):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=5).read()
    except Exception:
        pass


async def eval_js(ws_url, js):
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=15) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                if "exceptionDetails" in m.get("result", {}):
                    return {"__JS_ERROR__": json.dumps(m["result"]["exceptionDetails"], ensure_ascii=False)[:900]}
                return m.get("result", {}).get("result", {}).get("value")


def main():
    port = gdc.AUTO_PORT
    launched = False
    if not gdc.cdp_alive(port):
        print("[boot] 拉起自动化 Chrome …")
        launched = gdc.boot_auto_profile()
        if not launched:
            print("[FAIL] 拉起失败"); return 1
    else:
        print("[boot] 自动化 Chrome 已在运行")
    t = new_tab(port, URL)
    tid = t.get("id")
    print(f"[tab] 新标签 {tid}")
    try:
        print("[wait] 等页面加载 …")
        time.sleep(12)
        res = asyncio.run(eval_js(t["webSocketDebuggerUrl"], JS))
        print("\n===== 实测结果 =====")
        print(json.dumps(res, ensure_ascii=False, indent=1))
    finally:
        close_tab(port, tid)
        print("[cleanup] 已关标签")
        if launched:
            gdc.close_auto_profile()
    return 0


if __name__ == "__main__":
    sys.exit(main())
