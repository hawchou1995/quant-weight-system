# -*- coding: utf-8 -*-
"""oss_0913 批2: niuone（牛牛1号）七战法忠实转译库
源: /Tools/niuone-src app/strategies/scoring/{base,zettaranc,li_daxiao,common}.py
逐点精算 f(M, i, j)->dict|None; M=矩阵字典(oss_panel_0913.pkl + fmv/amt)
忠实规则: 打分公式/封顶/min 规则/hard blockers/entry_threshold/priority 全部按原码。
申报差异: ①数据用前复权(原版东财/腾讯原始价) ②换手率用 amount/float_mv 近似
③次新用"上市满110bar"代理(N/C 名称无数据) ④hard blockers 取原码 strategy_hard_blockers
"""
import numpy as np

def _mean(a):
    v = a[np.isfinite(a)]
    return float(v.mean()) if len(v) else None

def _valid(*xs):
    return all(x is not None and np.isfinite(x) for x in xs)

def _is_yin(o, c): return c < o
def _is_yang(o, c): return c >= o

# ---------- N 型结构 (find_n_structure_prior_low + n_structure_ok) ----------
def n_structure_ok(M, i, j, lookback=20, tolerance_pct=0.02):
    """近期存在上升的摆动低点对 (后低 >= 前低*0.98)。"""
    lo = M["low"][:, j]
    if i < 4: return False
    start = max(0, (i + 1) - max(5, lookback))
    swings = []
    for idx in range(max(1, start + 1), i):  # 开区间上界 = i (不含最新bar)
        a, b, c = lo[idx-1], lo[idx], lo[idx+1]
        if _valid(a, b, c) and b > 0 and a > 0 and c > 0 and b <= a and b <= c:
            swings.append((idx, b))
    for k in range(len(swings) - 1, 0, -1):
        earlier = swings[k-1]; latest = swings[k]
        if latest[1] >= earlier[1] * (1 - tolerance_pct):
            return True
    return False

# ---------- 1. 趋势回踩 trend_pullback (priority 68, th 8.0) ----------
def score_trend_pullback(M, i, j):
    if i < 30: return None
    close = M["close"][i, j]
    bbi_r = M["bbi"][i, j]; ema20_r = M["ema20"][i, j]; ema50_r = M["ema50"][i, j]
    if not _valid(bbi_r, ema20_r) or close <= 0: return None
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    dist_ema20 = (close / ema20_r - 1) * 100 if ema20_r else 99
    bbi_win = M["bbi"][i-3:i+1, j]
    bbi_up_3d = bool(np.isfinite(bbi_win).all() and all(bbi_win[k] > bbi_win[k-1] for k in range(1, 4)))
    recent5_low = np.nanmin(M["low"][i-4:i+1, j])
    pullback_occurred = recent5_low <= bbi_r * 1.03
    pullback_held = recent5_low >= bbi_r * 0.97
    recent5_vol = _mean(M["vol"][i-4:i+1, j]); prior10_vol = _mean(M["vol"][i-14:i-4, j])
    vol_shrink = (recent5_vol < prior10_vol * 0.85) if _valid(recent5_vol, prior10_vol) else False
    chg = M["chg"][i, j]
    today_strong = np.isfinite(chg) and chg > -1.5
    trend_up = bbi_up_3d and (ema20_r >= ema50_r * 0.98 if np.isfinite(ema50_r) else True)
    position_ok = 0 <= dist_bbi <= 5 and -1 <= dist_ema20 <= 4
    score = 0.0
    score += 2 if trend_up else (1 if bbi_up_3d else 0)
    if pullback_occurred and pullback_held and vol_shrink: score += 3
    elif pullback_occurred and pullback_held: score += 2
    elif pullback_occurred: score += 1
    score += 2 if (today_strong and close >= bbi_r) else (1 if close >= bbi_r else 0)
    if position_ok and dist_bbi <= 3: score += 3
    elif position_ok: score += 2
    elif close >= bbi_r: score += 1
    if dist_bbi > 6.5: score = max(0, score - 2)
    if dist_bbi > 10: score = max(0, score - 3)
    blockers = []
    if not bbi_up_3d: blockers.append("趋势未确认")
    if not pullback_held: blockers.append("回踩未守住")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.0, priority=68)

