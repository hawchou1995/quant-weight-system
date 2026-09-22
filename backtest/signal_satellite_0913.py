# -*- coding: utf-8 -*-
"""双卫星每日信号脚本（冷门低波 Top10/60d + SUPER Top20/月频 · 2026-09-13 轨B 由 A4D 换挡为 SUPER）
用法：每日收盘后运行 python signal_satellite_0913.py
 - 读 holdings_satellite.json（首次运行自动生成空仓模板；旧 a4d 键自动迁移为 super）
 - 输出：各轨明日开盘操作清单（卖出/买入/持有不动）
 - 成交后把实际成交价/数量回填 holdings_satellite.json
注意：两轨均为纯调仓制（冷门低波 60 交易日、SUPER 月频），非调仓日输出「无操作」。
SUPER 口径：13 因子 ICIR 复合（冻结自 oss_0913/super_combo_0913.json，phmed S 1.151 全闸通过）。"""
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
REBAL_LN = 30     # 冷门低波 v2：30 交易日（2026-09-14 拍板：turn+gate）
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

# 风险名称过滤（2026-09-13 落地）：轨A 仅排"退"；轨B 排 ST/*ST/退（回测依据见 st_filter_0913.json）
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str})
_nh = _nh.sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
ST_SET = set(_name[_name.str.contains("ST")].index)
print(f"数据截至：{LAST_DAY.date()}（收盘）→ 以下操作为次一交易日开盘执行")

# ---------- 轨 A：冷门低波 ln_amt20+atr20 ----------
def signal_ln_atr(hold):
    scores = []
    for code, d in px.items():
        if len(d) < 180 or d.index[-1] != LAST_DAY:
            continue   # ⚠ 2026-09-13 修复：必须当日有行情（剔除退市死票，与回测口径一致）
        if code in TUI_SET:
            continue   # 退市整理期排除（回测零成本）
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


# ---------- 轨 A v2：ln_amt20+atr20+turn20 三低 · Top20 · 闸门半仓 ----------
def signal_turn_gate(hold):
    """2026-09-14 拍板升级：amt/atr/turn 三低 rank 和 · Top20 · sc1000 破 MA20 → 半仓 Top10
    turn20 = 近 20 日 (成交额/流通市值) 均值；fmv 来自 data_fundamental/val_live/fmv_recent.csv（val_em 历史 + 每日快照）
    """
    fmv_file = BASE / "data_fundamental" / "val_live" / "fmv_recent.csv"
    scores = []
    if fmv_file.exists():
        fm = pd.read_csv(fmv_file, dtype={"code": str, "date": str})
        fm = fm.pivot_table(index="date", columns="code", values="float_mv", aggfunc="last")
    else:
        fm = pd.DataFrame()
    for code, d in px.items():
        if len(d) < 180 or d.index[-1] != LAST_DAY:
            continue
        if code in TUI_SET:
            continue
        tail = d.tail(70)
        amt20 = tail["amount"].tail(20).mean()
        pc = d["close"].shift(1)
        tr = np.nanmax(np.stack([tail["high"] - tail["low"],
                                 (tail["high"] - pc.tail(70)).abs(),
                                 (tail["low"] - pc.tail(70)).abs()]), axis=0)
        atr20 = np.nanmean(tr[-20:]) / tail["close"].iloc[-1]
        dts = [str(x)[:10] for x in d.index[-20:]]
        amts = d["amount"].tail(20).values
        tv = []
        for dt, a in zip(dts, amts):
            if (dt in fm.index) and (code in fm.columns):
                v = fm.at[dt, code]
                tv.append(a / v if (np.isfinite(v) and v > 0) else np.nan)
            else:
                tv.append(np.nan)
        turn20 = np.nanmean(tv) if np.isfinite(np.nanmean(tv)) else np.nan
        c = d["close"].iloc[-1]
        if amt20 <= 0 or not np.isfinite(atr20) or not np.isfinite(turn20) or c < 2:
            continue
        scores.append((code, amt20, atr20, turn20, c))
    df = pd.DataFrame(scores, columns=["code", "amt20", "atr20", "turn20", "close"]).dropna()
    df["rk"] = np.log(df["amt20"]).rank() + df["atr20"].rank() + df["turn20"].rank()
    gate_open, gate_note = True, "开（满仓 Top20）"
    gf = BASE / "data_full" / "sh512100.csv"
    if gf.exists():
        g_ = pd.read_csv(gf, dtype={"date": str})
        g_["ma20"] = g_["close"].rolling(20, min_periods=15).mean()
        g_ = g_[g_["date"] == str(LAST_DAY)[:10]]
        if len(g_) and np.isfinite(g_["ma20"].iloc[0]):
            gate_open = bool(g_["close"].iloc[0] > g_["ma20"].iloc[0])
            gate_note = "开（满仓 Top20）" if gate_open else "关（半仓 Top10）"
    N = 20 if gate_open else 10
    top = df.sort_values("rk").head(N)["code"].tolist()
    return top, df, {"gate_open": gate_open, "gate_note": gate_note, "n": N}


