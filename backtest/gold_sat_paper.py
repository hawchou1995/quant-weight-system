# -*- coding: utf-8 -*-
"""黄金卫星叠加模拟盘（R-gold-sat-0917 · 2026-09-17 用户拍板按推荐投产）
====================================================================
形态（研究里唯一同时过「卫星层 + 组合层」双闸的腿，证据 backtest/verify_gold_sat_0917.json）：
    卫星层 = (1−w)·r_B + w·r_gold，w = GOLD_W = 10%，**替换**轨B 的 10%（卫星总敞口仍 = CAP_B = 68000）
    黄金腿 = sh518880（黄金ETF华安）**买入持有，永不卖出**（研究臂 c_gold_bh phmed 1.002；
             择时臂 c_gold_mom phmed 0.757 明显更差 → 不采纳）
账本：backtest/gold_sat_paper.json（黄金袖独立账户，名义 GOLD_NOTIONAL = 6800）
资金：首次建仓从轨B 现金（satellite_paper_b.json 的 cash）**划出一次**，并把黄金腿**镜像**成轨B 的一个
      position（幂等）。satellite_paper_0914.py 的 mark 循环本就对持仓逐只 `load_px(code)` 取价
      → 黄金市值自动进轨B 净值，**生产脚本零逻辑改动**即可保证轨B 总敞口 = CAP_B（不超配）。
口径：T 日收盘定信号 → T+1 开盘成交（open×(1+SLIP)）；整百股；佣金 2.5bp（最低 5 元）；**无卖出**。
漂移：永不回补（研究只验证过 B&H；年度/阈值回补是未测变体）→ 实际占比仅在看板展示。

用法：
    python backtest/gold_sat_paper.py --dry                    # 预览，不写盘
    python backtest/gold_sat_paper.py                          # 日更；首次运行只登记信号日，等 T+1 自动建仓
    python backtest/gold_sat_paper.py --init-fill 2026-09-18   # 指定成交日建仓
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
HERE = BASE / "backtest"
STATE = HERE / "gold_sat_paper.json"
SAT_B = HERE / "satellite_paper_b.json"
CAL = BASE / "index_000300.csv"
COMM, MIN_COMM, SLIP, LOT = 0.00025, 5.0, 0.0020, 100

sys.path.insert(0, str(HERE))
import satellite_cfg as CFG                                    # 配额/权重单一来源（R-single-track-0915）

CODE = CFG.GOLD_CODE
W = float(CFG.GOLD_W)
NOTIONAL = float(CFG.GOLD_NOTIONAL)
NAME = "黄金ETF华安"

HARD_FLAGS = [
    "① 卫星档保 ΔS≥+0.02 需黄金年化 ≈5%/年（盈亏平衡 ≈3~4%/年；实测全窗 19.42%）",
    "② 黄金腿 B&H 换手≈0 → 50bp 成本压力档不构成稳健性证据",
    "③ 样本窗 2021-08→2026-09 为黄金大牛段，样本外风险未测（本题唯一的缓解=让它跑起来）",
]


def load_px(code, date=None):
    """返回 {date: (open, close)}；date=None 全量"""
    f = BASE / "data_full" / f"{code}.csv"
    if not f.exists():
        for pre in ("sh", "sz", "bj"):
            g = BASE / "data_full" / f"{pre}{code}.csv"
            if g.exists():
                f = g
                break
    if not f.exists():
        return {}
    df = pd.read_csv(f, dtype={"date": str}).sort_values("date")
    if date is not None:
        r = df[df["date"] == date]
        return {} if r.empty else {date: (float(r["open"].iloc[0]), float(r["close"].iloc[0]))}
    return {r.date: (float(r.open), float(r.close)) for r in df.itertuples()}


def calendar():
    idx = pd.read_csv(CAL, parse_dates=["date"])
    return sorted(idx["date"].dt.strftime("%Y-%m-%d").tolist())


def mirror_into_track_b(shares, px, close, amount, date):
    """把黄金腿**镜像**进轨B 账户：扣现金 + 落一个 position。
    为什么镜像而不是改 satellite_paper_0914.py：其 mark 循环已能对任意持仓 `load_px(code)` 取价
    （data_full/sh518880.csv 在位）→ 黄金市值自动进轨B 净值，**零逻辑改动**即可保持轨B 总敞口 = CAP_B。
    幂等：CODE 已在 positions 里就直接返回（黄金 B&H，永不加仓/减仓）。
    """
    if not SAT_B.exists():
        return None
    d = json.loads(SAT_B.read_text(encoding="utf-8"))
    pos = d.setdefault("positions", {})
    if CODE in pos:
        return float(d.get("cash", 0.0))
    d["cash"] = round(float(d.get("cash", 0.0)) - amount, 2)
    pos[CODE] = dict(shares=float(shares), cost=amount / shares, name=NAME,
                     industry="商品", last=close)
    d.setdefault("fills", []).append(dict(date=date, track="track_b", code=CODE, name=NAME,
                                          px=round(px, 3), shares=int(shares),
                                          amount=round(amount, 2), side="buy"))
    d.setdefault("events", []).append(dict(
        date=date,
        event=f"黄金卫星叠加：轨B 现金划出 {amount:.2f} 买入 {NAME} {int(shares)} 股"
              f"（轨B 内 {W:.0%} 替换，卫星总敞口仍 {CFG.CAP_B:.0f}）"))
    d["events"] = d["events"][-40:]
    SAT_B.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d["cash"]


def sat_b_nav():
    """轨B 当前净值（已含镜像进来的黄金腿市值）。"""
    try:
        d = json.loads(SAT_B.read_text(encoding="utf-8"))
        return float((d.get("nav_history") or [{}])[-1].get("track_b") or 0.0)
    except Exception:
        return 0.0


def main():
    dry = "--dry" in sys.argv
    target_date = None
    if "--init-fill" in sys.argv and len(sys.argv) > sys.argv.index("--init-fill") + 1:
        target_date = sys.argv[sys.argv.index("--init-fill") + 1]

    cal = calendar()
    if not cal:
        print("!! 日历为空（index_000300.csv 不可读）——中止")
        return 1
    last = cal[-1]

    if STATE.exists():
        st = json.loads(STATE.read_text(encoding="utf-8"))
        new = False
    else:
        st = dict(
            meta=dict(
                strategy="黄金卫星叠加（轨B 内 10% · sh518880 买入持有）",
                created=last,
                signal_date=last,
                code=CODE, name=NAME, weight=W, notional=NOTIONAL,
                cost_model="佣金 2.5bp(最低5元) + 滑点 20bp/边 · 无卖出",
                mode="buy_hold",
                rebalance="永不回补（B&H）；漂移仅在看板展示",
                note="叠加式 r_sat=(1−w)·r_B+w·r_gold；替轨B 的 10%，卫星总敞口仍 = CAP_B",
                hard_flags=HARD_FLAGS,
                decision="2026-09-17 用户拍板（按 grill 推荐：w=10% / B&H / 只做卫星层 / 独立账户轨B内替换）",
            ),
            track="gold_sat", cash=NOTIONAL, positions={}, fills=[], events=[], nav_history=[])
        new = True
        st["events"].append(dict(date=last, event=f"建档：名义 {NOTIONAL:.0f}（轨B {CFG.CAP_B:.0f} × {W:.0%}），信号日 {last}，等 T+1 开盘建仓"))

    pos = st["positions"]
    ash = 0.0
    for pn in pos.values():
        ash += float(pn.get("shares", 0))
    lots_held = int(ash // LOT)

    sig = st["meta"].get("signal_date")
    auto = [d for d in cal if sig and d > sig]
    fill_date = target_date or (auto[0] if auto else None)
    need = (not pos) and float(st.get("cash", 0.0)) > 0

    print(f"黄金卫星 | 码 {CODE} | 权重 {W:.0%} | 名义 {NOTIONAL:.0f} | 数据截至 {last} "
          f"| 信号日 {sig} | 持仓 {lots_held} 手 | 现金 {float(st.get('cash', 0.0)):.2f}")

    filled = False
    if need and fill_date:
        pxd = load_px(CODE, fill_date)
        if not pxd:
            print(f"!! {fill_date} 无 {CODE} 行情，跳过（等数据）")
        else:
            o = pxd[fill_date][0]
            px = o * (1 + SLIP)
            cash = float(st["cash"])
            lots = math.floor(min(NOTIONAL, cash) / (px * LOT))
            sh = lots * LOT
            amt = px * sh
            fee = max(amt * COMM, MIN_COMM)
            while lots > 0 and amt + fee > cash:
                lots -= 1
                sh = lots * LOT
                amt = px * sh
                fee = max(amt * COMM, MIN_COMM)
            if lots < 1:
                print(f"!! 资金不足一手（{cash:.2f} < {px * LOT:.2f}），跳过")
            else:
                cash -= amt + fee
                pos[CODE] = dict(shares=float(sh), cost=(amt + fee) / sh, name=NAME,
                                 last=pxd[fill_date][1])
                st["cash"] = round(cash, 2)
                st["fills"].append(dict(date=fill_date, code=CODE, name=NAME,
                                        px=round(px, 3), shares=int(sh),
                                        amount=round(amt + fee, 2), side="buy"))
                st["events"].append(dict(
                    date=fill_date,
                    event=f"建仓 {lots} 手 @ {px:.3f}（开盘 {o:.3f}+20bp），成交 {amt + fee:.2f}，余现金 {cash:.2f}"))
                filled = True
                print(f"== init-fill @ {fill_date} 开盘 {o:.3f} → {lots} 手 / {sh} 股 / 含费 {amt + fee:.2f}"
                      f"（剩 {cash:.2f}，名义剩余 {NOTIONAL - (amt + fee):.2f}）==")
    elif need:
        print(f"!! 待建仓但 T+1 数据未到（信号日 {sig}，最新日历 {last}）——等收盘数据后自动执行")

    # ---- mark ----
    pxc = load_px(CODE)
    mv = 0.0
    for code, p in pos.items():
        if last in pxc:
            p["last"] = pxc[last][1]
        mv += float(p["shares"]) * float(p.get("last", 0.0))
    cash = float(st.get("cash", 0.0))
    nav = cash + mv
    ret = nav / NOTIONAL - 1
    total_sat = sat_b_nav() or CFG.CAP_B
    share = (mv / total_sat) if total_sat else 0.0
    if pos:
        nh = st["nav_history"]
        if nh and nh[-1].get("date") == last:
            nh[-1].update(nav=round(nav, 2), pos=round(mv, 2), cash=round(cash, 2),
                          share=round(share, 4))
        else:
            nh.append(dict(date=last, nav=round(nav, 2), pos=round(mv, 2), cash=round(cash, 2),
                           share=round(share, 4), ret=round(ret, 5)))
        print(f"  mark {last}: 现金 {cash:.2f} + 市值 {mv:.2f} = 净值 {nav:.2f}"
              f"（{ret:+.2%}）| 占卫星 {share:.2%}")
    else:
        print("  未建仓 → 不记净值（等 T+1 开盘成交）")

    st["events"] = st["events"][-40:]
    if dry:
        print("[dry] 未写盘。")
        print("  state 预览:", json.dumps({k: st[k] for k in ("cash", "fills", "nav_history")},
                                            ensure_ascii=False)[:400])
        return 0
    # 先镜像（幂等）再写黄金袖账本：镜像成功而本文件写失败时，下次运行会重做且镜像自动 no-op。
    if filled:
        f = st["fills"][-1]
        nb = mirror_into_track_b(f["shares"], f["px"], pos[CODE]["last"], f["amount"], fill_date)
        if nb is not None:
            print(f"  轨B 镜像后现金 = {nb:.2f}（卫星总敞口仍 {CFG.CAP_B:.0f}）")
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"== 黄金袖净值 {nav:.2f} / {NOTIONAL:.0f} = {ret:+.2%} → {STATE.name}"
          f"{'（首建仓）' if filled else ''} ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
