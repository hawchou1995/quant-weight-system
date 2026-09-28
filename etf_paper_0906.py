# -*- coding: utf-8 -*-
"""
ETF 动量轮动 + 组合层波动率缩放 模拟盘验证器（2026-09-06 起）
====================================================================
目的：前向验证「核心动量不变 + 目标波动率 12%（20日窗口）」配置是否在真实
时间线上复现回测结论（回测证据：etf_momentum_volscale_0906.py 6/6 过验收门）。

实现思路（避免自造轮子）：
  - 信号/缩放/费用全部复用回测引擎 run_volscale(CORE,20,True,0.5,cost,target,vol_win)
    的"权重事件表"（signals at month-end → exec T+1 open 两段式），回测引擎已被
    基线复现校验（total 1.3544 精确吻合）——模拟盘只在前端把权重映射为真实份额。
  - 初始化：run_volscale 跑全历史，取最新权重 → 映射为 ¥100,000 组合的真实份额
    （100 份取整，买卖各 0.1% 成本、现金按货基 2%），NAV 起点 ¥100,000。
  - 交叉验证：模拟盘（份额法）最近 20 日 NAV 日变动 vs 回测 NAV 日变动，
    应几乎一致（份额取整允许 <0.5% 平均偏差）；这是"模拟盘=回测"的硬证据。
  - 前向：每个交易日收盘后运行 → 用最新数据估值；月末信号日生成挂单，次日开盘执行。

用法：
  python etf_paper_0906.py --init     # 初始化（回填到数据末端 + 交叉验证）
  python etf_paper_0906.py            # 日更（幂等，同一交易日跳过）
  python etf_paper_0906.py --dry      # 只扫描不落盘

状态：etf_paper_state.json
"""
import os, sys, json, time
from pathlib import Path
import pandas as pd
import numpy as np

# 2026-09-28（R-etf-chain-0928）：BASE 从文件位置解析（本文件在仓库根）+ 旧路径兜底 → 云端可移植
BASE = Path(__file__).resolve().parent
_LEGACY = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
if not (BASE / "data_full").is_dir() and (_LEGACY / "data_full").is_dir():
    BASE = _LEGACY
sys.path.insert(0, str(BASE / "backtest"))
from etf_momentum_volscale_0906 import run_volscale
from etf_momentum_20d_0906 import CORE

DATA_DIR = BASE / "data_full"
OUT = BASE / "backtest" / "etf_rotation_out"
STATE = BASE / "etf_paper_state.json"

TARGET_VOL = 0.12
VOL_WIN = 20
LOOKBACK = 20
W1 = 0.5
CASH_ANN = 0.02
COST = 0.001
INIT_CAP = 100000.0
SCALE_MIN, SCALE_MAX = 0.25, 1.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_prices():
    prices = {}
    for c in CORE:
        f = DATA_DIR / f"{c}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, usecols=["date", "open", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        if len(df) > LOOKBACK + 5:
            prices[c] = df
    return prices


def get_open(code, dt, prices):
    d = prices.get(code)
    if d is None or dt not in d.index:
        return None
    o = float(d.loc[dt, "open"])
    return o if o > 0 else None


def get_close(code, dt, prices):
    d = prices.get(code)
    if d is None or dt not in d.index:
        return None
    return float(d.loc[dt, "close"])


def cash_daily():
    return (1 + CASH_ANN) ** (1 / 252) - 1


def signal_day(prices, idx, sig_dt):
    """复刻回测 run_volscale 的月末信号逻辑：
    20 日动量（close_T/close_{T-20}-1）→ top1<0 空仓 → 前2等权 →
    组合层波动率缩放 clamp(目标波动率/实现波动率, 25%, 100%)。
    返回 (new_weights, scale) 或 None（数据不足）。"""
    moms = {}
    for c, d in prices.items():
        if sig_dt not in d.index:
            continue
        pos = d.index.get_loc(sig_dt)
        if pos < LOOKBACK:
            continue
        moms[c] = d["close"].iloc[pos] / d["close"].iloc[pos - LOOKBACK] - 1
    if len(moms) < 2:
        return None
    ranked = sorted(moms.items(), key=lambda x: -x[1])
    top1 = ranked[0][1]
    if top1 < 0:
        return {}, 0.0
    top2 = [ranked[0][0], ranked[1][0]]
    # 实现波动率：目标组合（前2等权合成分收益）过去 VOL_WIN 日年化
    rets = None
    for c in top2:
        d = prices[c]
        pos = d.index.get_loc(sig_dt)
        lo = max(0, pos - VOL_WIN)
        closes = d["close"].iloc[lo:pos + 1]
        r = closes.pct_change().dropna() * 0.5
        rets = r if rets is None else rets + r  # 自动按索引对齐
    if rets is not None and len(rets.dropna()) >= 5:
        rv = rets.std(ddof=1) * np.sqrt(252)
        scale = min(SCALE_MAX, max(SCALE_MIN, TARGET_VOL / rv)) if rv > 0 else 1.0
    else:
        scale = 1.0
    new_pos = {c: scale * (W1 if i == 0 else 1 - W1) for i, c in enumerate(top2)}
    return new_pos, scale


