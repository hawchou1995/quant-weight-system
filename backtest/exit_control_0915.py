# -*- coding: utf-8 -*-
"""pct40 生产上线 · 对照账本（control：同一持仓、不做 pct40 出场）
对照语义：生产 paper = 含 pct40 出场；本账本 = 复刻同一批成交但忽略 pct40 卖出（只随调仓换仓）。
每日记录：paper 净值 vs control 净值 + 累计差异（评估 pct40 的实时增量）。
同步规则：读取 satellite_paper.json 的 fills，应用除 reason=='pct40' 外的所有成交（买/卖）。
状态：backtest/exit_control_state.json
"""
import json, time
from pathlib import Path
import numpy as np, pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
HERE = BASE / "backtest"
PAPER = HERE / "satellite_paper.json"
STATE = HERE / "exit_control_state.json"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

def px_of(code):
    for c in (code, "sh" + code, "sz" + code, "bj" + code):
        f = BASE / "data_full" / f"{c}.csv"
        if f.exists():
            d = pd.read_csv(f, dtype={"date": str}).sort_values("date")
            return {r.date: (float(r.open), float(r.close)) for r in d.itertuples()}
    return {}

def main():
    paper = json.loads(PAPER.read_text(encoding="utf-8"))
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else dict(
        created=str(pd.Timestamp.today().date()), note="pct40 生产上线对照账本（无出场）",
        tracks={}, last_fill_idx=0, nav=[])
    n_applied = 0
    fills = paper.get("fills") or []
    for f in fills[st["last_fill_idx"]:]:
        tk = f.get("track"); reason = f.get("reason", "")
        s = st["tracks"].setdefault(tk, dict(init_cash=float((paper.get("meta") or {}).get(
            "cash_a" if tk == "track_a" else "cash_b", 0.0)), cash=0.0, held={}, skipped_pct40=0, armed=False))
        if not s["armed"]:
            s["cash"] = s["init_cash"]; s["armed"] = True
        if reason == "pct40":
            s["skipped_pct40"] += 1                     # 对照：忽略 pct40 卖出
            n_applied += 1
            continue
        code = f["code"]; sh = float(f.get("shares") or 0); amt = float(f.get("amount") or 0)
        if f.get("side") == "buy":
            if code not in s["held"]:
                s["held"][code] = dict(shares=sh, cost=float(f.get("px") or 0)); s["cash"] -= amt
        else:                                            # 非 pct40 的卖出（调仓）
            if code in s["held"]:
                s["cash"] += amt; s["held"].pop(code, None)
        n_applied += 1
    st["last_fill_idx"] = len(fills)
    # 净值（收盘 mark）
    last = max((max(px_of(c).keys()) for c in (paper.get('positions') or {}).get('track_b', {}) if px_of(c)), default=None)
    rows = []
    for tk, s in st["tracks"].items():
        mv = 0.0
        for code, h in s["held"].items():
            pxd = px_of(code)
            if pxd:
                dts = sorted(pxd.keys()); mv += h["shares"] * pxd[dts[-1]][1]
                last = max(last or dts[-1], dts[-1])
        nav = s["cash"] + mv
        paper_nav = None
        for row in reversed(paper.get("nav_history", [])):
            if tk in row: paper_nav = row[tk]; break
        rows.append(dict(date=last, track=tk, control=round(nav, 2), paper=paper_nav,
                         n_held=len(s["held"]), skipped_pct40=s["skipped_pct40"]))
        log(f"{tk}: 对照持仓 {len(s['held'])} | 忽略pct40卖出 {s['skipped_pct40']} 次 | 对照净值 {nav:.2f} vs paper {paper_nav}")
    st["nav"] = (st["nav"] + rows)[-600:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    log(f"state -> {STATE.name} | 新应用成交 {n_applied} 笔 | nav rows {len(st['nav'])}")

if __name__ == "__main__":
    main()