# ---------- 2. 突破确认 breakout (priority 76, th 8.0) ----------
def score_breakout(M, i, j):
    if i < 40: return None
    close = M["close"][i, j]; bbi_r = M["bbi"][i, j]
    if not _valid(bbi_r) or close <= 0: return None
    # 平台 rows[i-29:i-4] (30-5)
    ph = M["high"][i-29:i-4, j]; pl = M["low"][i-29:i-4, j]
    ph = ph[np.isfinite(ph)]; pl = pl[np.isfinite(pl)]
    if len(ph) < 10 or len(pl) < 10: return None
    platform_high = float(ph.max()); platform_low = float(pl.min())
    platform_range = (platform_high / platform_low - 1) * 100 if platform_low > 0 else 0
    has_platform = 3 <= platform_range <= 18
    above_platform = close > platform_high * 1.005
    recent3_vol = _mean(M["vol"][i-2:i+1, j]); platform_vol = _mean(M["vol"][i-29:i-4, j])
    vol_expand = (_valid(recent3_vol, platform_vol) and platform_vol > 0 and recent3_vol >= platform_vol * 1.15)
    vol_not_explode = (_valid(recent3_vol, platform_vol) and platform_vol > 0 and recent3_vol <= platform_vol * 3.5)
    high40 = np.nanmax(M["high"][i-39:i+1, j])
    is_new_high = close > high40 * 0.98 and close >= high40 * 0.99
    recent5_low = np.nanmin(M["low"][i-4:i+1, j])
    pullback_confirmed = (recent5_low >= platform_high * 0.97) if above_platform else True
    bbi_win = M["bbi"][i-3:i+1, j]
    bbi_up = bool(np.isfinite(bbi_win).all() and all(bbi_win[k] > bbi_win[k-1] for k in range(1, 4)))
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    score = 0.0
    score += 2 if has_platform else (1 if platform_range > 0 else 0)
    if above_platform and vol_expand and vol_not_explode and pullback_confirmed: score += 3
    elif above_platform and vol_expand: score += 2
    elif above_platform or (is_new_high and vol_expand): score += 1
    score += 2 if (bbi_up and close >= bbi_r) else (1 if close >= bbi_r else 0)
    if dist_bbi <= 4 and above_platform: score += 3
    elif dist_bbi <= 6: score += 2
    elif dist_bbi <= 8: score += 1
    if dist_bbi > 8: score = max(0, score - 2)
    if dist_bbi > 12: score = max(0, score - 3)
    blockers = []
    if not pullback_confirmed: blockers.append("突破后未回踩确认")
    if vol_expand and not vol_not_explode: blockers.append("突破放量过猛")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.0, priority=76)

