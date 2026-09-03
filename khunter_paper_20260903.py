# -*- coding: utf-8 -*-
"""
KHunter 优化配置模拟盘跟踪器（2026-09-03 起）
====================================================================
目的：实盘验证（小仓位模拟盘）——在切换生产前，用新配置跑真实前向信号跟踪。

配置（回测证据：khunter_opt5 + khunter_disaster_20260903）：
  - 入场：KHunter 15 信号命中(T) + RSI_T<35 + 熊市限定(hs300<MA60 T) + 主板 + 收盘价≥3元
  - 出场：RSI_T>55（T 确认 → T+1 开盘执行）
  - 仓位：最多 5 仓 × 每仓 ¥20,000（初始资金 ¥100,000，小仓位）
  - 成本：买 0.575% + 卖 0.575%（与回测一致）
  - 时序：今日 T 收盘确认 → 明日 T+1 开盘执行（生产口径，与回测「T-1 确认→T 执行」对齐）

用法：
  python khunter_paper_20260903.py            # 正常日更（收盘后跑，A 轨 RSI_SELL=55）
  python khunter_paper_20260903.py --dry      # 只扫描信号不落盘
  python khunter_paper_20260903.py --reset    # 清空状态重新开始
  # 多轨（2026-09-03 12:15 加，A/C 并行前向验证）：
  python khunter_paper_20260903.py --state khunter_paper_state_c --rsi-sell 50 --reset   # C 轨（OB50+低价3元）

状态：<state>.json（positions/pending/nav_history；A 轨默认 khunter_paper_state.json，C 轨 khunter_paper_state_c.json）
"""
import os, sys, json, time
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE / "backtest"))
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T

STATE = BASE / "khunter_paper_state.json"
DATA_DIR = BASE / "data_full"
IDX_CSV = BASE / "index_000300.csv"
NAMES = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
AMT20_MIN = 3e7   # 生产流动性硬过滤：20日均成交额 ≥ 3000万

# ===== 配置（新优化配置，待生产切换拍板）=====
# ⚠ 2026-09-03 牛熊分域投产（Phase 10 HYBRIDv2 定稿）：入场阈值按 regime 分域
RSI_BUY = 35          # 熊市入场：RSI_T < 35（生产现状）
RSI_BUY_BULL = 30     # 牛市入场：RSI_T < 30（定稿式 osl30）
RSI_SELL = 55         # 熊市出场：RSI_T > 55（A 版）
RSI_SELL_BULL = 75    # 牛市出场：RSI_T > 75（定稿式 ob75）
LOW_PRICE = 3.0       # 低价过滤（仅熊市）：确认日收盘 ≥ 3 元
LOW_PRICE_BULL = None # 牛市无低价过滤
N_SLOTS = 5           # 最多 5 仓
POS_SIZE = 20000.0    # 每仓 ¥20,000
INIT_CAP = 100000.0   # 初始资金 ¥100,000
HOLD_MAX = 25         # 持有上限（2026-09-03 三设施回测 Phase 8/9 定稿）：距入场 ≥25 交易日收盘 → 次日开盘卖
COST_BUY, COST_SELL = 0.00575, 0.00575

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def load_index():
    idx = pd.read_csv(IDX_CSV)
    idx['date'] = pd.to_datetime(idx['date'])
    idx = idx.sort_values('date').reset_index(drop=True)
    idx['ma20'] = idx['close'].rolling(20, min_periods=1).mean()
    idx['ma60'] = idx['close'].rolling(60, min_periods=1).mean()
    idx['is_bear'] = (idx['close'] < idx['ma60']).values
    idx['bull_ma20'] = (idx['close'] > idx['ma20']).values
    return idx

