# -*- coding: utf-8 -*-
"""双卫星每日信号脚本（冷门低波 Top10/60d + A4D Top20/月频）
用法：每日收盘后运行 python signal_satellite_0913.py
 - 读 holdings_satellite.json（首次运行自动生成空仓模板）
 - 输出：各轨明日开盘操作清单（卖出/买入/持有不动）
 - 成交后把实际成交价/数量回填 holdings_satellite.json
注意：两轨均为纯调仓制（冷门低波 60 交易日、A4D 月频），非调仓日输出「无操作」。"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
STATE = HERE / "holdings_satellite.json"
REBAL_LN = 60     # 冷门低波：60 交易日
SLIP = 0.002

# ---------- 数据 ----------
v = pd.read_csv(BASE / "data_fundamental" / "val_em" / "val_em_all.csv", dtype={"code": str})
v["date"] = pd.to_datetime(v["date"])
last_val_date = v["date"].max()
v = v[v["date"] == last_val_date].set_index("code")
total_mv = v["total_mv"]

days_all = []
px = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open", "high", "low", "close", "volume", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    code = c[2:]
    days_all.append(d["date"].max())
    px[code] = d.set_index("date").sort_index()
LAST_DAY = max(days_all)
print(f"数据截至：{LAST_DAY.date()}（收盘）→ 以下操作为次一交易日开盘执行")

# ---------- 轨 A：冷门低波 ln_amt20+atr20 ----------
def signal_ln_atr(hold):
    scores = []
    for code, d in px.items():
        if len(d) < 180 or d.index[-1] != LAST_DAY:
            continue   # ⚠ 2026-09-13 修复：必须当日有行情（剔除退市死票，与回测口径一致）
        tail = d.tail(70)
        amt20 = tail["amount"].tail(20).mean()
        pc = d["close"].shift(1)
        tr = np.nanmax(np.stack([tail["high"] - tail["low"],
                                 (tail["high"] - pc.tail(70)).abs(),
                                 (tail["low"] - pc.tail(70)).abs()]), axis=0)
        atr20 = np.nanmean(tr[-20:]) / tail["close"].iloc[-1]
        c = d["close"].iloc[-1]
        o = d["open"].iloc[-1]
        pc_last = d["close"].iloc[-2] if len(d) > 1 else np.nan
        if amt20 <= 0 or not np.isfinite(atr20) or c < 2:
            continue
        # 因子分（低成交额+低波动，双低排序：rank 和）
        scores.append((code, amt20, atr20, c, o, pc_last))
    df = pd.DataFrame(scores, columns=["code", "amt20", "atr20", "close", "open", "pc"]).dropna()
    df["rk"] = np.log(df["amt20"]).rank() + df["atr20"].rank()   # 双低 = rank 小者优先
    top = df.sort_values("rk").head(10)["code"].tolist()
    return top, df

# ---------- 轨 B：A4D（r6b 原引擎口径）----------
_A4D_CACHE = {}
def signal_a4d_orig(hold):
    """直接复用 factor_blend_r6b_0913.py 的 COMP_A4/ELIG_A4（icir 6 因子+地板 300 万+ST/新股过滤）"""
    if "top" not in _A4D_CACHE:
        src = open(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py", encoding="utf-8").read().split('if __name__')[0]
        gg = {"__file__": str(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py")}
        exec(src, gg)
        di = gg["ND"] - 1
        sc = gg["COMP_A4"][di]
        ok = np.where(np.isfinite(sc) & gg["ELIG_A4"][di])[0]
        ok = sorted(ok, key=lambda j: -sc[j])[:20]
        prev = gg["close_m"][di - 1]
        _A4D_CACHE["top"] = [(gg["codes"][j], float(gg["close_m"][di, j]),
                              "涨停勿追" if np.isfinite(prev[j]) and gg["close_m"][di, j] >= prev[j] * 1.098 else "")
                             for j in ok]
        _A4D_CACHE["asof"] = str(gg["cal"][-1])
    return [c for c, _, _ in _A4D_CACHE["top"]], _A4D_CACHE

# ---------- 轨 C：FB3-H20 主仓（基金 NAV 动量，build_short_pool 生产口径）----------
def signal_fb3():
    sp = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
    tier = sp.get("tiers", {}).get("基金", []) or sp.get("tiers", {}).get("fund", [])
    mg = sp.get("market_gate", {})
    det = sp.get("details", {})
    rows = []
    for c in tier:
        d = det.get(c, {})
        rows.append({"code": c, "name": d.get("name", ""), "score": d.get("score"),
                     "pool": d.get("pool", "fund")})
    return {"rows": rows, "gate": mg, "asof": sp.get("as_of"),
            "regime": "牛市 Top10 动量" if mg.get("open") else "熊市 Top3 低波防守"}


# ---------- 主流程 ----------
def main():
    if STATE.exists():
        st = json.load(open(STATE, encoding="utf-8"))
    else:
        st = {"ln_atr": {"last_rebal": "", "holdings": {}},
              "a4d": {"last_rebal": "", "holdings": {}}}
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已生成空仓状态模板 holdings_satellite.json（首run为建仓清单）")
    days_ix = sorted({d for p in px.values() for d in p.index})
    di_last = days_ix.index(LAST_DAY)
    print(f"交易日序号：{di_last}（自 2021-01-04）\n")
    ln_top, _ = signal_ln_atr(st["ln_atr"]["holdings"])
    a4_top, a4d_meta = signal_a4d_orig(st["a4d"]["holdings"])
    fb3 = signal_fb3()
    _held_c = list(st.get("track_c", {"holdings": {}}).get("holdings", {}).keys())
    _tgt_c = [r["code"] for r in fb3["rows"]]
    print(f"===== 轨C FB3-H20 主仓（{fb3['regime']} · as_of {fb3['asof']}）=====")
    print(f"  卖出（T+1 净值赎回）：{[c for c in _held_c if c not in _tgt_c] or '无'}")
    print(f"  买入（T+1 净值申购）：{[c for c in _tgt_c if c not in _held_c] or '无'}")
    for r in fb3["rows"]:
        print(f"    {r['code']} {r['name']} 动量分 {r['score']}")
    print(f"  市况门控：{'开' if fb3['gate'].get('open') else '关（熊市防守）'}\n")
    for track, top, reb, last_r in (("轨A 冷门低波 Top10/60d", ln_top, REBAL_LN, st["ln_atr"]["last_rebal"]),
                                    ("轨B A4D Top20/月频", a4_top, 20, st["a4d"]["last_rebal"])):
        held = list(st[track.split()[1]]["holdings"].keys()) if False else list(st["ln_atr" if "冷门" in track else "a4d"]["holdings"].keys())
        due = (not last_r) or (di_last - days_ix.index(pd.Timestamp(last_r)) >= reb)
        print(f"===== {track} =====")
        if not due:
            print("  未到调仓日 → 无操作")
            continue
        sell = [c for c in held if c not in top]
        buy = [c for c in top if c not in held]
        print(f"  卖出（明日开盘）：{sell or '无'}")
        print(f"  买入（明日开盘）：{buy or '无'}")
        if "冷门" in track:
            for c in top:
                d = px[c].tail(1).iloc[0]
                print(f"    {c} 收盘 {d['close']:.2f} 一手≈{d['close']*100:,.0f} 元")
        else:
            for c, clse, guard in a4d_meta["top"]:
                print(f"    {c} 收盘 {clse:.2f} 一手≈{clse*100:,.0f} 元 {guard}")

if __name__ == "__main__":
    main()