# ---------- 3. 少妇B1 shaofu_b1 (priority 72, th 8.0) ----------
def score_shaofu_b1(M, i, j):
    if i < 30: return None
    close = M["close"][i, j]; bbi_r = M["bbi"][i, j]; J = M["kdj_j"][i, j]
    if not _valid(bbi_r, J) or close <= 0: return None
    if J > 12.0: return None
    o4 = M["open"][i-3:i+1, j]; c4 = M["close"][i-3:i+1, j]
    if not np.isfinite(o4).all(): return None
    green_count = int(sum(1 for k in range(4) if _is_yin(o4[k], c4[k])))
    if green_count >= 4: return None
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    vol = M["vol"][i, j]; prev_vol = M["vol"][i-1, j]
    vol_shrink = bool(_valid(vol, prev_vol) and prev_vol > 0 and vol < prev_vol * 0.85)
    recent5_vol = _mean(M["vol"][i-4:i+1, j]); prior10_vol = _mean(M["vol"][i-14:i-4, j])
    pullback_shrink = bool(_valid(recent5_vol, prior10_vol) and prior10_vol > 0 and recent5_vol < prior10_vol * 0.9) if prior10_vol else vol_shrink
    n_ok = n_structure_ok(M, i, j, lookback=20)
    white = M["z_white"][i, j]; yellow = M["z_yellow"][i, j]
    bull_rope = bool(_valid(white, yellow) and white >= yellow * 0.98) or close >= bbi_r
    low_i = M["low"][i, j]
    stop_space = max(0, (close / low_i - 1) * 100) if low_i > 0 else 99
    yellow_dist = (close / yellow - 1) * 100 if _valid(yellow) and yellow > 0 else dist_bbi
    high20 = np.nanmax(M["high"][i-19:i+1, j])
    pressure_space = (high20 / close - 1) * 100 if close > 0 else 0
    score = 0.0
    if J <= -10: score += 2.5
    elif J <= 0: score += 2
    else: score += 1
    if vol_shrink and pullback_shrink: score += 2
    elif vol_shrink or pullback_shrink: score += 1.2
    if n_ok: score += 1.5
    if bull_rope: score += 1
    if stop_space <= 4.5: score += 1.5
    elif stop_space <= 6: score += 1
    if -3 <= dist_bbi <= 5 and abs(yellow_dist) <= 8: score += 1
    if pressure_space >= 5: score += 1
    if J > -10: score = min(score, 7.5)
    if dist_bbi > 6.5: score = min(score, 7.5)
    if stop_space > 8: score = min(score, 6.5)
    score = min(10, score)
    blockers = []
    if J > -10: blockers.append("B1核心J未≤-10")
    if not vol_shrink and not pullback_shrink: blockers.append("未缩量回调")
    if not n_ok: blockers.append("N型上移不足")
    if not bull_rope: blockers.append("牛绳/BBI支撑不足")
    if stop_space > 6: blockers.append("止损空间>6%")
    if pressure_space < 5: blockers.append("上方空间不足")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.0, priority=72)

# ---------- 4. B2 确认 b2_confirm (priority 82, th 8.0) ----------
def _recent_b1(M, i, j, lookback, end_offset=1):
    end = (i + 1) - end_offset
    start = max(0, end - lookback)
    out = []
    for idx in range(start, end):
        J = M["kdj_j"][idx, j]
        if not np.isfinite(J): continue
        s = max(0, idx - 3)
        o4 = M["open"][s:idx+1, j]; c4 = M["close"][s:idx+1, j]
        if not np.isfinite(o4).all(): continue
        green = sum(1 for k in range(len(o4)) if _is_yin(o4[k], c4[k]))
        if J <= -10.0 and green < 4: out.append(idx)
    return out

def score_b2_confirm(M, i, j):
    if i < 35: return None
    b1idxs = _recent_b1(M, i, j, lookback=3, end_offset=1)
    if not b1idxs: return None
    days_from_b1 = i - b1idxs[-1]
    if days_from_b1 < 1 or days_from_b1 > 3: return None
    close = M["close"][i, j]; o = M["open"][i, j]; hi = M["high"][i, j]
    bbi_r = M["bbi"][i, j]; J = M["kdj_j"][i, j]
    if not _valid(bbi_r) or not np.isfinite(J): return None
    chg = M["chg"][i, j]
    if not (np.isfinite(chg) and chg >= 4 and _is_yang(o, close)): return None
    vol_ratio = M["vol"][i, j] / M["vol"][i-1, j] if M["vol"][i-1, j] > 0 else 0
    vol_expand = vol_ratio >= 1.2
    above_bbi = close >= bbi_r
    upper_shadow = hi - max(close, o); body = abs(close - o)
    upper_ok = body <= 0 or upper_shadow <= body * 1.2
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    score = 4.0
    if 1 <= days_from_b1 <= 3: score += 1.5
    if vol_expand:
        score += 1.5
        if vol_ratio <= 3: score += 0.5
    if J < 55: score += 1.5
    elif J < 70: score += 0.5
    if above_bbi: score += 1
    if upper_ok: score += 1
    if dist_bbi <= 6.5: score += 1
    if J >= 70: score = min(score, 7.0)
    if dist_bbi > 8: score = min(score, 7.5)
    if chg >= 9 and dist_bbi > 6.5: score = min(score, 7.0)
    score = min(10, score)
    blockers = []
    if J >= 55: blockers.append("B2要求J<55")
    if not vol_expand: blockers.append("B2未放量确认")
    if days_from_b1 > 3: blockers.append("B2距离B1超过3日")
    if not upper_ok: blockers.append("B2上影过长")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.0, priority=82)