def khunter_sig(ddf, as_of):
    """复刻 build_short_pool._khunter_sig（今日 T 视角：T 确认 → T+1 执行）"""
    d = ddf[['open', 'high', 'low', 'close', 'volume']].copy()
    d.index.name = None
    d['date'] = d.index
    d = d.sort_values('date').reset_index(drop=True)
    cut = pd.Timestamp(as_of)
    d = d[d['date'] <= cut].reset_index(drop=True)
    if len(d) < 2:
        return None
    r = T.prep(d)
    sig_any = np.zeros(len(d), dtype=bool)
    for _name, _fn in K.SIGNALS.items():
        try:
            _sv = _fn(r)
            if _sv.any():
                sig_any |= _sv.values
        except Exception:
            continue
    i = len(d) - 1
    rsi_now = r['rsi'].iloc[i]
    return {
        'hit': bool(sig_any[i]),
        'rsi': (float(rsi_now) if not pd.isna(rsi_now) else None),
        'close': float(d['close'].iloc[i]),
        'open_next': None,  # T+1 开盘在下次运行时填
    }

def scan_today(idx, today):
    """扫描今日 T 信号：入场候选（hit & 分域 RSI & 分域低价 & 分域门控）与持仓出场（分域 RSI）
    分域（Phase 10 HYBRIDv2）：
      🐻 熊市(hs300<MA60)：rsi<35 + close≥3 + 可买
      🌞 牛市(hs300>MA20)：rsi<30 + 无低价 + 可买
      🌙 弱牛回调(MA20下/MA60上)：不开仓（仅观察/卖出）
    宇宙过滤镜像生产 build_short_pool：主板 + 剔ST/退市 + 剔停牌 + 20日均成交额≥3000万"""
    idx = idx.sort_values('date').reset_index(drop=True)
    d_today = idx.loc[idx['date'] == today]
    bear_t = bool(d_today['is_bear'].iloc[0]) if len(d_today) else False
    # 牛市判定：hs300 > MA20（与生产 _in_mkt 同口径；加载时已算 ma20）
    bull_t = bool(d_today['bull_ma20'].iloc[0]) if len(d_today) else False
    buys, sells = [], []
    n_stock = 0
    mkt_max = today
    for f in sorted(DATA_DIR.glob("*.csv")):
        code = f.stem
        if not (code.startswith("sh60") or code.startswith("sz00")):
            continue
        if code.startswith(("sh688", "sh689", "sz30")):
            continue
        nm = NAMES.get(code, code[-6:])
        if "ST" in nm or nm.startswith("S") or "退" in nm:
            continue
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
        except Exception:
            continue
        if df is None or len(df) < 70:
            continue
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        # 停牌判定（镜像 _is_suspended）：最新行零成交/零价，或日期落后 >1 自然日
        _last = df.iloc[-1]
        if float(_last.get("volume", 0) or 0) == 0 or float(_last.get("open", 0) or 0) == 0 \
           or float(_last.get("high", _last.get("low", 0)) or 0) == 0:
            continue
        if (mkt_max - _last["date"]).days > 1:
            continue
        # 流动性硬过滤：20日均成交额 ≥ 3000万（生产口径）
        if "amount" in df.columns:
            amt20 = df["amount"].tail(20).mean()
            if pd.isna(amt20) or amt20 < AMT20_MIN:
                continue
        df = df.set_index('date')
        sig = khunter_sig(df, today)
        if sig is None:
            continue
        n_stock += 1
        # 分域阈值
        if bear_t:
            osl, low = RSI_BUY, LOW_PRICE
        elif bull_t:
            osl, low = RSI_BUY_BULL, LOW_PRICE_BULL
        else:
            osl, low = None, None  # 弱牛回调：不开仓
        if sig['hit'] and sig['rsi'] is not None and osl is not None and sig['rsi'] < osl:
            if low is None or sig['close'] >= low:
                buys.append({'code': code, 'rsi': sig['rsi'], 'close': sig['close'], 'regime': 'bear' if bear_t else 'bull'})
        # 出场分域：熊 rsi>55 / 牛 rsi>75
        sell_thr = RSI_SELL if bear_t else (RSI_SELL_BULL if bull_t else RSI_SELL)
        if sig['rsi'] is not None and sig['rsi'] > sell_thr:
            sells.append(code)
    return buys, sells, bear_t, bull_t, n_stock

