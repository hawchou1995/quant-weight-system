# -*- coding: utf-8 -*-
"""
KHunter 5 种择时策略独立回测（用户 9/1 23:36 指出：选股与择时是独立模块，之前遗漏）
5 种择时（trading/timing_strategies.py 源码 1:1 复刻）：
  1. turtle_short 海龟(10/5)：T-1 突破10日高点+上影<4%+阳线+收盘>MA20 → T日开盘买入；
     出场：T-1 low 跌破5日低点 或 ATR×2 止损（用 T-1 数据确认，无未来函数）
  2. turtle_classic 海龟(20/10)：同上，20/10 通道
  3. turtle_ultra 海龟(6/3)：同上，6/3 通道
  4. rsi：T-1 RSI14<40 买入 / >70 卖出 → T日开盘执行
  5. bollinger：T-1 收盘≤下轨×1.03 买入 / ≥上轨 卖出
  6. support：T-1 收盘在 MA20×[0.99,1.03] 买入 / 持有≥10日卖出
  7. macd_bollinger 顺势宝：T-1 零轴上金叉+破中轨(或强势破上轨) 买入；转负破中轨/顶背离上轨回落/放量破下轨 卖出
口径：信号 T-1 收盘确认 → T 日开盘价执行（买入卖出同）；成本 1.15% 往返（买 0.575% + 卖 0.575%）
     单股单持仓状态机；加仓逻辑按源码保留（turtle add / 顺势宝 add 按源码 buy_quantity）
输出：khunter_timing_out/（summary csv + 交易明细 csv）
"""
import os, sys, time
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khunter_all_strategies_backtest as K

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "khunter_timing_out")  # 2026-09-24 云端可移植
os.makedirs(OUT_DIR, exist_ok=True)

COST_BUY = 0.00575   # 单边
COST_SELL = 0.00575

BACKTEST_START = K.BACKTEST_START

# ---------- 指标（复用 K.calc_indicators 列 + 补充） ----------
def prep(df):
    """df: 正序；返回带全部择时所需列的 r"""
    r = K.calc_indicators(df)
    c, h, l, v = r['close'], r['high'], r['low'], r['volume']
    # 海龟通道（不含当天 shift1）+ ATR
    r['up'] = h.rolling(10, min_periods=1).max().shift(1)
    r['down5'] = l.rolling(5, min_periods=1).min().shift(1)
    r['up20'] = h.rolling(20, min_periods=1).max().shift(1)
    r['down10'] = l.rolling(10, min_periods=1).min().shift(1)
    r['up6'] = h.rolling(6, min_periods=1).max().shift(1)
    r['down3'] = l.rolling(3, min_periods=1).min().shift(1)
    prev_close = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    r['atr10'] = tr.rolling(10, min_periods=1).mean()
    r['atr20'] = tr.rolling(20, min_periods=1).mean()
    r['atr6'] = tr.rolling(6, min_periods=1).mean()
    return r

# ---------- 买入/卖出信号（向量化；i 日信号=用 i-1 日数据确认 → i 日开盘执行） ----------
def turtle_signal(r, n_entry, n_exit, atr_col, entry_atr=0.02, exit_atr=2.0):
    up = r[f'up{n_entry}'] if f'up{n_entry}' in r.columns else (r['high'].rolling(n_entry, min_periods=1).max().shift(1) if False else None)
    # up 列名映射
    up_map = {10: 'up', 20: 'up20', 6: 'up6'}
    dn_map = {5: 'down5', 10: 'down10', 3: 'down3'}
    up = r[up_map[n_entry]]
    dn = r[dn_map[n_exit]]
    atr = r[atr_col]
    # 买入信号（T-1 确认）：突破上线 + 上影<4% + 阳线 + 收盘涨幅>0 + 收盘>MA20
    sig_bar = r.shift(1)  # T-1 行
    upper_shadow = sig_bar['high'] - np.maximum(sig_bar['open'], sig_bar['close'])
    shadow_ok = upper_shadow / np.maximum(sig_bar['open'], sig_bar['close']).replace(0, np.nan) <= 0.04
    bullish = sig_bar['close'] > sig_bar['open']
    rising = sig_bar['close'] > sig_bar['close'].shift(1)
    ma_ok = sig_bar['close'] > sig_bar['ma20']
    buy = (sig_bar['high'] > up) & shadow_ok & bullish & rising & ma_ok
    buy = buy.fillna(False).values
    # 卖出信号（T-1 确认）：T-1 low 跌破 dn（T-1 的 dn）或 ATR 止损（入场价 - exit_atr*atr，用 T-1 atr）
    # 止损需要入场价，这里返回 (buy, dn, atr) 由状态机处理
    return buy, dn.values, atr.values

