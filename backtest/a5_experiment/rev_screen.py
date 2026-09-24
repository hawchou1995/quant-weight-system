# -*- coding: utf8 -*-
"""rev_screen — A5 反向筛闸门（R-daban-negscreen-0919）

资产：`quant-weight-system/backtest/_tmp_0919_g52_block9.npz`
      （9 强臂回避集并集，kv 面板 2599×4087，2016-2026）
口径：臂信号日 s 起，该股在 [s, s+K+1] 回避；入场日 D 命中
      ⇔ ∃臂信号 s≤D-1 且 D-s≤K+1（只用已收盘数据，无前视）
作用面：只拦新开仓；在仓票按原规则出场
面板未覆盖（北交所/已退市/缺失）→ 不拦（保守，宁漏不错）

历史：R-g52negscreen-0919 影子对拍显示对 v1.3 双池剔 294/496 笔后，
      每笔 +0.768%→+1.774%、满仓年化 +4.12%→+6.94%、回撤 -48.63%→-36.81%、交易 393→163。
      本闸门不声称提升显著度，理由是"低换手+去弱标"的成本与回撤改善。

部署：本文件需要与扫描器同目录（或同 sys.path）。
      资产路径用绝对路径 + 多候选，本文件放任何位置都能定位到。
"""
import os
from datetime import date as _date
from pathlib import Path

import numpy as np

REV_SCREEN = os.environ.get("REV_SCREEN", "1") == "1"
_MASK_NAME = "_tmp_0919_g52_block9.npz"
_MASK_CANDIDATES = [
    Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest") / _MASK_NAME,
    Path(__file__).resolve().parent.parent / "backtest" / _MASK_NAME,
    Path(__file__).resolve().parent.parent.parent / "quant-weight-system" / "backtest" / _MASK_NAME,
    Path(__file__).resolve().parent / "backtest" / _MASK_NAME,
]
ARMS = ["g300", "g177a", "g093d", "g121a", "g83a", "g205g", "g93a", "g200b", "g134a"]
_cache = None


def _find_mask():
    env = os.environ.get("REV_SCREEN_MASK")
    if env and os.path.exists(env):
        return Path(env)
    for c in _MASK_CANDIDATES:
        if c.exists():
            return c
    return None


def _load():
    global _cache
    if _cache is None:
        path = _find_mask()
        if path is None:
            raise FileNotFoundError("找不到回避资产 %s" % _MASK_NAME)
        z = np.load(path, allow_pickle=True)
        bl = np.asarray(z["blocked"]).astype(bool)
        c2j = {str(c): j for j, c in enumerate(z["codes"])}
        d2i = {str(d): i for i, d in enumerate(z["cal"])}
        _cache = (bl, c2j, d2i, str(path))
    return _cache


def hit(code, date):
    """命中回避窗返回 True；面板未覆盖/读不到资产一律返回 False。"""
    if not REV_SCREEN:
        return False
    try:
        bl, c2j, d2i, _ = _load()
    except Exception:
        return False
    i = d2i.get(str(date))
    j = c2j.get(str(code))
    if i is None or j is None:
        return False
    try:
        return bool(bl[i, j])
    except Exception:
        return False


def mask_path():
    try:
        return _load()[3]
    except Exception as ex:
        return "MISSING: %s" % ex


def stats(date):
    """当日回避集规模（供日志用）。"""
    if not REV_SCREEN:
        return {"enabled": False}
    try:
        bl, c2j, d2i, _ = _load()
    except Exception as ex:
        return {"enabled": False, "error": str(ex)}
    i = d2i.get(str(date))
    if i is None:
        last = max(d2i.keys()) if d2i else "?"

        def _d(x):
            yy, mm, dd = str(x)[:10].split("-")
            return _date(int(yy), int(mm), int(dd))

        if not last or last == "?":
            gap = -1
        else:
            gap = (_d(str(date)) - _d(last)).days
        return {"enabled": True, "covered": False, "asked": str(date),
                "asset_last": last, "gap_days": int(gap),
                "stale": bool(gap > 0)}
    return {"enabled": True, "covered": True, "date": str(date),
            "avoided_symbols": int(bl[i].sum()), "universe": int(len(c2j))}