# ---------- 5. B3 中继 b3_accelerate (priority 90, th 8.5) ----------
def score_b3_accelerate(M, i, j):
    if i < 40: return None
    bbi_r = M["bbi"][i, j]
    if not _valid(bbi_r): return None
    has_b2 = False; b2_distance = None
    for offset in range(2, min(6, i + 1)):
        idx = i - offset
        chg_r = M["chg"][idx, j]
        vol_ok = M["vol"][idx - 1, j] > 0 and M["vol"][idx, j] >= M["vol"][idx - 1, j] * 1.2
        if np.isfinite(chg_r) and chg_r >= 4 and _is_yang(M["open"][idx, j], M["close"][idx, j]) and vol_ok:
            has_b2 = True; b2_distance = offset - 1; break
    if not has_b2 or b2_distance > 3: return None
    close = M["close"][i, j]; o = M["open"][i, j]
    chg = M["chg"][i, j]; amp = M["amp"][i, j]; J = M["kdj_j"][i, j]
    if not (np.isfinite(chg) and np.isfinite(amp) and np.isfinite(J)): return None
    small_consensus = (-1.5 <= chg < 2) and amp < 6 and close >= o * 0.985
    if not small_consensus: return None
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    score = 6.0
    if close >= bbi_r and dist_bbi <= 5: score += 1
    if J < 70: score += 0.8
    if amp <= 4.5: score += 1
    elif amp < 6: score += 0.5
    if b2_distance <= 1: score += 1.2
    elif b2_distance <= 2: score += 1
    else: score += 0.4
    volume_not_explode = (M["vol"][i, j] <= M["vol"][i-1, j] * 1.2) if M["vol"][i-1, j] > 0 else True
    if volume_not_explode: score += 1
    if -0.5 <= chg <= 1.5: score += 0.5
    if J >= 90: score = min(score, 8.0)
    elif J >= 70: score = min(score, 8.5)
    if dist_bbi > 6.5: score = min(score, 7.5)
    score = min(10, score)
    blockers = []
    if b2_distance > 2: blockers.append("B3距离B2过远")
    if J >= 70: blockers.append("B3 J值过热")
    if amp >= 6: blockers.append("B3振幅过大")
    if chg < -0.5: blockers.append("B3分歧未转一致")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.5, priority=90)

# ---------- 6. 超级B1 super_b1 (priority 58, th 8.5) ----------
def score_super_b1(M, i, j):
    if i < 35: return None
    bbi_r = M["bbi"][i, j]; J = M["kdj_j"][i, j]
    if not _valid(bbi_r, J) or J > -5: return None
    wash_idx = None
    for idx in range(max(1, i - 5), i):
        chg = M["chg"][idx, j]
        if _is_yin(M["open"][idx, j], M["close"][idx, j]) and M["vol"][idx-1, j] > 0 \
           and M["vol"][idx, j] >= M["vol"][idx-1, j] * 1.5 and np.isfinite(chg) and chg <= -2:
            wash_idx = idx; break
    if wash_idx is None: return None
    close = M["close"][i, j]; prev_vol = M["vol"][i-1, j]; vol = M["vol"][i, j]
    wash_low = M["low"][wash_idx, j]; wash_days_ago = i - wash_idx
    shrink = bool(prev_vol > 0 and vol < prev_vol * 0.85)
    stable = close >= wash_low * 0.98 and M["low"][i, j] >= wash_low * 0.97
    o = M["open"][i, j]
    body_pct = abs(close - o) / o * 100 if o > 0 else 0
    small_body = body_pct <= 2.5
    n_ok = n_structure_ok(M, i, j, lookback=20)
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    stop_space = (close / wash_low - 1) * 100 if wash_low > 0 else 99
    if not (shrink and stable): return None
    score = 2.5
    score += 2 if J <= -10 else 1
    if shrink: score += 1
    if stable: score += 1
    if small_body: score += 1
    if close >= bbi_r * 0.97 and dist_bbi <= 5: score += 1
    if n_ok: score += 1
    if wash_days_ago <= 3: score += 1
    if stop_space <= 6: score += 1
    if close < bbi_r * 0.97: score = min(score, 7.0)
    if stop_space > 8: score = min(score, 7.0)
    if wash_days_ago > 3: score = min(score, 7.5)
    score = min(9, score)
    blockers = []
    if stop_space > 6: blockers.append("超级B1止损空间>6%")
    if wash_days_ago > 3: blockers.append("洗盘信号不够新")
    if not n_ok or not small_body: blockers.append("超级B1结构未企稳")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.5, priority=58)

