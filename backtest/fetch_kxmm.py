# -*- coding: utf-8 -*-
"""kxmm.online（开心檬檬）市场情绪数据抓取 —— 看板「市场情绪」卡数据源（R-kxmm-0917）

抓取（全部 HTTP Basic，凭据从 D:/Documents/Obsidian/personal/kxmm-auth.json 读，绝不入 git）：
  恐贪：  A股 base + 六大分项(1..6) + 14 市场对比历史 + 类型表
  徽章：  美股 mg-base / 黄金 gold-base / 主题 theme-scan + theme-base（非 stale 的）
  热力图：板块(industry/region/concept) + ETF + 股票（成交额 Top600 裁剪）

输出：REPO/kxmm_data.js（window.KXMM_DATA = {...}）+ 同步 DIST/kxmm_data.js
纪律：任一步失败**不覆盖**旧文件（保留上一份 → 看板继续显示旧数据+日期）；
      非交易日也能跑（数据日期由站点给，标注为"交易日"）。
用法：python backtest/fetch_kxmm.py [--dry]
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # quant-weight-system/
REPO = BASE
DIST = BASE.parent / "dist"
AUTH_FILE = Path(r"D:/Documents/Obsidian/personal/kxmm-auth.json")
OUT_JS = REPO / "kxmm_data.js"
SITE = "https://kxmm.online"
TIMEOUT = 40
RETRIES = 3

# 股票热力图裁剪：按成交额取 Top N（Q4 拍板）
STOCK_TOPN = 600

# ---- 保留字段（树图/下拉指标所需）----
STOCK_KEEP = ["code", "name", "pct", "amount", "amplitude", "turnover", "pct_60d", "pct_ytd",
              "volume_ratio", "total_mv", "float_mv", "main_inflow", "xl_inflow", "l_inflow",
              "m_inflow", "s_inflow", "total_shares", "float_shares", "industry"]
BOARD_KEEP = STOCK_KEEP[:-1] + ["up_count", "down_count", "flat_count", "limit_up", "limit_down",
                                "lead_stock"]
MONEY_KEYS = {"amount", "total_mv", "float_mv", "main_inflow", "xl_inflow", "l_inflow", "m_inflow",
              "s_inflow", "total_shares", "float_shares", "up_count", "down_count", "flat_count",
              "limit_up", "limit_down"}
RATIO_KEYS = {"pct", "amplitude", "turnover", "pct_60d", "pct_ytd", "volume_ratio"}


def _opener():
    """禁代理（本机代理会抖动；站点为国内直连）"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_auth():
    if not AUTH_FILE.exists():
        raise SystemExit(f"缺凭据文件 {AUTH_FILE}（应为 {{\"user\":..,\"password\":..}}）")
    d = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    return d["user"], d["password"]


def make_fetch(user, pwd):
    import base64
    auth = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
    op = _opener()

    def fetch(path):
        last = None
        for i in range(RETRIES):
            try:
                req = urllib.request.Request(SITE + path, headers={"Authorization": auth})
                with op.open(req, timeout=TIMEOUT) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:                     # noqa: BLE001
                last = e
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"抓取失败 {path}: {last}")

    return fetch


def _round_item(it, keep):
    out = {}
    for k in keep:
        v = it.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            if k in MONEY_KEYS:
                v = int(round(v))
            elif k in RATIO_KEYS:
                v = round(float(v), 2)
            else:
                v = round(float(v), 4)
        out[k] = v
    return out


def trim_board(d, kind):
    return {"kind": kind, "date": d.get("date"), "file_time": d.get("file_time"),
            "count": d.get("count"),
            "items": [_round_item(it, BOARD_KEEP) for it in d.get("items", [])]}


def trim_etf(d):
    return {"date": d.get("date"), "file_time": d.get("file_time"), "count": d.get("count"),
            "items": [_round_item(it, STOCK_KEEP[:-1]) for it in d.get("items", [])]}


def trim_stock(d):
    items = sorted(d.get("items", []), key=lambda x: x.get("amount") or 0, reverse=True)
    return {"date": d.get("date"), "file_time": d.get("file_time"), "count": d.get("count"),
            "shown": min(STOCK_TOPN, len(items)), "total_items": len(d.get("items", [])),
            "items": [_round_item(it, STOCK_KEEP) for it in items[:STOCK_TOPN]]}


