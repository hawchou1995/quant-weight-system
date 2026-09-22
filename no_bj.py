# -*- coding: utf-8 -*-
"""北交所（bj*）硬闸 —— 池产物断言（R-no-bj-0923，2026-09-23）

背景：2026-09-18 用户拍板「**不做北交所**」（data_full/bj*.csv 保留不删、update_daily
`--include-bj` 语义不变，只做**下游**过滤）。2026-09-23 批准的「移除北交所」计划要求把
「过滤」升级为**可失败的构建期断言**：任何池产物里出现北交所代码 → 立即 raise（构建中止，
不许静默出池）。

口径（两层，任一层命中即 raise）：
  ① 前缀层：字符串形如 ``bj\\d{6}`` —— 北交所原始代码，零误判；
  ② 裸码层：6 位裸码落在北交所号段 ``43/83/87/88/920``（实测 data_full/bj*.csv 342 只
     全部是 920xxx），并**排除基金代码集合**（fund_nav_cache / data_hist / fund_list.csv，
     例如 880006 是场外基金不是北交所 —— 2026-09-23 实测 11 只 8xxxxx 基金）。
     ⚠ 裸码层只作用于「结构化代码位置」（键名 code/codes 等、以及 code→payload 的字典键），
     不做全文正则，避免金额/数量等 6 位数字误伤。

用法（构建期，**写盘前**）::

    from no_bj import assert_clean
    assert_clean(payload, "short_pool.json")   # 命中即 RuntimeError，构建中止

只读：本模块不写任何文件、不改数据。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

BJ_RE = re.compile(r"\bbj\d{6}\b", re.I)          # 前缀层（零误判）
CODE_RE = re.compile(r"^(?:bj|sh|sz)?\d{6}$", re.I)
# 裸码层：43/83/87/88 = 4+2 位（老号段）；920 = 3+3 位（实测 data_full/bj*.csv 342 只全为 920xxx）
# 注：88xxxx 与场外基金同号（880006 等 9 只）→ 由 fund_codes() 排除，避免误判成北交所
BARE_BSE_RE = re.compile(r"^(?:(?:43|83|87|88)\d{4}|920\d{3})$")
# 结构化代码位置：这些键的值（str 或 list[str]）视为代码；
# 另：形如 sh600345 / 300014 / bj920006 的**字典键**同样视为代码（details/track 的常见形态）
CODE_KEYS = {"code", "codes", "symbol", "sbl", "ts_code", "stock_code"}

_FUND_CACHE: set[str] | None = None


def fund_codes() -> set[str]:
    """基金代码集合（6 位）—— 用于排除「8xxxxx 是基金不是北交所」这类误判。惰性缓存。"""
    global _FUND_CACHE
    if _FUND_CACHE is not None:
        return _FUND_CACHE
    s: set[str] = set()
    for sub in ("fund_nav_cache", "data_hist"):
        d = BASE / sub
        if d.is_dir():
            for f in d.glob("*.csv"):
                c = f.stem
                if len(c) == 6 and c.isdigit():
                    s.add(c)
    fl = BASE / "fund_list.csv"
    if fl.exists():
        try:
            import csv as _csv
            with open(fl, encoding="utf-8") as fh:
                for row in _csv.DictReader(fh):
                    for k in ("code", "基金代码", "fund_code"):
                        v = str(row.get(k) or "").strip()
                        if len(v) == 6 and v.isdigit():
                            s.add(v)
        except Exception:
            pass
    _FUND_CACHE = s
    return s


def is_bj(code, fund: set[str] | None = None) -> bool:
    """单个代码是否北交所。code 可带 sh/sz/bj 前缀，也可为 6 位裸码。"""
    c = str(code or "").strip().lower()
    if not c:
        return False
    if c.startswith("bj") and len(c) == 8 and c[2:].isdigit():
        return True
    if c.startswith(("sh", "sz")):
        return False
    if not (len(c) == 6 and c.isdigit()):
        return False
    if not BARE_BSE_RE.match(c):
        return False
    return c not in (fund if fund is not None else fund_codes())


def collect_codes(obj, out: set[str] | None = None) -> set[str]:
    """递归收集结构化代码位置（不收集任意数字串）。"""
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if CODE_KEYS & {ks.lower()}:
                if isinstance(v, str):
                    out.add(v.strip())
                elif isinstance(v, (list, tuple, set)):
                    out.update(str(x).strip() for x in v if isinstance(x, (str, int)))
            if CODE_RE.match(ks):
                out.add(ks.strip())
            collect_codes(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            if isinstance(v, str) and CODE_RE.match(v.strip()):
                out.add(v.strip())
            else:
                collect_codes(v, out)
    return out


def bj_hits(obj) -> list[str]:
    """返回该 payload 命中的北交所代码（已排序去重）。obj 可为 dict / list / str / Path。"""
    if isinstance(obj, Path):
        obj = obj.read_text(encoding="utf-8", errors="replace")
    if isinstance(obj, str):
        pre = sorted({m.group(0) for m in BJ_RE.finditer(obj)}, key=str.lower)
        bare = [c for c in collect_codes(_try_json(obj)) if is_bj(c)]
        return sorted(set(pre) | set(bare), key=str.lower)
    fund = fund_codes()
    return sorted({c for c in collect_codes(obj) if is_bj(c, fund)}, key=str.lower)


def _try_json(s: str):
    """产物文本 → 结构（.json / window.X = {...}; 两种形态都能解）。"""
    t = s.strip()
    if t.startswith("window.") and "=" in t:
        t = t.split("=", 1)[1].strip().rstrip(";")
    try:
        return json.loads(t)
    except Exception:
        return {}


def assert_clean(obj, where: str) -> None:
    """池产物断言：命中北交所代码即 raise（构建期中止，不静默）。"""
    hits = bj_hits(obj)
    if hits:
        raise RuntimeError(
            "[no_bj] %s 出现北交所代码 %d 个：%s —— 北交所已从宇宙移除（2026-09-18 拍板），"
            "上游过滤失效，本步中止（不许静默出池）。" % (where, len(hits), hits[:20]))
    codes = collect_codes(obj) if not isinstance(obj, str) else set()
    print("  [no_bj] %s 断言通过：北交所命中 0（已检查代码 %d 个）" % (where, len(codes)))