def load_state():
    if STATE.exists():
        return json.load(open(STATE, encoding="utf-8"))
    return {"cash": INIT_CAP, "positions": [], "pending_buys": [], "pending_sells": [],
            "nav_history": [], "trades": [], "start": None}

def save_state(st):
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def get_open_px(code, today):
    """取 T+1 开盘价（执行日）"""
    f = DATA_DIR / f"{code}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, encoding="utf-8-sig")
    df['date'] = pd.to_datetime(df['date'])
    row = df[df['date'] == pd.Timestamp(today)]
    if len(row) == 0:
        return None
    o = float(row['open'].iloc[0])
    return o if o > 0 else None

def get_close_px(code, today):
    f = DATA_DIR / f"{code}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, encoding="utf-8-sig")
    df['date'] = pd.to_datetime(df['date'])
    row = df[df['date'] == pd.Timestamp(today)]
    if len(row) == 0:
        return None
    c = float(row['close'].iloc[0])
    return c if c > 0 else None

def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    reset = "--reset" in args
    # 多轨支持：--state <名称> 切换状态文件（A 轨默认），--rsi-sell/--low 覆盖出场阈值/低价线
    global STATE, RSI_SELL, LOW_PRICE
    if "--state" in args:
        STATE = BASE / f"{args[args.index('--state') + 1]}.json"
    if "--rsi-sell" in args:
        RSI_SELL = float(args[args.index('--rsi-sell') + 1])
    if "--low" in args:
        LOW_PRICE = float(args[args.index('--low') + 1])
    track = "A" if (RSI_SELL == 55) else ("C" if RSI_SELL == 50 else f"S{RSI_SELL:.0f}")
    log(f"轨[{track}] RSI_SELL={RSI_SELL:.0f} LOW_PRICE={LOW_PRICE:.1f} state={STATE.name}")

    idx = load_index()
    today = idx['date'].iloc[-1]
    _bt = bool(idx['is_bear'].iloc[-1]); _bl = bool(idx['bull_ma20'].iloc[-1])
    _regime = "🐻 熊市" if _bt else ("🌞 牛市" if _bl else "🌙 弱牛回调")
    log(f"确认日 T = {today.date()}  regime = {_regime}（熊MA60={_bt}, 牛MA20={_bl}）")

    st = load_state()
    if reset:
        st = {"cash": INIT_CAP, "positions": [], "pending_buys": [], "pending_sells": [],
              "nav_history": [], "trades": [], "start": str(today.date())}
        log("状态已重置")
    # 幂等守卫：今日已在 nav_history 则跳过（防同日重复运行/数据未更新时重扫同日）
    if not reset and any(h["date"] == str(today.date()) for h in st["nav_history"]):
        log(f"今日 {today.date()} 已记录，跳过（幂等守卫）")
        return

    # ===== 1) 执行昨日挂单（今日 T+1 开盘）=====
    if st["pending_buys"] or st["pending_sells"]:
        log(f"执行挂单：买 {len(st['pending_buys'])} 卖 {len(st['pending_sells'])}")
    for code in st["pending_sells"]:
        o = get_open_px(code, today)
        if o is None:
            log(f"  ⚠ {code} 今日无开盘数据（停牌？），挂单保留")
            continue
        pos = next((p for p in st["positions"] if p["code"] == code), None)
        if pos is None:
            continue
        px = o * (1 - COST_SELL)
        ret = px / pos["entry_px"] - 1
        st["cash"] += pos["shares"] * px
        reason = f"hold{HOLD_MAX}" if code in st.get("hold_over_codes", []) else f"rsi>{RSI_SELL:.0f}"
        st["trades"].append({"code": code, "side": "sell", "date": str(today.date()),
                             "px": round(px, 4), "ret": round(ret, 4),
                             "reason": reason, "hold_days": pos["hold_days"]})
        log(f"  ✅ 卖出 {code} @ {px:.3f} ({reason} ret {ret*100:+.2f}%)")
        st["positions"] = [p for p in st["positions"] if p["code"] != code]
    st["pending_sells"] = []

    for b in st["pending_buys"]:
        code = b["code"]
        if len(st["positions"]) >= N_SLOTS:
            log(f"  ⚠ {code} 满仓跳过（{N_SLOTS} 仓已满）")
            continue
        o = get_open_px(code, today)
        if o is None:
            log(f"  ⚠ {code} 今日无开盘数据（停牌？），挂单保留")
            st["pending_buys"].remove(b)
            st["pending_buys"].append(b)  # 移到队尾重试
            continue
        px = o * (1 + COST_BUY)
        shares = int(POS_SIZE / px / 100) * 100
        if shares <= 0 or shares * px > st["cash"]:
            log(f"  ⚠ {code} 资金不足或零股，跳过")
            continue
        st["cash"] -= shares * px
        st["positions"].append({"code": code, "entry_date": str(today.date()),
                                "entry_px": round(px, 4), "shares": shares,
                                "rsi_entry": b["rsi"], "hold_days": 0})
        st["trades"].append({"code": code, "side": "buy", "date": str(today.date()),
                             "px": round(px, 4), "reason": f"khunter_hit_rsi{b['regime']}"})
        log(f"  ✅ 买入 {code} @ {px:.3f} × {shares} 股（¥{shares*px:,.0f}）")
    st["pending_buys"] = []

    # ===== 2) 持仓标记 + 持仓天数 =====
    for p in st["positions"]:
        p["hold_days"] += 1
        c = get_close_px(p["code"], today)
        p["last_close"] = c if c else p.get("last_close", p["entry_px"])

    # ===== 2.5) 持有上限（回测 Phase 8/9：hold25 唯一必做补丁）=====
    # 回测口径：距 entry_i ≥ hold_max 交易日收盘 → 次日开盘卖（与上一步 hold_days 自增后比较，T 收盘检查）
    hold_over = [p["code"] for p in st["positions"] if p["hold_days"] >= HOLD_MAX]
    for c in hold_over:
        _p = next(p for p in st["positions"] if p["code"] == c)
        log(f"  ⏰ 持有上限 {c} 达 {HOLD_MAX} 交易日（{_p['hold_days']}），明日开盘卖出")
    st["hold_over_codes"] = hold_over

    # ===== 3) 扫描今日信号（明日执行）=====
    buys, sells, bear_t, bull_t, n_stock = scan_today(idx, today)
    held_codes = {p["code"] for p in st["positions"]}
    held_sells = [c for c in sells if c in held_codes]
    held_sells += [c for c in st.get("hold_over_codes", []) if c in held_codes]
    log(f"扫描 {n_stock} 只主板：入场候选 {len(buys)} 只 / RSI>分域阈值 {len(sells)} 只（其中持仓 {len(held_sells)} 只）")
    for b in buys:
        log(f"  📈 买入候选 {b['code']} (RSI {b['rsi']:.1f}, 收盘 {b['close']:.2f})")
    for c in held_sells:
        r = "持有上限" if c in st.get("hold_over_codes", []) else f"RSI>{RSI_SELL:.0f}"
        log(f"  📉 卖出候选 {c} ({r})")
    st["pending_buys"] = [{"code": b["code"], "rsi": b["rsi"], "close": b["close"]} for b in buys]
    st["pending_sells"] = held_sells

    # ===== 4) 净值 =====
    pos_val = sum(p["shares"] * p.get("last_close", p["entry_px"]) for p in st["positions"])
    nav = st["cash"] + pos_val
    st["nav_history"].append({"date": str(today.date()), "nav": round(nav, 2),
                              "cash": round(st["cash"], 2), "pos_val": round(pos_val, 2),
                              "n_pos": len(st["positions"]), "bear": bool(bear_t)})
    log(f"净值 ¥{nav:,.0f}（现金 ¥{st['cash']:,.0f} + 持仓 ¥{pos_val:,.0f}，{len(st['positions'])} 仓）"
        f"  累计收益 {(nav/INIT_CAP-1)*100:+.2f}%")

    if not dry:
        save_state(st)
        log(f"状态已保存 → {STATE.name}")
    else:
        log("--dry 模式：未落盘")

if __name__ == "__main__":
    main()