def build_positions(weights, prices, dt):
    """权重 → 真实份额（100 份取整），返回 (positions, cash)"""
    cash = INIT_CAP
    positions = []
    tot_w = sum(weights.values())
    for c, w in weights.items():
        if w <= 0:
            continue
        px = get_open(c, dt, prices) or get_close(c, dt, prices)
        if px is None or px <= 0:
            continue
        alloc = INIT_CAP * w
        shares = int(alloc / px / 100) * 100
        if shares <= 0:
            continue
        cost = shares * px * (1 + COST)
        if cost > cash:
            continue
        cash -= cost
        positions.append({"code": c, "entry_date": str(dt.date()),
                          "entry_px": round(px * (1 + COST), 4), "shares": shares,
                          "weight": round(w, 4)})
    return positions, round(cash, 2)


def nav_value(positions, cash, prices, dt):
    pos_val = 0.0
    for p in positions:
        c = get_close(p["code"], dt, prices)
        px = c if c is not None else p.get("last_close", p["entry_px"])
        pos_val += p["shares"] * px
        p["last_close"] = px
    return cash + pos_val, pos_val


def load_state():
    if STATE.exists():
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # 状态文件损坏（如上次写盘中断）：备份并干净重启——模拟盘不因一次崩溃丢数据
            bak = STATE.with_suffix(".json.bak_corrupt")
            try:
                import shutil
                shutil.copy2(STATE, bak)
                os.remove(STATE)
                log(f"⚠ 状态文件损坏（{e}），已备份为 {bak.name}，干净重启")
            except Exception:
                log(f"⚠ 状态文件损坏（{e}），直接忽略")
    return {"cash": INIT_CAP, "positions": [], "pending": None, "nav_history": [],
            "trades": [], "start": None, "last_signal": None}


