# -*- coding: utf-8 -*-
"""pct40 出场影子轨 v2（修复：改用实时引擎，不再用冻结研究面板）
- 日期/价格：data_full 实时（LAST_DAY）
- 轨A 分位：复用 signal_satellite_0913.signal_ln_atr() 返回的全池 df["rk"]（低=好，升序分位>0.40 触发）
- 轨B 分位：复用 oss_super_prod_0913 的 COMP_SUPER（高分好，降序分位>0.40 触发）
状态：backtest/exit_shadow_state.json
"""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
HERE = BASE / "backtest"
STATE = HERE / "exit_shadow_state.json"
PAPER = HERE / "satellite_paper.json"
sys.path.insert(0, str(HERE))
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---- 实时引擎（exec signal_satellite 前缀：px 字典 + signal_ln_atr + signal_super）----
src = open(HERE / "signal_satellite_0913.py", encoding="utf-8").read().split("def main()")[0]
src = src.replace("BASE = Path(__file__).resolve().parents[1]", f'BASE = Path(r"{BASE}")')
G = {"__file__": str(HERE / "signal_satellite_0913.py")}
exec(src, G)
LAST_DAY = G.get("LAST_DAY")
log(f"实时引擎就绪 | LAST_DAY={LAST_DAY}")

def pct_track_a():
    top, df = G["signal_ln_atr"]({})
    df = df.set_index("code")
    return df["rk"].rank(pct=True).to_dict()          # 低=好 → 升序分位；>0.40 = 跌出前40%

def pct_track_b():
    prod = HERE / "oss_0913" / "oss_super_prod_0913.py"
    gg = {"__file__": str(prod)}
    exec(open(prod, encoding="utf-8").read(), gg)
    di = gg["ND"] - 1
    sc = gg["COMP_SUPER"][di]
    codes = gg["codes"]; elig = gg["ELIG_SUPER"][di]
    s = pd.Series(np.where(np.isfinite(sc) & elig, sc, np.nan), index=[str(c) for c in codes]).dropna()
    return (-s).rank(pct=True).to_dict()               # 高分好 → 降序分位；>0.40 = 跌出前40%

def px_of(code):
    for c in (code, "sh" + code, "sz" + code, "bj" + code):
        f = BASE / "data_full" / f"{c}.csv"
        if f.exists():
            d = pd.read_csv(f, dtype={"date": str}).sort_values("date")
            r = d.iloc[-1]
            return dict(date=r["date"], open=float(r["open"]), close=float(r["close"]))
    return None

paper = json.loads(PAPER.read_text(encoding="utf-8")) if PAPER.exists() else {}
st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else dict(
    created=str(pd.Timestamp.today().date()), note="pct40 出场影子轨 v2（实时引擎）", tracks={}, pending_exits={}, nav_history=[])
st["note"] = "pct40 出场影子轨 v2（实时引擎）"

PCT_FN = {"track_a": pct_track_a, "track_b": pct_track_b}
for tk, cash_key in [("track_a", "cash_a"), ("track_b", "cash_b")]:
    pos = (paper.get("positions") or {}).get(tk) or {}
    s = st["tracks"].setdefault(tk, dict(init_cash=34000.0, cash=34000.0, held={}, exits=[], armed=False))
    if not pos:
        log(f"{tk}: paper 未建仓——影子待命（等卫星盘建仓后自动起跑）")
        continue
    if not s["armed"]:
        s["init_cash"] = float((paper.get("meta") or {}).get(cash_key, 34000.0)); s["cash"] = s["init_cash"]; s["armed"] = True
    pct = PCT_FN[tk]()
    last = LAST_DAY
    pend = st["pending_exits"].setdefault(tk, [])
    for code in list(pend):
        p = px_of(code)
        if not p or p["date"] != last: continue
        h = s["held"].get(code)
        if not h: pend.remove(code); continue
        px = p["open"] * 0.998
        s["cash"] += px * h["shares"]
        s["exits"].append(dict(date=last, code=code, px=round(px, 3), reason="pct40", pct=round(h.get("trigger_pct") or float("nan"), 3)))
        s["held"].pop(code, None); pend.remove(code)
        log(f"  {tk} 影子出场 {code} @ {px:.2f}（pct40）")
    n_flag = 0
    for code in list(pos.keys()):
        v = pct.get(code)
        if v is None: continue
        if code not in s["held"]:
            pp = px_of(code)
            s["held"][code] = dict(shares=(pos[code].get("shares") or 0),
                                   entry_px=pos[code].get("cost") or (pp or {}).get("close"), trigger_pct=None)
        s["held"][code]["pct"] = round(float(v), 4)
        if v > 0.40:
            s["held"][code]["trigger_pct"] = float(v)
            if code not in pend: pend.append(code); n_flag += 1
    mv = 0.0
    for code, h in s["held"].items():
        p = px_of(code)
        if p: mv += h["shares"] * p["close"]
    nav = s["cash"] + mv
    paper_nav = None
    for row in reversed(paper.get("nav_history", [])):
        if tk in row: paper_nav = row[tk]; break
    rec = dict(date=last, track=tk, paper=paper_nav, shadow=round(nav, 2),
               n_flag_today=n_flag, n_pend=len(pend), n_held=len(s["held"]))
    nh = st["nav_history"]
    if nh and nh[-1].get("date") == last and nh[-1].get("track") == tk: nh[-1] = rec
    else: nh.append(rec)
    log(f"{tk}: 持仓 {len(s['held'])} | 今日触发 {n_flag} | 影子净值 {nav:.2f} vs paper {paper_nav}")

st["nav_history"] = st["nav_history"][-400:]
STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
log(f"state -> {STATE.name} | nav rows {len(st['nav_history'])}")