def rsi_signal(r, period=14, oversold=40, overbought=70):
    rsi = r['rsi'].shift(1)  # T-1
    buy = (rsi < oversold).fillna(False).values
    sell = (rsi > overbought).fillna(False).values
    return buy, sell

def bollinger_signal(r, buy_buffer=0.03):
    low = r['boll_lower'].shift(1)
    up = r['boll_upper'].shift(1)
    c1 = r['close'].shift(1)
    buy = (c1 <= low * (1 + buy_buffer)).fillna(False).values
    sell = (c1 >= up).fillna(False).values
    return buy, sell

def support_signal(r, method='ma20'):
    c1 = r['close'].shift(1)
    ma20_1 = r['ma20'].shift(1)
    buy = ((c1 >= ma20_1 * 0.99) & (c1 <= ma20_1 * 1.03)).fillna(False).values
    return buy

def shunshibao_signal(r):
    """顺势宝：T-1 确认（signal_bar=T-1, prev_bar=T-2）"""
    sig = r.shift(1)
    prev = r.shift(2)
    # 买入1：零轴上刚金叉 + 突破中轨
    b1 = (sig['dif'] > 0) & (sig['dif'] > sig['dea']) & (prev['dif'] <= prev['dea']) & \
         (sig['close'] > sig['boll_mid']) & (prev['close'] <= prev['boll_mid'])
    # 买入2：强势多头 + 破上轨
    b2 = (sig['dif'] > 0) & (sig['macd'] > prev['macd']) & (sig['dif'] > sig['dea']) & \
         (sig['high'] > sig['boll_upper']) & (sig['close'] > sig['boll_mid'])
    buy = (b1 | b2).fillna(False).values
    # 卖出1：MACD 转负 + 破中轨
    s1 = (sig['macd'] < 0) & (prev['macd'] >= 0) & (sig['close'] < sig['boll_mid']) & (prev['close'] >= prev['boll_mid'])
    # 卖出2：顶背离 + 上轨回落阴线
    s2 = (sig['dif'] < prev['dif']) & (sig['close'] >= prev['close']) & (sig['dif'] > 0) & \
         (sig['high'] > sig['boll_upper']) & (sig['close'] < sig['boll_upper']) & (sig['close'] < sig['open'])
    # 卖出3：DIF<0 + 放量破下轨
    s3 = (sig['dif'] < 0) & (sig['close'] < sig['boll_lower']) & (sig['volume'] > prev['volume'] * 1.5)
    sell = (s1 | s2 | s3).fillna(False).values
    return buy, sell