# ---------- 7. 李大霄 li_daxiao_bottom (priority 56, th 8.0) ----------
LD_MIN_AMOUNT = 1.2e9; LD_MAX_TURNOVER = 6.0; LD_HOT_TURNOVER = 8.0
LD_MAX_BBI_DIST = 3.5; LD_MAX_CHASE = 3.5

def score_li_daxiao(M, i, j, core_board):
    if i < 80: return None
    close = M["close"][i, j]; bbi_r = M["bbi"][i, j]
    ema20_r = M["ema20"][i, j]; ema50_r = M["ema50"][i, j]
    if not _valid(bbi_r, ema20_r, ema50_r, close) or close <= 0: return None
    w = slice(i - min(120, i + 1) + 1, i + 1)
    hi120 = np.nanmax(M["high"][w, j]); lo120 = np.nanmin(M["low"][w, j])
    low20 = np.nanmin(M["low"][i-19:i+1, j])
    dd_high = (close / hi120 - 1) * 100 if hi120 > 0 else 0
    dist_low = (close / lo120 - 1) * 100 if lo120 > 0 else 0
    dist_bbi = (close / bbi_r - 1) * 100 if bbi_r else 99
    chg = M["chg"][i, j]
    chg = float(chg) if np.isfinite(chg) else None
    amount = M["amt"][i, j]; amount = float(amount) if np.isfinite(amount) else None
    fmv = M["fmv"][i, j]
    turnover = (amount / fmv * 100) if _valid(amount, fmv) and fmv > 0 else None
    # vol20: 20日收益率样本标准差
    c20 = M["close"][i-20:i+1, j]
    rets = np.diff(c20) / c20[:-1] * 100 if np.isfinite(c20).all() else None
    vol20 = float(np.std(rets, ddof=1)) if rets is not None and len(rets) > 1 else None
    recent5_vol = _mean(M["vol"][i-4:i+1, j]); prior20_vol = _mean(M["vol"][i-24:i-4, j]); avg60 = _mean(M["vol"][i-59:i+1, j])
    volume_shrink = bool(_valid(recent5_vol, prior20_vol) and prior20_vol > 0 and recent5_vol <= prior20_vol * 0.9)
    quote_liq_ok = amount is None or amount >= LD_MIN_AMOUNT
    volume_liq_ok = bool(_valid(avg60, recent5_vol) and avg60 > 0 and recent5_vol >= avg60 * 0.35)
    bluechip = volume_liq_ok and quote_liq_ok
    turnover_calm = turnover is None or turnover <= LD_MAX_TURNOVER
    turnover_hot = turnover is not None and turnover >= LD_HOT_TURNOVER
    not_fresh = i >= 109
    daily_chase = chg is not None and chg > LD_MAX_CHASE
    heat = turnover_hot or (turnover is not None and turnover > LD_MAX_TURNOVER and (chg or 0) > 2) \
           or (daily_chase and dist_bbi > 2.5)
    value_anchor = bluechip and turnover_calm and core_board
    anti_black5 = not_fresh and quote_liq_ok and not heat and (core_board or turnover_calm)
    no_chase = dist_bbi <= LD_MAX_BBI_DIST and not daily_chase
    b_win = M["bbi"][i-4:i+1, j]
    bbi_flat = bool(np.isfinite(b_win).all() and bbi_r >= b_win.min() * 0.995)
    stabilizing = close >= bbi_r * 0.98 and close >= ema20_r * 0.97 and M["low"][i, j] >= low20 * 0.985
    bottom_zone = -45 <= dd_high <= -12 and dist_low <= 18
    breakdown = close < low20 * 1.02 and (chg or 0) < -1.5
    low_vol = vol20 is not None and vol20 <= 3.8
    score = 0.0
    if bottom_zone: score += 2.2
    elif -55 <= dd_high <= -8 and dist_low <= 25: score += 1.3
    if stabilizing: score += 1.6
    elif close >= bbi_r * 0.96: score += 0.8
    if volume_shrink: score += 1.0
    if low_vol: score += 1.1 if vol20 <= 2.8 else 0.7
    if bbi_flat: score += 0.8
    if value_anchor: score += 1.4
    elif bluechip: score += 0.6
    if anti_black5: score += 1.0
    if no_chase: score += 0.8
    if not breakdown: score += 0.6
    if close >= ema50_r * 0.94: score += 0.5
    if dist_low > 25: score = min(score, 7.2)
    if breakdown: score = min(score, 6.8)
    if vol20 is not None and vol20 > 4.5: score = min(score, 6.5)
    if not value_anchor: score = min(score, 7.6)
    if not anti_black5: score = min(score, 7.4)
    if not no_chase: score = min(score, 7.0)
    if heat: score = min(score, 6.8)
    if not not_fresh: score = min(score, 6.8)
    score = min(10, score)
    blockers = []
    if not bottom_zone: blockers.append("未处低位区")
    if not stabilizing: blockers.append("底部未企稳")
    if not bluechip: blockers.append("蓝筹流动性代理不足")
    if not value_anchor: blockers.append("低估蓝筹代理不足")
    if not anti_black5: blockers.append("黑五类/题材热度代理偏高")
    if not no_chase: blockers.append("不符合正金字塔低吸")
    if dist_bbi > 6.5: blockers.append("距BBI>6.5%")
    return dict(score=score, blockers=blockers, threshold=8.0, priority=56)

