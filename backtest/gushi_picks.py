# -*- coding: utf-8 -*-
"""gushi picks 统一读取器：合并 legacy 样本（picks_0913.jsonl）+ 每日累积样本（picks_daily.jsonl）

用法：
    from gushi_picks import load_picks
    picks = load_picks()                 # 全部（按 日期/类型/策略/代码 去重）
    picks = load_picks(since="2026-09-01")   # 只看某日之后
旧脚本（analyze_gushi_0913 / gushi_infer_step1）口径保持原样不动；新分析一律走这里，
这样每日采集累积出来的样本会自动进入后续推断与审计。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GD = HERE / "gushi_data"
FILES = ("picks_0913.jsonl", "picks_daily.jsonl")


def load_picks(since=None):
    seen, out = set(), []
    for name in FILES:
        p = GD / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if since and (r.get("date") or "") < since:
                continue
            key = (r.get("date"), r.get("kind"), r.get("strategy"), r.get("stock_code"))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


if __name__ == "__main__":
    ps = load_picks()
    days = sorted({p["date"] for p in ps})
    print(f"[gushi-picks] {len(ps)} 条 | 覆盖 {len(days)} 个交易日：{days[0]} … {days[-1]}")
    kinds = {}
    for p in ps:
        kinds[p.get("kind")] = kinds.get(p.get("kind"), 0) + 1
    print(f"  按类型：{kinds}")
