# -*- coding: utf-8 -*-
"""双卫星目标持仓 json 生成器 v2（供 build_dual_system 渲染 sys-auto 卡片）
新增（2026-09-13 用户要求）：名称/行业、评分与拆解（排序键透明化）、加减仓操作、计划金额、排序说明
输出：backtest/satellite_pool.json"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

NAMES = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
ST_SET = set(_name[_name.str.contains("ST")].index)
IND = json.load(open(BASE / "stock_industry.json", encoding="utf-8"))["map"]
PAPER = HERE / "holdings_satellite.json"
CAP_A, CAP_B = 17000, 51000  # 2026-09-14 拍板：轨A 25% / 轨B 75%


def nm(code):
    return NAMES.get("sh" + code, NAMES.get("sz" + code, NAMES.get(code, code)))


def rd(code):
    return IND.get(code, "—")


# 当前持仓（模拟盘状态，未建仓则空）
try:
    _st = json.load(open(PAPER, encoding="utf-8"))
except Exception:
    _st = {}
held_a = set((_st.get("ln_atr", {}) or {}).get("holdings", {}).keys())
held_b = set((_st.get("super", _st.get("a4d", {})) or {}).get("holdings", {}).keys())
held_c = set((_st.get("track_c", {}) or {}).get("holdings", {}).keys())

# ---- 轨 A：冷门低波（ln_amt20+atr20）----
src = open(HERE / "signal_satellite_0913.py", encoding="utf-8").read().split("def main()")[0]
src = src.replace('BASE = Path(__file__).resolve().parents[1]', f'BASE = Path(r"{BASE}")')
g = {"__file__": str(HERE / "signal_satellite_0913.py")}
exec(src, g)
px, LAST_DAY = g["px"], g["LAST_DAY"]
all_days = sorted({d for p in px.values() for d in p.index})

ln_top, ln_df, ln_gate = g["signal_turn_gate"]({})
ln_top = [c for c in ln_top if c not in TUI_SET]
n_a = max(1, len(ln_top))
df_a = ln_df.set_index("code")
amt_pct = 1 - df_a["amt20"].rank(pct=True)   # 低成交额=高分位
atr_pct = 1 - df_a["atr20"].rank(pct=True)   # 低波动=高分位
turn_pct = 1 - df_a["turn20"].rank(pct=True) # 低换手=高分位
ln_rows = []
for c in ln_top:
    r = df_a.loc[c]
    d = px[c].tail(1).iloc[0]
    p_amt = round(33.3 * amt_pct[c], 1); p_atr = round(33.3 * atr_pct[c], 1); p_turn = round(33.4 * turn_pct[c], 1)
    sc = round(p_amt + p_atr + p_turn, 1)
    ln_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(float(d["close"]), 2), "lot": round(float(d["close"]) * 100),
        "score_txt": f"{sc:.0f}", "score": sc,
        "parts": f"额 {p_amt:.0f} · 波 {p_atr:.0f} · 换 {p_turn:.0f}（各 0-33.3）",
        "detail": f"额分位{amt_pct[c]:.0%}·波分位{atr_pct[c]:.0%}·换手分位{turn_pct[c]:.0%}（三低合分越高越冷门低波低换手）",
        "amount": round(CAP_A / n_a),
        "action": "持有" if c in held_a else "新建仓",
    })

# ---- 轨 B：A4D（r6b 原引擎 icir 6 因子）----
src_b = open(HERE / "oss_0913" / "oss_super_prod_0913.py", encoding="utf-8").read()
gb = {"__file__": str(HERE / "oss_0913" / "oss_super_prod_0913.py")}
exec(src_b, gb)
di = gb["ND"] - 1
sc_row = gb["COMP_SUPER"][di]
ok = np.where(np.isfinite(sc_row) & gb["ELIG_SUPER"][di])[0]
ok = sorted(ok, key=lambda j: -sc_row[j])
ok = [j for j in ok if gb["codes"][j] not in ST_SET and gb["codes"][j] not in TUI_SET][:20]
prev = gb["close_m"][di - 1]
picked, SIGN, W, FD, ELIG = gb["PICKED"], gb["SIGN"], gb["WEIGHTS"], gb["ALL"], gb["ELIG_SUPER"]
mask = ELIG[di]
# 逐因子 z 与贡献（复刻 r6b composite）
zmap = {}
for k in picked:
    row = FD[k][di].astype(np.float64) * SIGN[k]
    mu, sd = np.nanmean(row[mask]), np.nanstd(row[mask])
    z = np.clip((row - mu) / (sd if sd > 0 else 1), -3, 3)
    zmap[k] = z
n_b = max(1, len(ok))
a4_rows = []
for j in ok:
    c = gb["codes"][j]
    clse = float(gb["close_m"][di, j])
    guard = bool(np.isfinite(prev[j]) and clse >= prev[j] * 1.098)
    contrib = sorted(((k, float(zmap[k][j]) * W[k]) for k in picked), key=lambda x: -abs(x[1]))
    _lbl = {"amount20": "额", "size_rev": "市反", "amp20": "振", "ret60": "动60", "bp": "BP", "size_ep": "EP",
            "wy_ratio": "牛绳", "neg_sspace": "止损间", "neg_dbbi": "距BBI", "shrink": "缩量",
            "neg_j": "J低", "dd120": "回撤", "pspace": "压力间", "sqz_ratio": "挤压"}
    parts = " · ".join(f"{_lbl.get(k, k)} {v:+.2f}" for k, v in contrib)
    detail = "｜".join(f"{k} {v:+.2f}" for k, v in contrib[:3])
    a4_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(clse, 2), "lot": round(clse * 100),
        "score_txt": f"{sc_row[j]:.2f}", "score": round(float(sc_row[j]), 2),
        "parts": parts,
        "detail": f"icir复合分（z·权重：{detail}…）",
        "amount": round(CAP_B / n_b),
        "action": "持有" if c in held_b else "新建仓",
        "limit_guard": guard,
    })

# ---- 轨 C：FB3 基金池（生产口径 tiers 基金）----
sp = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
fund_tier = sp.get("tiers", {}).get("基金", []) or sp.get("tiers", {}).get("fund", [])
det = sp.get("details", {})
mg = sp.get("market_gate", {})
n_c = max(1, len(fund_tier))
fb3_rows = []
for c in fund_tier:
    d = det.get(c, {})
    fb3_rows.append({
        "code": c, "name": d.get("name", ""), "score_txt": str(d.get("score", "—")),
        "chg": d.get("chg"), "ret_1y": d.get("ret_1y"),
        "weight_pct": round(100 / n_c, 1), "amount": round(0.6 * 170000 / n_c),
        "action": "持有" if c in held_c else "申购",
    })


# ---- 行级指标（2026-09-14 看板新增列）：涨跌幅/近一年/RSI14/MACD柱/KDJ-J ----
def _ind(code):
    try:
        d = px.get(code)
        if d is None or len(d) < 30:
            return {}
        c = d["close"]
        chg = float(c.iloc[-1] / c.iloc[-2] - 1) * 100 if len(c) > 1 else None
        ret1y = float(c.iloc[-1] / c.iloc[-252] - 1) * 100 if len(c) > 252 else None
        delta = c.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        dn = (-delta).clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = float(100 - 100 / (1 + up.iloc[-1] / (dn.iloc[-1] if dn.iloc[-1] > 0 else np.nan)))
        e12 = c.ewm(span=12, adjust=False).mean(); e26 = c.ewm(span=26, adjust=False).mean()
        dif = e12 - e26; dea = dif.ewm(span=9, adjust=False).mean()
        macd = float(dif.iloc[-1] - dea.iloc[-1])
        lo9 = d["low"].rolling(9, min_periods=5).min(); hi9 = d["high"].rolling(9, min_periods=5).max()
        rsv = (c - lo9) / (hi9 - lo9).replace(0, np.nan) * 100
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean(); dd = k.ewm(alpha=1 / 3, adjust=False).mean()
        jj = float(3 * k.iloc[-1] - 2 * dd.iloc[-1])
        return dict(chg=round(chg, 2) if chg is not None else None, ret_1y=round(ret1y, 2) if ret1y is not None else None,
                    rsi14=round(rsi, 1) if np.isfinite(rsi) else None, macd_hist=round(macd, 3),
                    kdj_j=round(jj, 1) if np.isfinite(jj) else None)
    except Exception:
        return {}


def _fund_ind(code):
    """轨C 基金行级指标（2026-09-14 看板新增列）：NAV 序列算 涨跌幅/近1年/RSI14/MACD柱/KDJ-J"""
    try:
        f = BASE / "fund_nav_cache" / f"{code}.csv"
        if not f.exists():
            return {}
        df = pd.read_csv(f, encoding="utf-8-sig")
        nav = pd.to_numeric(df["单位净值"], errors="coerce").dropna().reset_index(drop=True)
        if len(nav) < 30:
            return {}
        chg = float(nav.iloc[-1] / nav.iloc[-2] - 1) * 100 if len(nav) > 1 else None
        ret1y = float(nav.iloc[-1] / nav.iloc[-252] - 1) * 100 if len(nav) > 252 else None
        delta = nav.diff()
        up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        dn = (-delta).clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = float(100 - 100 / (1 + up.iloc[-1] / (dn.iloc[-1] if dn.iloc[-1] > 0 else np.nan)))
        e12 = nav.ewm(span=12, adjust=False).mean(); e26 = nav.ewm(span=26, adjust=False).mean()
        dif = e12 - e26; dea = dif.ewm(span=9, adjust=False).mean()
        macd = float(dif.iloc[-1] - dea.iloc[-1])
        lo9 = nav.rolling(9, min_periods=5).min(); hi9 = nav.rolling(9, min_periods=5).max()
        rsv = (nav - lo9) / (hi9 - lo9).replace(0, np.nan) * 100
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean(); dd = k.ewm(alpha=1 / 3, adjust=False).mean()
        jj = float(3 * k.iloc[-1] - 2 * dd.iloc[-1])
        return dict(chg=round(chg, 2) if chg is not None else None, ret_1y=round(ret1y, 2) if ret1y is not None else None,
                    rsi14=round(rsi, 1) if np.isfinite(rsi) else None, macd_hist=round(macd, 3),
                    kdj_j=round(jj, 1) if np.isfinite(jj) else None)
    except Exception:
        return {}


for _rows in (ln_rows, a4_rows):
    for _r in _rows:
        _r.update(_ind(_r["code"]))
for _r in fb3_rows:
    _r.update(_fund_ind(_r["code"]))
out = {
    "asof": str(LAST_DAY.date()),
    "track_a": {
        "name": "冷门低波 ln_amt20+atr20+turn20 Top20（闸门半仓）",
        "ranking": "排序=三低合分降序（低成交额/低波动/低换手分位各 1/3，0-100）；闸门：中证1000ETF 破 MA20 → 半仓 Top10",
        "rebal": "每 30 个交易日（闸门联动）",
        "next_rebal_in_days": int(30 - (all_days.index(LAST_DAY) % 30)),
        "bt": {"phmed_sharpe": 0.827, "ann": 11.79, "mdd": -16.47, "sharpe_off0": 0.959, "note": "turn+gate N20/F30 · 30 相位中位 · 1M 容量中性口径（2026-09-14 拍板升级；旧口径数字不可复现已作废）· +pct40 出场后 phmed 1.090/年化 16.30%/回撤 −16.0%（轨A pct40 待启用）", "total": 82.99, "sharpe": 0.959},
        "rows": ln_rows,
    },
    "track_b": {
        "name": "SUPER 13因子 Top20（2026-09-13 替换 A4D）",
        "ranking": "排序=13 因子 ICIR 加权复合分降序（amount20/size_rev/neg_sspace/wy_ratio/amp20/size_ep/bp/shrink/neg_dbbi/dd120/neg_j/pspace/sqz_ratio，权重冻结自 super_combo_0913.json）",
        "rebal": "月频（rebal=20 · offset 0）",
        "next_rebal": "每月调仓窗",
        "bt": {"total": 22.87, "ann": 22.87, "mdd": -22.0, "sharpe": 1.30,
               "note": "相位中位 S 1.151 / 年化 19.61% · 20 相位最小 0.706 · 安慰剂500 p=0.000 · 50bp 压力档 S 1.00 · 100万对照 S 1.30 · 已过滤 ST/退（继承 A4D 过滤口径）"},
        "rows": a4_rows,
    },
    "track_c": {
        "name": "FB3-H20 基金主仓",
        "ranking": "排序=基金动量分降序（牛市 Top10 动量 / 熊市 Top3 低波，生产口径 build_short_pool）",
        "regime": "牛市 Top10 动量" if mg.get("open") else "熊市 Top3 低波防守",
        "asof": sp.get("as_of"),
        "gate": mg.get("open"),
        "rows": fb3_rows,
    },
}
json.dump(out, open(HERE / "satellite_pool.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"[satellite_pool v2] asof {out['asof']} | 轨A {len(ln_rows)} 只 | 轨B {len(a4_rows)} 只 | 轨C {len(fb3_rows)} 只")
print("轨A 样例:", {k: ln_rows[0][k] for k in ("code", "name", "industry", "score_txt", "action")})
print("轨B 样例:", {k: a4_rows[0][k] for k in ("code", "name", "industry", "score_txt", "action")})