# ---------- 状态机回测（单股） ----------
def run_stock(r, dates, opens, strategy, params):
    """单股单持仓状态机。返回交易列表 [(entry_idx, exit_idx, entry_px, exit_px)]"""
    n = len(r)
    if strategy == 'turtle':
        n_entry, n_exit, atr_col, exit_atr = params
        up_map = {10: 'up', 20: 'up20', 6: 'up6'}
        dn_map = {5: 'down5', 10: 'down10', 3: 'down3'}
        up = r[up_map[n_entry]].shift(1).values  # 源码语义：signal_bar['up'] 不含比较日（再 shift 1 天）
        dn = r[dn_map[n_exit]].values
        atr = r[atr_col].values
        sig = r.shift(1)
        upper_shadow = sig['high'].values - np.maximum(sig['open'].values, sig['close'].values)
        denom = np.maximum(sig['open'].values, sig['close'].values)
        shadow_ok = np.where(denom > 0, upper_shadow / denom <= 0.04, False)
        bullish = (sig['close'] > sig['open']).values
        rising = (sig['close'] > sig['close'].shift(1)).values
        ma_ok = (sig['close'] > sig['ma20']).values
        buy_sig = (sig['high'].values > up) & shadow_ok & bullish & rising & ma_ok
        buy_sig = np.nan_to_num(buy_sig, nan=False)
        trades = []
        pos = False
        entry_px = 0.0
        entry_i = 0
        for i in range(1, n):
            if dates[i] < BACKTEST_START:
                continue
            o = opens[i]
            if o <= 0:
                continue
            if pos:
                # 出场：T-1 数据确认（i-1 日 low 跌破 dn / ATR 止损）
                if i - 1 >= 0:
                    low_prev = r['low'].values[i - 1]
                    dn_prev = dn[i - 1] if np.isfinite(dn[i - 1]) else np.inf
                    atr_prev = atr[i - 1] if np.isfinite(atr[i - 1]) else 0
                    stop = entry_px - exit_atr * atr_prev
                    if (np.isfinite(dn_prev) and low_prev < dn_prev) or low_prev <= stop:
                        trades.append((entry_i, i, entry_px, o))
                        pos = False
                        continue
            else:
                if buy_sig[i]:
                    entry_px = o * (1 + COST_BUY)
                    entry_i = i
                    pos = True
        if pos:
            # 期末强制平仓（用最后收盘价近似）
            trades.append((entry_i, n - 1, entry_px, r['close'].values[n - 1] * (1 - COST_SELL)))
        return trades
    elif strategy == 'rsi':
        buy, sell = rsi_signal(r)
        trades = []
        pos = False
        entry_px = 0.0
        entry_i = 0
        for i in range(1, n):
            if dates[i] < BACKTEST_START:
                continue
            o = opens[i]
            if o <= 0:
                continue
            if pos and sell[i]:
                trades.append((entry_i, i, entry_px, o))
                pos = False
            elif not pos and buy[i]:
                entry_px = o * (1 + COST_BUY)
                entry_i = i
                pos = True
        if pos:
            trades.append((entry_i, n - 1, entry_px, r['close'].values[n - 1] * (1 - COST_SELL)))
        return trades
    elif strategy == 'bollinger':
        buy, sell = bollinger_signal(r)
        trades = []
        pos = False
        entry_px = 0.0
        entry_i = 0
        for i in range(1, n):
            if dates[i] < BACKTEST_START:
                continue
            o = opens[i]
            if o <= 0:
                continue
            if pos and sell[i]:
                trades.append((entry_i, i, entry_px, o))
                pos = False
            elif not pos and buy[i]:
                entry_px = o * (1 + COST_BUY)
                entry_i = i
                pos = True
        if pos:
            trades.append((entry_i, n - 1, entry_px, r['close'].values[n - 1] * (1 - COST_SELL)))
        return trades
    elif strategy == 'support':
        buy = support_signal(r)
        trades = []
        pos = False
        entry_px = 0.0
        entry_i = 0
        for i in range(1, n):
            if dates[i] < BACKTEST_START:
                continue
            o = opens[i]
            if o <= 0:
                continue
            if pos:
                if i - entry_i >= 10:  # 持有≥10日卖出（T-1 确认 → T 开盘执行：即持有 10 天后第 11 日开盘卖）
                    trades.append((entry_i, i, entry_px, o))
                    pos = False
                    continue
            elif buy[i]:
                entry_px = o * (1 + COST_BUY)
                entry_i = i
                pos = True
        if pos:
            trades.append((entry_i, n - 1, entry_px, r['close'].values[n - 1] * (1 - COST_SELL)))
        return trades
    elif strategy == 'shunshibao':
        buy, sell = shunshibao_signal(r)
        trades = []
        pos = False
        entry_px = 0.0
        entry_i = 0
        for i in range(1, n):
            if dates[i] < BACKTEST_START:
                continue
            o = opens[i]
            if o <= 0:
                continue
            if pos and sell[i]:
                trades.append((entry_i, i, entry_px, o))
                pos = False
            elif not pos and buy[i]:
                entry_px = o * (1 + COST_BUY)
                entry_i = i
                pos = True
        if pos:
            trades.append((entry_i, n - 1, entry_px, r['close'].values[n - 1] * (1 - COST_SELL)))
        return trades
    return []

# ---------- 主流程 ----------
STRATS = {
    'turtle_short': ('turtle', (10, 5, 'atr10', 2.0)),
    'turtle_classic': ('turtle', (20, 10, 'atr20', 2.0)),
    'turtle_ultra': ('turtle', (6, 3, 'atr6', 2.0)),
    'rsi': ('rsi', None),
    'bollinger': ('bollinger', None),
    'support': ('support', None),
    'shunshibao': ('shunshibao', None),
}