# ---------- 轨 B：SUPER（13 因子 icir 复合，2026-09-13 生产口径替换 A4D）----------
_SUPER_CACHE = {}
def signal_super(hold):
    """复用 oss_super_prod_0913.py 的 COMP_SUPER/ELIG_SUPER（13 因子冻结权重+地板 300 万+ST/退过滤）"""
    if "top" not in _SUPER_CACHE:
        prod = HERE / "oss_0913" / "oss_super_prod_0913.py"
        src = open(prod, encoding="utf-8").read()
        gg = {"__file__": str(prod)}
        exec(src, gg)
        di = gg["ND"] - 1
        sc = gg["COMP_SUPER"][di]
        ok = np.where(np.isfinite(sc) & gg["ELIG_SUPER"][di])[0]
        ok = sorted(ok, key=lambda j: -sc[j])
        ok = [j for j in ok if gg["codes"][j] not in ST_SET and gg["codes"][j] not in TUI_SET][:20]
        prev = gg["close_m"][di - 1]
        _SUPER_CACHE["top"] = [(gg["codes"][j], float(gg["close_m"][di, j]),
                              "涨停勿追" if np.isfinite(prev[j]) and gg["close_m"][di, j] >= prev[j] * 1.098 else "")
                             for j in ok]
        _SUPER_CACHE["asof"] = str(gg["cal"][-1])
    return [str(c) for c, _, _ in _SUPER_CACHE["top"]], _SUPER_CACHE

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
        if "super" not in st:  # 2026-09-13 轨 B 换挡迁移：a4d -> super（保留持仓）
            st["super"] = st.pop("a4d", {"last_rebal": "", "holdings": {}})
            json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("状态迁移：轨B a4d -> super（口径替换为 SUPER 13 因子）")
    else:
        st = {"ln_atr": {"last_rebal": "", "holdings": {}},
              "super": {"last_rebal": "", "holdings": {}}}
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已生成空仓状态模板 holdings_satellite.json（首run为建仓清单）")
    # 2026-09-22 修（用户批准 R-sat-state-0922）：调仓状态改由**模拟盘账本派生** = 唯一事实来源。
    #   缺陷：holdings_satellite.json 的 last_rebal/holdings 全库无任何代码推进 → 永远为空
    #         → due 恒为真 → 每天都输出完整 20 只清单，与 docstring「非调仓日输出无操作」矛盾。
    #   账本侧：轨A ← satellite_paper_a.json / 轨B ← satellite_paper_b.json。
    #   ⚠ 黄金腿（GOLD_CODE，B&H 永不卖出）必须**同时**从 last_rebal 与 holdings 剔除，
    #     否则会被并进 held → 出现在 sell 差集里（会被误读成卖出指令）。
    try:
        import satellite_cfg as _SCFG
        _GOLD = getattr(_SCFG, "GOLD_CODE", "sh518880")
    except Exception:
        _GOLD = "sh518880"
    for _k, _fn in (("ln_atr", "satellite_paper_a.json"), ("super", "satellite_paper_b.json")):
        _fp = HERE / _fn
        if not _fp.exists():
            print(f"  [{_k}] ⚠ 账本 {_fn} 不存在 → 沿用 holdings_satellite.json")
            continue
        try:
            _d = json.load(open(_fp, encoding="utf-8"))
        except Exception as _e:
            print(f"  [{_k}] ⚠ 账本 {_fn} 读取失败({_e}) → 沿用 holdings_satellite.json")
            continue
        _pos = {c: v for c, v in (_d.get("positions") or {}).items() if c != _GOLD}
        _buys = [f.get("date") for f in (_d.get("fills") or [])
                 if f.get("side") == "buy" and f.get("date") and f.get("code") != _GOLD]
        _lr = max(_buys) if _buys else ""
        _old = str((st.get(_k) or {}).get("last_rebal") or "")
        if _lr and _lr > _old:
            st.setdefault(_k, {})["last_rebal"] = _lr
        if _pos:
            st.setdefault(_k, {})["holdings"] = {c: {"shares": (_pos[c] or {}).get("shares")} for c in _pos}
        print(f"  [{_k}] 调仓状态 ← 账本 {_fn}：last_rebal={st[_k]['last_rebal'] or '—'} "
              f"持仓 {len(_pos)} 只（已剔黄金腿 {_GOLD}）")
    days_ix = sorted({d for p in px.values() for d in p.index})
    di_last = days_ix.index(LAST_DAY)
    print(f"交易日序号：{di_last}（自 2021-01-04）\n")
    ln_top, _, _ln_gate = signal_turn_gate(st["ln_atr"]["holdings"])
    print(f"轨A 闸门：{_ln_gate['gate_note']}")
    su_top, su_meta = signal_super(st["super"]["holdings"])
    fb3 = signal_fb3()
    _held_c = list(st.get("track_c", {"holdings": {}}).get("holdings", {}).keys())
    _tgt_c = [r["code"] for r in fb3["rows"]]
    print(f"===== 轨C FB3-H20 主仓（{fb3['regime']} · as_of {fb3['asof']}）=====")
    print(f"  卖出（T+1 净值赎回）：{[c for c in _held_c if c not in _tgt_c] or '无'}")
    print(f"  买入（T+1 净值申购）：{[c for c in _tgt_c if c not in _held_c] or '无'}")
    for r in fb3["rows"]:
        print(f"    {r['code']} {r['name']} 动量分 {r['score']}")
    print(f"  市况门控：{'开' if fb3['gate'].get('open') else '关（熊市防守）'}\n")
    for track, top, reb, last_r in (("轨A 冷门低波三低 Top20/30d【已退休 0916·仅对照·勿执行】", ln_top, REBAL_LN, st["ln_atr"]["last_rebal"]),
                                    ("轨B SUPER Top20/月频", su_top, 20, st["super"]["last_rebal"])):
        held = list(st["ln_atr" if "冷门" in track else "super"]["holdings"].keys())
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
            for c, clse, guard in su_meta["top"]:
                print(f"    {c} 收盘 {clse:.2f} 一手≈{clse*100:,.0f} 元 {guard}")

if __name__ == "__main__":
    main()
