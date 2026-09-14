# -*- coding: utf-8 -*-
"""基金主仓（轨C FB3-H20）模拟盘账本 —— 补齐「三轨模拟盘」最后一块
=================================================================
台账：backtest/fund_paper.json（meta/fills/positions/nav_history/events）
口径（来自 short_v3_fund_slip20_summary.json 权威配置）：
    FB3-H20 牛熊 · 牛动量重 Top10/S30 · 熊低波重 Top3/S45（C 类份额）
    初始资金 102000（= 17 万的 60% 主仓）；费用/滑点 5bp/边；持仓 20 个交易日（≈月度轮动）
信号：short_pool.json 的 tiers['基金']（build_short_pool 生产口径）+ fund_as_of（信号所用净值日）
成交：信号净值日（fund_as_of）之后**第一个净值日**按净值成交 —— 信息集干净（T 日信号 → T+1 净值）
      注：基金净值 T+1 公布，故运行当日往往还需等下一交易日净值才能成交（脚本自动等）
行为：
    --init-fill   空仓时按目标清单在该净值日建仓（默认自动）
    --rebal       强制换仓（卖出全部 → 按当前信号清单买入）
    默认          每只按最新可得净值 mark，追加 nav_history（同日不重复追加）
用法：python backtest/fund_paper_0914.py [--init-fill|--rebal] [--dry]
"""
import json
import sys
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
STATE = BASE / "backtest" / "fund_paper.json"
POOL = BASE / "short_pool.json"
NAV_DIR = BASE / "fund_nav_cache"
SLIP, INIT_CASH, HOLD_DAYS = 0.0005, 102000.0, 20


def load_nav(code):
    """{date: nav} 升序"""
    f = NAV_DIR / f"{code}.csv"
    if not f.exists():
        return {}
    out = {}
    for ln in f.read_text(encoding="utf-8").splitlines()[1:]:
        p = ln.split(",")
        if len(p) >= 2 and p[0]:
            try:
                out[p[0]] = float(p[1])
            except ValueError:
                pass
    return dict(sorted(out.items()))


def pool_signal():
    """(目标代码列表, fund_as_of, regime 描述)"""
    d = json.loads(POOL.read_text(encoding="utf-8"))
    codes = [c for c in (d.get("tiers", {}).get("基金") or []) if isinstance(c, str) and len(c) == 6]
    gate = d.get("market_gate") or {}
    regime = "牛市 Top10（动量重 S30）" if gate.get("open") else "熊市 Top3（低波重 S45）"
    return codes, d.get("fund_as_of"), regime


def fill_date(series, fund_as_of):
    """信号净值日**之后**第一个净值日（严格大于）。无 → None（=等下一交易日，禁止用信号日自身净值成交）。
    ⚠ 2026-09-14：初版在「无更晚净值」时回退到 latest（=信号日净值）→ 等于用信号看到的同一价格买入（前视），已修。"""
    if fund_as_of:
        return next((d for d in series if d > fund_as_of), None)
    return max(series) if series else None


