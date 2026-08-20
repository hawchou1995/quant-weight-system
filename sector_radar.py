# -*- coding: utf-8 -*-
"""板块强度雷达（2026-08-20 新增 · 纯观察层，不入主策略/主池）
================================================================
聚合：今日涨停股按行业聚类 → 统计各行业"涨停家数/涨幅占比/资金" → 标出板块启动。
数据源：
  1. limit_up_follow.json（当日涨停股，含 industry 标注）
  2. westock 板块行情（可选，--sector-data 注入申万板块指数涨幅）
输出 sector_radar.json 供看板「🧭 板块强度雷达（观察）」卡片渲染。
规则：
  - 板块热度 = 涨停家数占比加权 + 首板/连板家数
  - 热度 ≥ 3 家涨停 或 涨停家数占该行业成分 > 5% → 标「🔥 板块启动」
说明：观察层只做"提示哪个板块在发酵"，不构成买入指令。
"""
import os, json, sys
from pathlib import Path
from collections import Counter, defaultdict

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None, help="信号日 YYYY-MM-DD")
    ap.add_argument("--quotes", default=None, help="盘中 quotes（已跑 limit_up_follow 时忽略）")
    args = ap.parse_args()

    # 1) 读取涨停跟随结果（先跑过 limit_up_follow.py 生成 limit_up_follow.json）
    lu_path = BASE / "limit_up_follow.json"
    if not lu_path.exists():
        print("⚠ 缺 limit_up_follow.json，先运行 limit_up_follow.py")
        return
    lu = json.load(open(lu_path, encoding="utf-8"))
    items = lu.get("items", [])
    as_of = lu.get("as_of", args.day or "—")
    print(f"涨停回溯 {len(items)} 只（{as_of}）", flush=True)

    # 2) 按行业聚类（limit_up_follow 已用统一行业池标注；兜底不再落「综合」）
    by_ind = defaultdict(list)
    for it in items:
        ind = it.get("industry") or "其他"
        if ind == "综合":
            ind = "其他"
        by_ind[ind].append(it)

    # 3) 板块热度计算
    sectors = []
    for ind, lst in by_ind.items():
        n = len(lst)
        limit_counts = Counter(it.get("code") for it in lst)
        n2 = sum(1 for it in lst if it.get("streak", 1) >= 2)   # 连板
        total_pct = sum(it.get("chg", 0) for it in lst)
        avg_pct = round(total_pct / n, 1) if n else 0
        hot = "🔥 板块启动" if (n >= 3 or n2 >= 2) else ("⚠ 发酵中" if n >= 2 else "关注")
        sectors.append({
            "industry": ind, "limit_up": n, "streak2": n2,
            "avg_pct": avg_pct, "hot": hot,
            "members": [{"code": x["code"], "name": x["name"], "chg": x["chg"], "board": x["board"]} for x in lst],
        })
    sectors.sort(key=lambda x: (-x["limit_up"], -x["avg_pct"]))
    print("板块聚类:", flush=True)
    for s in sectors[:12]:
        print(f"  {s['industry']:<8} 涨停{s['limit_up']} 连板{s['streak2']} 均涨+{s['avg_pct']}% {s['hot']}")

    # 4) 可选的申万板块指数涨幅注入（--sector-data json: code->chg）
    idx_gain = {}
    if os.path.exists(str(BASE / "sector_idx_gain.json")):
        try:
            idx_gain = json.load(open(BASE / "sector_idx_gain.json", encoding="utf-8"))
        except Exception:
            pass

    out = {"as_of": as_of,
           "note": "板块强度雷达（观察层）：涨停家数聚类标度板块热度；🔥=板块启动（≥3家涨停或≥2连板）。仅提示板块发酵，非买入指令；T+1 参与需看次日开盘（高开>3% 不追）。",
           "sectors": sectors, "idx_gain": idx_gain}
    with open(BASE / "sector_radar.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n已写 sector_radar.json（{len(sectors)} 个板块）")

if __name__ == "__main__":
    main()
