# -*- coding: utf-8 -*-
"""GitHub Actions 可行性探针（2026-08-28）
验证 4 条链路（全云化替代每日本地自动化的前置条件）：
  1. qt 行情 HTTP（qt.gtimg.cn）—— 海外 runner 可达性 + 数据新鲜度
  2. 腾讯 K 线 HTTP（web.ifzq.gtimg.cn）—— 海外可达性
  3. akshare 数据源（新浪实时快照 stock_zh_a_spot / 腾讯日线 stock_zh_a_hist_tx）
  4. schedule 触发（event_name 记录）+ 构建产物部署 gh-pages（由 workflow 完成）
输出 probe_report.json + out/probe.html
"""
import json, os, sys, time, traceback
from datetime import datetime, timezone

import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT_DIR, exist_ok=True)
rep = {"event_name": os.environ.get("GITHUB_EVENT_NAME", "local"),
       "runner": os.environ.get("RUNNER_OS", "unknown"),
       "ts_utc": datetime.now(timezone.utc).isoformat(),
       "tests": {}}


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def t(name, fn):
    t0 = time.time()
    try:
        res = fn()
        rep["tests"][name] = {"ok": True, "sec": round(time.time() - t0, 1), **res}
        print(f"[OK] {name} ({time.time()-t0:.1f}s) {res}", flush=True)
    except Exception as e:
        rep["tests"][name] = {"ok": False, "sec": round(time.time() - t0, 1), "err": str(e)[:300]}
        print(f"[FAIL] {name}: {str(e)[:200]}", flush=True)


# ---- Probe 1: qt 行情 ----
def p_qt():
    body = http_get("https://qt.gtimg.cn/q=sh600000")
    if "600000" not in body:
        raise RuntimeError("qt 响应无 sh600000 行情")
    # 解析关键字段：v_sh600000="1~浦发银行~600000~价格~..."
    fields = body.split("~")
    px = float(fields[3]) if len(fields) > 3 else 0.0
    return {"code": "sh600000", "name": fields[1] if len(fields) > 1 else "?", "px": px,
            "len": len(body)}


# ---- Probe 2: 腾讯 K 线 ----
def p_tx_kline():
    body = http_get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600000,day,,,5,qfq")
    d = json.loads(body)
    k = d.get("data", {}).get("sh600000", {}).get("qfqday") or d.get("data", {}).get("sh600000", {}).get("day")
    if not k:
        raise RuntimeError("腾讯 K 线响应无 qfqday")
    return {"rows": len(k), "last": k[-1]}


# ---- Probe 3a: akshare 新浪实时快照（全市场）----
def p_sina_spot():
    import akshare as ak
    df = ak.stock_zh_a_spot()
    return {"rows": int(len(df)), "cols": list(df.columns)[:6]}


# ---- Probe 3b: akshare 腾讯日线 ----
def p_tx_hist():
    import akshare as ak
    df = ak.stock_zh_a_hist_tx(symbol="sh600000", start_date="20260820", end_date="20260828")
    if len(df) == 0:
        raise RuntimeError("腾讯日线返回空")
    return {"rows": int(len(df)), "last_date": str(df.iloc[-1, 0]), "last_close": float(df.iloc[-1, 2])}


t("qt_quote", p_qt)
t("tx_kline", p_tx_kline)
t("ak_sina_spot", p_sina_spot)
t("ak_tx_hist", p_tx_hist)

with open(os.path.join(OUT_DIR, "probe_report.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

all_ok = all(v["ok"] for v in rep["tests"].values())
html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>Probe RT</title><style>body{{font-family:sans-serif;max-width:720px;margin:40px auto;}}
.ok{{color:#0a0;}} .fail{{color:#c00;}} table{{border-collapse:collapse;width:100%;}}
td,th{{border:1px solid #999;padding:6px 10px;text-align:left;}}</style></head><body>
<h2>GitHub Actions 实时化探针 · {rep["ts_utc"]}</h2>
<p>event={rep["event_name"]} · runner={rep["runner"]} · 结论：<b class="{'ok' if all_ok else 'fail'}">{'全部可达' if all_ok else '存在不可达项'}</b></p>
<table><tr><th>链路</th><th>状态</th><th>耗时</th><th>详情</th></tr>
{''.join(f'<tr><td>{k}</td><td class="{"ok" if v["ok"] else "fail"}">{"OK" if v["ok"] else "FAIL"}</td>'
         f'<td>{v.get("sec","-")}s</td><td>{json.dumps({kk: vv for kk, vv in v.items() if kk not in ("ok","sec")}, ensure_ascii=False)[:160]}</td></tr>'
         for k, v in rep["tests"].items())}
</table>
<p>部署链路：本页由 peaceiris/actions-gh-pages 推送到 gh-pages-probe 分支（验证部署机制，不触碰正式 gh-pages）。</p>
</body></html>"""
with open(os.path.join(OUT_DIR, "probe.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("SUMMARY:", json.dumps({k: v["ok"] for k, v in rep["tests"].items()}, ensure_ascii=False))
sys.exit(0 if all_ok else 1)
