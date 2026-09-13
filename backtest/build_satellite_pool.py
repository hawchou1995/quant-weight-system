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
CAP_A, CAP_B = 34000, 34000


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
held_b = set((_st.get("a4d", {}) or {}).get("holdings", {}).keys())
held_c = set((_st.get("track_c", {}) or {}).get("holdings", {}).keys())

# ---- 轨 A：冷门低波（ln_amt20+atr20）----
src = open(HERE / "signal_satellite_0913.py", encoding="utf-8").read().split("def main()")[0]
src = src.replace('BASE = Path(__file__).resolve().parents[1]', f'BASE = Path(r"{BASE}")')
g = {"__file__": str(HERE / "signal_satellite_0913.py")}
exec(src, g)
px, LAST_DAY = g["px"], g["LAST_DAY"]
all_days = sorted({d for p in px.values() for d in p.index})

ln_top, ln_df = g["signal_ln_atr"]({})
ln_top = [c for c in ln_top if c not in TUI_SET]
n_a = max(1, len(ln_top))
df_a = ln_df.set_index("code")
amt_pct = 1 - df_a["amt20"].rank(pct=True)   # 低成交额=高分位
atr_pct = 1 - df_a["atr20"].rank(pct=True)   # 低波动=高分位
ln_rows = []
for c in ln_top:
    r = df_a.loc[c]
    d = px[c].tail(1).iloc[0]
    p_amt = round(50 * amt_pct[c], 1); p_atr = round(50 * atr_pct[c], 1)
    sc = round(p_amt + p_atr, 1)
    ln_rows.append({
        "code": c, "name": nm(c), "industry": rd(c),
        "close": round(float(d["close"]), 2), "lot": round(float(d["close"]) * 100),
        "score_txt": f"{sc:.0f}", "score": sc,
        "parts": f"额 {p_amt:.0f} · 波 {p_atr:.0f}（各 0-50）",
        "detail": f"额分位{amt_pct[c]:.0%}·波分位{atr_pct[c]:.0%}（双低合分越高越冷门低波）",
        "amount": round(CAP_A / n_a),
        "action": "持有" if c in held_a else "新建仓",
    })

# ---- 轨 B：A4D（r6b 原引擎 icir 6 因子）----
src_b = open(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py", encoding="utf-8").read().split("if __name__")[0]
gb = {"__file__": str(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py")}
exec(src_b, gb)
di = gb["ND"] - 1
sc_row = gb["COMP_A4"][di]
ok = np.where(np.isfinite(sc_row) & gb["ELIG_A4"][di])[0]
ok = sorted(ok, key=lambda j: -sc_row[j])
ok = [j for j in ok if gb["codes"][j] not in ST_SET and gb["codes"][j] not in TUI_SET][:20]
prev = gb["close_m"][di - 1]
picked, SIGN, W, FD, ELIG = gb["picked"], gb["SIGN"], gb["W"], gb["FD"], gb["ELIG_A4"]
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
    _lbl = {"amount20": "额", "size_rev": "市反", "amp20": "振", "ret60": "动60", "bp": "BP", "size_ep": "EP"}
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
        "weight_pct": round(100 / n_c, 1), "amount": round(0.6 * 170000 / n_c),
        "action": "持有" if c in held_c else "申购",
    })

out = {
    "asof": str(LAST_DAY.date()),
    "track_a": {
        "name": "冷门低波 ln_amt20+atr20 Top10",
        "ranking": "排序=双低合分降序（低成交额分位+低波动分位各半，0-100）",
        "rebal": "每 60 个交易日",
        "next_rebal_in_days": int(60 - (all_days.index(LAST_DAY) % 60)),
        "bt": {"total": 127.4, "ann": 16.2, "mdd": -18.4, "sharpe": 1.238,
               "note": "安慰剂500 p=0.0000 · 与FB3相关-0.165 · slip50稳健 · 已排除退市整理期\"退\"（回测零成本；全排ST减收益7.3pp故保留ST）"},
        "rows": ln_rows,
    },
    "track_b": {
        "name": "A4D icir6因子 Top20",
        "ranking": "排序=icir 加权复合分降序（amount20/size_rev/amp20/ret60/bp/size_ep，权重=ICIR 归一，符号=IC 方向）",
        "rebal": "月频（rebal=20 · offset 0）",
        "next_rebal": "每月调仓窗",
        "bt": {"total": 114.2, "ann": 15.1, "mdd": -18.3, "sharpe": 1.074,
               "note": "相位中位1.075 · 安慰剂500 p=0.000 · DSR 0.987 · 已过滤 ST/*ST/退（回测 +3.2pp/回撤 -2.5pp/相位一致改善）"},
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
