# -*- coding: utf-8 -*-
"""黄金卫星叠加验证 v3（轻量：rB 引自存档净值，黄金腿按窗口首日开盘入场）
A 复算：卫星层/组合层/分半/安慰剂/黄金打折敏感性 —— 对拍 stage2 v0916 JSON 数字
B 可执行性审计：标的行情/整手/卫星额度/黄金 20d 动向
"""
import json, os, sys, time
import numpy as np, pandas as pd
np.seterr(all="ignore")
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__)); BASE = os.path.dirname(HERE)
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

ANN_BLEND = 244.0


def perf(r):
    r = pd.Series(r).dropna()
    eq = (1 + r).cumprod()
    ann = eq.iloc[-1] ** (244 / len(r)) - 1
    sh = r.mean() / r.std() * np.sqrt(244)
    dd = (eq / eq.cummax() - 1).min()
    return dict(ann_pct=round(float(ann) * 100, 2), sharpe=round(float(sh), 3), mdd_pct=round(float(dd) * 100, 1), n=len(r))


# ---- rB：优先 v0917 转储；否则 0913 存档（= v0916 口径，S1.297/mdd−22.0/ann22.74 已对拍）----
rb_src = os.path.join(HERE, "_rb_equity_0917.csv")
_rb_vintage = "v0917 转储"
if not os.path.exists(rb_src):
    rb_src = os.path.join(HERE, "oss_0913", "super_champion_equity_0913.csv")
    _rb_vintage = "0913 存档（=v0916 口径：22.74%/S1.297/回撤−22.0）"
_rbd = pd.read_csv(rb_src)
if "date" in _rbd.columns:
    rB = pd.Series(_rbd["value"].astype(float).to_numpy(), index=[str(x)[:10] for x in _rbd["date"]])
else:
    rB = pd.Series(_rbd.iloc[:, 1].astype(float).to_numpy(), index=[str(x)[:10] for x in _rbd.iloc[:, 0]])
rB = rB.pct_change().dropna()

# ---- FB3 / 黄金 行情 ----
fb3 = pd.read_csv(os.path.join(BASE, "short_v3_fund_slip20_equity.csv"), parse_dates=["date"]).set_index("date")["value"]
fb3.index = [str(d)[:10] for d in fb3.index]
rF_all = fb3.pct_change().dropna()
gpx = pd.read_csv(os.path.join(BASE, "data_full", "sh518880.csv"), parse_dates=["date"]).set_index("date")
gpx.index = [str(d)[:10] for d in gpx.index]

# ---- 对齐：公共日历；黄金按窗口首日开盘×1.002 入场 ----
I = sorted(set(rB.index) & set(rF_all.index) & set(gpx.index))
gw = gpx.reindex(I)
o0 = float(gw["open"].iloc[0]) * 1.002
eq_g = gw["close"].astype(float) / o0                      # 建仓即持有
gr = eq_g.pct_change().dropna()                            # 覆盖 I[1:]
tail = I[1:]
rb, rf, rg = rB.reindex(tail), rF_all.reindex(tail), gr.reindex(tail)
ok = rb.notna() & rf.notna() & rg.notna()
rb, rf, rg = rb[ok], rf[ok], rg[ok]
tw = list(rb.index)
gold_ann = (1 + rg).prod() ** (ANN_BLEND / len(rg)) - 1
log(f"[口径] rB={_rb_vintage} | 窗口 {tw[0]}→{tw[-1]}（{len(tw)}d）| 黄金入场 {o0:.4f}（含滑点）全窗年化 {gold_ann*100:.2f}%")

IDX = pd.to_datetime(tw)
RES = {"meta": {"ts": time.strftime("%Y-%m-%d %H:%M"), "rb_source": os.path.basename(rb_src), "rb_vintage": _rb_vintage,
                "method": "黄金腿=单资产 B&H（窗口首日开盘×1.002 入场，一次佣金 2.5bp 略）；FB3=生产净值 CSV",
                "window": [tw[0], tw[-1]], "n_days": len(tw), "gold_ann_pct": round(float(gold_ann) * 100, 2)}}

base_b = perf(pd.Series(rb.to_numpy(), index=IDX))
sat, logrows = {}, []
for w in (0.10, 0.15, 0.20, 0.30):
    v = perf(pd.Series(((1 - w) * rb + w * rg).to_numpy(), index=IDX))
    sat[f"w{int(w*100)}"] = {"sharpe": v["sharpe"], "ann_pct": v["ann_pct"], "mdd_pct": v["mdd_pct"],
                             "vs_100B_sharpe": round(v["sharpe"] - base_b["sharpe"], 3)}
    log(f"[卫星] w{int(w*100)}: S{v['sharpe']} ({sat[f'w{int(w*100)}']['vs_100B_sharpe']:+.3f}) 年化 {v['ann_pct']}% 回撤 {v['mdd_pct']}%")