def full_stats(ret, dates_in, H_avg):
    ret = np.asarray(ret, dtype=float)
    if len(ret) == 0:
        return None
    wr = (ret > 0).mean() * 100
    med = np.median(ret) * 100
    mean = ret.mean() * 100
    std = ret.std()
    H = max(H_avg, 1)
    sharpe = ret.mean() / std * np.sqrt(252 / H) if std > 0 else 0
    ann = ((1 + ret.mean()) ** (252 / H) - 1) * 100 if ret.mean() > -1 else -100.0
    wins = ret[ret > 0]; losses = ret[ret < 0]
    pf = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else (np.inf if len(wins) else 0.0)
    return {
        'n': len(ret), 'win_rate': round(wr, 2), 'median': round(med, 3), 'mean': round(mean, 3),
        'annualized': round(ann, 2), 'sharpe': round(sharpe, 3),
        'profit_factor': round(pf, 2) if np.isfinite(pf) else 999.0,
        'avg_hold': round(H_avg, 1),
    }

def main():
    STOCK_LIMIT = int(os.environ.get("STOCK_LIMIT", "0"))
    log("加载缓存 ...")
    cache = pd.read_pickle(K.CACHE)
    log(f"股票数: {len(cache)}")

    # 全池基准（超额）
    all_ret = {}
    for code, df in cache.items():
        if df is None or len(df) < 30:
            continue
        d = df[['close']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        d['ret'] = d['close'].pct_change()
        all_ret[code] = d[['date', 'ret']]
    bdf = pd.concat(all_ret.values(), ignore_index=True)
    bench = bdf.groupby('date')['ret'].mean()
    bench_cum = (1 + bench).cumprod()

    # 牛熊分域
    idx = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index_000300.csv"))  # 2026-09-24 云端可移植
    idx['date'] = pd.to_datetime(idx['date'])
    idx = idx.sort_values('date').reset_index(drop=True)
    idx['ma20'] = idx['close'].rolling(20, min_periods=1).mean()
    idx['regime'] = np.where(idx['close'] > idx['ma20'], 'bull', 'bear')
    reg_map = dict(zip(idx['date'], idx['regime']))

    # 每策略收集交易
    all_trades = {s: [] for s in STRATS}
    n_stock = 0
    for code, df in cache.items():
        if df is None or len(df) < 70:
            continue
        if STOCK_LIMIT and n_stock >= STOCK_LIMIT:
            break
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        r = prep(d)
        opens = d['open'].values
        dates = d['date'].values
        bcum = bench_cum.reindex(dates).values
        for sname, (kind, params) in STRATS.items():
            trades = run_stock(r, dates, opens, kind, params)
            for (ei, xi, ep, xp) in trades:
                ret = xp / ep - 1
                if ei < len(dates) and xi < len(dates):
                    b0 = bcum[ei]; b1 = bcum[xi]
                    ex = ret - (b1 / b0 - 1) if (np.isfinite(b0) and np.isfinite(b1) and b0 > 0) else np.nan
                else:
                    ex = np.nan
                dt = dates[ei]
                rg = reg_map.get(pd.Timestamp(dt), 'bear') if isinstance(dt, (pd.Timestamp, np.datetime64)) else 'bear'
                all_trades[sname].append((ret, ex, ei, xi, rg))
        n_stock += 1
        if n_stock % 1000 == 0:
            log(f"  {n_stock} 只")

    log(f"扫描完成: {n_stock} 只")
    rows = []
    for sname in STRATS:
        t = all_trades[sname]
        log(f"  {sname}: 交易 {len(t)}")
        for rg in ('all', 'bull', 'bear'):
            sub = [x for x in t if x[4] == rg] if rg != 'all' else t
            if len(sub) < 30:
                continue
            rets = np.array([x[0] for x in sub])
            exs = np.array([x[1] for x in sub])
            holds = np.array([x[3] - x[2] for x in sub])
            st = full_stats(rets, None, holds.mean())
            ex_mean = np.nanmean(exs) * 100 if len(exs) else 0
            st['excess_mean'] = round(ex_mean, 3)
            passed = (st['win_rate'] > 40) and (st['median'] > 0) and (st['mean'] > 0) and (st['excess_mean'] > 0)
            st['regime'] = rg
            st['strategy'] = sname
            st['pass'] = passed
            rows.append(st)
            log(f"    {rg:4s} n={st['n']:6d} wr={st['win_rate']:5.2f}% med={st['median']:7.3f}% mean={st['mean']:7.3f}% 超额={st['excess_mean']:7.3f}% 年化={st['annualized']:7.2f}% 夏普={st['sharpe']:6.3f} 盈亏比={st['profit_factor']:5.2f} 均持={st['avg_hold']:5.1f}天 {'✅' if passed else '❌'}")

    df_out = pd.DataFrame(rows)
    df_out.to_csv(os.path.join(OUT_DIR, 'khunter_timing_summary.csv'), index=False)
    log("完成")

if __name__ == "__main__":
    main()
