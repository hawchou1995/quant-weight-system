#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""connector_mx.py —— 东方财富妙想（MX）金融数据接口 · 可复用调用脚本

三条端点（均来自官方 skill 包源码，非臆造；apikey 头鉴权）：
  /finskillshub/api/claw/query        —— 数据查询    body {"toolQuery": "..."}   （mx-data）
  /finskillshub/api/claw/stock-screen  —— 智能选股    body {"keyword": "..."}     （mx-xuangu）
  /finskillshub/api/claw/news-search  —— 资讯/研报检索 body {"query": "..."}      （mx-search）
依据：官方《东方财富妙想Skills安装指南》https://marketing.dfcfw.com/res/download/A620260623NIYC2U.md
      及 A620260331IHX67H.zip / A620260623PHDKPP.zip / A620260331K5WDTK.zip 内脚本
鉴权：请求头 `apikey: <MX_APIKEY>`（key 见 connector-keys.json → eastmoney_miaoxiang.key）
规范：限速 >=0.3s、重试 <=2、结果落 D:/Tools/cache/connectors/mx/

注意：WorkBuddy 侧的 MCP 端点 https://mxapi.eastmoney.com/mxds/v2/mcp 走 OAuth2（401），
      与 apikey 版 claw/* 不是同一条链路；本脚本走官方 skill 的 apikey 直连（实测三条全通）。

用法：
    python connector_mx.py query  "贵州茅台近5日涨跌幅"
    python connector_mx.py screen "创业板市盈率最低的10只股票"
    python connector_mx.py news   "半导体设备 研报"
"""
import json
import sys
import time

import requests

sys.path.insert(0, "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
from connector_mcp import load_key, save_json  # noqa: E402

NAME = "mx"
BASE = "https://mkapi2.dfcfs.com/finskillshub/api/claw"
MIN_INTERVAL = 0.35
BODY_FIELD = {"query": "toolQuery", "screen": "keyword", "news": "query"}


def _key():
    k = load_key("eastmoney_miaoxiang")
    if not k:
        raise SystemExit("[ERROR] connector-keys.json 缺少 eastmoney_miaoxiang.key")
    return k


def _post(kind: str, payload_text: str, retries: int = 2):
    """kind ∈ {query, screen, news}；限速 0.35s、重试 <=2"""
    key = _key()
    url = f"{BASE}/{'stock-screen' if kind == 'screen' else kind + '-search' if kind == 'news' else 'query'}"
    body = {BODY_FIELD[kind]: payload_text}
    last = None
    for attempt in range(retries + 1):
        time.sleep(MIN_INTERVAL)
        try:
            r = requests.post(url, headers={"Content-Type": "application/json", "apikey": key},
                              json=body, timeout=40)
            if r.status_code == 401:
                return {"ok": False, "http": 401, "message": "apikey 无效/未授权（HTTP 401）"}
            j = r.json()
            ok = bool(j.get("success")) and j.get("status") == 0
            last = {"ok": ok, "http": r.status_code, "message": j.get("message"), "raw": j}
            if ok:
                save_json(NAME, kind, {"input": payload_text, "resp": j})
                return last
        except Exception as e:  # noqa: BLE001
            last = {"ok": False, "http": -1, "message": f"{type(e).__name__}: {e}"}
        time.sleep(0.6 * (attempt + 1))
    return last or {"ok": False, "message": "unknown"}


def query(tool_query: str, retries: int = 2):
    return _post("query", tool_query, retries)


def screen(keyword: str, retries: int = 2):
    return _post("screen", keyword, retries)


def news(q: str, retries: int = 2):
    return _post("news", q, retries)


def summarize(res: dict, limit_chars: int = 2500) -> str:
    """把 dataTableDTOList 压成可读表格"""
    if not res.get("ok"):
        return f"[FAIL] http={res.get('http')} message={res.get('message')}"
    j = res["raw"]
    dto_list = ((((j.get("data") or {}).get("data") or {})
                 .get("searchDataResultDTO") or {}).get("dataTableDTOList")) or []
    lines = []
    for dto in dto_list[:3]:
        ent = dto.get("entityName") or dto.get("title") or ""
        table = dto.get("table") or {}
        name_map = dto.get("nameMap") or {}
        head = table.get("headName") or []
        lines.append(f"[{ent}]")
        for k, v in table.items():
            if k == "headName":
                continue
            label = name_map.get(k, k)
            vals = v if isinstance(v, list) else [v]
            lines.append(f"  {label}: {vals[:5]}  (head={head[:3]})")
    return "\n".join(lines)[:limit_chars]


def summarize_screen(res: dict, limit_chars: int = 2000) -> str:
    if not res.get("ok"):
        return f"[FAIL] http={res.get('http')} message={res.get('message')}"
    inner = ((res["raw"].get("data") or {}).get("data") or {})
    rows = ((inner.get("allResults") or {}).get("result") or {}).get("dataList") or []
    cols = ((inner.get("allResults") or {}).get("result") or {}).get("columns") or []
    name_by_key = {c.get("key"): c.get("title") for c in cols if isinstance(c, dict)}
    lines = [f"rows={len(rows)}"]
    for row in rows[:10]:
        pick = {name_by_key.get(k, k): v for k, v in row.items()
                if k in ("SECURITY_CODE", "SECURITY_SHORT_NAME", "NEWEST_PRICE", "CHG", "PCHG")}
        lines.append(json.dumps(pick or row, ensure_ascii=False)[:220])
    return "\n".join(lines)[:limit_chars]


def summarize_news(res: dict, limit_chars: int = 2500) -> str:
    if not res.get("ok"):
        return f"[FAIL] http={res.get('http')} message={res.get('message')}"
    items = (((res["raw"].get("data") or {}).get("data") or {})
             .get("llmSearchResponse") or {}).get("data") or []
    lines = [f"items={len(items)}"]
    for it in items[:8]:
        lines.append(f"- [{it.get('informationType')}] {it.get('date')} {it.get('insName','')} "
                     f"{it.get('title','')[:80]}")
    return "\n".join(lines)[:limit_chars]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    kind, text = sys.argv[1], sys.argv[2]
    fn = {"query": query, "screen": screen, "news": news}.get(kind)
    if not fn:
        print(__doc__)
        sys.exit(1)
    res = fn(text)
    if "--raw" in sys.argv:
        print(json.dumps(res.get("raw"), ensure_ascii=False)[:6000])
    else:
        print({"query": summarize, "screen": summarize_screen, "news": summarize_news}[kind](res))