half = len(tw) // 2
halves = {}
for tag, sl in (("h1", slice(0, half)), ("h2", slice(half, None))):
    _rb = pd.Series(rb.to_numpy()[sl], index=IDX[sl]); _rg = pd.Series(rg.to_numpy()[sl], index=IDX[sl])
    b_s = perf(_rb)["sharpe"]
    for w in (0.20, 0.30):
        halves[f"{tag}_w{int(w*100)}"] = round(perf((1 - w) * _rb + w * _rg)["sharpe"] - b_s, 3)
RES["satellite"] = {"vs_100B": round(base_b["sharpe"], 3), **sat, "halves_delta": halves}
log(f"[卫星分半] {halves}")

base_w = perf(pd.Series((0.60 * rf + 0.40 * rb).to_numpy(), index=IDX))
book = {"base_on_window": base_w}
for w in (0.10, 0.15, 0.20):
    v = perf(pd.Series((0.60 * rf + (0.40 - w) * rb + w * rg).to_numpy(), index=IDX))
    pl = perf(pd.Series((0.60 * rf + (0.40 - w) * rb).to_numpy(), index=IDX))
    book[f"w{int(w*100)}"] = {"sharpe": v["sharpe"], "vs_base_sharpe": round(v["sharpe"] - base_w["sharpe"], 3),
                              "placebo_cash_vs_base": round(pl["sharpe"] - base_w["sharpe"], 3)}
    log(f"[组合] w{int(w*100)}: S{v['sharpe']} ({book[f'w{int(w*100)}']['vs_base_sharpe']:+.3f}) | 安慰剂现金 {book[f'w{int(w*100)}']['placebo_cash_vs_base']:+.3f}")
RES["book"] = book

drift = {}
for cut in (0, 4, 8, 12, 16):
    gc = rg - cut / 100.0 / ANN_BLEND
    g_ann = (1 + gc).prod() ** (ANN_BLEND / len(gc)) - 1
    _k = f"cut{cut}pct"
    drift[_k] = {
        "gold_ann_pct": round(float(g_ann) * 100, 2),
        "satellite_w20_delta": round(perf(pd.Series((0.8 * rb + 0.2 * gc).to_numpy(), index=IDX))["sharpe"] - base_b["sharpe"], 3),
        "book_w15_delta": round(perf(pd.Series((0.60 * rf + 0.25 * rb + 0.15 * gc).to_numpy(), index=IDX))["sharpe"] - base_w["sharpe"], 3)}
    log(f"[打折 {cut}pp] 黄金年化 {drift[_k]['gold_ann_pct']}% → 卫星w20 ΔS {drift[_k]['satellite_w20_delta']:+.3f} | 组合w15 ΔS {drift[_k]['book_w15_delta']:+.3f}")
RES["gold_drift_sensitivity"] = drift

# ---- B 可执行性审计 ----
spot = gpx.iloc[-1]
last_px = float(spot["close"]); last_dt = str(gpx.index[-1])
lot_cost = last_px * 100
amt20 = float(pd.to_numeric(gpx["amount"], errors="coerce").tail(20).mean())
mom20 = float(last_px / float(gpx["close"].iloc[-21]) - 1)
sp = json.load(open(os.path.join(BASE, "backtest", "satellite_pool.json"), encoding="utf-8"))
cap = {tk: sum(float(r.get("amount") or 0) for r in (sp.get(tk, {}).get("rows") or [])) for tk in ("track_a", "track_b")}
pb = json.load(open(os.path.join(BASE, "backtest", "satellite_paper_b.json"), encoding="utf-8"))
basis_b = float((pb.get("meta") or {}).get("basis") or 0)
tgt = cap["track_b"] * 0.10
lots = int(tgt // lot_cost)
RES["feasibility"] = {"instrument": "sh518880 黄金ETF", "last_date": last_dt, "close": round(last_px, 3),
                      "lot_cost": round(lot_cost, 1), "amt20_mean": round(amt20), "mom20_pct": round(mom20 * 100, 2),
                      "caps": cap, "paper_b_basis": basis_b,
                      "afford_10pct": {"target": round(tgt), "lots": lots, "cost": round(lots * lot_cost), "residual": round(tgt - lots * lot_cost)}}
log(f"[可执行] {last_dt} 518880 收 {last_px:.3f} 整手 {lot_cost:.0f} 元 | 20日均额 {amt20/1e8:.2f}亿 | 20d动量 {mom20*100:+.1f}%")
log(f"[可执行] 轨B 额度 {cap['track_b']:.0f}（轨A {cap['track_a']:.0f}）| 10% 黄金 = {round(tgt)} 元 → {lots} 手（{round(lots*lot_cost)} 元，余 {round(tgt-lots*lot_cost)}）")

json.dump(RES, open(os.path.join(HERE, "verify_gold_sat_0917.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
log("[落盘] backtest/verify_gold_sat_0917.json")
