# -*- coding: utf-8 -*-
"""全量池因子缓存重建（R-v8cache-0921 · 2026-09-21 用户批准接进日链）
================================================================================
为什么需要这一步
----------------
`v8_factor_cache.pkl` 是**派生缓存**（源 = data_full/*.csv 预计算因子），但**从不在日链里**：

    v9_auto.py:14       pool_all = V.load_pool()      ← import 时就读缓存
    build_enhanced_data.py:265   pool_all = A.pool_all
    review_daily.py:31  import build_enhanced_data as E   ← 导入即执行

→ 缓存一冻，`enhanced_data.js` 的 `meta.as_of` 就冻，**看板页面标题「数据截至 X」**
  和中长线池的股价/评分一起停住。

实测事故（2026-09-21）：缓存停在 09-15，线上标题写「数据截至 2026-09-18」，
而全市场数据其实已到 09-21 —— 用户报「看板还是旧的」。

语义与守卫
----------
- 跳过条件：sidecar `v8_factor_cache.meta.json` 的 `as_of` ≥ 当日交易日 → 直接跳过（幂等，正常日 0 成本）
- 落盘守卫：重算结果的末行最大日期 < 现有 as_of → **拒绝落盘**（防 data_full 回退时把缓存写坏）
- 原子替换：先写 `.pkl.new` 再 `os.replace` → 不会出现半截缓存被下游读到
- 标量守卫：标的数 < 1000 → 拒绝落盘
- 重算走 `V.load_pool(use_cache=False)`。⚠ 该分支**不写盘**（源码 `if use_cache: pd.to_pickle(...)`
  只在加载路径成立），落盘必须由本脚本显式完成 —— 2026-09-21 踩过一次「算完 1.6 分钟没落盘」。

代价：5394 只 / 约 1.6 分钟 / 约 1.33 GB（实测 2026-09-21，M3 Air）。

用法：
    python backtest/rebuild_v8cache.py            # 陈旧才重建；已最新则跳过
    python backtest/rebuild_v8cache.py --force    # 强制重建（写 sidecar）
    python backtest/rebuild_v8cache.py --dry      # 只判断，不落盘
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
CACHE = BASE / "v8_factor_cache.pkl"
META = BASE / "v8_factor_cache.meta.json"
CAL = BASE / "index_000300.csv"

MIN_STOCKS = 1000          # 标的数下限（低于此判为异常，拒绝落盘）


def trade_day():
    """交易日 = index_000300.csv 末行日期（与全链同一口径）"""
    idx = pd.read_csv(CAL, dtype={"date": str})
    return str(idx["date"].iloc[-1])


def load_meta():
    if not META.exists():
        return {}
    try:
        return json.loads(META.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    force = "--force" in sys.argv
    dry = "--dry" in sys.argv

    if not CAL.exists():
        print("!! index_000300.csv 不存在 —— 中止")
        return 1
    day = trade_day()
    meta = load_meta()
    have = str(meta.get("as_of") or "")

    if not force and CACHE.exists() and have >= day:
        print(f"v8 因子缓存已最新（as_of {have} ≥ 交易日 {day}）→ 跳过")
        return 0

    print(f"v8 因子缓存需重建：现有 as_of {have or '（无 sidecar）'} < 交易日 {day}")
    if dry:
        print("[dry] 未落盘。")
        return 0

    sys.path.insert(0, str(BASE))
    t0 = time.time()
    import v8_selector as V
    d = V.load_pool(use_cache=False)          # ⚠ 该分支不写盘，落盘见下

    if len(d) < MIN_STOCKS:
        print(f"!! 标的数异常 {len(d)} < {MIN_STOCKS} → 拒绝落盘（旧缓存保持不动）")
        return 2
    mx = max(str(v.index[-1].date()) for v in d.values())
    if have and mx < have:
        print(f"!! 重算末行最大 {mx} < 现有 as_of {have}（data_full 可能在回退）→ 拒绝落盘")
        return 2
    if mx < day:
        # 不拒绝：把「能拿到的」落盘，sidecar 如实记 mx → 次日仍会重试（自愈），
        # 而不是继续拿一个更旧的缓存去渲染看板。
        print(f"⚠ 重算末行最大 {mx} < 交易日 {day}（data_full 未补齐）——仍落盘并如实记 as_of={mx}，次日自动重试")

    tmp = CACHE.with_suffix(".pkl.new")
    pd.to_pickle(d, tmp)
    os.replace(tmp, CACHE)                    # 原子替换
    META.write_text(json.dumps({
        "as_of": mx, "n": len(d), "trade_day": day,
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "minutes": round((time.time() - t0) / 60, 2),
        "source": "data_full/*.csv 预计算（v8_selector.load_pool(use_cache=False)）",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    size = os.path.getsize(CACHE) / 1e9
    print(f"== v8 因子缓存重建完成：{len(d)} 只 / 末行 {mx} / {(time.time()-t0)/60:.1f} 分钟 "
          f"/ {size:.3f} GB → {CACHE.name}（sidecar {META.name}）==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