def main():
    dry = "--dry" in sys.argv
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {
        "meta": {"strategy": "FB3-H20 基金主仓（轨C）", "initial_cash": INIT_CASH,
                 "cost_model": "C 类份额；5bp/边（含申赎与滑点）", "hold_days": HOLD_DAYS,
                 "note": "信号=T 日 short_pool 基金层；成交=信号净值日之后第一个净值日；持仓 20 交易日"},
        "cash": INIT_CASH, "positions": {}, "fills": [], "nav_history": [], "events": [], "last_rebal": None,
    }
    codes, fund_as_of, regime = pool_signal()
    if not codes:
        print("!! short_pool 基金层为空，跳过")
        return

    navs = {c: load_nav(c) for c in codes}
    # 全池最新净值日（用于 mark 与判断可成交日）
    all_dates = sorted({d for s in navs.values() for d in s})
    latest = all_dates[-1] if all_dates else None
    # 成交日 = 信号净值日之后第一个净值日（逐只各自找，跨基金允许不同日）
    print(f"信号 {len(codes)} 只 | {regime} | fund_as_of={fund_as_of} | 池内最新净值日={latest}")

    # 上次调仓后的交易日数（用 all_dates 近似交易日历）
    def days_since(d):
        if not d or d not in all_dates:
            return 10 ** 6
        return len(all_dates) - all_dates.index(d) - 1

    need_rebal = (not st["positions"]) or days_since(st.get("last_rebal")) >= HOLD_DAYS
    forced = "--rebal" in sys.argv

    # ---- 换仓（含首次建仓）----
    if need_rebal or forced:
        # 卖出（有持仓时）
        proceeds = st["cash"]
        sells = []
        for c, p in list(st["positions"].items()):
            series = navs.get(c) or load_nav(c)
            fd = fill_date(series, fund_as_of)
            if fd is None:
                print(f"  !! {c} 在信号净值日 {fund_as_of} 之后尚无新净值（基金 T+1 公布）—— 待下一交易日")
                return
            nav = series.get(fd)
            if nav is None:
                print(f"  !! {c} 无 {fd} 净值，持仓保持")
                return
            amt = p["amount"] * (1 - SLIP)
            proceeds += amt
            sells.append((c, fd, nav, amt))
        # 买入：等权
        per = proceeds / len(codes)
        buys, used = [], 0.0
        for c in codes:
            series = navs[c]
            fd = fill_date(series, fund_as_of)
            if fd is None:
                print(f"  !! {c} 在信号净值日 {fund_as_of} 之后尚无新净值 —— 待下一交易日")
                return
            nav = series.get(fd)
            if nav is None or nav <= 0:
                print(f"  !! {c} 无 {fd} 净值，跳过该基金")
                continue
            amt = per * (1 - SLIP)
            buys.append((c, fd, nav, amt))
            used += per
        cash_left = proceeds - used
        if not buys:
            print("!! 无可用买入净值，本轮不换仓")
            return
        if dry:
            print(f"[dry] 将卖出 {len(sells)} 只、买入 {len(buys)} 只（新持仓 {len(codes)} 只目标），剩现金 {cash_left:.2f}")
            for c, fd, nav, amt in buys[:6]:
                print(f"    买 {c} @ {fd} 净值 {nav} 金额 {amt:.0f}")
            print(f"[dry] 未写盘。")
            return
        st["positions"] = {c: {"nav": nav, "amount": amt, "cost_nav": nav, "name": c} for c, fd, nav, amt in buys}
        st["cash"] = round(cash_left, 2)
        st["last_rebal"] = buys[0][1]
        for c, fd, nav, amt in sells:
            st["fills"].append({"date": fd, "code": c, "nav": nav, "amount": round(amt, 2), "side": "sell"})
        for c, fd, nav, amt in buys:
            st["fills"].append({"date": fd, "code": c, "nav": nav, "amount": round(amt, 2), "side": "buy"})
        st["events"].append({"date": buys[0][1], "event": f"换仓：卖 {len(sells)} 买 {len(buys)}（{regime}）；target={codes}"})
        print(f"  ✅ 换仓完成：卖 {len(sells)} 只、买 {len(buys)} 只，剩现金 {cash_left:.2f}（成交净值日 {buys[0][1]}）")

    # ---- mark 净值 ----
    mv = 0.0
    for c, p in st["positions"].items():
        series = navs.get(c) or load_nav(c)
        if series:
            last_d = max(series)
            cur = series[last_d]
            p["last_nav"] = cur
            p["last_nav_date"] = last_d
            mv += p["amount"] * (cur / p["cost_nav"])
    nav_now = st["cash"] + mv
    if latest and (not st["nav_history"] or st["nav_history"][-1]["date"] != latest):
        st["nav_history"].append({"date": latest, "nav": round(nav_now, 2),
                                  "ret": round(nav_now / INIT_CASH - 1, 5), "positions": len(st["positions"])})
    elif latest and st["nav_history"]:
        st["nav_history"][-1].update({"nav": round(nav_now, 2), "ret": round(nav_now / INIT_CASH - 1, 5),
                                      "positions": len(st["positions"])})
    st["events"] = st["events"][-40:]
    print(f"  持仓 {len(st['positions'])} 只 | 现金 {st['cash']:.2f} + 市值 {mv:.2f} = 净值 {nav_now:.2f}"
          f"（{nav_now/INIT_CASH-1:+.2%}）| 净值日 {latest}")
    if dry:
        print("[dry] 未写盘")
        return
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {STATE.name}")


if __name__ == "__main__":
    main()