def main():
    dry = "--dry" in sys.argv
    user, pwd = load_auth()
    fetch = make_fetch(user, pwd)
    t0 = time.time()
    out = {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "kxmm.online/kxmm-g"}

    # ---------- ① 恐贪 A股 ----------
    base = fetch("/api/fear-greed/base")["data"]
    types = fetch("/api/fear-greed/types")["data"]
    idx_list = fetch("/api/fear-greed/index-list")["data"]
    indicators = {}
    for t in types:
        tid = t["id"]
        try:
            d = fetch(f"/api/fear-greed/list?type_id={tid}")["data"]
            cd = d.get("canvas_data") or {}
            indicators[str(tid)] = {
                "title": d.get("title"), "status_name": d.get("status_name"),
                "status_html_name": d.get("status_html_name"),
                "status_color": d.get("status_color"), "desc": (d.get("desc") or "")[:600],
                "y_company": cd.get("y_company", ""),
                "series": [{"name": s.get("name"), "data": s.get("data", [])}
                           for s in cd.get("series", [])],
            }
        except Exception as e:                          # noqa: BLE001
            print(f"  [warn] 分项 type_id={tid} 抓取失败：{e}", flush=True)
    # 14 市场对比历史（近一年 242 点）
    markets = {}
    for m in idx_list:
        code = m.get("code")
        try:
            d = fetch(f"/api/fear-greed/market-history?market={code}")["data"]
            tb = d.get("tb_data") or {}
            markets[code] = {"name": m.get("name"), "update_time": d.get("update_time"),
                             "display": d.get("display"), "x_data": tb.get("x_data", []),
                             "series": [{"name": s.get("name"), "color": s.get("color"),
                                         "data": s.get("data", [])} for s in tb.get("series", [])],
                             "value_max": d.get("value_max"), "value_min": d.get("value_min"),
                             "close_max": d.get("close_max"), "close_min": d.get("close_min")}
        except Exception as e:                          # noqa: BLE001
            print(f"  [warn] 市场 {code} 历史抓取失败：{e}", flush=True)

    out["fear_greed"] = {
        "base": {k: base.get(k) for k in ("current_time", "num", "status_str", "status_color",
                                          "explain", "explain_sub")},
        "base_archives": [{"name": x.get("name"), "status_str": x.get("status_str"),
                           "status_color": x.get("status_color"),
                           "value": ((x.get("data") or {}).get("series") or [{}])[0].get("data")}
                          for x in base.get("list", [])],
        "types": [{"id": t["id"], "name": t["name"], "title": t["title"]} for t in types],
        "index_list": [{"code": m.get("code"), "name": m.get("name")} for m in idx_list],
        "indicators": indicators,
        "markets": markets,
    }

    # ---------- ② 七个徽章 ----------
    badges = []
    try:
        b = fetch("/api/fear-greed/base")["data"]
        badges.append({"key": "cn", "name": "A股恐贪", "num": b.get("num"),
                       "status": b.get("status_str"), "date": b.get("current_time"),
                       "color": b.get("status_color")})
    except Exception as e:                              # noqa: BLE001
        print(f"  [warn] A股徽章失败：{e}", flush=True)
    for key, name, ep in [("us", "美股恐贪", "/api/fear-greed/mg-base"),
                          ("gold", "黄金恐贪", "/api/fear-greed/gold-base")]:
        try:
            d = fetch(ep)["data"]
            badges.append({"key": key, "name": name, "num": d.get("num"),
                           "status": d.get("status_str"), "date": d.get("current_time"),
                           "color": d.get("status_color")})
        except Exception as e:                          # noqa: BLE001
            print(f"  [warn] {name}失败：{e}", flush=True)
    try:
        scan = fetch("/api/fear-greed/theme-scan")["data"]
        for t in scan:
            if t.get("stale"):
                continue
            kt = t.get("kt_type")
            status, color = "", ""
            try:
                tb = fetch(f"/api/fear-greed/theme-base?kt_type={kt}")["data"]
                status, color = tb.get("status_str"), tb.get("status_color")
            except Exception as e:                      # noqa: BLE001
                print(f"  [warn] theme kt={kt} base 失败：{e}", flush=True)
            badges.append({"key": f"kt{kt}", "name": t.get("name"), "num": t.get("latest_num"),
                           "status": status, "date": t.get("last_date"), "color": color,
                           "value_name": t.get("value_name")})
    except Exception as e:                              # noqa: BLE001
        print(f"  [warn] theme-scan 失败：{e}", flush=True)
    out["badges"] = badges

    # ---------- ③ 热力图 ----------
    heat = {}
    for kind in ("industry", "region", "concept"):
        d = fetch(f"/api/board-list?kind={kind}")
        heat[f"board_{kind}"] = trim_board(d, kind)
    heat["etf"] = trim_etf(fetch("/api/etf-list"))
    heat["stock"] = trim_stock(fetch("/api/stock-list"))
    out["heat"] = heat

    # ---------- 写出 ----------
    js_body = "window.KXMM_DATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";"
    size = len(js_body.encode("utf-8"))
    print(f"[kxmm] 抓取完成 {time.time()-t0:.0f}s，数据日期：恐贪 {out['fear_greed']['base']['current_time']} / "
          f"板块 {heat['board_industry']['date']} / 股票 {heat['stock']['date']}"
          f"（{heat['stock']['shown']}/{heat['stock']['total_items']} 只）")
    print(f"[kxmm] 徽章 {len(badges)} 个 | 六分项 {len(indicators)} 项 | 市场对比 {len(markets)} 个 | "
          f"输出 {size/1024/1024:.2f} MB")
    if dry:
        print("[kxmm] --dry：未写文件")
        return
    OUT_JS.write_text(js_body, encoding="utf-8")
    print(f"[kxmm] 已写 {OUT_JS}")
    if DIST.exists():
        (DIST / "kxmm_data.js").write_text(js_body, encoding="utf-8")
        print(f"[kxmm] 已同步 {DIST / 'kxmm_data.js'}")


if __name__ == "__main__":
    main()
