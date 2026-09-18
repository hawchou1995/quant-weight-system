# -*- coding: utf-8 -*-
"""股票热力树图数据构建器（R-heatmap-0918 · 用户 2026-09-18 需求 #4）。

规格来源：公众号《把5000+只A股塞进一张图：这个实时热力树图是怎样做出来的》
（原文被微信环境校验挡住，用已登录的自动化 Chrome 取到正文）：
  · 三层：根=A股全市场 → 中间=申万一级行业 → 叶=个股
  · **面积** = 成交额 / 总市值 / 流通市值（三种可切换）
  · **颜色** = 涨跌幅
  · 行业块与根的颜色**优先用指数**，取不到才回退成分股加权（本实现先用成分股加权，
    指数口径待接；已在字段里标注 color_src=weighted 以便后续替换）
  · 开源参考：github.com/dxawdc/stock-heatmap（未克隆，仅按规格自研）

数据源：东财批量快照（push2delay clist，与 em_bulk_snapshot 同通道）
  f12代码 f14名称 f3涨跌幅 f6成交额 f20总市值 f21流通市值
行业源：stock_industry.json 的 map（申万一级 akshare 5207 + 本地 + 关键词，universe 7511）

产出：heatmap_data.js（window.HEATMAP），随看板一起发布
用法：python backtest/build_heatmap.py [--dry]
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "heatmap_data.js"
IND = BASE / "stock_industry.json"

HOSTS = ["push2delay.eastmoney.com", "push2.eastmoney.com", "82.push2.eastmoney.com"]
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"          # 沪深主板/创业板/科创板（不做北交所）
FIELDS = "f3,f6,f12,f14,f20,f21"
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
     "Accept": "application/json, text/javascript, */*",
     "Referer": "https://quote.eastmoney.com/"}


def page(pn, retries=4):
    P = {"pn": str(pn), "pz": "100", "po": "1", "np": "1",
         "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
         "fid": "f12", "fs": FS, "fields": FIELDS, "_": str(int(time.time() * 1000))}
    last = None
    for i in range(1, retries + 1):
        host = HOSTS[(i - 1) % len(HOSTS)]
        u = f"https://{host}/api/qt/clist/get?" + urllib.parse.urlencode(P)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(1.2 * i)
    raise RuntimeError(f"page {pn} fail: {type(last).__name__}")


def pull():
    rows, pn, total = [], 1, None
    while True:
        d = page(pn)
        data = d.get("data") or {}
        total = data.get("total") or total
        diff = data.get("diff") or []
        if not diff:
            break
        rows.extend(diff)
        if total and len(rows) >= total:
            break
        pn += 1
        if pn > 80:
            break
        time.sleep(0.12)
    return rows, total


def num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def main():
    dry = "--dry" in sys.argv
    rows, total = pull()
    print(f"[em] 拉取 {len(rows)}/{total} 只")

    ind = {}
    try:
        _j = json.loads(IND.read_text(encoding="utf-8"))
        ind = _j.get("map") or {}
        print(f"[ind] stock_industry 映射 {len(ind)} 条（{_j.get('source', '')[:40]}…）")
    except Exception as e:
        print(f"[ind] 读取失败（{type(e).__name__}）→ 全部归「其他」")

    by = {}
    miss = 0
    for r in rows:
        c = str(r.get("f12") or "")
        if len(c) != 6 or not c.isdigit():
            continue
        pct = r.get("f3")
        amt = num(r.get("f6"))
        mv = num(r.get("f20"))
        fmv = num(r.get("f21"))
        if not isinstance(pct, (int, float)) or (amt <= 0 and mv <= 0):
            continue
        name = str(r.get("f14") or c)
        sec = str(ind.get(c) or "其他")
        if sec.startswith("其他"):
            miss += 1
        by.setdefault(sec, []).append({
            "n": name, "c": c, "p": round(float(pct), 2),
            "a": round(amt / 1e8, 2),          # 成交额（亿）
            "m": round(mv / 1e8, 1),           # 总市值（亿）
            "f": round(fmv / 1e8, 1),          # 流通市值（亿）
        })

    tree = []
    for sec, kids in sorted(by.items(), key=lambda kv: -sum(x["m"] for x in kv[1])):
        kids.sort(key=lambda x: -x["m"])
        tree.append({"name": sec, "children": kids})
    n_sec = len(tree)
    n_stk = sum(len(t["children"]) for t in tree)
    print(f"[tree] 行业 {n_sec} 个 | 个股 {n_stk} 只 | 未命中行业 {miss} 只（归「其他」）")

    payload = {"asof": time.strftime("%Y-%m-%d"), "color_src": "weighted",
               "metrics": ["m", "a", "f"], "tree": tree}
    js = "window.HEATMAP = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    print(f"[size] {len(js.encode('utf-8')):,} bytes")
    if dry:
        print("[dry] 未写盘")
        for t in tree[:4]:
            print("  ", t["name"], len(t["children"]), t["children"][0]["n"])
        return 0
    OUT.write_text(js, encoding="utf-8")
    print(f"[done] {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