# ---------- 注册表 ----------
STRATEGIES = {
    "trend_pullback": dict(fn=score_trend_pullback, priority=68, threshold=8.0),
    "breakout": dict(fn=score_breakout, priority=76, threshold=8.0),
    "shaofu_b1": dict(fn=score_shaofu_b1, priority=72, threshold=8.0),
    "b2_confirm": dict(fn=score_b2_confirm, priority=82, threshold=8.0),
    "b3_accelerate": dict(fn=score_b3_accelerate, priority=90, threshold=8.5),
    "super_b1": dict(fn=score_super_b1, priority=58, threshold=8.5),
    "li_daxiao": dict(fn=score_li_daxiao, priority=56, threshold=8.0),
}
# 粗筛（必须在精算前通过; 与精算前置条件一致, 保证 exact）
def prefilter(M, di, strategy):
    if strategy == "trend_pullback":
        return (np.isfinite(M["bbi"][di]) & np.isfinite(M["ema20"][di]) & (M["close"][di] > 0))
    if strategy == "breakout":
        return np.isfinite(M["bbi"][di]) & (M["close"][di] > 0)
    if strategy == "shaofu_b1":
        return np.isfinite(M["kdj_j"][di]) & (M["kdj_j"][di] <= 12.0) & np.isfinite(M["bbi"][di]) & (M["close"][di] > 0)
    if strategy == "b2_confirm":
        chg = M["chg"][di]; o = M["open"][di]; c = M["close"][di]
        return (np.isfinite(chg) & (chg >= 4) & (c >= o) & np.isfinite(M["bbi"][di]))
    if strategy == "b3_accelerate":
        chg = M["chg"][di]; amp = M["amp"][di]; o = M["open"][di]; c = M["close"][di]; J = M["kdj_j"][di]
        return (np.isfinite(chg) & (chg >= -1.5) & (chg < 2) & (amp < 6) & (c >= o * 0.985)
                & np.isfinite(J) & np.isfinite(M["bbi"][di]))
    if strategy == "super_b1":
        return np.isfinite(M["kdj_j"][di]) & (M["kdj_j"][di] <= -5) & np.isfinite(M["bbi"][di])
    if strategy == "li_daxiao":
        return np.isfinite(M["bbi"][di]) & np.isfinite(M["ema20"][di]) & np.isfinite(M["ema50"][di]) & (M["close"][di] > 0)
    raise KeyError(strategy)
