# -*- coding: utf-8 -*-
"""口径对照视图（2026-08-18）：把线上看板 enhanced_data.js 的「池档位」与 data_full 的
「年线(MA200)偏离」汇集成对照表，供 9:30/14:30 早/尾盘监控生成飞书摘要时做
「监控分(短期强度) vs 池档位(收盘决策)」冲突标注。

背景：监控体系（行情监控/weight_score.py + monitor.py）与池信号体系
（quant-weight-system/enhanced_data.js 的 V.score）是两套独立评分，对同一标的可能相反：
  例：榕基软件 002474 → 监控 79.2 满仓加仓（20 日反弹强） vs 池 23.2 清仓（年线下方-19.8%）。
口径约定（写进 9:30/14:30 提示词）：
  · 监控数字 = 20 日短期强度（是"温度计"，不是操盘指令）
  · 池档位   = 回测验证、收盘口径的决策信号（加减仓/持有/清仓依据）
  · 冲突时以池档位为决策参考。

用法：python pool_decision_view.py [--out pool_decision.json]
只读：不修改 enhanced_data.js / data_full / 任何数据文件。
"""
import os, sys, json, re, datetime
import pandas as pd
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_FULL = Path(r"D:/Documents/Quant data/data_full")
ENH = BASE / "enhanced_data.js"


def load_enhanced():
    src = ENH.read_text(encoding="utf-8")
    m = re.search(r"window\.ENH\s*=\s*(.*);\s*$", src, re.S)
    if not m:
        raise SystemExit(f"❌ 无法解析 {ENH}")
    return json.loads(m.group(1))


def ma200_dev_of(code):
    """年线(MA200)偏离%（data_full 收盘口径）；基金/数据不足→None"""
    k = ("sh" if code.startswith(("6", "5")) else "sz") + code
    f = DATA_FULL / f"{k}.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        c = df["close"].astype(float)
        if len(c) < 200:
            return None
        px = float(c.iloc[-1])
        ma200 = float(c.rolling(200).mean().iloc[-1])
        if ma200 <= 0:
            return None
        return round((px / ma200 - 1) * 100, 1)
    except Exception:
        return None


def main():
    out = BASE / "pool_decision.json"
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    enh = load_enhanced()
    meta = enh.get("meta", {}) or {}
    details = enh.get("details", {}) or {}
    items = {}
    for code, d in details.items():
        dev = d.get("ma200_dev")
        if dev is None:
            dev = ma200_dev_of(code)
        items[code] = {
            "name": d.get("name"),
            "pool": d.get("pool"),
            "pool_score": d.get("score"),
            "pool_tier": d.get("tier"),
            "tier_prev": d.get("tier_prev") if d.get("tier_prev") is not None else None,
            "short_score": d.get("short_score"),
            "short_tier": d.get("short_tier"),
            "px": d.get("px"),
            "chg": d.get("chg"),
            "ret_1y": d.get("ret_1y"),
            "ma200_dev": dev,   # 年线偏离%（负=年线下方）
        }
    res = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "as_of": meta.get("as_of"),
        "intraday_note": meta.get("intraday") or meta.get("intraday_note"),
        "note": "enhanced_data.js 池档位（收盘口径，回测决策信号） + data_full 年线偏离。"
                "监控摘要的分数=20日短期强度（非操盘指令）；两口径冲突时以池档位为决策参考。",
        "items": items,
    }
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    n_below = sum(1 for v in items.values() if (v.get("ma200_dev") or 0) < 0)
    print(f"✅ {out.name}: {len(items)} 只 | 年线下方 {n_below} 只 | as_of={meta.get('as_of')}")
    # 打印几只年线下方样例便于人读
    shown = 0
    for code, v in sorted(items.items(), key=lambda kv: (kv[1].get("ma200_dev") or 0)):
        if (v.get("ma200_dev") or 0) < 0:
            print(f"   {code} {v['name']} 池={v['pool_tier']}({v['pool_score']}) 年线{v['ma200_dev']}%")
            shown += 1
            if shown >= 8:
                break


if __name__ == "__main__":
    main()