def save_state(st):
    def _clean(o):
        if isinstance(o, dict):
            return {str(k): _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, (pd.Timestamp, np.datetime64)):
            return str(o)
        if isinstance(o, (np.floating, np.integer)):
            return float(o) if isinstance(o, np.floating) else int(o)
        return o
    json.dump(_clean(st), open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def init(prices, verbose=True):
    """初始化：全历史回测取最新权重 → 映射份额；交叉验证最近 20 日 NAV 变动"""
    nav, trades, scales = run_volscale(CORE, LOOKBACK, True, W1, COST, TARGET_VOL, VOL_WIN)
    if nav is None or len(nav) < 60:
        log("回测引擎返回空，初始化失败")
        return None
    # 最新权重 = 最后一次调仓事件的目标权重（无明显信号则用当前持仓）
    last_w = {}
    for t in reversed(trades):
        last_w = t["to"]
        break
    last_dt = nav.index[-1]
    log(f"回测末端 = {last_dt.date()}，最新权重 = " +
        (json.dumps(last_w, ensure_ascii=False) if last_w else "空仓"))
    positions, cash = build_positions(last_w, prices, last_dt)
    st = {"cash": cash, "positions": positions, "pending": None, "nav_history": [],
          "trades": [{"date": str(last_dt.date()), "type": "init",
                      "to": last_w, "scales": scales[-1] if scales else None}],
          "start": str(last_dt.date()), "last_signal": None}
    # 交叉验证：份额法最近 20 日 NAV 变动 vs 回测 NAV 变动
    seg = nav.tail(20)
    daily_bt = seg.pct_change().dropna().values
    sim_vals = []
    for dt in seg.index:
        v, _ = nav_value(positions, cash, prices, dt)
        sim_vals.append(v)
    sim_vals = pd.Series(sim_vals, index=seg.index)
    daily_sim = sim_vals.pct_change().dropna().values
    diff = daily_sim - daily_bt
    log(f"交叉验证（最近 {len(daily_bt)} 日份额法 vs 回测）: 平均日收益差 = {diff.mean()*100:+.4f}pp，"
        f"最大差 = {np.abs(diff).max()*100:.4f}pp，日收益差均值绝对值 = {np.abs(diff).mean()*100:.4f}pp")
    ok = abs(np.abs(diff).mean()) < 0.005  # <0.5pp/日 合计级
    log(f"  验证结论: {'PASS（份额取整偏差在容差内，模拟盘=回测逻辑）' if ok else 'FAIL（偏差超出容差，检查实现）'}")
    st["nav_history"].append({"date": str(last_dt.date()), "nav": round(sim_vals.iloc[-1], 2),
                              "cash": cash, "pos_val": round(sim_vals.iloc[-1] - cash, 2),
                              "n_pos": len(positions)})
    return st


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    reset = "--reset" in args
    do_init = "--init" in args

    prices = load_prices()
    if len(prices) < 2:
        log("数据不足，退出")
        return
    idx = None
    for d in prices.values():
        idx = d.index if idx is None else idx.intersection(d.index)
    idx = idx.sort_values()
    today = idx[-1]
    log(f"数据末端 = {today.date()}，可用标的 = {len(prices)}/{len(CORE)}")

    st = load_state()
    if do_init or reset or not st.get("nav_history"):
        st = init(prices)
        if st is None:
            return
        # 初始化只建最近一次调仓截面；下轮调仓前可观测数据不足时用空仓 + 现金（保守）
        # （8/31 → 9/1 已执行，st 里的 positions=黄金+中证500 即对应回测最新事件）
        save_state(st)
        log(f"初始化完成：{len(st['positions'])} 仓，现金 ¥{st['cash']:,.0f}，"
            f"NAV ¥{st['nav_history'][-1]['nav']:,.0f}")
        return

    # 幂等：今日已记录则跳过
    if any(h["date"] == str(today.date()) for h in st["nav_history"]):
        log(f"今日 {today.date()} 已记录，跳过（幂等守卫）")
        return

    # ===== 前向推进：1) 检查挂单（上一月末信号 → 今日（或最近完成日）开盘执行）===
    if st.get("pending"):
        pend = st["pending"]
        exec_for = pend.get("exec_date")
        if exec_for is not None and today >= pd.Timestamp(exec_for):
            pend_weights = pend.get("weights", {})
            # 全部清仓旧持仓 → 买入新权重（按 T+1 开盘）
            log(f"执行挂单（信号 {pend.get('signal_date')}，开仓日 {exec_for}）：")
            for p in st["positions"]:
                # 按入场价+当日开盘卖（简化：本金回笼）
                px = get_open(p["code"], today, prices) or p.get("last_close", p["entry_px"])
                st["cash"] += p["shares"] * px * (1 - COST)
                log(f"  卖出 {p['code']} @ {px:.3f} × {p['shares']}")
            st["positions"] = []
            new_pos, new_cash = build_positions(pend_weights, prices, today)
            st["positions"] = new_pos
            st["cash"] = new_cash
            st["trades"].append({"date": str(today.date()), "type": "rebalance",
                                 "signal": pend.get("signal_date"),
                                 "to": pend_weights,
                                 "scale": pend.get("scale")})
            st["pending"] = None
            log(f"  调仓完成：{len(new_pos)} 仓（权重 {json.dumps(pend_weights, ensure_ascii=False)}）")
        else:
            log(f"挂单未到执行日（{exec_for}），今日仅估值")

    # ===== 2) 每日估值 =====
    nav, pos_val = nav_value(st["positions"], st["cash"], prices, today)
    st["nav_history"].append({"date": str(today.date()), "nav": round(nav, 2),
                              "cash": round(st["cash"], 2), "pos_val": round(pos_val, 2),
                              "n_pos": len(st["positions"])})
    log(f"每日估值：NAV ¥{nav:,.0f}（现金 ¥{st['cash']:,.0f} + 持仓 ¥{pos_val:,.0f}，"
        f"{len(st['positions'])} 仓）累计收益 {(nav/INIT_CAP-1)*100:+.2f}%")

    # ===== 3) 月末信号扫描（今日为近期最后交易日 → 生成次日挂单）=====
    if today >= idx[-1]:
        pass
    m_days = [d for d in idx if d.to_period("M") == today.to_period("M")]
    is_last_trade_day_of_month = (len(m_days) > 0 and today == m_days[-1])
    if not is_last_trade_day_of_month and today.day < 25:
        log("  非月末，无调仓信号")
    else:
        # 有足够数据后：今日为月末 → 收盘计算信号 → 明日（下一交易日）开盘执行
        res = signal_day(prices, idx, today)
        if res is None:
            log("  月末信号不足（<2 只有动量），保持当前持仓")
        else:
            nw, sc = res
            nxt = idx[idx > today]
            if len(nxt) == 0:
                log("  数据末端=月末，下个执行日数据未更新（明日再跑）")
            else:
                exec_dt = nxt[0]
                st["pending"] = {"signal_date": str(today.date()), "exec_date": str(exec_dt.date()),
                                 "weights": {k: float(v) for k, v in nw.items()}, "scale": float(sc)}
                log(f"  生成挂单：信号 {today.date()} → 执行 {exec_dt.date()}，"
                    f"权重 {json.dumps(st['pending']['weights'], ensure_ascii=False)}（scale {sc:.3f}）")

    if not dry:
        save_state(st)
        log(f"状态已保存 → {STATE.name}")
    else:
        log("--dry 模式：未落盘")


if __name__ == "__main__":
    main()
